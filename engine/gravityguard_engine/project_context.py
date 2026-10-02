#!/usr/bin/env python3
"""
GravityGuard Engine — Project Context, Multi-Root Workspace & Configuration Subsystem.
Zero external dependencies.
"""
import fnmatch
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DEFAULT_COMPLEXITY_THRESHOLDS: Dict[str, int] = {
    "monolithLoc": 1000,              # projected LOC that makes a file a monolith
    "singleWriteLoc": 200,            # one tool call adding this much to an EXISTING file
    "creepBaseLoc": 800,              # file size above which additions are "creep"
    "creepAddedLoc": 80,              # addition that counts as creep on such a file
    "overEngineeringMaxLoc": 50,      # "small change" window for the abstraction spike
    "overEngineerAbstractions": 2,    # declarations inside that window that trip it
}

_COMPLEXITY_THRESHOLD_FLOORS: Dict[str, int] = {
    "monolithLoc": 100,
    "singleWriteLoc": 10,
    "creepBaseLoc": 100,
    "creepAddedLoc": 10,
    "overEngineeringMaxLoc": 5,
    "overEngineerAbstractions": 2,
}



def harden_streams_to_utf8() -> None:
    """Forces stdin/stdout/stderr to UTF-8 with replacement (never raises)."""
    for stream_name in ("stdin", "stdout", "stderr"):
        try:
            getattr(sys, stream_name).reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError, LookupError):
            continue


def extract_project_info(target_file: str) -> Tuple[str, str]:
    """Extracts project name and project root from target_file."""
    if not target_file:
        return "", ""
    try:
        p = Path(os.path.abspath(target_file))
        curr = p.parent
        for _ in range(6):
            if (curr / ".git").exists() or (curr / ".gravityguard.json").exists():
                return curr.name, str(curr)
            curr = curr.parent
        parts = p.parts
        for i, part in enumerate(parts):
            if part.lower() == "github" and i + 1 < len(parts):
                if parts[i + 1].lower() in ("public", "private") and i + 2 < len(parts):
                    return parts[i + 2], str(Path(*parts[:i + 3]))
                return parts[i + 1], str(Path(*parts[:i + 2]))
        return p.parent.name, str(p.parent)
    except Exception:
        return "", ""


def resolve_project_root(payload: Optional[dict] = None, target_file: str = "") -> Path:
    """
    Resolves the actual project root for the active request.
    Multi-root workspace priority order:
    1. GRAVITYGUARD_LOG_DIR override (for testing & isolated execution).
    2. If target_file is provided, check if it belongs to any declared workspacePaths.
    3. If target_file is provided, walk up to find .gravityguard.json or .git marker.
    4. If workspacePaths provided without matching target_file, use first workspacePath.
    5. Fallback to Path.cwd().
    """
    override_dir = os.environ.get("GRAVITYGUARD_LOG_DIR")
    if override_dir:
        return Path(override_dir)

    ws_paths = payload.get("workspacePaths", []) if isinstance(payload, dict) else []

    if target_file and isinstance(ws_paths, list):
        try:
            target_abs = Path(os.path.abspath(target_file))
            for ws in ws_paths:
                if not ws:
                    continue
                ws_abs = Path(os.path.abspath(ws))
                try:
                    target_abs.relative_to(ws_abs)
                    return ws_abs
                except ValueError:
                    continue
        except (ValueError, OSError):
            target_abs = None

    if target_file:
        try:
            p = Path(os.path.abspath(target_file))
            curr = p.parent
            for _ in range(8):
                if (curr / ".gravityguard.json").exists() or (curr / ".git").exists():
                    return curr
                if curr.parent == curr:
                    break
                curr = curr.parent
        except (IOError, OSError, ValueError):
            return Path.cwd()

    if isinstance(ws_paths, list) and ws_paths and ws_paths[0]:
        return Path(os.path.abspath(ws_paths[0]))

    return Path.cwd()


