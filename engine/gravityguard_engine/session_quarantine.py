"""Per-conversation memory of file targets a file tool was denied, so the shell cannot be used to finish the same write.

Hook processes are short lived, so the set is persisted next to the other guard state. Every step is best effort: a
failure to read or write the store loses the quarantine, never the decision of the rule that already denied the write.
A later approved write of the same target lifts its quarantine: the denial was fixed through the file tool.
"""
import json
import os
import sys

_MAX_TARGETS_PER_CONVERSATION = 200
_MAX_CONVERSATIONS = 200


def normalize_target(path: str) -> str:
    return os.path.abspath(path).replace("\\", "/").lower()


def _store_path(log_dir: str | None) -> str:
    if not log_dir:
        from .audit import _resolve_log_dir

        log_dir = _resolve_log_dir()
    return os.path.join(log_dir, "denied_targets.json")


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def denied_targets(conversation_id: str, log_dir: str | None = None) -> list[str]:
    targets = _load(_store_path(log_dir)).get(conversation_id)
    return [t for t in targets if isinstance(t, str)] if isinstance(targets, list) else []


def session_logger(log_event, tool_name: str, conversation_id: str):
    """The dispatcher's `_log`: audit every event and remember file targets denied in this conversation."""
    def _log(status: str, target: str, reason: str, rule_id: str = "", evasion_markers=None) -> None:
        if status == "BLOCKED":
            record_denied_target(conversation_id, target)
        elif status == "APPROVED" and rule_id != "READ_ALLOW":
            forget_denied_target(conversation_id, target)  # the file tool accepted the corrected write: the denial is resolved
        log_event(tool_name, status, target, reason, rule_id=rule_id, conversation_id=conversation_id,
                  evasion_markers=evasion_markers)

    return _log


def forget_denied_target(conversation_id: str, target: str, log_dir: str | None = None) -> None:
    if not target or not os.path.isabs(target):
        return
    try:
        path = _store_path(log_dir)
        state = _load(path)
        known = state.get(conversation_id)
        norm = normalize_target(target)
        if not isinstance(known, list) or norm not in known:
            return
        state[conversation_id] = [t for t in known if t != norm]
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, path)
    except OSError as exc:
        print(f"[GravityGuard] denied-target store not updated: {exc}", file=sys.stderr)


def record_denied_target(conversation_id: str, target: str, log_dir: str | None = None) -> None:
    if not target or not os.path.isabs(target):
        return
    try:
        path = _store_path(log_dir)
        state = _load(path)
        known = state.get(conversation_id)
        known = known if isinstance(known, list) else []
        norm = normalize_target(target)
        if norm in known:
            return
        state.pop(conversation_id, None)  # re-insert so the newest conversations stay last
        state[conversation_id] = (known + [norm])[-_MAX_TARGETS_PER_CONVERSATION:]
        if len(state) > _MAX_CONVERSATIONS:
            state = dict(list(state.items())[-_MAX_CONVERSATIONS:])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, path)
    except OSError as exc:
        print(f"[GravityGuard] denied-target store not updated: {exc}", file=sys.stderr)
