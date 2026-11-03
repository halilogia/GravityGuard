#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GravityGuard — OpenCode adapter.

Translates OpenCode tool events into the engine's (Antigravity) dialect and runs the UNCHANGED engine
(`engine/gravity-validator.py`) as a subprocess, so rules, state files and the audit log behave as under Antigravity.

    PreToolUse (write | edit | multiedit | read | bash | patch) -> engine PreToolUse payload -> block / warn / allow
    Stop (`--stop`, fired on session.idle)                     -> engine `--stop` payload     -> block (advisory) / allow

The conversation id is prefixed with `opencode:`, so GravityGuard's live stream attributes every event to
OpenCode (`detect_agent_name` in the engine) instead of falling back to Antigravity IDE.

Fail-open by design: when the engine cannot be started or gives no answer, the tool call proceeds and the reason
goes to stderr. Bash is covered only for the shared shell-security and token guards; the Stop hook is the
backstop for files written through a shell.
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

# Shared schema classifier and fail-open helpers are shipped alongside the engine.
sys.path.insert(0, str(_HERE.parent.parent / "engine"))
sys.path.insert(0, str(_HERE.parent))
from gravityguard_hook_safety import failure_response
try:
    from gravityguard_engine.operations import provider_tool_call
except (ImportError, SyntaxError):
    def provider_tool_call(name, args, cwd):
        return {"name": name, "args": args}

# OpenCode tool name -> the engine's tool dialect. camelCase payloads are translated to engine keys first.
WRITE_TOOLS = {"write", "writefile", "create_file"}
EDIT_TOOLS = {"edit", "editfile"}
MULTI_EDIT_TOOLS = {"multiedit", "multi_edit"}
READ_TOOLS = {"read", "readfile"}
PATCH_TOOLS = {"patch", "apply_patch", "apply_diff"}


def engine_path() -> Path:
    override = os.environ.get("GRAVITYGUARD_ENGINE")
    return Path(override) if override else _DEFAULT_ENGINE


def failure_answer(stop: bool = False) -> Optional[Dict[str, Any]]:
    """Shared degraded-mode row, translated to the OpenCode plugin dialect."""
    raw = failure_response(stop)
    if raw is None:
        return None  # operator escape hatch (GRAVITYGUARD_ADAPTER_FAIL_OPEN=1)
    if stop:
        return {"block": True, "reason": str(raw.get("reason") or "")}
    reason = str(raw.get("hookSpecificOutput", {}).get("permissionDecisionReason") or "")
    return {"block": True, "reason": reason}


def emit_failure(stop: bool = False) -> None:
    answer = failure_answer(stop)
    if answer is not None:
        print(json.dumps(answer, ensure_ascii=False))


def conversation_id(event: Dict[str, Any]) -> str:
    """Provider-prefixed so an OpenCode session can never collide with an Antigravity, Claude or Codex conversation."""
    session = event.get("session_id") or event.get("sessionID") or event.get("sessionId")
    return "opencode:" + str(session or "default")


def workspace_paths(event: Dict[str, Any]) -> List[str]:
    return [str(event.get("cwd") or os.getcwd())]


def _tool_name(event: Dict[str, Any]) -> str:
    return str(event.get("tool") or event.get("tool_name") or event.get("toolName") or "")


def _tool_args(event: Dict[str, Any]) -> Dict[str, Any]:
    args = event.get("args", event.get("tool_input", event.get("toolInput", {})))
    return args if isinstance(args, dict) else {}


