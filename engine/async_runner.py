#!/usr/bin/env python3
"""
GravityGuard Async Static Validation Runner (Tier 2 / Tier 3)
Executes lightweight linters in the background without blocking the AI tool-call loop.
Writes findings to .gravityguard/runtime/diagnostics.json for next-hook consumption.
"""

import sys
import os
import json
import time
import shutil
import argparse
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional


def find_project_root(target_file: str) -> Path:
    """Finds the nearest directory containing .gravityguard.json or .git, or falls back to file parent."""
    p = Path(target_file).resolve()
    for parent in [p.parent] + list(p.parents):
        if (parent / ".gravityguard.json").exists() or (parent / ".git").exists():
            return parent
    return p.parent if p.is_file() else p


def get_diagnostics_file_path(project_root: Path) -> Path:
    runtime_dir = project_root / ".gravityguard" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir / "diagnostics.json"


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
    except (IOError, OSError) as e:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                return


def run_ruff(target_file: str) -> Optional[List[Dict[str, Any]]]:
    """Runs ruff check on a single python file."""
    if not shutil.which("ruff"):
        return None
    try:
        res = subprocess.run(
            ["ruff", "check", "--output-format=json", target_file],
            capture_output=True,
            text=True,
            timeout=10
        )
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
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
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
        res = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=15
        )
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
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return None


def run_godot_check(target_file: str) -> Optional[List[Dict[str, Any]]]:
    """Runs headless Godot script syntax check."""
    if not shutil.which("godot"):
        return None
    try:
        res = subprocess.run(
            ["godot", "--headless", "--check-only", "-s", target_file],
            capture_output=True,
            text=True,
            timeout=10
        )
        if res.returncode != 0:
            err_line = res.stderr.strip() or res.stdout.strip()
            return [{
                "line": 1,
                "rule": "GDScriptSyntax",
                "message": err_line[:200]
            }]
        return []
    except (subprocess.SubprocessError, OSError):
        return None


def run_batch_tsc(project_root: Path) -> Optional[List[Dict[str, Any]]]:
    """Runs tsc --noEmit across the project (debounced burst check)."""
    if not shutil.which("npx") and not shutil.which("tsc"):
        return None
    cmd = ["npx", "tsc", "--noEmit"] if shutil.which("npx") else ["tsc", "--noEmit"]
    try:
        res = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30
        )
        if res.returncode == 0:
            return []
        errors = []
        for line in res.stdout.splitlines()[:10]:
            if "error TS" in line:
                errors.append({
                    "line": 1,
                    "rule": "TypeScriptCompiler",
                    "message": line.strip()
                })
        return errors
    except (subprocess.SubprocessError, OSError):
        return None


def main():
    parser = argparse.ArgumentParser(description="GravityGuard Async Linter Runner")
    parser.add_argument("--file", help="Changed file path to validate")
    parser.add_argument("--batch-tsc", action="store_true", help="Run project-wide tsc --noEmit")
    args = parser.parse_args()

    if not args.file and not args.batch_tsc:
        sys.exit(0)

    target_file = args.file or ""
    project_root = find_project_root(target_file) if target_file else Path.cwd()
    diag_path = get_diagnostics_file_path(project_root)
    state = load_diagnostics(diag_path)
    entries = state.setdefault("entries", {})

    if args.batch_tsc:
        tsc_errs = run_batch_tsc(project_root)
        if tsc_errs is not None:
            entries["[project-tsc]"] = {
                "tool": "tsc",
                "timestamp": time.time(),
                "errors": tsc_errs
            }
            save_diagnostics(diag_path, state)
        sys.exit(0)

    if not os.path.exists(target_file):
        sys.exit(0)

    file_lower = target_file.lower()
    tool_name = None
    errors = None

    if file_lower.endswith(".py"):
        tool_name = "ruff"
        errors = run_ruff(target_file)
    elif file_lower.endswith((".ts", ".tsx", ".js", ".jsx")):
        tool_name = "eslint"
        errors = run_eslint(target_file, project_root)
    elif file_lower.endswith(".gd"):
        tool_name = "godot"
        errors = run_godot_check(target_file)

    if tool_name and errors is not None:
        norm_key = str(Path(target_file).resolve()).replace("\\", "/")
        if errors:
            entries[norm_key] = {
                "tool": tool_name,
                "timestamp": time.time(),
                "errors": errors[:5]  # Keep top 5
            }
        else:
            entries.pop(norm_key, None)
        save_diagnostics(diag_path, state)


if __name__ == "__main__":
    main()
