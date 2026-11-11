#!/usr/bin/env python3
"""
GravityGuard Async Static Validation Runner (Tier 2 / Tier 3)
Executes lightweight linters in the background without blocking the AI tool-call loop.
Writes findings to .gravityguard/runtime/diagnostics.json for next-hook consumption.
Features state-based debouncing for TypeScript project batch checks (tsc --noEmit)
and per-file lint burst coalescing to eliminate redundant linter spawns.

Live copy: ~/.gemini/config/plugins/srp-swarm-guardian/scripts/async_runner.py
(kept under the same name as here). Two deployment targets, one source of truth
in this repo: edit here, and tools/sync_plugin.py copies it to the plugin on
every commit. Its sibling, gravity-validator.py, also keeps its name in the
plugin; the manifests that name the entry point (plugin/hooks.json,
plugin/plugin.json) are version controlled here too.
"""

import sys
import os
import re
import json
import time
import shutil
import argparse
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional


# ============================================================================
# UTF-8 STREAM HARDENING (Windows cp1252 defence)
# ============================================================================
def _harden_streams_to_utf8() -> None:
    """Forces stdin/stdout/stderr to UTF-8 with replacement (never raises)."""
    for stream_name in ("stdin", "stdout", "stderr"):
        try:
            getattr(sys, stream_name).reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError, LookupError):
            continue


_harden_streams_to_utf8()


from gravityguard_engine.async_process import _CREATE_NEW_PROCESS_GROUP, _CREATE_NO_WINDOW, _hidden_popen_kwargs, _hidden_startupinfo, _kill_process_tree, run_hidden  # noqa: F401 (re-export)
from gravityguard_engine.async_state import _PROJECT_ROOT_MARKERS, _has_project_marker, _is_ancestor_or_self, find_project_root, get_debounce_file_path, get_diagnostics_file_path, get_runtime_dir, is_trusted_project_root, load_debounce_state, load_diagnostics, save_debounce_state, save_diagnostics  # noqa: F401 (re-export)
from gravityguard_engine.async_linter import (  # noqa: F401 (re-export)
    parse_tsc_output,
    run_ruff,
    run_eslint,
    run_godot_check,
    run_batch_tsc,
)


# ============================================================================
# PURE DECISION HELPERS (Deterministic, 0-ms & Unit-Testable)
# ============================================================================

def should_run_after_idle(last_edit_time: float, current_time: float, idle_threshold: float = 3.0) -> bool:
    """Returns True if the quiet window (idle_threshold) has elapsed since the last edit."""
    if last_edit_time <= 0.0:
        return False
    return (current_time - last_edit_time) >= (idle_threshold - 1e-6)


def should_spawn_worker(worker_already_running: bool) -> bool:
    """Returns True when no batch worker is already claimed in the persisted state."""
    return not worker_already_running


def should_spawn_file_worker(active_workers: Dict[str, bool], file_key: str) -> bool:
    """Returns True if no lint worker is currently active for this specific file."""
    return not active_workers.get(file_key, False)


def async_spawning_disabled() -> bool:
    """True when background process spawning is disabled via environment."""
    return os.environ.get("GRAVITYGUARD_DISABLE_ASYNC", "").strip() == "1"


def should_run_file_lint(last_edit_time: float, current_time: float, coalesce_window: float = 0.3) -> bool:
    """Returns True if file edit activity has settled past the coalesce window (300ms)."""
    if last_edit_time <= 0.0:
        return True
    return (current_time - last_edit_time) >= (coalesce_window - 1e-6)


def clean_file_state(state: Dict[str, Any], file_key: str) -> None:
    """Cleans up active worker and edit timestamps after lint completion so state stays minimal."""
    state.setdefault("active_lint_workers", {}).pop(file_key, None)
    state.setdefault("file_edits", {}).pop(file_key, None)


def should_wait_for_target_file(target_exists: bool, waited_seconds: float,
                               grace_period: float = 2.0) -> bool:
    """Returns True while the target file is still missing and grace remains."""
    if target_exists:
        return False
    return waited_seconds < (grace_period - 1e-6)


