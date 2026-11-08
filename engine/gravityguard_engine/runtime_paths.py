"""Where a project's guard runtime data lives.

A real project keeps it in ``<root>/.gravityguard/runtime``. A system or user folder (home, Desktop, Documents,
Downloads, the drive root, an Obsidian vault) is not a project: a local ``.gravityguard`` there is sprawl, so its runtime data
goes to ``~/.gravityguard/ephemeral/<name>-<hash>/runtime`` instead.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

EPHEMERAL_ROOT_NAME = "ephemeral"
_USER_FOLDER_NAMES = {"desktop", "documents", "downloads", "pictures", "videos", "music"}
_PROJECT_CONTAINER_NAMES = {"public", "private"}


def _norm(path: str | Path) -> str:
    return os.path.normcase(os.path.realpath(str(path)))


def is_system_or_user_root(path: str | Path) -> bool:
    """True for a folder that can never be a project root: drive/filesystem root, ``C:\\Users``, the user's home and its
    well-known folders, the ``GitHub`` workspace containers, and anything inside an ``.obsidian`` folder."""
    try:
        resolved = Path(os.path.realpath(str(path)))
        norm = _norm(resolved)
        home = Path(os.path.realpath(os.path.expanduser("~")))
        if resolved.parent == resolved or norm in (_norm(home), _norm(home.parent)):
            return True
        parts = [part.lower() for part in resolved.parts]
        if ".obsidian" in parts:
            return True
        name = resolved.name.lower()
        if resolved.parent == home and (name in _USER_FOLDER_NAMES or name.startswith("onedrive")):
            return True
        if name == "github" and resolved.parent.name.lower() in _USER_FOLDER_NAMES:
            return True
        return name in _PROJECT_CONTAINER_NAMES and resolved.parent.name.lower() == "github"
    except (OSError, ValueError):
        return False


def ephemeral_dir(project_root: str | Path) -> Path:
    """Central per-directory runtime location under ``~/.gravityguard/ephemeral``."""
    resolved = os.path.realpath(str(project_root))
    digest = hashlib.sha1(os.path.normcase(resolved).encode("utf-8")).hexdigest()[:10]
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(resolved).name)[:40] or "root"
    return Path(os.path.expanduser("~")) / ".gravityguard" / EPHEMERAL_ROOT_NAME / f"{slug}-{digest}"


def runtime_dir(project_root: str | Path) -> Path:
    """``.gravityguard/runtime`` of a real project; the central ephemeral runtime for system/user folders."""
    if is_system_or_user_root(project_root):
        return ephemeral_dir(project_root) / "runtime"
    return Path(project_root) / ".gravityguard" / "runtime"


def gravityguard_dir(project_root: str | Path) -> Path:
    """``.gravityguard`` of a real project; the central ephemeral folder for system/user folders."""
    if is_system_or_user_root(project_root):
        return ephemeral_dir(project_root)
    return Path(project_root) / ".gravityguard"
