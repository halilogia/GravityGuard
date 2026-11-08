"""Git-independent debt baselines: the LOC a source file had right before the agent's first write.

The debt ratchet takes a file's first-seen baseline from git HEAD. Outside git (or before the first commit) there is no
HEAD, and "current size" would grandfather a file the agent just bloated. So the PreToolUse path records the size of
the file as it was before the write (``old_full_content``) in ``<runtime>/debt_baselines.json``, and the ratchet falls
back to that record when HEAD is unavailable.

A recorded value only ever goes down (min of old and new record) and is dropped once the file is back under the limit.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
from pathlib import Path

from .runtime_paths import runtime_dir

BASELINES_FILE = "debt_baselines.json"


def _warn(message: str) -> None:
    sys.stderr.write(f"[GravityGuard DebtBaselines] {message}\n")


def baselines_path(project_root: str | Path) -> Path:
    return runtime_dir(project_root) / BASELINES_FILE


def load_baselines(project_root: str | Path) -> dict[str, int]:
    """rel_path -> LOC. Missing or unreadable store means no baselines (never raises)."""
    path = baselines_path(project_root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        _warn(f"Cannot read {path}: {err}")
        return {}
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict):
        return {}
    return {k: v for k, v in files.items() if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool)}


def recorded_baseline(project_root: str | Path, rel_path: str) -> int | None:
    return load_baselines(project_root).get(rel_path)


def _save(project_root: str | Path, files: dict[str, int]) -> None:
    path = baselines_path(project_root)
    temp_path = ""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix="debt_baselines.", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "files": files}, fh, indent=2, ensure_ascii=False)
        os.replace(temp_path, path)
    except OSError as err:
        _warn(f"Failed to save {path}: {err}")
        if temp_path:
            with contextlib.suppress(OSError):
                os.remove(temp_path)


def record_pre_write_baseline(project_root: str | Path, rel_path: str, old_loc: int, projected_loc: int, threshold: int) -> None:
    """Remember `old_loc` (0 for a new file) for a file this write pushes over `threshold`; forget it once it is back under."""
    files = load_baselines(project_root)
    if projected_loc <= threshold:
        if rel_path in files:
            del files[rel_path]
            _save(project_root, files)
        return
    previous = files.get(rel_path)
    if previous is not None and previous <= old_loc:
        return
    files[rel_path] = old_loc
    _save(project_root, files)