# ============================================================================
# LINT & BATCH WORKERS (With Quiet-Window Coalescing)
# ============================================================================

def execute_single_file_lint(target_file: str, project_root: Path, diag_path: Path) -> None:
    """Executes the specific linter for the given file and updates diagnostics.json."""
    if not os.path.exists(target_file):
        return

    norm_key = str(Path(target_file).resolve()).replace("\\", "/")
    file_lower = target_file.lower()
    tool_name = None
    errors = None

    if file_lower.endswith(".py"):
        tool_name = "ruff"
        errors = run_ruff(target_file)
    elif file_lower.endswith((".ts", ".tsx", ".js", ".jsx")):
        tool_name = "eslint"
        errors = run_eslint(target_file, project_root)
        trigger_debounce_worker_if_needed(project_root)
    elif file_lower.endswith(".gd"):
        tool_name = "godot"
        errors = run_godot_check(target_file)

    if tool_name and errors is not None:
        state = load_diagnostics(diag_path)
        entries = state.setdefault("entries", {})
        if errors:
            entries[norm_key] = {
                "tool": tool_name,
                "timestamp": time.time(),
                "errors": errors[:5]
            }
        else:
            entries.pop(norm_key, None)
        save_diagnostics(diag_path, state)


def _await_target_file(target_file: str, poll_interval: float, grace_period: float) -> bool:
    """Polls (bounded) for target_file to appear; returns True once it exists."""
    waited = 0.0
    while should_wait_for_target_file(os.path.exists(target_file), waited, grace_period):
        time.sleep(poll_interval)
        waited += poll_interval
    return os.path.exists(target_file)


def run_coalesced_file_lint_worker(target_file: str, project_root: Path,
                                   coalesce_window: float = 0.3,
                                   grace_period: float = 2.0) -> None:
    """
    Coalesces rapid successive edits on the same file.
    Waits until no edits have occurred on target_file for coalesce_window (300ms),
    then executes the linter once on the final file state and cleans up state.
    """
    debounce_path = get_debounce_file_path(project_root)
    diag_path = get_diagnostics_file_path(project_root)
    norm_key = str(Path(target_file).resolve()).replace("\\", "/")

    while True:
        time.sleep(coalesce_window)
        state = load_debounce_state(debounce_path)
        file_edits = state.get("file_edits", {})
        last_edit = file_edits.get(norm_key, 0.0)
        now = time.time()

        if should_run_file_lint(last_edit, now, coalesce_window):
            if not _await_target_file(target_file, coalesce_window, grace_period):
                clean_file_state(state, norm_key)
                save_debounce_state(debounce_path, state)
                return

            execute_single_file_lint(target_file, project_root, diag_path)
            clean_file_state(state, norm_key)
            save_debounce_state(debounce_path, state)
            break
        else:
            continue


