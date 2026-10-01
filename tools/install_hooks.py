#!/usr/bin/env python3
"""
Installs git hooks from .githooks directory into .git/hooks.
Works across Windows, macOS, and Linux.
"""
import os
import shutil
import sys
from pathlib import Path


def install_hooks() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    src_hooks = repo_root / ".githooks"
    dest_hooks = repo_root / ".git" / "hooks"

    if not dest_hooks.parent.is_dir():
        print("Not a git repository, skipping hook installation.")
        return 0

    dest_hooks.mkdir(parents=True, exist_ok=True)

    if not src_hooks.is_dir():
        print(f"Source hooks dir {src_hooks} not found.")
        return 1

    installed = 0
    for hook_file in src_hooks.iterdir():
        if hook_file.is_file():
            target = dest_hooks / hook_file.name
            shutil.copy2(hook_file, target)
            try:
                target.chmod(0o755)
            except (OSError, PermissionError) as err:
                print(f"Note: chmod skipped on {target.name} ({err})")
            print(f"Installed hook: {hook_file.name} -> {target}")
            installed += 1

    print(f"Successfully installed {installed} git hook(s).")
    return 0


if __name__ == "__main__":
    sys.exit(install_hooks())
