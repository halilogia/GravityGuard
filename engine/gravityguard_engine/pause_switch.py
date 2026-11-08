"""User-owned pause switch: while active, rejections other than the mandatory security floor become allow + note.

The flag lives in the user's home (outside every project and outside the agent-writable plugin tree), so only the
human CLI/UI turns it on. It always expires (default 2 h, max 8 h) so it cannot be forgotten.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

DEFAULT_MINUTES = 120
MAX_MINUTES = 480
# Never relaxed by a pause, on top of policy_integrity.MANDATORY_RULES.
ALWAYS_ON = frozenset(("FINAL_SECURITY_SCAN",))
_RULE_IN_REASON = re.compile(r"\[([A-Z][A-Z0-9_]+)\]")


def flag_path() -> Path:
    override = os.environ.get("GRAVITYGUARD_PAUSE_FILE")
    return Path(override) if override else Path.home() / ".gravityguard" / "pause.json"


def pause(minutes: int = DEFAULT_MINUTES, reason: str = "", now: float | None = None) -> dict:
    minutes = max(1, min(int(minutes), MAX_MINUTES))
    start = time.time() if now is None else now
    state = {"until": start + minutes * 60, "minutes": minutes, "reason": reason[:200], "since": start}
    path = flag_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")
    return state


def resume() -> bool:
    try:
        flag_path().unlink()
        return True
    except OSError:
        return False


def status(now: float | None = None) -> dict | None:
    """The active pause state with `remaining` seconds, or None (missing, unreadable or expired)."""
    try:
        state = json.loads(flag_path().read_text(encoding="utf-8"))
        until = float(state["until"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    left = until - (time.time() if now is None else now)
    if left <= 0:
        return None
    state["remaining"] = int(left)
    return state


def relax_output(out: str, floor: frozenset) -> str:
    """Turn a non-mandatory rejection into an allow that still states what the rule would have said."""
    try:
        data = json.loads(out)
    except ValueError:
        return out
    if not isinstance(data, dict) or data.get("decision") not in ("deny", "block", "continue"):
        return out
    reason = str(data.get("reason", ""))
    match = _RULE_IN_REASON.search(reason)
    rule = match.group(1) if match else ""
    if rule in floor or rule in ALWAYS_ON or rule == "GUARD_UNAVAILABLE":
        return out
    return json.dumps({"decision": "allow", "reason": f"[GG_PAUSED] {reason}"})
