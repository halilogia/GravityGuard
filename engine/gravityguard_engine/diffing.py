#!/usr/bin/env python3
"""
GravityGuard Engine — Content Projection & Diff Analysis Subsystem.
Zero external dependencies (difflib SequenceMatcher based, no git CLI required).
"""
import difflib
import os
from typing import List, Set, Tuple
from .operations import normalize_operation


class ProjectionError(ValueError):
    """A proposed mutation cannot be projected faithfully."""


def _replace(content: str, args: dict) -> str:
    target = args["TargetContent"]
    if not target:
        raise ProjectionError("Empty search text requires an explicit insertion adapter")
    lines = content.splitlines(keepends=True)
    start = args.get("StartLine", 1) - 1
    end = args.get("EndLine", len(lines))
    if start < 0 or end <= start or start >= len(lines) or end > len(lines):
        raise ProjectionError("Edit line bounds are outside the file")
    window = "".join(lines[start:end])
    count = window.count(target)
    if count == 0:
        raise ProjectionError("Search text was not found in the requested range")
    multiple = args.get("AllowMultiple", False)
    if count > 1 and not multiple:
        raise ProjectionError("Search text is ambiguous; specify a range or replace_all")
    changed = window.replace(target, args["ReplacementContent"], -1 if multiple else 1)
    return "".join(lines[:start]) + changed + "".join(lines[end:])


def _text(value) -> str:
    """Content arguments are strings; anything else (int, None, list) counts as empty."""
    return value if isinstance(value, str) else ""


def get_projected_and_old_content(
    target_file: str,
    tool_name: str,
    args: dict,
    allow_virtual: bool = False,
) -> Tuple[str, str]:
    """
    Simulates the before and after state of the file without calling any external git CLI.
    Returns: (old_full_content, projected_full_content)
    """
    operation = normalize_operation(tool_name, args)
    if operation is not None:
        args = operation.args
        tool_name = {"WRITE": "write_to_file", "EDIT": "replace_file_content",
                     "MULTI_EDIT": "multi_replace_file_content", "READ": "read_file"}[operation.kind]
    existing_content = ""
    exists = os.path.exists(target_file)
    if exists:
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                existing_content = f.read()
        except (OSError, UnicodeError) as exc:
            raise ProjectionError("Existing file could not be read as UTF-8") from exc

    if tool_name in ("write_to_file", "write_file"):
        new_content = _text(args.get("CodeContent"))
        return existing_content, new_content

    if tool_name in ("replace_file_content", "edit_file"):
        target = _text(args.get("TargetContent"))
        repl = _text(args.get("ReplacementContent"))
        if exists:
            return existing_content, _replace(existing_content, args)
        elif allow_virtual:
            # Explicit synthetic-fixture mode; production hooks require disk state.
            return target, repl
        raise ProjectionError("Cannot edit a file that does not exist")

    if tool_name == "multi_replace_file_content":
        chunks = args.get("ReplacementChunks")
        if not isinstance(chunks, list):
            chunks = []
        if exists:
            projected = existing_content
            for chunk in chunks:
                projected = _replace(projected, chunk)
            return existing_content, projected
        elif allow_virtual:
            old_parts = [_text(chunk.get("TargetContent")) for chunk in chunks if isinstance(chunk, dict)]
            new_parts = [_text(chunk.get("ReplacementContent")) for chunk in chunks if isinstance(chunk, dict)]
            return "\n".join(old_parts), "\n".join(new_parts)
        raise ProjectionError("Cannot edit a file that does not exist")

    return existing_content, existing_content


def get_diff_analysis(
    old_content: str,
    projected_content: str
) -> Tuple[List[str], str, Set[int]]:
    """
    Extracts strictly added/modified lines using difflib.SequenceMatcher.
    Zero git commands executed.
    Returns:
      - added_lines: list of newly introduced lines
      - added_text: joined string of added lines
      - added_line_numbers: set of 1-indexed line numbers in projected_content that are new or modified
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = projected_content.splitlines(keepends=True)

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    added_lines: List[str] = []
    added_line_numbers: Set[int] = set()

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ('insert', 'replace'):
            for new_line_idx in range(j1, j2):
                added_lines.append(new_lines[new_line_idx])
                added_line_numbers.add(new_line_idx + 1)

    added_text = "".join(added_lines)
    return added_lines, added_text, added_line_numbers


def extract_diff_and_projected(
    target_file: str,
    tool_name: str,
    args: dict
) -> Tuple[str, str, str]:
    """Compatibility alias for old signature."""
    old_c, proj_c = get_projected_and_old_content(target_file, tool_name, args)
    added_lines, added_text, _ = get_diff_analysis(old_c, proj_c)
    return old_c, added_text, proj_c


# --- Content Hashing & Git State Utilities (Relocated from review_governance) ---
import hashlib
from pathlib import Path
import subprocess
from typing import Optional, Dict, Any

def _normalize_newlines(text: str) -> str:
    """CRLF/CR → LF so a text hash is stable across platforms."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def hash_text(text: str) -> str:
    """SHA-256 of newline-normalized UTF-8 text."""
    return hashlib.sha256(_normalize_newlines(text or "").encode("utf-8")).hexdigest()


def read_disk_text_hash(path: Path) -> Optional[str]:
    """Newline-normalized text hash of a file, or None when it cannot be read."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return hash_text(handle.read())
    except (IOError, OSError):
        return None


def _norm_rel(target_file: str, project_root: Optional[Path]) -> str:
    p = Path(str(target_file))
    if project_root is not None:
        try:
            rel = p.resolve().relative_to(Path(project_root).resolve())
            return rel.as_posix().lower()
        except (OSError, ValueError):
            pass
    return p.as_posix().lower()


def fingerprint_from_hashes(file_hashes: Dict[str, str]) -> str:
    lines = [f"{path}:{file_hashes[path]}" for path in sorted(file_hashes)]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _git_out(root: Path, *args: str) -> Optional[str]:
    try:
        proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None


def git_binding(project_root: Optional[Path] = None) -> Dict[str, Optional[str]]:
    root = Path(project_root or Path.cwd())
    return {
        "commit": _git_out(root, "rev-parse", "HEAD"),
        "tree": _git_out(root, "rev-parse", "HEAD^{tree}"),
    }


def binding_is_stale(binding: Dict[str, Any], project_root: Optional[Path] = None) -> bool:
    root = Path(project_root or Path.cwd())
    bound_tree = binding.get("tree")
    if bound_tree and git_binding(root).get("tree") != bound_tree:
        return True
    for rel, expected in (binding.get("file_hashes") or {}).items():
        if read_disk_text_hash(root / rel) != expected:
            return True
    return False
