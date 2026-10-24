#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GravityGuard — Claude Code adapter.

Claude Code and Antigravity speak different hook dialects. This file translates between them and runs the UNCHANGED
engine (`engine/gravity-validator.py`) as a subprocess, so every rule, the state files and the audit log behave exactly
as they do under Antigravity.

    PreToolUse (Write | Edit | MultiEdit | Read) -> engine PreToolUse payload -> deny / additionalContext / silent allow
    Stop                                   ->  engine `--stop` payload    ->  {"decision": "block"} or silent allow

What it only partly covers: Bash and PowerShell. A shell command cannot be reliably reduced to "which lines were added to
which file", so a file written with `echo > x` or `sed -i` never reaches the file rules. `shell_deny` still refuses the two
decidable cases (a secret literal in the command, a shell read of a live `.env`); the Stop hook (final diff guard, doc and
test obligations) is the backstop for the rest; there is no git-level secret scanner.

Fail-open by design: when the engine cannot be started or gives no answer, the tool call proceeds and the reason goes to
stderr. A guard that wedges the agent on its own bug is worse than a guard that steps aside and says so.
One exception: a secret about to be written to a file, or a live `.env` read, is denied by a small built-in check
(`emergency_deny`), because that harm cannot be undone. `GRAVITYGUARD_ADAPTER_FAIL_OPEN=1` turns the exception off.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_HERE = Path(__file__).resolve().parent
_DEFAULT_ENGINE = _HERE.parent.parent / "engine" / "gravity-validator.py"
ENGINE_TIMEOUT_SECONDS = 20

# Shared schema classifier is shipped alongside the engine.
sys.path.insert(0, str(_HERE.parent.parent / "engine"))
sys.path.insert(0, str(_HERE.parent))
from gravityguard_hook_safety import failure_response, emit_failure
try:
    from gravityguard_engine.operations import provider_tool_call
except (ImportError, SyntaxError):
    def provider_tool_call(name, args, cwd):
        return {"name": name, "args": args}

# Claude Code tool name -> the engine's (Antigravity) tool name.
TOOL_MAP = {
    "Write": "write_to_file",
    "Edit": "replace_file_content",
    "MultiEdit": "multi_replace_file_content",
    "Read": "read_file",
    # A notebook cell is not a file diff: the new cell source is checked as the text of a whole-file write.
    "NotebookEdit": "write_to_file",
}

