"""GravityGuard Engine — project-root resolution and diagnostics/debounce state files for the async runner."""
import json
import os
import time
from pathlib import Path
from typing import Dict, Any


# ============================================================================
# PATH RESOLUTION & STATE UTILITIES
# ============================================================================

# Project-root markers, in addition to .gravityguard.json / .git. The previous
# two-marker set only ever matched git checkouts, so every non-git project
# (a Godot project, a bare npm package, a standalone Python tool) fell through
# to the file's own parent directory and got its own .gravityguard tree.
_PROJECT_ROOT_MARKERS = (
    ".gravityguard.json",
    ".git",
    ".hg",
    ".svn",
    # Game / engine manifests
    "project.godot",
    # JS / TS
    "package.json",
    "tsconfig.json",
    # Python
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    # Other ecosystems
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "composer.json",
    "Gemfile",
)


def _has_project_marker(directory: Path) -> bool:
    """True if directory carries any recognized project-root marker."""
    for marker in _PROJECT_ROOT_MARKERS:
        if marker == ".gravityguard.json" and os.path.normcase(os.path.abspath(directory)) == os.path.normcase(
                os.path.abspath(os.path.expanduser("~"))):
            continue  # the user-level default config is not a project marker
        try:
            if (directory / marker).exists():
                return True
        except OSError:
            continue
    return False


def _is_ancestor_or_self(candidate: Path, path: Path) -> bool:
    """True if candidate is path itself or one of its ancestors."""
    return candidate == path or candidate in path.parents


def find_project_root(target_file: str) -> Path:
    """Finds the nearest project root for target_file.

    Resolution order:
      1. Nearest ancestor carrying a project-root marker (.gravityguard.json,
         .git, project.godot, package.json, pyproject.toml, ...).
      2. The process working directory, when it is genuinely an ancestor of the
         target file. The working directory is the workspace the agent was
         launched in, which is the authoritative notion of "this project" even
         when the tree carries no manifest at all.
      3. The file's own directory. This is a guess, not a root -- see
         is_trusted_project_root() before creating anything there.
    """
    p = Path(target_file).resolve()

    for parent in p.parents:
        if _has_project_marker(parent):
            return parent

    try:
        cwd = Path.cwd().resolve()
    except (OSError, RuntimeError):
        cwd = None

    if cwd is not None and _is_ancestor_or_self(cwd, p):
        return cwd

    return p.parent if p.is_file() else p


def is_trusted_project_root(project_root: Path) -> bool:
    """Whether state may be *created* under project_root.

    The distinction matters because GravityGuard runs as a PreToolUse hook:
    get_runtime_dir() mkdir's its directories, so an untrusted root does not
    merely misread state, it writes a fresh .gravityguard tree into the user's
    source tree. This predicate MUST agree with find_project_root(): a directory
    that root resolution can return is trusted, otherwise state is created in
    one place and read back from nowhere.

    A root is trusted when it is marker-anchored, when it already holds a
    .gravityguard directory, or when it is the process working directory (the
    workspace the agent was launched in). The untrusted remainder is the
    file's own parent in a tree with no project structure at all.
    """
    if _has_project_marker(project_root):
        return True

    try:
        if (project_root / ".gravityguard").is_dir():
            return True
    except OSError:
        return False

    try:
        return project_root == Path.cwd().resolve()
    except (OSError, RuntimeError):
        return False


def get_runtime_dir(project_root: Path) -> Path:
    """Returns the runtime state directory, creating it only for a trusted root."""
    runtime_dir = project_root / ".gravityguard" / "runtime"
    if is_trusted_project_root(project_root):
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
