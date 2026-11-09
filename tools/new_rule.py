#!/usr/bin/env python3
"""Create a drop-in rule file: python tools/new_rule.py MY_RULE_ID [--deny]

Writes engine/gravityguard_engine/rules/<my_rule_id>.py with working placeholders. Fill in pattern, message, tip and
the bad/good samples, then run: python -m unittest engine.tests.test_plugin_rules  (from the repo root).
"""
import argparse
import re
import sys
from pathlib import Path

TEMPLATE = '''"""TODO: one line on what this rule catches and why."""
from gravityguard_engine.plugin_rules import regex_rule

RULE = regex_rule(
    id="{rid}",
    pattern=r"TODO_REGEX",  # matched against each added line
    message="TODO: what is wrong, in one sentence.",
    tip="TODO: what to do instead, one imperative sentence.",
    example="",  # optional: a few tokens of correct code
    severity="{sev}",  # "warn" never blocks; "deny" blocks the edit
    extensions=(".py",),  # empty tuple = every file
    bad="TODO_REGEX\\n",  # sample that must trigger the rule
    good="nothing_to_see\\n",  # sample that must not
)
'''


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("rule_id", help="UPPER_SNAKE_CASE, at least 3 characters")
    ap.add_argument("--deny", action="store_true", help="block instead of warn (use sparingly)")
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", args.rule_id):
        print("rule id must be UPPER_SNAKE_CASE, e.g. NO_TODO_WITHOUT_OWNER", file=sys.stderr)
        return 2
    target = Path(__file__).resolve().parents[1] / "engine" / "gravityguard_engine" / "rules" / f"{args.rule_id.lower()}.py"
    if target.exists():
        print(f"{target} already exists", file=sys.stderr)
        return 1
    target.write_text(TEMPLATE.format(rid=args.rule_id, sev="deny" if args.deny else "warn"), encoding="utf-8")
    print(f"created {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
