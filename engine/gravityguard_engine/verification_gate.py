"""
GravityGuard Engine — Verification gate report (compile, tests, preview).

The webview shows four stages: compile, GravityGuard shield, logic tests, live preview. The shield is read from the
event log; the other three come from `.gravityguard/runtime/verification.json`, which only this module writes.
A stage result is never declared: `run` takes it from the command's exit code, `preview` from a screenshot on disk
and the console error count, so an agent cannot mark a stage green without running it.
"""
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

RUN_STAGES = ("compile", "tests")
REPORT_NAME = "verification.json"
DETAIL_MAX = 160
RUN_TIMEOUT_S = 900


def report_path(root: Path) -> Path:
    return Path(root) / ".gravityguard" / "runtime" / REPORT_NAME


def load_report(root: Path) -> dict[str, Any]:
    path = report_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _write_stage(root: Path, stage: str, entry: dict[str, Any]) -> dict[str, Any]:
    report = load_report(root)
    report[stage] = entry
    path = report_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)
    return entry


def _last_line(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    line = lines[-1]
    return line if len(line) <= DETAIL_MAX else line[: DETAIL_MAX - 3] + "..."


def run_stage(root: Path, stage: str, argv: list[str], timeout: int = RUN_TIMEOUT_S) -> dict[str, Any]:
    """Runs a compile or test command and records pass/fail from its exit code."""
    if stage not in RUN_STAGES:
        raise ValueError(f"unknown stage: {stage}")
    if not argv:
        raise ValueError("a command is required after --")
    command = " ".join(argv)
    try:
        proc = subprocess.run(argv, cwd=str(root), capture_output=True, text=True, check=False,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              shell=os.name == "nt")
        code = proc.returncode
        detail = _last_line(proc.stderr if code and proc.stderr.strip() else proc.stdout) or f"exit {code}"
    except subprocess.TimeoutExpired:
        code, detail = -1, f"timeout after {timeout}s"
    except OSError as exc:
        code, detail = -1, f"could not start: {exc}"
    return _write_stage(root, stage, {
        "status": "pass" if code == 0 else "fail",
        "detail": detail,
        "command": command,
        "exitCode": code,
        "at": _now_iso(),
    })


def record_preview(root: Path, screenshot: str, console_errors: int) -> dict[str, Any]:
    """Records the live preview stage: pass only with a non-empty screenshot and zero console errors."""
    shot = Path(screenshot)
    if not shot.is_absolute():
        shot = Path(root) / shot
    has_shot = shot.is_file() and shot.stat().st_size > 0
    if not has_shot:
        status, detail = "fail", f"screenshot not found: {screenshot}"
    elif console_errors > 0:
        status, detail = "fail", f"console.error: {console_errors}"
    else:
        status, detail = "pass", f"{shot.name}, console.error: 0"
    return _write_stage(root, "preview", {
        "status": status,
        "detail": detail,
        "screenshot": str(shot),
        "consoleErrors": console_errors,
        "at": _now_iso(),
    })


def stage_summary(report: dict[str, Any]) -> list[str]:
    lines = []
    for stage in ("compile", "tests", "preview"):
        entry: dict[str, Any] | None = report.get(stage)
        if isinstance(entry, dict):
            lines.append(f"{stage:8} {entry.get('status', '?'):7} {entry.get('at', '')}  {entry.get('detail', '')}")
        else:
            lines.append(f"{stage:8} pending")
    return lines
