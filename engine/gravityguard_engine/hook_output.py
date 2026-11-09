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


def _action_from(value: dict | None) -> dict | None:
    """Accept the dispatcher's call context and return {tool, target, command, args}."""
    if not isinstance(value, dict):
        return None
    if "raw" not in value:
        return value
    try:
        payload = json.loads(value.get("raw") or "")
    except (ValueError, TypeError):
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    call = payload.get("toolCall") if isinstance(payload.get("toolCall"), dict) else {}
    args = call.get("args") if isinstance(call.get("args"), dict) else {}
    target = args.get("TargetFile") or args.get("target_file") or args.get("path") or args.get("file_path") or ""
    command = args.get("command") or args.get("CommandLine") or ""
    return {"tool": str(value.get("tool") or call.get("name") or ""), "target": str(target),
            "command": str(command), "args": args}


def _apply_approvals(out: str, action: dict | None) -> str:
    """Honour a user approval for this exact action, otherwise offer one. Never changes an allow."""
    try:
        from . import approvals
    except Exception as import_err:  # an unreadable ticket store must never decide an operation
        sys.stderr.write(f"[GravityGuard] approval store unavailable: {import_err}\n")
        return out
    action = _action_from(action)
    try:
        data = json.loads(out)
    except ValueError:
        return out
    if not isinstance(data, dict) or data.get("decision") not in ("deny", "block"):
        return out
    reason = str(data.get("reason", ""))
    rule = approvals.rule_of(reason)
    if not rule or rule == "GUARD_UNAVAILABLE":
        return out  # an engine failure is not a policy decision; approving it would approve nothing
    key = approvals.action_key(rule, action)
    live = approvals.approved(key)
    if live:
        approvals.consume(key)
        left = max(0, int(live.get("remaining") or 1) - 1)
        sys.stderr.write(f"[GravityGuard] user approval honoured: {key} ({rule}), uses left {left}\n")
        return json.dumps({"decision": "allow", "reason": f"[GG_APPROVED] {rule}: user approved this action ({key}). {reason}"})
    approvals.record_block(rule, reason, action)
    hint = (f"\nOnay: kullanıcı bu işlemi IDE bildirimindeki veya GravityGuard panelindeki 'Bir kez izin ver' "
            f"düğmesiyle açabilir (id {key}, tek kullanımlık, {approvals.DEFAULT_TTL_MINUTES} dk). "
            "Onay verilmezse kural yürürlükte kalır.")
    return json.dumps({**data, "reason": reason + hint})


def finalize(out: str, stop: bool, conversation_id: str, action: dict | None = None) -> str:
    """Rejections get their lesson; the first allowed call of a conversation gets the briefing.

    `action` identifies the call that produced `out` (tool, target, command) so a rejection can be
    matched to a user approval for that one action.
    """
    out = _apply_approvals(out, action)
    try:
        from . import pause_switch
        from .policy_integrity import MANDATORY_RULES

        if pause_switch.status():
            return pause_switch.relax_output(out, MANDATORY_RULES)
    except Exception as pause_err:
        sys.stderr.write(f"[GravityGuard] pause check failed: {pause_err}\n")
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
