#!/usr/bin/env python3
"""
GravityGuard Engine — Project Context, Multi-Root Workspace & Configuration Subsystem.
Zero external dependencies.
"""
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .doc_policy import is_doc_governed_path

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


_REAL_HOME = os.path.normcase(os.path.realpath(os.path.expanduser("~")))


def _is_project_config_dir(directory: Path) -> bool:
    """True if `directory` holds a project .gravityguard.json. The one in the user's home is the user-level default,
    not a project config, so it neither marks a project root nor wins the upward search."""
    if not (directory / ".gravityguard.json").exists():
        return False
    try:
        norm_dir = os.path.normcase(os.path.realpath(str(directory)))
        expand_home = os.path.normcase(os.path.realpath(os.path.expanduser("~")))
        if norm_dir == _REAL_HOME or norm_dir == expand_home:
            return False
        return True
    except OSError:
        return True


def extract_project_info(target_file: str) -> Tuple[str, str]:
    """Extracts project name and project root from target_file."""
    if not target_file:
        return "", ""
    try:
        p = Path(os.path.abspath(target_file))
        curr = p.parent
        for _ in range(6):
            if (curr / ".git").exists() or _is_project_config_dir(curr):
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
    1. If target_file is provided, check if it belongs to any declared workspacePaths.
    2. If target_file is provided, walk up to find .gravityguard.json or .git marker.
    3. If workspacePaths provided without matching target_file, use first workspacePath.
    4. Fallback to Path.cwd().
    GRAVITYGUARD_LOG_DIR only relocates the audit log and the state files; it never changes the project root or which
    .gravityguard.json is read.
    """
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
                if _is_project_config_dir(curr) or (curr / ".git").exists():
                    return curr
                if curr.parent == curr:
                    break
                curr = curr.parent
        except (IOError, OSError, ValueError):
            return Path.cwd()

    if isinstance(ws_paths, list) and ws_paths and ws_paths[0]:
        return Path(os.path.abspath(ws_paths[0]))

    return Path.cwd()


def _load_user_default_config() -> Optional[dict]:
    """User-level default (~/.gravityguard.json, or the file named by GRAVITYGUARD_USER_CONFIG).
    Missing or invalid file -> None, same as having no config."""
    path = os.environ.get("GRAVITYGUARD_USER_CONFIG") or os.path.join(os.path.expanduser("~"), ".gravityguard.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def load_gravityguard_config(target_file: str = "", project_root: Optional[Path] = None) -> Optional[dict]:
    """Project .gravityguard.json (walking upward); only when none exists, the user-level default.
    A project file wins completely (no merging)."""
    found, cfg = _load_project_config(target_file, project_root)
    return cfg if found else _load_user_default_config()


def _load_project_config(target_file: str, project_root: Optional[Path]) -> Tuple[bool, Optional[dict]]:
    """(file_found, config). An unreadable project file counts as found with no config."""
    if target_file:
        try:
            p = Path(target_file).resolve()
            current_dir = p if p.is_dir() else p.parent
        except (ValueError, OSError):
            current_dir = Path.cwd()

        for _ in range(10):  # up to 10 levels up
            cfg_file = current_dir / ".gravityguard.json"
            if cfg_file.is_file() and _is_project_config_dir(current_dir):
                try:
                    with open(cfg_file, "r", encoding="utf-8") as f:
                        return True, json.load(f)
                except (json.JSONDecodeError, IOError):
                    return True, None
            if (project_root and current_dir == project_root) or (current_dir / ".git").exists() or (current_dir.parent == current_dir):
                break
            current_dir = current_dir.parent
        return False, None

    # Check project_root or cwd as fallback only when no target_file was specified
    root = project_root or Path.cwd()
    cwd_cfg = root / ".gravityguard.json"
    if cwd_cfg.is_file() and _is_project_config_dir(root):
        try:
            with open(cwd_cfg, "r", encoding="utf-8") as f:
                return True, json.load(f)
        except (json.JSONDecodeError, IOError):
            return True, None
    return False, None


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


def is_doc_governed_target(target_file: str, cfg: Optional[dict] = None, project_root: Optional[Path] = None) -> bool:
    """
    Checks if modifying target_file creates a documentation obligation under docs/KNOWLEDGE.md §6.
    The rules live in ``doc_policy`` and are shared with the commit-time verifier (tools/verify_doc_governance.py).
    """
    return is_doc_governed_path(target_file, cfg, project_root)
