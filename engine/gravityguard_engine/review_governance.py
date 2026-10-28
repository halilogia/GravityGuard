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
import ast
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .governance import _visible_pending, governance_transaction, load_governance_state
from .review_policy import (
    RISK_LOW,
    RISK_ORDER,
    check_review_risk_triggers,
    classify_file_risk,
    get_review_governance_config,
    is_review_enabled,
    is_review_governance_enabled,
    risk_meets_threshold,
    should_require_review,
)
from .state_lock import StateLock

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


def _git_out(root: Path, *args: str) -> Optional[str]:
    try:
        proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as err:
        _git_err = err
        return None
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None


def git_binding(project_root: Optional[Path] = None) -> Dict[str, Optional[str]]:
    """Current ``{commit, tree}`` (HEAD and HEAD^{tree}); both None outside a repository."""
    root = Path(project_root or Path.cwd())
    return {
        "commit": _git_out(root, "rev-parse", "HEAD"),
        "tree": _git_out(root, "rev-parse", "HEAD^{tree}"),
    }


def binding_is_stale(binding: Dict[str, Any], project_root: Optional[Path] = None) -> bool:
    """True when a recorded binding no longer describes the code on disk.

    Stale when the git tree moved, or any bound file's content hash changed
    (covers uncommitted edits that leave HEAD's tree untouched). A binding
    without a tree (no git at bind time) is judged on file hashes alone.
    """
    root = Path(project_root or Path.cwd())
    bound_tree = binding.get("tree")
    if bound_tree and git_binding(root).get("tree") != bound_tree:
        return True
    for rel, expected in (binding.get("file_hashes") or {}).items():
        if read_disk_text_hash(root / rel) != expected:
            return True
    return False


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
                # Optional git binding, checked only here (Stop / pre-push, never on the hook
                # fast path): a receipt naming the tree/commit it was written against is void
                # once HEAD moved (rebase, pull, amend).
                if receipt.get("gitTree") or receipt.get("gitCommit"):
                    current = git_binding(root)
                    for key, rkey in (("tree", "gitTree"), ("commit", "gitCommit")):
                        if receipt.get(rkey) and current.get(key) and receipt[rkey] != current[key]:
                            problems.append(f"git-{key}-mismatch")

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


# ---------------------------------------------------------------------------
# Zero-context review: risk -> diff-fed payload -> session registry -> anti-loop
#
# The reviewer (Codex or a fresh Claude session) receives ONLY the payload built
# here: diff + changed-function boundaries. No chat history, no writer identity.
# The writer identity lives in the registry so findings can be routed back.
# ---------------------------------------------------------------------------
ZC_SUBDIR = (".gravityguard", "zero-context-review")
ZC_REGISTRY = (".gravityguard", "review-registry.json")
PAYLOAD_SCHEMA = "gravityguard.zero-context-review/1"
KNOWN_AGENTS = ("antigravity", "claude-code", "codex", "opencode")
FINDING_TYPES = ("logic", "security", "test", "docs", "hallucination", "style", "other")
_MAX_UNTRACKED_BYTES = 200_000
_MAX_FUNCTION_LINES = 200
_GIT_EXCLUDE = ":(exclude).gravityguard"
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@ ?(.*)$")

STATUS_PENDING = "pending"
STATUS_PASSED = "passed"
STATUS_FINDINGS = "findings"


