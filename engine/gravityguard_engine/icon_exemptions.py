"""DESIGN_ICON_RULE exemptions: places where an emoji is data, not rendered UI."""
import re
from typing import Sequence

_EXEMPT_DIRS = frozenset({
    "doc", "docs", "documentation", "test", "tests", "__tests__",
    "scratch", "scratchpad", "scripts", "bin", "cli", "hooks",
})

# A regex call or a raw string literal on the line: the emoji is something to match or strip.
_PATTERN_CONTEXT = re.compile(
    r"\bre\.(?:compile|sub|subn|search|match|fullmatch|findall|finditer|split)\("
    r"|(?<![\w])[rR][bBuU]?[\"']"
)


def is_icon_exempt_path(parts: Sequence[str]) -> bool:
    """True when a directory component of the path (file name excluded) is a doc, test or scratch folder."""
    return any(part in _EXEMPT_DIRS for part in parts[:-1])


def is_emoji_pattern_line(line: str) -> bool:
    return bool(_PATTERN_CONTEXT.search(line))
