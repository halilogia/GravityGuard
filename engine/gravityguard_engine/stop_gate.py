"""
GravityGuard Engine — Stop-hook helpers: debt ratchet findings, circuit-breaker blockers, session knowledge.

- ratchet_findings: working-tree files that grew past their accepted ceiling, each message carrying a refactoring blueprint.
- critical_blockers: what the circuit breaker must never wave through (a failing test run).
  Soft obligations (documentation, screenshots, ratchet regressions) are forgiven after five retries.
"""
import os
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from .audit import log_event
from .debt_ratchet import (
    SCAN_SOURCE_SUFFIXES,
    evaluate_changed_files_ratchet,
    get_session_changed_files,
    to_project_rel_path,
)
from .governance import governance_transaction, load_governance_state
from .project_context import resolve_complexity_thresholds
from .refactor_hint import build_refactor_hint
from .test_evidence import evaluate_t0_gate

CRITICAL_TEST_RULE = "T0_TEST_RUN_FAILED"
MAX_TOUCHED_FILES = 500


def other_stop_roots(payload: dict, primary: Path) -> List[Path]:
    """Other roots of a multi-root window that already keep governance state, for the Stop check.

    A Stop carries no target file, so the primary root is only the first declared workspace; a conversation that edited
    the second root would otherwise end with its obligations unseen. Only roots that already have a state file are
    returned (the check never creates state in a root this conversation did not touch), and obligations are session
    scoped, so another conversation's debt in those roots is not seen either. With the log-directory override
    (tests, isolated runs) the single override root is used as before.
    """
    if os.environ.get("GRAVITYGUARD_LOG_DIR"):
        return []
    workspaces = payload.get("workspacePaths", [])
    if not isinstance(workspaces, list):
        return []
    try:
        seen = {str(primary.resolve()).lower()}
    except OSError:
        seen = set()
    roots: List[Path] = []
    for ws in workspaces:
        if not ws:
            continue
        candidate = Path(str(ws))
        try:
            key = str(candidate.resolve()).lower()
        except OSError:
            continue
        if key in seen or not candidate.is_dir():
            continue
        seen.add(key)
        if (candidate / ".gravityguard" / "runtime" / "governance.json").is_file():
            roots.append(candidate)
    return roots


def note_touched_file(project_root: Path, conversation_id: str, file_path: str) -> None:
    """Remember a file this conversation wrote (governance.json), so the Stop check still sees it after `git commit`."""
    rel = to_project_rel_path(str(project_root), file_path)
    if rel.startswith("../") or os.path.isabs(rel) or not rel.lower().endswith(SCAN_SOURCE_SUFFIXES):
        return
    with governance_transaction(project_root) as state:
        session = state.setdefault("sessions", {}).setdefault(conversation_id or "default", {"stop_retries": 0})
        touched = session.setdefault("touched_files", [])
        if rel not in touched:
            touched.append(rel)
            del touched[:-MAX_TOUCHED_FILES]


def session_touched_files(project_root: Path, conversation_id: str) -> List[str]:
    """Absolute paths of the existing files this conversation wrote."""
    session = load_governance_state(project_root).get("sessions", {}).get(conversation_id or "default", {})
    names = session.get("touched_files", []) if isinstance(session, dict) else []
    paths = (os.path.normpath(os.path.join(str(project_root), n)) for n in names if isinstance(n, str))
    return [p for p in paths if os.path.isfile(p)]


def ratchet_findings(
    project_root: Path, cfg: Optional[dict], conversation_id: str, shadow: bool, extra_files: Sequence[str] = (),
) -> List[Tuple[str, str]]:
    """Regressions as (relative path, message); logged here. In shadow mode they are only observed, never returned."""
    try:
        candidates = get_session_changed_files(str(project_root))
        candidates += [p for p in (*session_touched_files(project_root, conversation_id), *extra_files) if p not in candidates]
        found = evaluate_changed_files_ratchet(
            str(project_root), candidates, threshold=resolve_complexity_thresholds(cfg)["ratchetLoc"])
    except Exception as err:  # an advisory scan must never take the Stop hook down
        sys.stderr.write(f"[GravityGuard StopHook] Ratchet check error: {err}\n")
        return []

    findings = []
    for rel, _base, _delta, message in found:
        try:
            hint = build_refactor_hint((Path(project_root) / rel).read_text(encoding="utf-8", errors="ignore"), rel)
        except OSError:
            hint = ""
        message = f"{message} {hint}".strip()
        if shadow:
            log_event("stop", "SHADOW_TRIGGER", rel, f"[SHADOW] {message}", rule_id="ARCH_RATCHET_REGRESSION", conversation_id=conversation_id)
        else:
            # target = the file itself, so a later clean write to it supersedes the warning on the Live tab
            log_event("stop", "WARNING", rel, message, rule_id="ARCH_RATCHET_REGRESSION", conversation_id=conversation_id)
            findings.append((rel, message))
    return findings


def critical_blockers(project_root: Path, cfg: Optional[dict]) -> List[Tuple[str, str]]:
    """(rule id, message) pairs the circuit breaker may not override. A ratchet regression is only a warning."""
    return [(rule, msg) for rule, msg in evaluate_t0_gate(str(project_root), cfg) if rule == CRITICAL_TEST_RULE]


