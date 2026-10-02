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
from pathlib import Path
from typing import List, Tuple

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
        if errors:
            first_err = errors[0]
            err_summary = first_err.get("message", "Lint issue")
            rule = first_err.get("rule", "")
            rule_disp = f" [{rule}]" if rule else ""
            msg = (
                f"Statik Doğrulama Uyarısı (STATIC_LINTER_DIAGNOSTIC): '{tool}' önceki yazımda "
                f"{len(errors)} hata tespit etti{rule_disp}: {err_summary}"
            )
            return [("STATIC_LINTER_DIAGNOSTIC", msg)]
    except (IOError, OSError, json.JSONDecodeError, ValueError):
        return []

    return []


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
