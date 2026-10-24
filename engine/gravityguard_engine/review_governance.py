#!/usr/bin/env python3
"""
GravityGuard Engine — Self-Review Obligation Subsystem.

The invariant this module exists to enforce:

    GravityGuard verifies that a review step happened, not that it was correct.

The goal is catching *omission* (a weaker model forgetting to review), not
malice. The agent reviews its own diff and writes a short self-review record;
the record is accepted when it (a) is schema-valid, (b) carries the fingerprint
of the current candidate, and (c) is not stale — the candidate on disk still
hashes to the fingerprint the review was made against. Code changed after the
review (including fixes for its findings) invalidates the record.

Zero external dependencies.
"""
import hashlib
import json
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .governance import _visible_pending, governance_transaction, load_governance_state
from .review_policy import (
    check_review_risk_triggers,
    is_review_enabled,
    should_require_review,
)

#: Where the agent writes its self-review record, relative to the workspace root.
#: Deliberately outside ``runtime/`` and ``reviews/``, which are agent-read-only control paths.
RECEIPT_SUBDIR = (".gravityguard", "self-review")

#: Shortest accepted ``notes``; a blank or one-word note is not a review.
MIN_NOTES_LENGTH = 20


def _normalize_newlines(text: str) -> str:
    """CRLF/CR → LF so a text hash is stable across platforms."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def hash_text(text: str) -> str:
    """SHA-256 of newline-normalized UTF-8 text."""
    return hashlib.sha256(_normalize_newlines(text or "").encode("utf-8")).hexdigest()


def read_disk_text_hash(path: Path) -> Optional[str]:
    """Newline-normalized text hash of a file, or None when it cannot be read."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return hash_text(handle.read())
    except (IOError, OSError) as err:
        _read_err = err
        return None


def _norm_rel(target_file: str, project_root: Optional[Path]) -> str:
    """Project-relative, forward-slash, lower-cased key for a file.

    Both sides are resolved first, so a Windows 8.3 short path and its long form
    (common for temp dirs) normalize to the same key. Falls back to the raw path
    when the file lies outside the project root.
    """
    p = Path(str(target_file))
    if project_root is not None:
        try:
            rel = p.resolve().relative_to(Path(project_root).resolve())
            return rel.as_posix().lower()
        except (OSError, ValueError) as err:
            _rel_err = err
    return p.as_posix().lower()


def fingerprint_from_hashes(file_hashes: Dict[str, str]) -> str:
    """Stable fingerprint over ``{relpath: sha256}`` (sorted, order-independent)."""
    lines = [f"{path}:{file_hashes[path]}" for path in sorted(file_hashes)]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def new_review_id() -> str:
    return f"rev-{int(time.time())}-{uuid.uuid4().hex[:8]}"


