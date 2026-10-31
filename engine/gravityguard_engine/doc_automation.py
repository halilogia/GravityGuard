"""
GravityGuard — deterministic documentation automation run from the Stop hook.

Best-effort jobs (callers wrap them; a failure must never break the session):
- ``sync_architecture``: refresh ARCHITECTURE.md using the project's generator or a built-in source inventory.
- ``inject_knowledge_entry``: capture rule/configuration changes as idempotent ADR bullets.
- ``inject_changelog_entry``: last-resort one-line CHANGELOG.md entry under the FIRST ``## [Unreleased]`` heading,
  so a doc obligation can be closed even when the model's ``edit_file`` keeps failing on an ambiguous search text.

Standard library only.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

ARCH_TRIGGER_DIRS = ("engine/", "src/", "addons/", "app/", "lib/", "core/", "ui/", "scripts/", "tools/", "web/")
SOURCE_EXTS = {".py", ".ts", ".tsx", ".js", ".mjs", ".gd", ".rs", ".go", ".cs"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "target", ".godot", "vendor"}
ARCH_START = "<!-- ARCH-AUTO:START (tools/generate_architecture.py --sync; elle düzenlemeyin) -->"
ARCH_END = "<!-- ARCH-AUTO:END -->"
UNRELEASED_HEADING = "## [Unreleased]"
AUTO_ENTRY_PREFIX = "- **[auto]**"


def _git(project_root: Path, *args: str) -> str:
    try:
        res = subprocess.run(
            ["git", *args], cwd=str(project_root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return res.stdout if res.returncode == 0 else ""


def _relative(project_root: Path, path_str: str) -> str:
    """Project-relative posix path; the path as given when it lies outside the project."""
    norm = path_str.replace("\\", "/")
    try:
        return Path(norm).resolve().relative_to(project_root.resolve()).as_posix()
    except (ValueError, OSError):
        return norm


def changed_code_files(project_root: Path) -> List[str]:
    """Uncommitted changed paths (project-relative, posix) under the architecture trigger directories."""
    paths = []
    entries = iter(_git(project_root, "status", "--porcelain", "-z", "--untracked-files=all").split("\0"))
    for entry in entries:
        rel = entry[3:].replace("\\", "/")
        candidates = [rel]
        if "R" in entry[:2] or "C" in entry[:2]:
            candidates.append(next(entries, ""))
        paths.extend(p for p in candidates if p.startswith(ARCH_TRIGGER_DIRS) and Path(p).suffix in SOURCE_EXTS)
    return sorted(set(paths))


def sync_architecture(project_root: Path, target: str = "ARCHITECTURE.md") -> Optional[Dict[str, str]]:
    """Use the project generator or the built-in fallback when source files change."""
    tool = project_root / "tools" / "generate_architecture.py"
    if not changed_code_files(project_root):
        return None
    if not tool.is_file():
        return sync_generic_architecture(project_root, target)
    spec = importlib.util.spec_from_file_location("_gg_generate_architecture", tool)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sync = getattr(module, "sync_architecture", None)
    if sync is None:
        return None
    status, path = sync(project_root, target)
    return {"status": status, "path": str(path)}


def sync_generic_architecture(project_root: Path, target: str = "ARCHITECTURE.md") -> Optional[Dict[str, str]]:
    """Replace only the managed section; cap that section at 200 lines."""
    path = project_root / target
    if not path.is_file() or path.is_symlink():
        return None
    try:
        path.resolve().relative_to(project_root.resolve())
    except (ValueError, OSError):
        return None
    from .doc_policy import _is_test_file
    groups = {}
    total = loc = tests = 0
    for directory, dirs, names in os.walk(project_root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (Path(directory) / d).is_symlink())
        for name in sorted(names):
            source = Path(directory) / name
            if source.suffix not in SOURCE_EXTS or source.is_symlink():
                continue
            rel = source.relative_to(project_root)
            count = sum(bool(line.strip()) for line in source.read_text(encoding="utf-8", errors="replace").splitlines())
            group = rel.parts[0] if len(rel.parts) > 1 else "(root)"
            row = groups.setdefault(group, [0, 0])
            row[0] += 1
            row[1] += count
            total += 1
            loc += count
            tests += int(_is_test_file(rel))
    lines = [ARCH_START, "## Source inventory", "", f"- Source files: **{total}**; non-empty LOC: **{loc}**",
             f"- Test files: **{tests}**", "", "| Directory | Files | LOC |", "|---|---:|---:|"]
    rows = sorted(groups.items())
    for name, values in rows[:190]:
        safe = name.replace("|", "&#124;").replace("\n", " ").replace("\r", " ")
        lines.append(f"| {safe} | {values[0]} | {values[1]} |")
    if len(rows) > 190:
        lines.append(f"| Other directories | {sum(v[0] for _, v in rows[190:])} | {sum(v[1] for _, v in rows[190:])} |")
    lines.append(ARCH_END)
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    current = raw.decode("utf-8")
    block = newline.join(lines)
    start, end = current.find(ARCH_START), current.find(ARCH_END)
    if start >= 0 and end > start:
        updated = current[:start] + block + current[end + len(ARCH_END):]
        status = "updated"
    elif start >= 0 or end >= 0:
        raise ValueError("Incomplete architecture markers")
    else:
        updated = current.rstrip("\r\n") + newline * 2 + block + newline
        status = "appended"
    if updated == current:
        status = "unchanged"
    else:
        path.write_bytes(updated.encode("utf-8"))
    return {"status": status, "path": str(path)}


def is_knowledge_governed_path(path_str: str, project_root: Optional[Path] = None) -> bool:
    path = Path(path_str.replace("\\", "/"))
    if project_root is not None:
        root = project_root.resolve()
        try:
            path = (path if path.is_absolute() else root / path).resolve().relative_to(root)
        except (ValueError, OSError):
            return False
    rel = path.as_posix()
    return (rel in {".gravityguard.json", "hooks.json", "plugin/hooks.json"}
            or "rules" in path.parts[:-1] or path.name.endswith("_rules.py") or path.name == "doc_policy.py")


def resolve_knowledge_doc(project_root: Path) -> Optional[str]:
    return next((p for p in ("docs/KNOWLEDGE.md", "KNOWLEDGE.md") if (project_root / p).is_file()), None)


def inject_knowledge_entry(knowledge_path: Path, summary: str) -> bool:
    """Append an idempotent ADR bullet, retaining the document's newline style."""
    if not knowledge_path.is_file():
        return False
    raw = knowledge_path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    current = raw.decode("utf-8")
    summary = " ".join(summary.splitlines())
    entry = f"- **[auto-ADR]** {summary} kural/mimari değişikliği yapıldı (GravityGuard otomatik kayıt)."
    if entry in current.splitlines():
        return False
    knowledge_path.write_bytes((current + (newline if current and not current.endswith("\n") else "") + entry + newline).encode("utf-8"))
    return True


