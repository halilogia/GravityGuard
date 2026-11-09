"""Drop-in rules: one small file per rule in `gravityguard_engine/rules/`, no dispatcher edit needed.

A rule file defines `RULE = regex_rule(...)` (pattern on added lines) or `RULE = Rule(...)` (own check function).
`bad` and `good` samples are mandatory; the test suite runs every rule against them. See CONTRIBUTING.md.
Rules are repo code that goes through review. Nothing is loaded from the user's home folder, so an agent cannot add
or switch off a rule for itself. A broken rule is skipped and reported on stderr, never allowed to crash the hook.
"""
from __future__ import annotations

import importlib
import json
import pkgutil
import re
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

from . import rule_tips

Hit = Tuple[int, str]  # (1-based line number, offending text)


@dataclass(frozen=True)
class Context:
    path: str
    ext: str
    added: Tuple[Hit, ...]  # only new or modified lines
    content: str  # whole file after the edit


@dataclass(frozen=True)
class Rule:
    id: str
    message: str
    tip: str
    check: Callable[[Context], Sequence[Hit]]
    bad: str  # sample content that must trigger the rule
    good: str  # sample content that must not
    severity: str = "warn"  # "warn" or "deny"
    extensions: Tuple[str, ...] = ()  # empty = every file
    example: str = ""
    sample_ext: str = ""  # extension used for the bad/good samples; defaults to the first of `extensions`
    skip_tests: bool = True  # test files are exempt unless the rule says otherwise


_ID = re.compile(r"[A-Z][A-Z0-9_]{2,}")


def regex_rule(id: str, pattern: str, message: str, tip: str, bad: str, good: str, **kw) -> Rule:
    """Rule that fires on any added line matching `pattern` (re.search, per line)."""
    rx = re.compile(pattern)

    def check(ctx: Context) -> List[Hit]:
        return [(n, text.strip()) for n, text in ctx.added if rx.search(text)]

    return Rule(id=id, message=message, tip=tip, check=check, bad=bad, good=good, **kw)


def validate(rule: Rule) -> Optional[str]:
    """Reason the rule definition is unusable, or None."""
    if not _ID.fullmatch(rule.id):
        return f"id '{rule.id}' must be UPPER_SNAKE_CASE"
    if rule.severity not in ("warn", "deny"):
        return "severity must be 'warn' or 'deny'"
    if not rule.message.strip() or not rule.tip.strip():
        return "message and tip must not be empty"
    if not rule.bad.strip() or not rule.good.strip():
        return "bad and good samples are required"
    return None


def load_rules() -> List[Rule]:
    from . import rules as pkg

    found: List[Rule] = []
    for info in pkgutil.iter_modules(pkg.__path__):
        if info.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{pkg.__name__}.{info.name}")
            for rule in ([mod.RULE] if hasattr(mod, "RULE") else list(getattr(mod, "RULES", []))):
                problem = validate(rule)
                if problem:
                    raise ValueError(problem)
                found.append(rule)
        except Exception as exc:  # a broken rule file must not take the hook down
            sys.stderr.write(f"[GravityGuard] rule file '{info.name}' skipped: {exc}\n")
    return found


def _is_test_path(path: str) -> bool:
    low = "/" + path.replace("\\", "/").lower().lstrip("/")
    base = low.rsplit("/", 1)[-1]
    return "/tests/" in low or "/test/" in low or base.startswith("test_") or ".test." in base or ".spec." in base


def _mode(rule_id: str, cfg: Optional[dict]) -> str:
    """'on', 'shadow' or 'off' from .gravityguard.json: {"rules": {"RULE_ID": "off" | "shadow" | {"mode": ...}}}."""
    entry = ((cfg or {}).get("rules") or {}).get(rule_id) if isinstance((cfg or {}).get("rules"), dict) else None
    mode = entry.get("mode") if isinstance(entry, dict) else entry
    return mode if mode in ("off", "shadow") else "on"


def evaluate(rules: Sequence[Rule], path: str, content: str, added_line_numbers, cfg: Optional[dict] = None
             ) -> List[Tuple[Rule, str, List[Hit], str]]:
    """Returns (rule, mode, hits, message) for every rule that fires. Pure function, no I/O."""
    ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] else ""
    lines = content.splitlines()
    added = tuple((n, lines[n - 1]) for n in sorted(added_line_numbers) if 0 < n <= len(lines))
    ctx = Context(path=path, ext=ext, added=added, content=content)
    out = []
    for rule in rules:
        mode = _mode(rule.id, cfg)
        if mode == "off" or (rule.extensions and ext not in rule.extensions) or (rule.skip_tests and _is_test_path(path)):
            continue
        try:
            hits = list(rule.check(ctx))
        except Exception as exc:
            sys.stderr.write(f"[GravityGuard] rule {rule.id} failed: {exc}\n")
            continue
        if hits:
            n, snippet = hits[0]
            extra = f" (+{len(hits) - 1} more)" if len(hits) > 1 else ""
            out.append((rule, mode, hits, f"line {n}: {rule.message}{extra}\nline: '{snippet[:120]}'"))
    return out


def apply_plugin_rules(path: str, content: str, added_line_numbers, cfg, log, all_warnings: list) -> None:
    """Dispatcher entry point: logs findings, appends warnings, prints a deny verdict and exits on a deny rule."""
    rules = load_rules()
    for rule in rules:
        rule_tips.TIPS.setdefault(rule.id, (rule.tip, rule.example))
    for rule, mode, _hits, message in evaluate(rules, path, content, added_line_numbers, cfg):
        if mode == "shadow":
            log("SHADOW_TRIGGER", path, f"[SHADOW] {message}", rule_id=rule.id)
        elif rule.severity == "deny":
            log("BLOCKED", path, message, rule_id=rule.id)
            print(json.dumps({"decision": "deny", "reason": f"[{rule.id}]: {message}" + rule_tips.lesson_text(rule.id)}))
            sys.exit(0)
        else:
            log("WARNING", path, message, rule_id=rule.id)
            all_warnings.append((rule.id, message))
