#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GravityGuard — Claude Code adapter.

Claude Code and Antigravity speak different hook dialects. This file translates between them and runs the UNCHANGED
engine (`engine/gravity-validator.py`) as a subprocess, so every rule, the state files and the audit log behave exactly
as they do under Antigravity.

    PreToolUse (Write | Edit | MultiEdit)  ->  engine PreToolUse payload  ->  deny / additionalContext / silent allow
    Stop                                   ->  engine `--stop` payload    ->  {"decision": "block"} or silent allow

What it does not cover: Bash. A shell command cannot be reliably reduced to "which lines were added to which file", so
a file written with `echo > x` or `sed -i` never reaches the file rules. The git pre-commit secret net and the Stop
hook are the backstops there.

Fail-open by design: when the engine cannot be started or gives no answer, the tool call proceeds and the reason goes to
stderr. A guard that wedges the agent on its own bug is worse than a guard that steps aside and says so.
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

# Claude Code tool name -> the engine's (Antigravity) tool name.
TOOL_MAP = {
    "Write": "write_to_file",
    "Edit": "replace_file_content",
    "MultiEdit": "multi_replace_file_content",
}


def engine_path() -> Path:
    override = os.environ.get("GRAVITYGUARD_ENGINE")
    return Path(override) if override else _DEFAULT_ENGINE


def conversation_id(event: Dict[str, Any]) -> str:
    """Provider-prefixed so a Claude Code session can never collide with an Antigravity conversation id."""
    return "claude:" + str(event.get("session_id") or "default")


def workspace_paths(event: Dict[str, Any]) -> List[str]:
    """The project directory Claude Code was started in; `cwd` drifts when the agent `cd`s, the project dir does not."""
    project = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
    return [str(project)]


def to_engine_pretool(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Translate a Claude Code PreToolUse event; None for tools the engine has no file rules for."""
    name = event.get("tool_name", "")
    if name not in TOOL_MAP:
        return None
    tool_input = event.get("tool_input") or {}
    target = tool_input.get("file_path", "")
    if name == "Write":
        args: Dict[str, Any] = {"TargetFile": target, "CodeContent": tool_input.get("content", "")}
    elif name == "Edit":
        args = {
            "TargetFile": target,
            "TargetContent": tool_input.get("old_string", ""),
            "ReplacementContent": tool_input.get("new_string", ""),
            "AllowMultiple": bool(tool_input.get("replace_all", False)),
        }
    else:
        args = {
            "TargetFile": target,
            "ReplacementChunks": [
                {
                    "TargetContent": edit.get("old_string", ""),
                    "ReplacementContent": edit.get("new_string", ""),
                    "AllowMultiple": bool(edit.get("replace_all", False)),
                }
                for edit in tool_input.get("edits") or []
                if isinstance(edit, dict)
            ],
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
    """deny -> Claude Code deny; an allow that carries a warning -> context for the model only.

    A warning must never become `permissionDecision: "allow"`: that would auto-approve the call and skip the user's own
    permission prompt for a write the user may well have wanted to see.
    """
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
        print(f"[GravityGuard Claude adapter] engine not found: {engine} (set GRAVITYGUARD_ENGINE)", file=sys.stderr)
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(engine), *extra_args],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=ENGINE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[GravityGuard Claude adapter] engine did not run: {exc}", file=sys.stderr)
        return None
    lines = proc.stdout.strip().splitlines()
    try:
        answer = json.loads(lines[-1]) if lines else None
    except ValueError:
        answer = None
    if not isinstance(answer, dict):
        print(f"[GravityGuard Claude adapter] engine gave no readable answer: {proc.stderr.strip()[:300]}", file=sys.stderr)
        return None
    return answer


def handle(event: Dict[str, Any], stop: bool) -> Optional[Dict[str, Any]]:
    """Claude Code event in, Claude Code answer out (None = say nothing, let it proceed)."""
    if stop:
        if event.get("stop_hook_active"):
            # Claude Code already continued once because of this hook; asking again would loop.
            return None
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
    if not isinstance(event, dict):
        return 0
    result = handle(event, stop="--stop" in argv)
    if result is not None:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