def get_unresolved_review_obligations(
    project_root: Optional[Path] = None,
    conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Pending review obligations this conversation owes (same isolation rule as other categories)."""
    return _visible_pending(load_governance_state(project_root), "review_obligations", conversation_id)


def record_review_obligation(
    target_file: str,
    projected_content: str,
    project_root: Optional[Path] = None,
    conversation_id: Optional[str] = None,
    cfg: Optional[dict] = None,
) -> Optional[Dict[str, Any]]:
    """Creates or extends the review obligation for this conversation's candidate.

    The obligation is keyed by ``review_id`` and accumulates every governed file
    written in the session, so a session is reviewed as one candidate rather than
    file by file. Returns the obligation entry, or None when review does not apply.

    ``projected_content`` is the file body *as it will be written* (the PreToolUse
    hook already computed it), so the fingerprint describes the real candidate.
    """
    if not should_require_review(target_file, cfg, project_root):
        return None

    root = project_root or Path.cwd()
    rel = _norm_rel(target_file, root)
    file_hash = hash_text(projected_content)

    cid = conversation_id or "default"
    with governance_transaction(project_root) as state:
        pending = state.setdefault("review_obligations", {}).setdefault("pending", {})
        session = state.setdefault("sessions", {}).setdefault(cid, {})
        session_pending = session.setdefault("review_obligations", {}).setdefault("pending", {})

        # Reuse this session's open review, or start a new one.
        review_id = next(iter(session_pending), None)
        if review_id is None:
            review_id = new_review_id()
            entry: Dict[str, Any] = {
                "review_id": review_id,
                "conversation_id": cid,
                "changed_files": {},
                "timestamp": time.time(),
                "reason": (
                    "Governed code changed; a self-review of the diff is required "
                    "before the session may stop."
                ),
            }
        else:
            entry = session_pending[review_id]

        changed = entry.setdefault("changed_files", {})
        changed[rel] = file_hash
        entry["source_fingerprint"] = fingerprint_from_hashes(changed)
        entry["timestamp"] = time.time()
        if cfg:
            entry["cfg"] = cfg

        pending[review_id] = entry
        session_pending[review_id] = entry
        return dict(entry)


def _load_receipt(project_root: Path, review_id: str) -> Tuple[Optional[dict], Optional[str]]:
    """Reads and validates the agent's self-review record. Returns ``(receipt, error)``."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", review_id):
        return None, "receipt-invalid-id"
    path = Path(project_root).joinpath(*RECEIPT_SUBDIR) / f"{review_id}.json"
    if not path.is_file():
        return None, "receipt-missing"
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (IOError, OSError, json.JSONDecodeError, ValueError) as err:
        return None, f"receipt-unreadable: {err}"
    if not isinstance(data, dict):
        return None, "receipt-not-an-object"
    if data.get("reviewId") != review_id:
        return None, "receipt-id-mismatch"
    if not isinstance(data.get("findings"), list):
        return None, "receipt-findings-invalid"
    notes = data.get("notes")
    if not isinstance(notes, str) or len(notes.strip()) < MIN_NOTES_LENGTH:
        return None, "receipt-notes-too-short"
    return data, None


def _is_stale(root: Path, entry: Dict[str, Any]) -> bool:
    """True when the candidate on disk no longer matches the recorded fingerprint."""
    changed = entry.get("changed_files", {})
    if not isinstance(changed, dict) or not changed:
        return False
    current: Dict[str, str] = {}
    for rel in changed:
        disk_hash = read_disk_text_hash(root / rel)
        if disk_hash is not None:
            current[rel] = disk_hash
    if len(current) != len(changed):
        return True
    return fingerprint_from_hashes(current) != entry.get("source_fingerprint")


def evaluate_review_obligations(
    project_root: Optional[Path] = None,
    conversation_id: Optional[str] = None,
    cfg: Optional[dict] = None,
) -> Dict[str, Any]:
    """Evaluates each pending review obligation and resolves the satisfied ones.

    Under R1.1 Risk-Gated Review Policy:
    - Low-risk changes (<5 files, <120 lines, non-security) are auto-exempt (resolved without blocking).
    - High-risk changes (security paths, dependency changes, large scale) require a matching self-review record.
    """
    root = project_root or Path.cwd()
    passed_cfg = cfg

    unresolved: Dict[str, Any] = {}
    resolved: List[str] = []

    with governance_transaction(project_root) as state:
        pending = _visible_pending(state, "review_obligations", conversation_id)
        for review_id, entry in list(pending.items()):
            if not isinstance(entry, dict):
                continue

            changed_files = list(entry.get("changed_files", {}).keys())

            # Calculate total line volume of changed files
            total_lines = 0
            for rel in changed_files:
                p = root / rel
                if p.is_file():
                    try:
                        with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                            total_lines += sum(1 for _ in fp)
                    except OSError:
                        pass

            eff_cfg = passed_cfg or entry.get("cfg")
            if eff_cfg is None:
                try:
                    from .project_context import load_gravityguard_config
                    eff_cfg = load_gravityguard_config("", root)
                except Exception:
                    eff_cfg = {}

            is_required, trigger_reason = check_review_risk_triggers(
                changed_files, eff_cfg, root, total_lines_changed=total_lines
            )

            # If not risk-triggered, this change is low-risk: auto-exempt!
            if not is_required:
                entry["status"] = "exempt"
                entry["trigger_reason"] = trigger_reason
                resolved.append(review_id)
                continue

            entry["trigger_reason"] = trigger_reason
            problems: List[str] = []

            receipt, receipt_err = _load_receipt(root, review_id)
            if receipt_err:
                problems.append(receipt_err)
            else:
                if receipt.get("sourceFingerprint") != entry.get("source_fingerprint"):
                    problems.append("fingerprint-mismatch")

            if _is_stale(root, entry):
                problems.append("stale-candidate")

            if problems:
                entry["status"] = "pending"
                entry["problems"] = problems
                unresolved[review_id] = entry
            else:
                resolved.append(review_id)

        if resolved:
            global_pending = state.get("review_obligations", {}).get("pending", {})
            for rid in resolved:
                global_pending.pop(rid, None)
            for s_data in state.get("sessions", {}).values():
                if not isinstance(s_data, dict):
                    continue
                review_pending = s_data.get("review_obligations")
                if isinstance(review_pending, dict) and isinstance(review_pending.get("pending"), dict):
                    for rid in resolved:
                        review_pending["pending"].pop(rid, None)

    return {"unresolved": unresolved, "resolved": resolved}


def scan_git_governed_changes(
    project_root: Optional[Path] = None,
    cfg: Optional[dict] = None,
) -> List[str]:
    """FINAL DIFF GUARD (best effort): governed code changed on disk.

    Returns workspace-relative paths of changed, review-triggering files. Runs
    ``git status --porcelain`` in the project root, so a shell write that bypassed
    the PreToolUse hook still shows up here. Fail-open: if git is unavailable or
    the root is not a repository, an empty list is returned and nothing changes.
    """
    if not is_review_enabled(cfg):
        return []
    root = project_root or Path.cwd()
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as err:
        _git_err = err
        return []
    if proc.returncode != 0:
        return []

    changed: List[str] = []
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        # porcelain v1: "XY path" or "XY orig -> path"
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip('"').strip()
        if not path:
            continue
        if should_require_review(str(root / path), cfg, root):
            changed.append(path)
    return changed


def record_final_diff_guard(
    project_root: Optional[Path] = None,
    conversation_id: Optional[str] = None,
    cfg: Optional[dict] = None,
) -> List[str]:
    """Extends the review obligation with files only the final diff could see.

    Reads each escaped file's current disk content and folds it into the same
    session obligation, so the candidate fingerprint covers what actually landed.
    Returns the newly covered paths (empty when nothing new).
    """
    root = project_root or Path.cwd()
    unseen = scan_git_governed_changes(root, cfg)
    if not unseen:
        return []
    newly: List[str] = []
    for rel in unseen:
        abs_path = root / rel
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except (IOError, OSError) as err:
            _read_err = err
            continue
        record_review_obligation(str(abs_path), text, root, conversation_id, cfg)
        newly.append(rel)
    return newly