# Last-resort secret shapes, used ONLY when the engine could not give an answer (see `emergency_deny`). A strict subset of
# the engine's G0: no placeholder logic, no entropy heuristics, so it can be wrong in the cautious direction only.
EMERGENCY_SECRET_PATTERNS = (
    ("özel anahtar başlığı", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b")),
    ("Anthropic API anahtarı", re.compile(r"\bsk-ant-(?:api|admin)\d{0,2}-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI API anahtarı", re.compile(r"\bsk-(?:proj|svcacct|admin)-[A-Za-z0-9_\-]{20,}")),
    ("AWS erişim anahtarı", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
)
_LIVE_ENV_NAME = re.compile(r"^\.env(\..+)?$", re.IGNORECASE)
_ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")
FAIL_OPEN_ENV = "GRAVITYGUARD_ADAPTER_FAIL_OPEN"


def engine_path() -> Path:
    override = os.environ.get("GRAVITYGUARD_ENGINE")
    return Path(override) if override else _DEFAULT_ENGINE


def conversation_id(event: Dict[str, Any]) -> str:
    """Provider-prefixed so a Claude Code session can never collide with an Antigravity conversation id."""
    return "claude:" + str(event.get("session_id") or "default")


def workspace_paths(event: Dict[str, Any]) -> List[str]:
    """The project directory Claude Code was started in; `cwd` drifts when the agent `cd`s, the project dir does not."""
    project = os.environ.get("CLAUDE_PROJECT_DIR")
    if not project:
        cwd = str(event.get("cwd") or os.getcwd())
        project = _find_project_root(Path(cwd)) or cwd
    return [str(project)]


def _find_project_root(start: Path) -> Optional[Path]:
    """Without CLAUDE_PROJECT_DIR: the nearest parent of `start` holding .git or .gravityguard.json (None if none)."""
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists() or (candidate / ".gravityguard.json").is_file():
            return candidate
    return None


def to_engine_pretool(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize file schemas; preserve unsupported calls for an explicit deny."""
    name = event.get("tool_name") or event.get("toolName") or ""
    tool_input = event.get("tool_input", event.get("toolInput", {}))
    if name == "NotebookEdit" and isinstance(tool_input, dict):
        # Cell insertion has no whole-notebook projection; retain the explicit
        # adapter that scans the proposed cell source for secrets.
        name = "write_to_file"
        tool_input = {"TargetFile": tool_input.get("notebook_path", ""),
                      "CodeContent": tool_input.get("new_source", "")}
    # A missing path on a bare read conveys no file access to check.
    if name in ("Read", "read_file") and tool_input == {}:
        return None
    call = provider_tool_call(name, tool_input, str(event.get("cwd") or os.getcwd()))
    if call is None:
        return None
    return {
        "toolCall": call,
        "conversationId": conversation_id(event),
        "workspacePaths": workspace_paths(event),
        "cwd": str(event.get("cwd") or os.getcwd()),
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
    # The audit log stays in the central ~/.gemini/logs (the Live Monitor watches it) unless the caller overrides it
    # through GRAVITYGUARD_LOG_DIR / GRAVITYGUARD_AUDIT_DIR.
    env = dict(os.environ)
    try:
        proc = subprocess.run(
            [sys.executable, str(engine), *extra_args],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=ENGINE_TIMEOUT_SECONDS,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[GravityGuard Claude adapter] engine did not run: {exc}", file=sys.stderr)
        return None
    lines = proc.stdout.strip().splitlines()
    try:
        answer = json.loads(lines[-1]) if lines else None
    except ValueError:
        answer = None
    if proc.returncode != 0 or not isinstance(answer, dict) or answer.get("decision") not in ("allow", "deny", "continue"):
        print(f"[GravityGuard Claude adapter] engine gave no readable answer: {proc.stderr.strip()[:300]}", file=sys.stderr)
        return None
    return answer


def added_text(event: Dict[str, Any]) -> str:
    """The text a Write/Edit/MultiEdit/NotebookEdit call would put into a file (what the engine's G0 looks at)."""
    tool_input = event.get("tool_input") or {}
    name = event.get("tool_name", "")
    if name == "Write":
        return str(tool_input.get("content") or "")
    if name == "Edit":
        return str(tool_input.get("new_string") or "")
    if name == "NotebookEdit":
        return str(tool_input.get("new_source") or "")
    if name == "MultiEdit":
        return "\n".join(str(e.get("new_string") or "") for e in tool_input.get("edits") or [] if isinstance(e, dict))
    return ""


def emergency_deny(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Engine gave no answer: still refuse the two things that must never slip through unchecked.

    A secret written to a file, or a live `.env` read, cannot be undone, so for those the adapter does not fail open.
    Everything else (style, tests, docs) still passes: a guard that wedges the agent on its own bug is worse.
    `GRAVITYGUARD_ADAPTER_FAIL_OPEN=1` switches this off when the engine is known to be broken and work must go on.
    """
    if os.environ.get(FAIL_OPEN_ENV) == "1":
        return None
    name = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    reason = ""
    if name == "Read":
        base = os.path.basename(str(tool_input.get("file_path") or "")).lower()
        if _LIVE_ENV_NAME.match(base) and not base.endswith(_ENV_TEMPLATE_SUFFIXES):
            reason = f"'{base}' canlı bir .env dosyası"
    elif name in TOOL_MAP:
        text = added_text(event)
        for label, pattern in EMERGENCY_SECRET_PATTERNS:
            if pattern.search(text):
                reason = f"yazılacak metinde {label} var"
                break
    if not reason:
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"🛑 [GravityGuard acil durum kontrolü]: Doğrulama motoru çalışmadığı için kural motoru devre dışı, ve {reason}. "
            "Bu işlem motor olmadan geçirilmiyor. Sırrı ortam değişkenine taşıyın veya motoru onarın "
            f"(bilerek devam etmek için {FAIL_OPEN_ENV}=1)."
        ),
    }}


SHELL_TOOLS = ("Bash", "PowerShell")
# A live .env named as an argument (not `.env.example` and friends), next to a verb that reads or copies it.
_ENV_TOKEN = re.compile(r"(?<![\w./\\-])(?:[\w./\\:-]*[/\\])?\.env(?:\.[\w-]+)?(?![\w.-])", re.IGNORECASE)
# One simple command at a time: the read verb must open the segment and the `.env` must be its argument, so a commit
# message or a `| tail` elsewhere in the line that merely mentions `.env` is not a read.
_SHELL_SEGMENT_SPLIT = re.compile(r"[;&|\n(`]+")
_ENV_READ_SEGMENT = re.compile(
    r"^\s*(?:sudo\s+)?(?:cat|type|less|more|head|tail|grep|rg|sed|awk|cp|copy|xxd|base64|source|Get-Content|gc|"
    r"Select-String|sls|Copy-Item|cpi|Import-Csv|\.)\s+(?P<args>.*)$",
    re.IGNORECASE,
)


def shell_deny(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Bash/PowerShell cannot be reduced to file diffs, but two things in the command text are still decidable.

    A secret literal in the command (it is about to land in a file, in shell history or in a remote) and a shell read of
    a live `.env` (the Read-tool check is useless if `cat .env` is open). Everything else passes, as before.
    """
    if os.environ.get(FAIL_OPEN_ENV) == "1":
        return None
    command = str((event.get("tool_input") or {}).get("command") or "")
    reason = ""
    for label, pattern in EMERGENCY_SECRET_PATTERNS:
        if pattern.search(command):
            reason = f"komutta {label} var"
            break
    if not reason:
        for segment in _SHELL_SEGMENT_SPLIT.split(command):
            read = _ENV_READ_SEGMENT.match(segment)
            for match in (_ENV_TOKEN.finditer(read.group("args")) if read else ()):
                name = os.path.basename(match.group(0).replace("\\", "/")).lower()
                if _LIVE_ENV_NAME.match(name) and not name.endswith(_ENV_TEMPLATE_SUFFIXES):
                    reason = f"'{name}' canlı bir .env dosyası ve komut onu okuyor"
                    break
            if reason:
                break
    if not reason:
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"[GravityGuard kabuk kontrolü]: {reason}. Sırrı ortam değişkeninden okuyun; "
            f"bilerek devam etmek için {FAIL_OPEN_ENV}=1."
        ),
    }}


def handle(event: Dict[str, Any], stop: bool) -> Optional[Dict[str, Any]]:
    """Claude Code event in, Claude Code answer out (None = say nothing, let it proceed)."""
    if stop:
        # `stop_hook_active` is deliberately ignored: it only says that Claude Code is already continuing because of
        # a Stop hook, and answering "allow" to it would let an agent leave after ONE extra turn without clearing its
        # obligations. The loop is bounded twice instead: the engine's own circuit breaker allows the stop after 5
        # blocked retries (per session), and Claude Code overrides a Stop hook that blocked 8 times in a row.
        answer = run_engine(to_engine_stop(event), ["--stop"])
        return from_engine_stop(answer) if answer else failure_response(stop=True)
    payload = to_engine_pretool(event)
    if payload is None:
        return None
    answer = run_engine(payload)
    if not answer:
        return emergency_deny(event) or failure_response()
    return from_engine_pretool(answer)


def main(argv: Sequence[str]) -> int:
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        event = json.load(sys.stdin)
    except ValueError:
        emit_failure(stop="--stop" in argv)
        return 0
    except RecursionError:
        print("[GravityGuard Claude adapter] hook payload nested too deeply to parse", file=sys.stderr)
        emit_failure(stop="--stop" in argv)
        return 0
    if not isinstance(event, dict):
        emit_failure(stop="--stop" in argv)
        return 0
    try:
        result = handle(event, stop="--stop" in argv)
    except Exception:
        emit_failure(stop="--stop" in argv)
        return 0
    if result is not None:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