def summarize_changes(project_root: Path, files: List[str]) -> str:
    """One-line summary of changed files with +/- line counts from git (best effort)."""
    parts = []
    for f in files[:4]:
        rel = _relative(project_root, f)
        stat = _git(project_root, "diff", "--numstat", "HEAD", "--", rel).split()
        delta = f" (+{stat[0]}/-{stat[1]})" if len(stat) >= 2 else ""
        parts.append(f"`{rel}`{delta}")
    more = f" ve {len(files) - 4} dosya daha" if len(files) > 4 else ""
    return ", ".join(parts) + more


def inject_changelog_entry(changelog: Path, summary: str) -> bool:
    """Insert a bullet directly under the first ``## [Unreleased]`` heading. Idempotent; False when it cannot be done
    safely (file or heading missing, entry already present)."""
    if not changelog.is_file():
        return False
    raw = changelog.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    lines = raw.decode("utf-8", errors="replace").split(newline)
    entry = f"{AUTO_ENTRY_PREFIX} {summary} değişti; ayrıntılı açıklama eklenmeli (GravityGuard otomatik kayıt)."
    if any(line.strip() == entry for line in lines):
        return False
    for i, line in enumerate(lines):
        if line.strip() == UNRELEASED_HEADING:
            lines[i + 1:i + 1] = ["", entry]
            changelog.write_bytes(newline.join(lines).encode("utf-8"))
            return True
    return False
