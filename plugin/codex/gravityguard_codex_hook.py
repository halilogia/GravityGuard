#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GravityGuard — OpenAI Codex CLI adapter.

Translates Codex hook events into the engine's (Antigravity) dialect and runs the UNCHANGED engine
(`engine/gravity-validator.py`) as a subprocess, so rules, state files and the audit log behave as under Antigravity.

    PreToolUse (write_file | apply_diff | edit_file | read_file) -> engine PreToolUse payload -> deny / context / allow
    Stop (`--stop`)                                              -> engine `--stop` payload  -> block or allow

Fail-open by design: when the engine cannot be started or gives no answer, the tool call proceeds and the reason goes
to stderr. Bash is not covered; the Stop hook is the only backstop for files written through a shell.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_HERE = Path(__file__).resolve().parent
_DEFAULT_ENGINE = _HERE.parent.parent / "engine" / "gravity-validator.py"
ENGINE_TIMEOUT_SECONDS = 20

# Codex tool name -> the engine's (Antigravity) tool name.
TOOL_MAP = {
    "write_file": "write_to_file",
    "Write": "write_to_file",
    "apply_diff": "replace_file_content",
    "edit_file": "replace_file_content",
    "Edit": "replace_file_content",
    "read_file": "read_file",
    "Read": "read_file",
}
_READ_TOOLS = {"read_file", "Read"}
_WRITE_TOOLS = {"write_file", "Write"}


def engine_path() -> Path:
    override = os.environ.get("GRAVITYGUARD_ENGINE")
    return Path(override) if override else _DEFAULT_ENGINE


def conversation_id(event: Dict[str, Any]) -> str:
    """Provider-prefixed so a Codex session can never collide with an Antigravity or Claude Code conversation."""
    session = event.get("session_id") or event.get("sessionId")
    return "codex:" + str(session or "default")


def workspace_paths(event: Dict[str, Any]) -> List[str]:
    return [str(event.get("cwd") or os.getcwd())]


def _first(mapping: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if mapping.get(key) is not None:
            return mapping[key]
    return ""


def to_engine_pretool(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Translate a Codex PreToolUse event; None for tools the engine has no file rules for."""
    name = event.get("tool_name") or event.get("toolName") or ""
    if name not in TOOL_MAP:
        return None
    tool_input = event.get("tool_input") or event.get("toolInput") or {}
    if not isinstance(tool_input, dict):
        return None
    target = str(_first(tool_input, "file_path", "path", "target_file", "TargetFile") or "")
    if target and not os.path.isabs(target):
        cwd = str(event.get("cwd") or os.getcwd())
        target = os.path.abspath(os.path.join(cwd, target))
    if name in _READ_TOOLS:
        # Only the live-.env check matters for a read; skip the engine process for every other file.
        if "env" not in os.path.basename(target).lower():
            return None
        args: Dict[str, Any] = {"TargetFile": target}
    elif name in _WRITE_TOOLS:
        args = {"TargetFile": target, "CodeContent": _first(tool_input, "content", "contents", "text")}
    else:
        args = {
            "TargetFile": target,
            "TargetContent": _first(tool_input, "old_string", "old_str", "search"),
            "ReplacementContent": _first(tool_input, "new_string", "new_str", "replace"),
            "AllowMultiple": bool(tool_input.get("replace_all", False)),
        }
    return {
        "toolCall": {"name": TOOL_MAP[name], "args": args},
        "conversationId": conversation_id(event),
        "workspacePaths": workspace_paths(event),
    }


def to_engine_stop(event: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "terminationReason": "completed",
        "conversationId": conversation_id(event),
        "workspacePaths": workspace_paths(event),
    }


def from_engine_pretool(answer: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """deny -> Codex deny; an allow that carries a warning -> context for the model only (never an auto-approve)."""
    reason = str(answer.get("reason") or "")
    if answer.get("decision") == "deny":
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}
    if reason:
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": reason}}
    return None


def from_engine_stop(answer: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if answer.get("decision") == "continue":
        return {"decision": "block", "reason": str(answer.get("reason") or "")}
    return None


def run_engine(payload: Dict[str, Any], extra_args: Sequence[str] = ()) -> Optional[Dict[str, Any]]:
    """Run the engine; None (with a note on stderr) when it cannot be started or answers with something unreadable."""
    engine = engine_path()
    if not engine.is_file():
        print(f"[GravityGuard Codex adapter] engine not found: {engine} (set GRAVITYGUARD_ENGINE)", file=sys.stderr)
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(engine), *extra_args],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=ENGINE_TIMEOUT_SECONDS,
            env=dict(os.environ),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[GravityGuard Codex adapter] engine did not run: {exc}", file=sys.stderr)
        return None
    lines = proc.stdout.strip().splitlines()
    try:
        answer = json.loads(lines[-1]) if lines else None
    except ValueError:
        answer = None
    if not isinstance(answer, dict):
        print(f"[GravityGuard Codex adapter] engine gave no readable answer: {proc.stderr.strip()[:300]}", file=sys.stderr)
        return None
    return answer


def handle(event: Dict[str, Any], stop: bool) -> Optional[Dict[str, Any]]:
    """Codex event in, Codex answer out (None = say nothing, let it proceed)."""
    if stop:
        answer = run_engine(to_engine_stop(event), ["--stop"])
        return from_engine_stop(answer) if answer else None
    payload = to_engine_pretool(event)
    if payload is None:
        return None
    answer = run_engine(payload)
    return from_engine_pretool(answer) if answer else None


def main(argv: Sequence[str]) -> int:
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    except RecursionError:
        print("[GravityGuard Codex adapter] hook payload nested too deeply to parse; letting the call proceed", file=sys.stderr)
        return 0
    if not isinstance(event, dict):
        return 0
    try:
        result = handle(event, stop="--stop" in argv)
    except Exception as exc:  # fail-open: never wedge the agent on an adapter bug
        print(f"[GravityGuard Codex adapter] unexpected error: {exc}", file=sys.stderr)
        return 0
    if result is not None:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
