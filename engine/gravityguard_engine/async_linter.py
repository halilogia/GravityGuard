#!/usr/bin/env python3
"""
GravityGuard Engine — Async Linter Parsers & Execution Adapters.
Runs Ruff, ESLint, Godot headless syntax checks, and TypeScript project batch compilation.
Zero external dependencies.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

from .async_process import run_hidden


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
