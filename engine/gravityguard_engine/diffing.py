#!/usr/bin/env python3
"""
GravityGuard Engine — Content Projection & Diff Analysis Subsystem.
Zero external dependencies (difflib SequenceMatcher based, no git CLI required).
"""
import difflib
import os
from typing import List, Set, Tuple


def get_projected_and_old_content(
    target_file: str,
    tool_name: str,
    args: dict
) -> Tuple[str, str]:
    """
    Simulates the before and after state of the file without calling any external git CLI.
    Returns: (old_full_content, projected_full_content)
    """
    existing_content = ""
    if os.path.exists(target_file):
        try:
            with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
                existing_content = f.read()
        except (IOError, OSError):
            existing_content = ""

    if tool_name == "write_to_file":
        new_content = args.get("CodeContent", "")
        return existing_content, new_content

    if tool_name == "replace_file_content":
        target = args.get("TargetContent", "")
        repl = args.get("ReplacementContent", "")
        allow_multiple = args.get("AllowMultiple", False)
        if existing_content:
            count = -1 if allow_multiple else 1
            if target and target in existing_content:
                projected = existing_content.replace(target, repl, count)
            elif repl:
                projected = existing_content + "\n" + repl
            else:
                projected = existing_content
            return existing_content, projected
        else:
            # File does not exist on disk (mock/virtual payload in tests or new file)
            return target, repl

    if tool_name == "multi_replace_file_content":
        chunks = args.get("ReplacementChunks", [])
        if existing_content:
            projected = existing_content
            for chunk in chunks:
                if isinstance(chunk, dict):
                    t = chunk.get("TargetContent", "")
                    r = chunk.get("ReplacementContent", "")
                    m = chunk.get("AllowMultiple", False)
                    if t and t in projected:
                        c = -1 if m else 1
                        projected = projected.replace(t, r, c)
            return existing_content, projected
        else:
            old_parts = [chunk.get("TargetContent", "") for chunk in chunks if isinstance(chunk, dict)]
            new_parts = [chunk.get("ReplacementContent", "") for chunk in chunks if isinstance(chunk, dict)]
            return "\n".join(old_parts), "\n".join(new_parts)

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