def _git_text(root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-c", "core.quotepath=false", *args],
            cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as err:
        _git_err = err
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def _untracked_pseudo_diff(root: Path) -> str:
    """Unified-diff text for untracked files so new files are reviewed like any other change."""
    out: List[str] = []
    names = _git_text(root, "ls-files", "--others", "--exclude-standard", "-z", "--", ".", _GIT_EXCLUDE)
    for rel in sorted(n for n in names.split("\0") if n):
        path = root / rel
        try:
            if path.stat().st_size > _MAX_UNTRACKED_BYTES:
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as err:
            _read_err = err
            continue
        out.append(f"diff --git a/{rel} b/{rel}\nnew file mode 100644\n--- /dev/null\n+++ b/{rel}")
        if lines:
            out.append(f"@@ -0,0 +1{',' + str(len(lines)) if len(lines) > 1 else ''} @@")  # git omits ",1"
            out.extend("+" + line for line in lines)
    return "\n".join(out) + ("\n" if out else "")


def collect_diff_text(repo_root: Path, staged_only: bool = False) -> str:
    """Unified diff of the change under review (staged-only, or HEAD vs working tree + untracked)."""
    root = Path(repo_root)
    if staged_only:
        return _git_text(root, "diff", "--cached", "--unified=3", "--", ".", _GIT_EXCLUDE)
    tracked = _git_text(root, "diff", "HEAD", "--unified=3", "--", ".", _GIT_EXCLUDE)
    if not tracked and not _git_out(root, "rev-parse", "HEAD"):
        # Repository without commits: everything staged is new, plus any unstaged edits.
        tracked = _git_text(root, "diff", "--cached", "--unified=3", "--", ".", _GIT_EXCLUDE)
        tracked += _git_text(root, "diff", "--unified=3", "--", ".", _GIT_EXCLUDE)
    return tracked + _untracked_pseudo_diff(root)


def parse_unified_diff(diff_text: str) -> List[Dict[str, Any]]:
    """Per-file change records: counts, added/removed text, added line numbers, hunks."""
    files: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    in_hunk = False
    new_ln = 0
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            path = line.rsplit(" b/", 1)[1] if " b/" in line else line[11:]
            cur = {
                "path": path, "added": 0, "removed": 0, "deleted": False,
                "added_lines": [], "removed_lines": [], "added_numbers": [], "hunks": [], "diff": [],
            }
            files.append(cur)
            in_hunk = False
        if cur is None:
            continue
        cur["diff"].append(line)
        hunk = _HUNK_RE.match(line)
        if hunk:
            in_hunk = True
            new_ln = int(hunk.group(1))
            cur["hunks"].append({"start": new_ln, "length": int(hunk.group(2) or 1), "context": hunk.group(3).strip()})
        elif not in_hunk:
            if line.startswith("deleted file mode"):
                cur["deleted"] = True
            elif line.startswith("+++ b/"):
                cur["path"] = line[6:]
        elif line.startswith("+"):
            cur["added"] += 1
            cur["added_lines"].append(line[1:])
            cur["added_numbers"].append(new_ln)
            new_ln += 1
        elif line.startswith("-"):
            cur["removed"] += 1
            cur["removed_lines"].append(line[1:])
        elif line.startswith(" ") or line == "":
            new_ln += 1
    return files


def snapshot_hash_for(root: Path, parsed: List[Dict[str, Any]]) -> str:
    """Order-independent hash over per-file diffs plus the base tree (idempotency key)."""
    # ``index <sha>..<sha>`` lines differ between staged and untracked views of the same change.
    rows = sorted(
        f"{rec['path']}\0{hash_text(chr(10).join(ln for ln in rec['diff'] if not ln.startswith('index ')))}" for rec in parsed
    )
    base = git_binding(root).get("tree") or ""
    return hashlib.sha256(("\n".join(rows) + "\n" + base).encode("utf-8")).hexdigest()


def compute_snapshot_hash(repo_root: Any, staged_only: bool = False) -> str:
    """Diff snapshot hash (``snapshot_hash``); empty string when there is no change."""
    root = Path(repo_root)
    parsed = parse_unified_diff(collect_diff_text(root, staged_only))
    return snapshot_hash_for(root, parsed) if parsed else ""


def classify_change_risk(repo_root: Any, staged_only: bool = False, cfg: Optional[dict] = None) -> Dict[str, Any]:
    """Classify the pending change as LOW_RISK / MEDIUM_RISK / HIGH_RISK.

    Returns ``{risk, reasons, files, lines_changed, snapshot_hash}``; ``risk`` is the
    highest per-file level. An empty diff is LOW_RISK with an empty ``snapshot_hash``.
    """
    root = Path(repo_root)
    settings = get_review_governance_config(cfg)
    parsed = parse_unified_diff(collect_diff_text(root, staged_only))
    files, reasons, overall, total = [], [], RISK_LOW, 0
    for rec in parsed:
        level, why = classify_file_risk(
            rec["path"], rec["added_lines"], rec["removed_lines"], rec["deleted"],
            settings["highLines"], settings["mediumLines"],
        )
        files.append({"path": rec["path"], "risk": level, "reason": why, "added": rec["added"], "removed": rec["removed"]})
        total += rec["added"] + rec["removed"]
        if level != RISK_LOW:
            reasons.append(f"{rec['path']}: {why}")
        if RISK_ORDER[level] > RISK_ORDER[overall]:
            overall = level
    return {
        "risk": overall,
        "reasons": reasons,
        "files": files,
        "lines_changed": total,
        "snapshot_hash": snapshot_hash_for(root, parsed) if parsed else "",
    }


def _read_new_text(root: Path, rel: str, staged_only: bool) -> Optional[str]:
    if staged_only:
        return _git_text(root, "show", f":{rel}") or None
    try:
        return (root / rel).read_text(encoding="utf-8", errors="replace")
    except OSError as err:
        _read_err = err
        return None


def _python_function_spans(text: str, numbers: List[int]) -> List[Dict[str, Any]]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as err:
        _parse_err = err
        return []
    lines = text.splitlines()
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
        end = node.end_lineno or node.lineno
        if any(start <= n <= end for n in numbers):
            spans.append({"name": node.name, "start": start, "end": end})
    # Keep the innermost function only; its enclosing function would just bloat the payload.
    spans = [a for a in spans if not any(b is not a and a["start"] <= b["start"] and b["end"] <= a["end"] for b in spans)]
    for span in spans:
        body = lines[span["start"] - 1:span["end"]]
        if len(body) > _MAX_FUNCTION_LINES:
            body = body[:_MAX_FUNCTION_LINES] + ["# ... truncated ..."]
        span["source"] = "\n".join(body)
    return sorted(spans, key=lambda s: s["start"])


def changed_function_boundaries(root: Path, rec: Dict[str, Any], staged_only: bool = False) -> List[Dict[str, Any]]:
    """Changed function spans: real AST bounds for Python, hunk-header context for other languages."""
    if rec["deleted"] or not rec["added_numbers"]:
        return []
    if rec["path"].endswith(".py"):
        text = _read_new_text(root, rec["path"], staged_only)
        if text is not None:
            spans = _python_function_spans(text, rec["added_numbers"])
            if spans:
                return spans
    seen, spans = set(), []
    for hunk in rec["hunks"]:
        ctx = hunk["context"]
        if ctx and ctx not in seen:
            seen.add(ctx)
            spans.append({"name": ctx, "start": hunk["start"], "end": hunk["start"] + max(hunk["length"], 1) - 1, "source": None})
    return spans


def build_review_payload(repo_root: Any, staged_only: bool = False, cfg: Optional[dict] = None) -> Dict[str, Any]:
    """Isolated, history-free payload for the independent reviewer (JSON-serializable)."""
    root = Path(repo_root)
    diff_text = collect_diff_text(root, staged_only)
    parsed = parse_unified_diff(diff_text)
    risk = classify_change_risk(root, staged_only, cfg)
    by_path = {f["path"]: f for f in risk["files"]}
    files = []
    for rec in parsed:
        meta = by_path.get(rec["path"], {})
        files.append({
            "path": rec["path"], "risk": meta.get("risk", RISK_LOW), "added": rec["added"], "removed": rec["removed"],
            "deleted": rec["deleted"], "functions": changed_function_boundaries(root, rec, staged_only),
        })
    return {
        "schema": PAYLOAD_SCHEMA,
        "snapshot_hash": risk["snapshot_hash"],
        "risk": risk["risk"],
        "reasons": risk["reasons"],
        "files": files,
        "diff": diff_text,
        "instructions": (
            "You are an independent reviewer with no prior context. Review only this diff. "
            "Report findings as JSON: [{\"file\", \"line\", \"type\", \"suggestion\"}]; "
            f"type is one of {', '.join(FINDING_TYPES)}. Empty list means the change is acceptable."
        ),
    }


def render_review_payload_markdown(payload: Dict[str, Any]) -> str:
    out = [
        f"# Zero-Context Review — {payload['risk']}",
        f"snapshot: `{payload['snapshot_hash']}`", "",
        payload["instructions"], "", "## Risk reasons",
        *([f"- {r}" for r in payload["reasons"]] or ["- (none)"]), "", "## Changed functions",
    ]
    for f in payload["files"]:
        out.append(f"### {f['path']} ({f['risk']}, +{f['added']}/-{f['removed']})")
        for fn in f["functions"]:
            out.append(f"- `{fn['name']}` lines {fn['start']}-{fn['end']}")
            if fn.get("source"):
                out.extend(["```", fn["source"], "```"])
    out.extend(["", "## Diff", "```diff", payload["diff"].rstrip("\n"), "```", ""])
    return "\n".join(out)


def payload_paths(repo_root: Any, snapshot_hash: str) -> Dict[str, Path]:
    base = Path(repo_root).joinpath(*ZC_SUBDIR)
    key = snapshot_hash[:16]
    return {"payload_json": base / f"{key}.payload.json", "payload_md": base / f"{key}.payload.md", "result": base / f"{key}.result.json"}


def write_review_payload(repo_root: Any, payload: Dict[str, Any]) -> Dict[str, Path]:
    paths = payload_paths(repo_root, payload["snapshot_hash"])
    paths["payload_json"].parent.mkdir(parents=True, exist_ok=True)
    paths["payload_json"].write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["payload_md"].write_text(render_review_payload_markdown(payload), encoding="utf-8")
    return paths


# --- Session registry & correlation ----------------------------------------
def normalize_agent(name: Optional[str]) -> str:
    """Canonical writer agent name; anything unrecognized is ``unknown``."""
    key = re.sub(r"[\s_]+", "-", (name or "").strip().lower())
    aliases = {"claude": "claude-code", "claudecode": "claude-code", "agy": "antigravity", "gemini": "antigravity"}
    key = aliases.get(key, key)
    return key if key in KNOWN_AGENTS else "unknown"


def detect_writer_agent(payload: Optional[dict] = None) -> str:
    """Writer agent from the hook payload (``agent``/``agentName``) or ``GRAVITYGUARD_AGENT``."""
    if isinstance(payload, dict):
        for key in ("agent", "agentName"):
            if isinstance(payload.get(key), str):
                return normalize_agent(payload[key])
    return normalize_agent(os.environ.get("GRAVITYGUARD_AGENT"))


def _registry_path(root: Path) -> Path:
    return Path(root).joinpath(*ZC_REGISTRY)


def _load_registry(root: Path) -> Dict[str, Any]:
    try:
        data = json.loads(_registry_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        _reg_err = err
        data = {}
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("sessions"), dict):
        data["sessions"] = {}
    if not isinstance(data.get("snapshots"), dict):
        data["snapshots"] = {}
    return data


def _registry_update(root: Path, mutate) -> Any:
    """Read-modify-write the registry under a file lock; returns ``mutate(registry)``."""
    path = _registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with StateLock(path.with_suffix(".lock"), timeout=5.0):
        registry = _load_registry(root)
        result = mutate(registry)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    return result


def register_writer_session(repo_root: Any, session_id: str, agent: Optional[str], snapshot_hash: str = "") -> Dict[str, Any]:
    """Correlate ``session_id`` with the writing agent (and optionally a snapshot it produced)."""
    def mutate(reg):
        sess = reg["sessions"].setdefault(session_id, {"agent": "unknown", "fix_turns": 0, "snapshots": []})
        if normalize_agent(agent) != "unknown" or sess["agent"] == "unknown":
            sess["agent"] = normalize_agent(agent)
        if snapshot_hash:
            if snapshot_hash not in sess["snapshots"]:
                sess["snapshots"].append(snapshot_hash)
            reg["snapshots"].setdefault(snapshot_hash, {"status": STATUS_PENDING, "findings": []}).setdefault("session_id", session_id)
        return dict(sess)
    return _registry_update(Path(repo_root), mutate)


def get_session_record(repo_root: Any, session_id: str) -> Optional[Dict[str, Any]]:
    return _load_registry(Path(repo_root))["sessions"].get(session_id)


def get_snapshot_record(repo_root: Any, snapshot_hash: str) -> Optional[Dict[str, Any]]:
    return _load_registry(Path(repo_root))["snapshots"].get(snapshot_hash)


# --- Findings, feedback, anti-loop ------------------------------------------
def normalize_findings(raw: Any) -> List[Dict[str, Any]]:
    """Keep well-formed findings only: ``{file, line, type, suggestion}``."""
    if isinstance(raw, dict):
        raw = raw.get("findings")
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("file"), str) or not item["file"].strip():
            continue
        line = item.get("line")
        ftype = str(item.get("type", "other")).lower()
        out.append({
            "file": item["file"].strip(),
            "line": line if isinstance(line, int) and not isinstance(line, bool) and line > 0 else 0,
            "type": ftype if ftype in FINDING_TYPES else "other",
            "suggestion": str(item.get("suggestion", "")).strip(),
        })
    return out


