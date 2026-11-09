"""Measurement-only quality signal: suppression markers in a "fix".

It never blocks. Evasion markers are attached to a recovery so the UI can tell a real fix from a silenced one.
"""
import re
from typing import List

# Lines that silence a checker instead of fixing the code.
_EVASION_PATTERNS = (
    ("ts-ignore", re.compile(r"@ts-(?:ignore|nocheck|expect-error)\b")),
    ("eslint-disable", re.compile(r"eslint-disable")),
    ("noqa", re.compile(r"#\s*noqa\b", re.IGNORECASE)),
    ("type-ignore", re.compile(r"#\s*type:\s*ignore\b")),
    ("pylint-disable", re.compile(r"#\s*pylint:\s*disable\b")),
    ("no-cover", re.compile(r"#\s*pragma:\s*no\s*cover\b")),
    ("discarded-error", re.compile(r"\bvoid\s+(?:e|err|error|ex)\b\s*;?|^\s*_\s*=\s*(?:e|err|error|ex)\s*$")),
)


def find_evasion_markers(added_text: str) -> List[str]:
    """Names of suppression markers present in the added lines, in first-seen order, without duplicates."""
    if not added_text:
        return []
    found: List[str] = []
    for line in added_text.splitlines():
        for name, pattern in _EVASION_PATTERNS:
            if name not in found and pattern.search(line):
                found.append(name)
    return found


