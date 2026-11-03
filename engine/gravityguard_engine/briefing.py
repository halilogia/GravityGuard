"""Session-start briefing: the rules this agent tripped most in recent days, each with one "do this" line.

Rejections teach after the mistake; the briefing tells the agent before its first write. It is built from the permanent
audit journal, per agent, so each agent hears about its own weak spots. Output is short plain text meant for a hook's
additionalContext; an empty string means there is nothing worth saying.

    python -m gravityguard_engine.briefing --agent "Claude Code" [--days 7] [--top 4]
"""
import argparse
import json
import os
import sys
from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from .rule_tips import TIPS

# Bookkeeping and compliance records, not mistakes (mirrors src/audit_stats.ts NON_VIOLATION_RULES).
_NOT_MISTAKES = {"PASS", "EXEMPT", "READ_ALLOW", "G7_TS_MANDATORY_FEEDBACK", "T1_PENDING", "DOC_OBLIGATION_PENDING", "BRIEFING_SENT"}
_MAX_LINE_BYTES = 64 * 1024


def _journal_path() -> str:
    from .audit import (
        _resolve_log_dir,  # same journal the engine writes, test/CI redirection included
    )

    return os.path.join(_resolve_log_dir(), "gravityguard_permanent_audit.jsonl")


def _records(path: str) -> Iterable[dict]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if len(line) > _MAX_LINE_BYTES:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    yield rec
    except OSError:
        return


def build_briefing(agent: str, days: int = 7, top: int = 4, journal: str | None = None,
                   now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    mistakes: Counter = Counter()
    writes = clean = 0
    for rec in _records(journal or _journal_path()):
        if rec.get("agent") != agent:
            continue
        try:
            ts = datetime.fromisoformat(str(rec.get("timestamp")))
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts < since:
            continue
        rule = rec.get("ruleId") or ""
        status = rec.get("status")
        if rule == "PASS":
            writes += 1
            if rec.get("outcome") == "CLEAN":
                clean += 1
        elif status == "BLOCKED":
            writes += 1
        if status in ("BLOCKED", "WARNING") and rule not in _NOT_MISTAKES and rec.get("outcome") != "REPEATED_VIOLATION":
            mistakes[rule] += 1

    tipped = [(r, n) for r, n in mistakes.most_common() if r in TIPS][:top]
    if not tipped:
        return ""
    lines = [f"GravityGuard: son {days} günde en sık takıldığın kurallar. İlk yazımda bunlara uy:"]
    for rule, n in tipped:
        lines.append(f"- {rule}, {n} kez: {TIPS[rule][0]}")
    if writes:
        lines.append(f"İlk seferde temiz yazma oranın: %{round(clean * 100 / writes)}, {clean}/{writes} yazım.")
    return "\n".join(lines)


# Agents briefed through their own channel: a SessionStart hook (Claude Code, Codex) or an instructions file
# (OpenCode, whose hook warnings only reach the server log). The rest get it on their first allowed tool call.
_SESSION_HOOK_AGENTS = {"Claude Code", "Codex", "OpenCode"}
_MAX_BRIEFED = 300


def _attach(out: str, text: str) -> tuple[str, bool]:
    """Puts the briefing in front of the reason of the last allow/continue decision line. False when there is none."""
    lines = out.splitlines(keepends=True)
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except ValueError:
            continue
        if not isinstance(payload, dict) or payload.get("decision") not in ("allow", "continue"):
            return out, False
        reason = payload.get("reason")
        payload["reason"] = text + ("\n\n" + reason if isinstance(reason, str) and reason else "")
        lines[i] = json.dumps(payload) + ("\n" if lines[i].endswith("\n") else "")
        return "".join(lines), True
    return out, False


def record_briefing(conversation_id: str, text: str) -> None:
    """Marks the conversation as briefed in the journal, so the Insights tab can compare briefed and unbriefed sessions."""
    try:
        from .audit import log_event

        first_line = text.splitlines()[1] if len(text.splitlines()) > 1 else text
        log_event("briefing", "APPROVED", "", f"Session briefing sent: {first_line[:160]}",
                  rule_id="BRIEFING_SENT", conversation_id=conversation_id)
    except Exception as err:  # the mark only feeds a statistic
        sys.stderr.write(f"[GravityGuard] briefing not recorded: {err}\n")


def brief_first_call(out: str, conversation_id: str, log_dir: str | None = None) -> str:
    """Adds the agent's briefing to the first non-rejected tool call of a conversation; later calls pass unchanged."""
    from .audit import _resolve_log_dir, detect_agent_name

    agent = detect_agent_name(conversation_id)
    if agent in _SESSION_HOOK_AGENTS or not out:
        return out
    log_dir = log_dir or _resolve_log_dir()
    state_path = os.path.join(log_dir, "briefed_sessions.json")
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            seen = json.load(f)
        if not isinstance(seen, list):
            seen = []
    except (OSError, ValueError):
        seen = []
    if conversation_id in seen:
        return out
    text = build_briefing(agent, journal=os.path.join(log_dir, "gravityguard_permanent_audit.jsonl"))
    if text:
        out, attached = _attach(out, text)
        if not attached:  # a rejection already teaches; try again on the next call
            return out
        record_briefing(conversation_id, text)
    seen = (seen + [conversation_id])[-_MAX_BRIEFED:]
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(seen, f)
    except OSError as err:
        sys.stderr.write(f"[GravityGuard] could not record briefed session: {err}\n")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--agent", required=True)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--top", type=int, default=4)
    ap.add_argument("--out", help="write the briefing to this file instead of stdout (empty file when nothing to say)")
    args = ap.parse_args(argv)
    text = build_briefing(args.agent, days=args.days, top=args.top)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n" if text else "")
        return 0
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if text:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
