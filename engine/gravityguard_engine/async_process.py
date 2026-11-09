"""GravityGuard Engine — hidden-console subprocess policy for async linters."""
import sys
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