def run_debounce_worker(project_root: Path, idle_threshold: float = 3.0,
                        max_lifetime: float = 120.0) -> None:
    """
    Background worker loop that waits for a quiet window (e.g. 3.0s idle)
    before triggering project-wide tsc --noEmit and writing per-file entries.
    """
    debounce_path = get_debounce_file_path(project_root)
    diag_path = get_diagnostics_file_path(project_root)
    started_at = time.time()

    while True:
        time.sleep(idle_threshold)

        if (time.time() - started_at) > max_lifetime:
            if debounce_path.exists():
                expired_state = load_debounce_state(debounce_path)
                expired_state["worker_running"] = False
                save_debounce_state(debounce_path, expired_state)
            return

        if not project_root.exists():
            return

        if not debounce_path.exists():
            return

        state = load_debounce_state(debounce_path)
        last_edit = state.get("last_edit_time", 0.0)
        now = time.time()

        if last_edit <= 0.0:
            state["worker_running"] = False
            save_debounce_state(debounce_path, state)
            return

        if should_run_after_idle(last_edit, now, idle_threshold):
            file_errors_map = run_batch_tsc(project_root)
            state["worker_running"] = False
            save_debounce_state(debounce_path, state)

            if file_errors_map is not None:
                diag = load_diagnostics(diag_path)
                entries = diag.setdefault("entries", {})

                tsc_keys_to_clear = [k for k, v in entries.items() if v.get("tool") == "tsc"]
                for k in tsc_keys_to_clear:
                    entries.pop(k, None)

                for f_path, errs in file_errors_map.items():
                    if errs:
                        entries[f_path] = {
                            "tool": "tsc",
                            "timestamp": time.time(),
                            "errors": errs[:5]
                        }

                total_err_count = sum(len(errs) for errs in file_errors_map.values())
                if total_err_count > 0:
                    entries["[project-tsc]"] = {
                        "tool": "tsc",
                        "timestamp": time.time(),
                        "errors": [{"line": 1, "rule": "TypeScriptCompiler", "message": f"TypeScript project has {total_err_count} compile error(s)"}]
                    }
                else:
                    entries.pop("[project-tsc]", None)

                save_diagnostics(diag_path, diag)
            return


def trigger_debounce_worker_if_needed(project_root: Path) -> None:
    """Spawns the (hidden) debounce worker process if one is not already active."""
    if async_spawning_disabled():
        return

    debounce_path = get_debounce_file_path(project_root)
    state = load_debounce_state(debounce_path)
    state["last_edit_time"] = time.time()

    if should_spawn_worker(state.get("worker_running", False)):
        state["worker_running"] = True
        save_debounce_state(debounce_path, state)

        runner_script = os.path.abspath(__file__)
        try:
            subprocess.Popen(
                [sys.executable, runner_script, "--debounce-worker", "--project", str(project_root)],
                **_hidden_popen_kwargs()
            )
        except (OSError, ValueError):
            state["worker_running"] = False
            save_debounce_state(debounce_path, state)
    else:
        save_debounce_state(debounce_path, state)


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="GravityGuard Async Linter Runner")
    parser.add_argument("--file", help="Changed file path to validate")
    parser.add_argument("--project", help="Project root directory")
    parser.add_argument("--batch-tsc", action="store_true", help="Run project-wide tsc --noEmit immediately")
    parser.add_argument("--debounce-worker", action="store_true", help="Run background debounced tsc worker")
    args = parser.parse_args()

    if args.debounce_worker:
        p_root = Path(args.project).resolve() if args.project else Path.cwd()
        run_debounce_worker(p_root)
        sys.exit(0)

    if not args.file and not args.batch_tsc:
        sys.exit(0)

    target_file = args.file or ""
    project_root = find_project_root(target_file) if target_file else Path.cwd()
    diag_path = get_diagnostics_file_path(project_root)
    debounce_path = get_debounce_file_path(project_root)

    if args.batch_tsc:
        file_errors_map = run_batch_tsc(project_root)
        if file_errors_map is not None:
            diag = load_diagnostics(diag_path)
            entries = diag.setdefault("entries", {})
            for f_path, errs in file_errors_map.items():
                if errs:
                    entries[f_path] = {
                        "tool": "tsc",
                        "timestamp": time.time(),
                        "errors": errs[:5]
                    }
            save_diagnostics(diag_path, diag)
        sys.exit(0)

    norm_key = str(Path(target_file).resolve()).replace("\\", "/")
    debounce_state = load_debounce_state(debounce_path)
    file_edits = debounce_state.setdefault("file_edits", {})
    active_workers = debounce_state.setdefault("active_lint_workers", {})

    now = time.time()
    file_edits[norm_key] = now

    if should_spawn_file_worker(active_workers, norm_key):
        active_workers[norm_key] = True
        save_debounce_state(debounce_path, debounce_state)
        run_coalesced_file_lint_worker(target_file, project_root, coalesce_window=0.3)
    else:
        save_debounce_state(debounce_path, debounce_state)
        sys.exit(0)


if __name__ == "__main__":
    main()
