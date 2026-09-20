#!/usr/bin/env python3
"""
GravityGuard Async Static Validation Runner (Tier 2 / Tier 3)
Executes lightweight linters in the background without blocking the AI tool-call loop.
Writes findings to .gravityguard/runtime/diagnostics.json for next-hook consumption.
Features state-based debouncing for TypeScript project batch checks (tsc --noEmit)
and per-file lint burst coalescing to eliminate redundant linter spawns.
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
# HIDDEN SUBPROCESS POLICY (Single Source of Truth)
# ============================================================================
# On Windows a background-spawned console program (npx -> cmd.exe -> node,
# ruff.exe, godot.exe) flashes a visible terminal window unless the console is
# suppressed at creation time. CREATE_NO_WINDOW (0x08000000) grants a *hidden*
# console which every descendant inherits. DETACHED_PROCESS is deliberately
# avoided: it leaves the process with no console, so each console child would
# allocate its own brand-new *visible* window.
_CREATE_NO_WINDOW = 0x08000000
_CREATE_NEW_PROCESS_GROUP = 0x00000200


def _hidden_startupinfo() -> "subprocess.STARTUPINFO":
    """STARTUPINFO that keeps the child window hidden (Windows only)."""
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return startupinfo


def _hidden_popen_kwargs() -> Dict[str, Any]:
    """Popen kwargs for a fire-and-forget process that must never show a window."""
    kwargs: Dict[str, Any] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = _CREATE_NO_WINDOW
        kwargs["startupinfo"] = _hidden_startupinfo()
    else:
        kwargs["start_new_session"] = True
    return kwargs


def _kill_process_tree(proc: subprocess.Popen) -> bool:
    """Force-kills a timed-out process *and its descendants* (Windows-safe).

    Killing only the direct child leaves orphaned cmd.exe/node.exe grandchildren
    behind, so on Windows we walk the tree with taskkill /T. Returns True when a
    termination attempt was issued, False when the tree could not be reached.
    """
    issued = False
    if sys.platform == "win32" and proc.poll() is None:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_CREATE_NO_WINDOW,
                startupinfo=_hidden_startupinfo(),
            )
            issued = True
        except (OSError, subprocess.SubprocessError) as exc:
            # taskkill missing or refused (e.g. process already gone): fall back
            # to a direct kill below and report the failure to the caller.
            _ = exc
    try:
        proc.kill()
        issued = True
    except OSError as exc:
        _ = exc
    return issued


def run_hidden(cmd: List[str], cwd: Optional[Path] = None, timeout: float = 10) -> Optional[subprocess.CompletedProcess]:
    """Runs a linter command silently; no console window ever appears.

    Returns a CompletedProcess (.stdout/.stderr/.returncode), or None when the
    command times out or cannot be launched.
    """
    popen_kwargs: Dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "stdin": subprocess.DEVNULL,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if cwd is not None:
        popen_kwargs["cwd"] = str(cwd)
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP
        popen_kwargs["startupinfo"] = _hidden_startupinfo()

    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
    except (OSError, ValueError):
        return None

    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        try:
            out, err = proc.communicate(timeout=5)
        except (subprocess.TimeoutExpired, ValueError):
            return None

    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


# ============================================================================
# PURE DECISION HELPERS (Deterministic, 0-ms & Unit-Testable)
# ============================================================================

def should_run_after_idle(last_edit_time: float, current_time: float, idle_threshold: float = 3.0) -> bool:
    """Returns True if the quiet window (idle_threshold) has elapsed since the last edit."""
    if last_edit_time <= 0.0:
        return False
    return (current_time - last_edit_time) >= (idle_threshold - 1e-6)


def should_spawn_worker(worker_already_running: bool) -> bool:
    """Returns True when no batch worker is already claimed in the persisted state.

    This is state-based duplicate suppression, not a mutex: concurrent callers can
    in principle both observe an unclaimed state. For the sequential tool-call loop
    GravityGuard serves, that window is not reachable in practice, but the guarantee
    is best-effort rather than formally atomic.
    """
    return not worker_already_running


def should_spawn_file_worker(active_workers: Dict[str, bool], file_key: str) -> bool:
    """Returns True if no lint worker is currently active for this specific file."""
    return not active_workers.get(file_key, False)


def async_spawning_disabled() -> bool:
    """True when background process spawning is disabled via environment.

    Tests and CI set GRAVITYGUARD_DISABLE_ASYNC=1 so the suite never launches real
    background workers. Without it, tests that create real files in temp dirs spawn
    live async_runner processes which then get orphaned when the temp dir is removed.
    """
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
    """Returns True while the target file is still missing and grace remains.

    GravityGuard runs as a PreToolUse hook, so this worker is spawned *before* the AI
    writes the file and the target may legitimately not exist yet. The wait is bounded
    by grace_period so the worker can never outlive its purpose; once the file lands
    the worker stops waiting immediately.
    """
    if target_exists:
        return False
    return waited_seconds < (grace_period - 1e-6)


# ============================================================================
# PATH RESOLUTION & STATE UTILITIES
# ============================================================================

def find_project_root(target_file: str) -> Path:
    """Finds the nearest directory containing .gravityguard.json or .git, or falls back to file parent."""
    p = Path(target_file).resolve()
    for parent in [p.parent] + list(p.parents):
        if (parent / ".gravityguard.json").exists() or (parent / ".git").exists():
            return parent
    return p.parent if p.is_file() else p


def get_runtime_dir(project_root: Path) -> Path:
    runtime_dir = project_root / ".gravityguard" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir


def get_diagnostics_file_path(project_root: Path) -> Path:
    return get_runtime_dir(project_root) / "diagnostics.json"


def get_debounce_file_path(project_root: Path) -> Path:
    return get_runtime_dir(project_root) / "debounce_state.json"


def load_diagnostics(diag_path: Path) -> Dict[str, Any]:
    if not diag_path.exists():
        return {"version": 1, "lastUpdated": 0, "entries": {}}
    try:
        with open(diag_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (IOError, OSError, json.JSONDecodeError, ValueError):
        return {"version": 1, "lastUpdated": 0, "entries": {}}


def save_diagnostics(diag_path: Path, data: Dict[str, Any]) -> None:
    data["lastUpdated"] = time.time()
    tmp_path = diag_path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp_path.replace(diag_path)
    except (IOError, OSError):
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                return


def load_debounce_state(debounce_path: Path) -> Dict[str, Any]:
    if not debounce_path.exists():
        return {"last_edit_time": 0.0, "worker_running": False, "file_edits": {}, "active_lint_workers": {}}
    try:
        with open(debounce_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (IOError, OSError, json.JSONDecodeError, ValueError):
        return {"last_edit_time": 0.0, "worker_running": False, "file_edits": {}, "active_lint_workers": {}}


def save_debounce_state(debounce_path: Path, state: Dict[str, Any]) -> None:
    tmp_path = debounce_path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        tmp_path.replace(debounce_path)
    except (IOError, OSError):
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                return


# ============================================================================
# PARSERS & ADAPTERS
# ============================================================================

def parse_tsc_output(stdout_text: str, project_root: Path) -> Dict[str, List[Dict[str, Any]]]:
    """
    Parses tsc --noEmit compiler output into per-file error lists.
    Format: <filepath>(<line>,<col>): error <codeId>: <message>
    Returns: { normalized_file_path: [ {line, rule, message} ] }
    """
    file_errors: Dict[str, List[Dict[str, Any]]] = {}
    pattern = re.compile(r"^(.+?)\((\d+),\d+\):\s+error\s+(TS\d+):\s+(.*)$")

    for line in stdout_text.splitlines():
        line = line.strip()
        m = pattern.match(line)
        if m:
            rel_or_abs_path = m.group(1).strip()
            line_no = int(m.group(2))
            code_id = m.group(3).strip()
            msg = m.group(4).strip()

            p = Path(rel_or_abs_path)
            if not p.is_absolute():
                p = (project_root / p).resolve()
            norm_key = str(p).replace("\\", "/")

            file_errors.setdefault(norm_key, []).append({
                "line": line_no,
                "rule": code_id,
                "message": msg
            })

    return file_errors


def run_ruff(target_file: str) -> Optional[List[Dict[str, Any]]]:
    """Runs ruff check on a single python file."""
    if not shutil.which("ruff"):
        return None
    try:
        res = run_hidden(["ruff", "check", "--output-format=json", target_file], timeout=10)
        if res is None:
            return None
        output = res.stdout.strip()
        if not output:
            return []
        items = json.loads(output)
        errors = []
        for item in items:
            errors.append({
                "line": item.get("location", {}).get("row", 1),
                "rule": item.get("code", "Ruff"),
                "message": item.get("message", "Lint warning")
            })
        return errors
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError, AttributeError):
        return None


def run_eslint(target_file: str, project_root: Path) -> Optional[List[Dict[str, Any]]]:
    """Runs eslint on a single TS/JS file."""
    cmd = None
    if shutil.which("npx"):
        cmd = ["npx", "--no-install", "eslint", "--format", "json", target_file]
    elif shutil.which("eslint"):
        cmd = ["eslint", "--format", "json", target_file]

    if not cmd:
        return None

    try:
        res = run_hidden(cmd, cwd=project_root, timeout=15)
        if res is None:
            return None
        output = res.stdout.strip()
        if not output:
            return []
        data = json.loads(output)
        errors = []
        for file_entry in data:
            for msg in file_entry.get("messages", []):
                errors.append({
                    "line": msg.get("line", 1),
                    "rule": msg.get("ruleId", "ESLint"),
                    "message": msg.get("message", "Lint error")
                })
        return errors
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError, AttributeError):
        return None


def run_godot_check(target_file: str) -> Optional[List[Dict[str, Any]]]:
    """Runs headless Godot script syntax check."""
    if not shutil.which("godot"):
        return None
    try:
        res = run_hidden(["godot", "--headless", "--check-only", "-s", target_file], timeout=10)
        if res is None:
            return None
        if res.returncode != 0:
            err_line = (res.stderr or "").strip() or (res.stdout or "").strip()
            return [{
                "line": 1,
                "rule": "GDScriptSyntax",
                "message": err_line[:200]
            }]
        return []
    except (subprocess.SubprocessError, OSError, AttributeError):
        return None


def run_batch_tsc(project_root: Path) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    """Runs tsc --noEmit across the project and returns per-file errors."""
    if not shutil.which("npx") and not shutil.which("tsc"):
        return None
    cmd = ["npx", "tsc", "--noEmit"] if shutil.which("npx") else ["tsc", "--noEmit"]
    try:
        res = run_hidden(cmd, cwd=project_root, timeout=30)
        if res is None:
            return None
        if res.returncode == 0:
            return {}
        return parse_tsc_output(res.stdout, project_root)
    except (subprocess.SubprocessError, OSError, AttributeError):
        return None


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

    GravityGuard is a PreToolUse hook, so this worker is spawned *before* the AI
    writes the file and the target may legitimately not exist yet. After the quiet
    window the worker therefore spends a bounded grace_period waiting for the file
    to land; if it never appears the worker cleans up and exits quietly.
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
            # Quiet window reached. The write may not have landed yet (pre-tool hook),
            # so allow a bounded grace period for the file to appear.
            if not _await_target_file(target_file, coalesce_window, grace_period):
                # File never materialised: release the claim and exit silently.
                clean_file_state(state, norm_key)
                save_debounce_state(debounce_path, state)
                return

            # Execute linter once on the final file state
            execute_single_file_lint(target_file, project_root, diag_path)

            # Cleanup worker state so future modifications start fresh
            clean_file_state(state, norm_key)
            save_debounce_state(debounce_path, state)
            break
        else:
            # More edits arrived during sleep; continue waiting for calm
            continue


def run_debounce_worker(project_root: Path, idle_threshold: float = 3.0,
                        max_lifetime: float = 120.0) -> None:
    """
    Background worker loop that waits for a quiet window (e.g. 3.0s idle)
    before triggering project-wide tsc --noEmit and writing per-file entries.

    Termination guarantees (a worker must never outlive its purpose):
      1. Quiet window reached     -> run batch tsc once, then exit.
      2. Project root disappeared -> exit (nothing left to validate).
      3. Debounce state file gone -> exit (no pending edit to debounce).
      4. max_lifetime exceeded    -> release the worker claim, then exit.

    Every exit path that leaves a persisted state file behind must clear
    worker_running. Otherwise the stale True blocks all future spawns in
    trigger_debounce_worker_if_needed() and the TSC debounce silently deadlocks.
    """
    debounce_path = get_debounce_file_path(project_root)
    diag_path = get_diagnostics_file_path(project_root)
    started_at = time.time()

    while True:
        time.sleep(idle_threshold)

        # Guard: hard upper bound on total worker lifetime. The claim must be
        # released first, otherwise the persisted worker_running=True would block
        # every future spawn (a lifecycle deadlock). If the state file is already
        # gone we exit directly and deliberately avoid re-creating the runtime
        # directory tree.
        if (time.time() - started_at) > max_lifetime:
            if debounce_path.exists():
                expired_state = load_debounce_state(debounce_path)
                expired_state["worker_running"] = False
                save_debounce_state(debounce_path, expired_state)
            return

        # Guard: project root disappeared (e.g. temp workspace cleaned up).
        if not project_root.exists():
            return

        # Guard: state file removed -> no pending edit to debounce. Without this,
        # load_debounce_state() yields last_edit_time == 0.0, should_run_after_idle()
        # stays permanently False, and the loop spins forever while re-creating the
        # deleted .gravityguard/runtime directory tree on every iteration.
        if not debounce_path.exists():
            return

        state = load_debounce_state(debounce_path)
        last_edit = state.get("last_edit_time", 0.0)
        now = time.time()

        if last_edit <= 0.0:
            # No recorded edit activity: nothing to coalesce.
            state["worker_running"] = False
            save_debounce_state(debounce_path, state)
            return

        if should_run_after_idle(last_edit, now, idle_threshold):
            # Burst is over! Run batch tsc once
            file_errors_map = run_batch_tsc(project_root)
            state["worker_running"] = False
            save_debounce_state(debounce_path, state)

            if file_errors_map is not None:
                diag = load_diagnostics(diag_path)
                entries = diag.setdefault("entries", {})

                # Remove existing tsc entries that may have been resolved
                tsc_keys_to_clear = [k for k, v in entries.items() if v.get("tool") == "tsc"]
                for k in tsc_keys_to_clear:
                    entries.pop(k, None)

                # Store per-file tsc entries so read_recent_diagnostics(target_file) can match them
                for f_path, errs in file_errors_map.items():
                    if errs:
                        entries[f_path] = {
                            "tool": "tsc",
                            "timestamp": time.time(),
                            "errors": errs[:5]
                        }

                # Also keep summary entry
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

    # Per-file burst coalescing logic.
    #
    # NOTE: the target file intentionally does NOT have to exist here. GravityGuard
    # runs as a PreToolUse hook, so this runner is spawned *before* the AI writes the
    # file. Bailing out early on a missing file would mean every newly created file
    # is never linted. Existence is handled inside run_coalesced_file_lint_worker(),
    # which waits a bounded grace period and no-ops cleanly if the file never lands.
    norm_key = str(Path(target_file).resolve()).replace("\\", "/")
    debounce_state = load_debounce_state(debounce_path)
    file_edits = debounce_state.setdefault("file_edits", {})
    active_workers = debounce_state.setdefault("active_lint_workers", {})

    now = time.time()
    file_edits[norm_key] = now

    if should_spawn_file_worker(active_workers, norm_key):
        # Claim file lint worker
        active_workers[norm_key] = True
        save_debounce_state(debounce_path, debounce_state)
        # Execute coalesced worker (waits 300ms quiet window, then lints once)
        run_coalesced_file_lint_worker(target_file, project_root, coalesce_window=0.3)
    else:
        # A worker is already running for this file; updating file_edits[norm_key] = now
        # successfully resets its timer window. Exit immediately without spawning extra processes!
        save_debounce_state(debounce_path, debounce_state)
        sys.exit(0)


if __name__ == "__main__":
    main()
