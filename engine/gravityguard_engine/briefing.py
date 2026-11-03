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
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from .rule_tips import TIPS

# Bookkeeping and compliance records, not mistakes (mirrors src/audit_stats.ts NON_VIOLATION_RULES).
_NOT_MISTAKES = {"PASS", "EXEMPT", "READ_ALLOW", "G7_TS_MANDATORY_FEEDBACK", "T1_PENDING", "DOC_OBLIGATION_PENDING"}
_MAX_LINE_BYTES = 64 * 1024


def _journal_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".gemini", "logs", "gravityguard_permanent_audit.jsonl")


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


def build_briefing(agent: str, days: int = 7, top: int = 4, journal: Optional[str] = None,
                   now: Optional[datetime] = None) -> str:
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--agent", required=True)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--top", type=int, default=4)
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    text = build_briefing(args.agent, days=args.days, top=args.top)
    if text:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