def build_feedback_prompt(agent: str, findings: List[Dict[str, Any]], snapshot_hash: str, turn: int, max_turns: int) -> str:
    """Prompt addressed back to the writer agent with the reviewer's structured findings."""
    lines = [
        f"[GravityGuard Bağımsız İnceleme] {agent} için geri bildirim "
        f"(düzeltme turu {turn}/{max_turns}, snapshot {snapshot_hash[:12]}):",
    ]
    for i, f in enumerate(findings, 1):
        where = f"{f['file']}:{f['line']}" if f["line"] else f["file"]
        lines.append(f"{i}. [{f['type']}] {where} — {f['suggestion'] or 'açıklama yok'}")
    lines.append("Bu bulguları düzelt; ardından değişiklik yeniden incelenecek.")
    return "\n".join(lines)


def record_review_result(repo_root: Any, snapshot_hash: str, findings: Any, cfg: Optional[dict] = None) -> Dict[str, Any]:
    """Store a reviewer verdict and advance the anti-loop counter.

    A result for an already-decided snapshot is idempotent: it is returned as-is and
    does not consume another fix turn. Findings consume one fix turn of the writer
    session (which survives the snapshot hash changing after each fix); a clean
    verdict resets that session's counter.
    """
    root = Path(repo_root)
    max_turns = get_review_governance_config(cfg)["maxFixTurns"]
    clean = normalize_findings(findings)

    def mutate(reg):
        snap = reg["snapshots"].setdefault(snapshot_hash, {"status": STATUS_PENDING, "findings": []})
        sess = reg["sessions"].get(snap.get("session_id", ""))
        cached = snap["status"] != STATUS_PENDING
        if not cached:
            snap["findings"] = clean
            snap["status"] = STATUS_FINDINGS if clean else STATUS_PASSED
            snap["reviewed_at"] = int(time.time())
            if sess is not None:
                sess["fix_turns"] = sess["fix_turns"] + 1 if clean else 0
        turns = sess["fix_turns"] if sess is not None else (1 if clean and not cached else 0)
        return {"cached": cached, "snap": dict(snap), "turns": turns, "agent": sess["agent"] if sess is not None else "unknown"}

    res = _registry_update(root, mutate)
    status, turns, stored = res["snap"]["status"], res["turns"], res["snap"]["findings"]
    prompt = None
    if status == STATUS_FINDINGS:
        prompt = build_feedback_prompt(res["agent"], stored, snapshot_hash, min(turns, max_turns), max_turns)
    return {
        "status": status, "cached": res["cached"], "fix_turns": turns, "max_fix_turns": max_turns,
        "escalate": status == STATUS_FINDINGS and turns >= max_turns,
        "findings": stored, "feedback_prompt": prompt, "writer_agent": res["agent"],
    }