def _path_arg(args: Dict[str, Any]) -> str:
    for key in ("filePath", "file_path", "path", "TargetFile"):
        value = args.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _canonical_args(name: str, args: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    """Return (engine tool name, engine-shaped args).

    Unknown shapes are forwarded untouched on purpose: the engine's normalizer then answers with an explicit
    `[TOOL_SCHEMA_UNSUPPORTED]` deny instead of silently letting an unchecked write through.
    """
    target = _path_arg(args)
    if name in WRITE_TOOLS:
        content = args.get("content", args.get("contents"))
        if target and isinstance(content, str):
            return "write_to_file", {"TargetFile": target, "CodeContent": content}
    elif name in EDIT_TOOLS:
        old = args.get("oldString", args.get("old_string"))
        new = args.get("newString", args.get("new_string"))
        if target and isinstance(old, str) and isinstance(new, str):
            return "replace_file_content", {
                "TargetFile": target,
                "TargetContent": old,
                "ReplacementContent": new,
                "AllowMultiple": bool(args.get("replaceAll", args.get("replace_all", False))),
            }
    elif name in MULTI_EDIT_TOOLS:
        edits = args.get("edits")
        if target and isinstance(edits, list) and edits:
            chunks = []
            for chunk in edits:
                if not isinstance(chunk, dict):
                    return name, args
                old = chunk.get("oldString", chunk.get("old_string"))
                new = chunk.get("newString", chunk.get("new_string"))
                if not (isinstance(old, str) and isinstance(new, str)):
                    return name, args
                chunks.append({"old_string": old, "new_string": new})
            return "edit_file", {"filePath": target, "edits": chunks}
    elif name in READ_TOOLS:
        if target:
            return "read_file", {"TargetFile": target}
    elif name in PATCH_TOOLS:
        text = args.get("patchText", args.get("patch", args.get("diff")))
        if isinstance(text, str):
            # A unified diff cannot be checked as a file operation: the engine denies it explicitly.
            return "apply_diff", {"filePath": target or "patch", "diff": text}
    return name, args


def to_engine_pretool(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize file schemas; non-file tools are dropped, unreadable ones are preserved for an explicit deny."""
    name = _tool_name(event)
    args = _tool_args(event)
    if not name:
        return None
    cwd = str(event.get("cwd") or os.getcwd())
    engine_name, engine_args = _canonical_args(name.lower(), args)
    call = provider_tool_call(engine_name, engine_args, cwd)
    if call is None:
        return None
    return {
        "toolCall": call,
        "conversationId": conversation_id(event),
        "workspacePaths": workspace_paths(event),
        "cwd": cwd,
    }


def to_engine_stop(event: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "terminationReason": "completed",
        "conversationId": conversation_id(event),
        "workspacePaths": workspace_paths(event),
    }


def from_engine_pretool(answer: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """`block` aborts the tool call in OpenCode; a warning rides along as `reason` for the plugin to surface."""
    if not answer:
        return None
    reason = str(answer.get("reason") or "")
    if answer.get("decision") == "deny":
        return {"block": True, "reason": reason or "[GravityGuard] blocked by policy"}
    if reason:
        return {"block": False, "reason": reason}
    return None


def from_engine_stop(answer: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if answer and answer.get("decision") == "continue":
        return {"block": True, "reason": str(answer.get("reason") or "")}
    return None


def run_engine(payload: Dict[str, Any], extra_args: Sequence[str] = ()) -> Optional[Dict[str, Any]]:
    """Run the engine; None (with a note on stderr) when it cannot be started or answers with something unreadable."""
    engine = engine_path()
    if not engine.is_file():
        print(f"[GravityGuard OpenCode adapter] engine not found: {engine} (set GRAVITYGUARD_ENGINE)", file=sys.stderr)
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
        print(f"[GravityGuard OpenCode adapter] engine did not run: {exc}", file=sys.stderr)
        return None
    lines = proc.stdout.strip().splitlines()
    try:
        answer = json.loads(lines[-1]) if lines else None
    except ValueError:
        answer = None
    if proc.returncode != 0 or not isinstance(answer, dict) or answer.get("decision") not in ("allow", "deny", "continue"):
        print(f"[GravityGuard OpenCode adapter] engine gave no readable answer: {proc.stderr.strip()[:300]}", file=sys.stderr)
        return None
    return answer


def handle(event: Dict[str, Any], stop: bool) -> Optional[Dict[str, Any]]:
    """OpenCode event in, plugin answer out (None = say nothing, let it proceed)."""
    if stop:
        answer = run_engine(to_engine_stop(event), ["--stop"])
        return from_engine_stop(answer) if answer else failure_answer(stop=True)
    payload = to_engine_pretool(event)
    if payload is None:
        return None
    answer = run_engine(payload)
    return from_engine_pretool(answer) if answer else failure_answer()


def write_briefing(path: str) -> None:
    """Writes the OpenCode briefing to `path`, read by OpenCode as an `instructions` file. Empty file = nothing to say.

    OpenCode warnings only reach the server log, so a file in `instructions` is the one channel the model reads.
    """
    try:
        from gravityguard_engine.briefing import build_briefing
        text = build_briefing("OpenCode")
    except Exception as err:  # a failure only costs the briefing
        print(f"[GravityGuard OpenCode adapter] briefing unavailable: {err}", file=sys.stderr)
        return
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text + "\n" if text else "", encoding="utf-8")
    except OSError as err:
        print(f"[GravityGuard OpenCode adapter] briefing not written: {err}", file=sys.stderr)


def main(argv: Sequence[str]) -> int:
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if "--briefing-file" in argv:
        idx = list(argv).index("--briefing-file")
        if idx + 1 < len(argv):
            write_briefing(argv[idx + 1])
        return 0
    try:
        event = json.load(sys.stdin)
    except ValueError:
        emit_failure(stop="--stop" in argv)
        return 0
    except RecursionError:
        emit_failure(stop="--stop" in argv)
        print("[GravityGuard OpenCode adapter] hook payload nested too deeply to parse; letting the call proceed", file=sys.stderr)
        return 0
    if not isinstance(event, dict):
        emit_failure(stop="--stop" in argv)
        return 0
    try:
        result = handle(event, stop="--stop" in argv)
    except Exception as exc:  # fail-open: never wedge the agent on an adapter bug
        print(f"[GravityGuard OpenCode adapter] unexpected error: {exc}", file=sys.stderr)
        emit_failure(stop="--stop" in argv)
        return 0
    if result is not None:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
