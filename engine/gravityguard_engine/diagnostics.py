#!/usr/bin/env python3
"""
GravityGuard Engine — Diagnostics Bridge & Async Static Linter Subsystem.
Zero external dependencies.
"""
import json
import os
import subprocess
import sys
import time
import zlib
from collections import Counter
from pathlib import Path
from typing import List, Optional, Set, Tuple

_CREATE_NO_WINDOW = 0x08000000


def _hidden_console_kwargs() -> dict:
    """Returns Popen kwargs that run a background process with no visible window."""
    kwargs = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs["creationflags"] = _CREATE_NO_WINDOW
        kwargs["startupinfo"] = startupinfo
    else:
        kwargs["start_new_session"] = True
    return kwargs


def read_recent_diagnostics(target_file: str) -> List[Tuple[str, str]]:
    """
    Reads background static diagnostics (.gravityguard/runtime/diagnostics.json)
    if available. Validates freshness against target file mtime / content hash.
    Execution latency: < 0.5 ms.
    Returns: List of (rule_id, warning_message)
    """
    if not target_file:
        return []

    diagnostics_path = None
    try:
        p = Path(target_file).resolve()
        for parent in [p.parent] + list(p.parents):
            cand = parent / ".gravityguard" / "runtime" / "diagnostics.json"
            if cand.is_file():
                diagnostics_path = cand
                break
    except (OSError, RuntimeError):
        return []

    if not diagnostics_path or not diagnostics_path.exists():
        return []
    if _is_scratch(Path(target_file), diagnostics_path.parents[2]):
        return []
    changed = _changed_lines(diagnostics_path, target_file)

    try:
        with open(diagnostics_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        entries = data.get("entries", {})
        norm_target = str(Path(target_file).resolve()).replace("\\", "/")

        matched_entry = None
        for path_key, entry in entries.items():
            norm_key = str(Path(path_key).resolve()).replace("\\", "/") if os.path.isabs(path_key) else path_key
            if norm_key == norm_target or norm_target.endswith(path_key.replace("\\", "/")):
                matched_entry = entry
                break

        if not matched_entry:
            return []

        # Freshness check: timestamp must be within last 600s
        entry_time = matched_entry.get("timestamp", 0)
        if time.time() - entry_time > 600:
            return []

        # Stale check: if file on disk has mtime newer than entry by > 2 seconds, diagnostic is likely stale
        if os.path.exists(target_file):
            file_mtime = os.path.getmtime(target_file)
            if file_mtime - entry_time > 2.0:
                return []

        tool = matched_entry.get("tool", "linter")
        errors = matched_entry.get("errors", [])
        if changed is not None:  # only what this edit touched; older findings are not the agent's to clean up now
            errors = [e for e in errors if not isinstance(e.get("line"), int) or e["line"] in changed]
        if errors:
            first_err = errors[0]
            err_summary = first_err.get("message", "Lint issue")
            rule = first_err.get("rule", "")
            rule_disp = f" [{rule}]" if rule else ""
            # One linter run is one finding: later writes to the same file within the freshness window used to
            # repeat it, which counted a single lint result up to a dozen times.
            signature = f"{entry_time}:{len(errors)}:{rule}:{err_summary}"
            if _already_reported(diagnostics_path, norm_target, signature):
                return []
            msg = (
                f"Statik doğrulama uyarısı: '{tool}' önceki yazımda "
                f"{len(errors)} hata tespit etti{rule_disp}: {err_summary}"
            )
            return [("STATIC_LINTER_DIAGNOSTIC", msg)]
    except (IOError, OSError, json.JSONDecodeError, ValueError):
        return []

    return []


_SCRATCH_DIRS = frozenset(("scratch", "tmp", "temp"))
_LINE_SNAPSHOT_CAP = 5000


def _is_scratch(target: Path, project_root: Path) -> bool:
    """Scratch/temp files are throwaway: their lint results are noise. Judged relative to the project, not the OS temp dir."""
    posix = str(target).replace("\\", "/").lower()
    if "/.gemini/antigravity/scratch/" in posix:
        return True
    try:
        rel_parts = target.resolve().relative_to(project_root.resolve()).parts[:-1]
    except (OSError, ValueError):
        return False
    return any(part.lower() in _SCRATCH_DIRS for part in rel_parts)


def _changed_lines(diagnostics_path: Path, target_file: str) -> Optional[Set[int]]:
    """1-based lines that differ from the file's snapshot at the previous check; None when there is no snapshot."""
    state_path = diagnostics_path.with_name("diagnostics_lines.json")
    key = str(Path(target_file).resolve()).replace("\\", "/")
    try:
        with open(target_file, "rb") as f:
            current = [zlib.crc32(line.strip()) for line in f.read().splitlines()][:_LINE_SNAPSHOT_CAP]
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
        state = state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return None
    previous = state.get(key)
    state.pop(key, None)
    state[key] = current
    try:
        state_path.write_text(json.dumps(dict(list(state.items())[-100:])), encoding="utf-8")
    except OSError as err:
        sys.stderr.write(f"[GravityGuard] could not record line snapshot: {err}\n")
    if not isinstance(previous, list):
        return None
    unused = Counter(previous)
    changed = set()
    for number, digest in enumerate(current, 1):
        if unused[digest] > 0:
            unused[digest] -= 1
        else:
            changed.add(number)
    return changed


def _already_reported(diagnostics_path: Path, norm_target: str, signature: str) -> bool:
    """True when this exact lint result was already reported for the file; records it otherwise."""
    state_path = diagnostics_path.with_name("diagnostics_reported.json")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    if state.get(norm_target) == signature:
        return True
    state[norm_target] = signature
    if len(state) > 500:  # keep the file small; the oldest entries are the least likely to repeat
        state = dict(list(state.items())[-250:])
    try:
        state_path.write_text(json.dumps(state), encoding="utf-8")
    except OSError as err:
        sys.stderr.write(f"[GravityGuard] could not record reported diagnostic: {err}\n")
    return False


def trigger_background_validation(target_file: str) -> None:
    """
    Spawns async_runner.py in a fully hidden background subprocess.
    Never blocks the AI tool-call loop: returns in ~1ms without waiting for completion.
    Only triggers for supported code files (.py, .ts, .tsx, .js, .jsx, .gd).
    """
    if not target_file:
        return

    # Kill switch: tests/CI disable all background spawning
    if os.environ.get("GRAVITYGUARD_DISABLE_ASYNC", "").strip() == "1":
        return

    file_lower = target_file.lower()
    if not file_lower.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".gd")):
        return

    # async_runner.py is located in engine/ (parent directory of gravityguard_engine)
    runner_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "async_runner.py")
    if not os.path.exists(runner_path):
        return

    try:
        subprocess.Popen(
            [sys.executable, runner_path, "--file", target_file],
            close_fds=True,
            **_hidden_console_kwargs()
        )
    except (OSError, ValueError):
        return