def load_gravityguard_config(target_file: str = "", project_root: Optional[Path] = None) -> Optional[dict]:
    """Traverse upward looking for .gravityguard.json config."""
    override_dir = os.environ.get("GRAVITYGUARD_LOG_DIR")
    if override_dir:
        cfg_override = Path(override_dir) / ".gravityguard.json"
        if cfg_override.is_file():
            try:
                with open(cfg_override, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return None

    if target_file:
        try:
            p = Path(target_file).resolve()
            current_dir = p if p.is_dir() else p.parent
        except (ValueError, OSError):
            current_dir = Path.cwd()

        for _ in range(10):  # up to 10 levels up
            cfg_file = current_dir / ".gravityguard.json"
            if cfg_file.is_file():
                try:
                    with open(cfg_file, "r", encoding="utf-8") as f:
                        return json.load(f)
                except (json.JSONDecodeError, IOError):
                    return None
            if current_dir.parent == current_dir:
                break
            current_dir = current_dir.parent
        return None

    # Check project_root or cwd as fallback only when no target_file was specified
    root = project_root or Path.cwd()
    cwd_cfg = root / ".gravityguard.json"
    if cwd_cfg.is_file():
        try:
            with open(cwd_cfg, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    return None


def resolve_complexity_thresholds(cfg: Optional[dict]) -> Dict[str, int]:
    """Merges the `complexity` block of .gravityguard.json over the defaults."""
    block = cfg.get("complexity") if isinstance(cfg, dict) else None
    if not isinstance(block, dict):
        return DEFAULT_COMPLEXITY_THRESHOLDS

    resolved = dict(DEFAULT_COMPLEXITY_THRESHOLDS)
    for key, floor in _COMPLEXITY_THRESHOLD_FLOORS.items():
        value = block.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if value < floor:
            continue
        resolved[key] = int(value)

    return resolved


def should_enforce_doc_obligations(target_file: str = "", cfg: Optional[dict] = None) -> bool:
    """
    Determines whether documentation obligations should be enforced for this target file.
    Strictly opt-in: Requires explicit configuration in .gravityguard.json:
        {"governance": {"enforceDocObligations": true}}
    """
    if cfg and isinstance(cfg.get("governance"), dict):
        explicit = cfg["governance"].get("enforceDocObligations")
        if explicit is not None:
            return bool(explicit)
    return False


def is_doc_governed_target(target_file: str, cfg: Optional[dict] = None) -> bool:
    """
    Checks if modifying target_file creates a documentation obligation under docs/KNOWLEDGE.md §6.
    By default, changes to engine/, src/, plugin/, or rules/ require a CHANGELOG update.
    """
    p = Path(target_file)
    file_name_lower = p.name.lower()
    parent_parts_lower = [part.lower() for part in p.parent.parts]

    # Exclude test files
    is_in_test_dir = any(d in parent_parts_lower for d in ("tests", "test", "__tests__"))
    is_test_name = (
        file_name_lower.startswith("test_") or
        "_test." in file_name_lower or
        file_name_lower.endswith("_test.py") or
        ".test." in file_name_lower or
        ".spec." in file_name_lower
    )
    if is_in_test_dir or is_test_name:
        return False

    norm = target_file.replace("\\", "/").lower()
    # Exclude temporary, cache, and runtime dirs
    if any(m in norm for m in ["/.gravityguard/", "/logs/", "/scratch/", "/brain/", "/dist/", "/node_modules/", "/.git/"]):
        return False
    if file_name_lower.endswith((".md", ".txt", ".json", ".lock", ".svg", ".png", ".jpg", ".jpeg", ".ico")):
        return False

    governed_dirs = {"engine", "src", "plugin", "rules", "scripts"}
    if any(part in governed_dirs for part in parent_parts_lower):
        return True

    if cfg and isinstance(cfg.get("governance"), dict):
        patterns = cfg["governance"].get("docObligationPatterns", [])
        for pat in patterns:
            if fnmatch.fnmatch(norm, pat.lower()):
                return True

    return False
