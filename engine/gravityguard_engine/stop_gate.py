"""
GravityGuard Engine — Stop-hook helpers: debt ratchet findings, circuit-breaker blockers, session knowledge.

- ratchet_findings: working-tree files that grew past their accepted ceiling, each message carrying a refactoring blueprint.
- critical_blockers: what the circuit breaker must never wave through (ratchet regressions, a failing test run).
  Soft obligations (documentation, screenshots) are still forgiven after five retries.
- note_raised_rules / distill_session_knowledge: a session that was held up and then finished clean leaves one line in
  brain/knowledge.md, so the next agent reads what tripped the last one.
"""
import os
import sys
import time
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from .audit import log_event
from .debt_ratchet import evaluate_changed_files_ratchet, get_session_changed_files
from .governance import governance_transaction
from .project_context import resolve_complexity_thresholds
from .ratchet_growth import session_touched_files
from .refactor_hint import build_refactor_hint
from .test_evidence import evaluate_t0_gate

CRITICAL_TEST_RULE = "T0_TEST_RUN_FAILED"
KNOWLEDGE_PATH = ("brain", "knowledge.md")
KNOWLEDGE_HEADING = "## Otomatik Oturum Notları"
KNOWLEDGE_MAX_NOTES = 40


def ratchet_findings(
    project_root: Path, cfg: Optional[dict], conversation_id: str, shadow: bool, extra_files: Sequence[str] = (),
) -> List[Tuple[str, str]]:
    """Regressions as (relative path, message); logged here. In shadow mode they are only observed, never returned."""
    try:
        candidates = get_session_changed_files(str(project_root))
        # touched files outlive a commit: the agent may have committed the bloat before stopping
        candidates += [p for p in (*extra_files, *session_touched_files(project_root, conversation_id)) if p not in candidates]
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


def critical_blockers(project_root: Path, cfg: Optional[dict], conversation_id: str, shadow: bool) -> List[Tuple[str, str]]:
    """(rule id, message) pairs the circuit breaker may not override."""
    blockers = [("ARCH_RATCHET_REGRESSION", message) for _rel, message in ratchet_findings(project_root, cfg, conversation_id, shadow)]
    blockers += [(rule, msg) for rule, msg in evaluate_t0_gate(str(project_root), cfg) if rule == CRITICAL_TEST_RULE]
    return blockers


def note_raised_rules(project_root: Path, conversation_id: str, rule_ids: Iterable[str]) -> None:
    ids = sorted({r for r in rule_ids if r})
    if not ids:
        return
    with governance_transaction(project_root) as state:
        session = state.setdefault("sessions", {}).setdefault(conversation_id or "default", {"stop_retries": 0})
        session["raised_rules"] = sorted(set(session.get("raised_rules", [])) | set(ids))


def distill_session_knowledge(project_root: Path, conversation_id: str, forgiven: bool = False) -> Optional[str]:
    """Writes the one-line note for a session that was held up and then finished; returns it, or None.

    `forgiven`: the circuit breaker let it end with only soft obligations open, so the note must not claim they were resolved."""
    with governance_transaction(project_root) as state:
        session = state.get("sessions", {}).get(conversation_id or "default", {})
        raised = session.pop("raised_rules", [])
        session.pop("touched_files", None)  # the session is over: its ratchet scope ends with it
    knowledge = Path(project_root).joinpath(*KNOWLEDGE_PATH)
    if not raised or not knowledge.is_file():
        return None

    line = f"- {time.strftime('%Y-%m-%d')} · Oturumda aşılan engeller: {', '.join(raised)} — {'kritik olanlar çözüldü, yumuşak yükümlülükler devre kesiciyle affedildi' if forgiven else 'hepsi çözülerek kapatıldı'}."
    try:
        with open(knowledge, "r", encoding="utf-8", newline="") as fh:
            text = fh.read()
        eol = "\r\n" if "\r\n" in text else "\n"
        lines = text.replace("\r\n", "\n").split("\n")
        if KNOWLEDGE_HEADING not in lines:
            lines += ["", KNOWLEDGE_HEADING, ""]
        head = lines.index(KNOWLEDGE_HEADING)
        if line in lines:
            return None
        while lines and lines[-1] == "":
            lines.pop()
        lines.append(line)
        excess = len([i for i in range(head + 1, len(lines)) if lines[i].startswith("- ")]) - KNOWLEDGE_MAX_NOTES
        for _ in range(max(0, excess)):
            lines.pop(next(i for i in range(head + 1, len(lines)) if lines[i].startswith("- ")))
        tmp = f"{knowledge}.tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(eol.join(lines) + eol)
        os.replace(tmp, knowledge)
    except OSError as err:
        sys.stderr.write(f"[GravityGuard StopHook] Knowledge distillation failed: {err}\n")
        return None
    log_event("stop", "APPROVED", "brain/knowledge.md", line, rule_id="KNOWLEDGE_DISTILLED", conversation_id=conversation_id)
    return line