def ingest_result_file(repo_root: Any, snapshot_hash: str, cfg: Optional[dict] = None) -> Optional[Dict[str, Any]]:
    """Read the reviewer's ``<hash>.result.json`` (if present) and record it."""
    result_path = payload_paths(repo_root, snapshot_hash)["result"]
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        _res_err = err
        return None
    return record_review_result(repo_root, snapshot_hash, data, cfg)


def evaluate_zero_context_gate(
    repo_root: Any,
    cfg: Optional[dict] = None,
    session_id: str = "default",
    agent: Optional[str] = None,
) -> Dict[str, Any]:
    """Deterministic gate. ``action`` is one of:

    disabled | skip (risk below threshold / no diff) | passed | review_unavailable (no reviewer
    configured: never blocks) | review_required (only with ``requireReviewer``) |
    fix_required (feedback for the writer) | escalate (fix budget spent: human decides).
    ``block`` is True only for review_required / fix_required.
    """
    if not is_review_governance_enabled(cfg):
        return {"action": "disabled", "block": False}
    root = Path(repo_root)
    settings = get_review_governance_config(cfg)
    risk = classify_change_risk(root, settings["stagedOnly"], cfg)
    base = {"risk": risk["risk"], "snapshot_hash": risk["snapshot_hash"], "reasons": risk["reasons"], "block": False}
    if not risk["snapshot_hash"] or not risk_meets_threshold(risk["risk"], settings["minRisk"]):
        return {**base, "action": "skip"}

    sid = risk["snapshot_hash"]
    register_writer_session(root, session_id, agent, sid)
    snap = get_snapshot_record(root, sid) or {}
    if snap.get("status") == STATUS_PENDING:
        ingest_result_file(root, sid, cfg)
        snap = get_snapshot_record(root, sid) or {}

    if snap.get("status") == STATUS_PASSED:
        return {**base, "action": "passed"}
    if snap.get("status") == STATUS_FINDINGS:
        sess = get_session_record(root, session_id) or {"agent": "unknown", "fix_turns": 0}
        if sess["fix_turns"] >= settings["maxFixTurns"]:
            return {**base, "action": "escalate", "fix_turns": sess["fix_turns"], "findings": snap["findings"],
                    "message": f"Otomatik düzeltme sınırı doldu ({settings['maxFixTurns']} tur); insan incelemesi gerekli."}
        return {**base, "action": "fix_required", "block": True, "fix_turns": sess["fix_turns"], "findings": snap["findings"],
                "message": build_feedback_prompt(sess["agent"], snap["findings"], sid, sess["fix_turns"], settings["maxFixTurns"])}

    if not settings["requireReviewer"]:
        return {**base, "action": "review_unavailable", "status": "local_passed_ai_unavailable",
                "message": "İkinci AI inceleyicisi yapılandırılmamış (atlandı); yerel kontroller geçerli."}

    paths = write_review_payload(root, build_review_payload(root, settings["stagedOnly"], cfg))
    return {**base, "action": "review_required", "block": True,
            "payload_path": str(paths["payload_md"]), "result_path": str(paths["result"]),
            "message": (
                f"Sıfır Bağlamlı İnceleme ({risk['risk']}): taze bir inceleyici (Codex/yeni Claude oturumu) payload'ı okuyup "
                f"yalnızca diff'e dayanarak bulgularını {paths['result']} dosyasına JSON olarak yazmalı "
                f"([{{\"file\",\"line\",\"type\",\"suggestion\"}}] veya boş liste). Payload: {paths['payload_md']}"
            )}
