"""What the agent hears, decided after the rules ran: repeats dropped, lessons added to rejections, briefing on first call.

The rules decide allow / warn / deny; this module only shapes the text that goes back to the host. Every step is best
effort: a failure here costs the extra text, never the decision.
"""
import hashlib
import json
import os
import re
import sys

_DIGITS = re.compile(r"\d+")
_MAX_KEYS_PER_CONVERSATION = 400
_MAX_CONVERSATIONS = 200


def _state_path(log_dir: str | None) -> str:
    if not log_dir:
        from .audit import _resolve_log_dir

        log_dir = _resolve_log_dir()
    return os.path.join(log_dir, "warned_once.json")


def _warning_key(target_file: str, rule_id: str, message: str) -> str:
    # Counts change on every write ("1005 LOC", "3 hata") without changing what the agent should do.
    norm_file = (target_file or "").replace("\\", "/").lower()
    text = f"{norm_file}|{rule_id}|{_DIGITS.sub('#', message)}"
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def drop_repeated_warnings(warnings: list[tuple[str, str]], conversation_id: str, target_file: str,
                           log_dir: str | None = None) -> list[tuple[str, str]]:
    """Keeps only warnings not yet said in this conversation for this file. The audit log still records every one."""
    if not warnings:
        return warnings
    path = _state_path(log_dir)
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    said = state.get(conversation_id)
    said = said if isinstance(said, list) else []
    kept = []
    for rule_id, message in warnings:
        key = _warning_key(target_file, rule_id, message)
        if key in said:
            continue
        said.append(key)
        kept.append((rule_id, message))
    if not kept:  # nothing new to remember
        return kept
    state.pop(conversation_id, None)
    state[conversation_id] = said[-_MAX_KEYS_PER_CONVERSATION:]
    if len(state) > _MAX_CONVERSATIONS:  # oldest conversations first in insertion order
        state = dict(list(state.items())[-_MAX_CONVERSATIONS:])
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except OSError as err:
        sys.stderr.write(f"[GravityGuard] could not record said warnings: {err}\n")
    return kept


def finalize(out: str, stop: bool, conversation_id: str) -> str:
    """Rejections get their lesson; the first allowed call of a conversation gets the briefing."""
    try:
        from .rule_tips import enrich_hook_output

        out = enrich_hook_output(out)
    except Exception as tip_err:
        sys.stderr.write(f"[GravityGuard] rule tip failed: {tip_err}\n")
    if not stop:
        try:
            from .briefing import brief_first_call

            out = brief_first_call(out, conversation_id or "default")
        except Exception as brief_err:
            sys.stderr.write(f"[GravityGuard] briefing failed: {brief_err}\n")
    return out
