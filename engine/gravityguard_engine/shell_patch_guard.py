"""SCRATCH_PATCH_DENY: a throwaway or inline interpreter script that rewrites project source files.

When an edit tool fails (CRLF, quoting) or the ratchet refuses growth, the detour is `python patch_x.py` whose body does
`Path("src/app.py").write_text(...)`. That skips every file-tool guard. Legitimate scratch work (parsing JSON/CSV, analysis
under `scratch/`, build scripts with a real name) stays allowed: only a script that is throwaway by name (or inline code)
AND writes to a source-file path outside scratch/temp directories is refused. Command text only, no interpreter or sandbox.
"""
import os
import re

from .debt_ratchet import SCAN_SOURCE_SUFFIXES
from .shell_control_guard import (
    _INTERPRETERS,
    _SEGMENTS,
    _WRITE_API,
    _base_dir,
    _norm,
    _read_script,
    _script_files,
    _tokens,
)
from .shell_danger import parse_command

_THROWAWAY_TOKENS = frozenset({"patch", "patched", "temp", "tmp", "scratch", "hotfix", "fixup", "fix", "apply", "mutate", "oneoff"})
_SOURCE_SUFFIX = re.compile("(?:" + "|".join(re.escape(s) for s in SCAN_SOURCE_SUFFIXES) + r")(?!\w)")
_PATH_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_./~:-")
_MAX_PATH = 300
_SCRATCH_DIR = re.compile(r"(?:^|/)(?:scratch|brain|tmp|temp|node_modules)/")
_INLINE_FLAG = re.compile(r"(?<!\S)-(?:c|e|command|encodedcommand)(?!\S)|<<|(?<!\S)-(?!\S)")


def _is_throwaway(path: str) -> bool:
    stem = os.path.basename(path).lower().rsplit(".", 1)[0]
    return bool(set(re.split(r"[_\-.\s]+", stem)) & _THROWAWAY_TOKENS) or "/scratch/" in _norm(path)


def _writes_source(text: str) -> bool:
    """Normalized script/inline text that has a write API and names a source file outside scratch directories."""
    if not _WRITE_API.search(text):
        return False
    for match in _SOURCE_SUFFIX.finditer(text):  # walk back from each suffix: linear, no regex backtracking
        start = match.start()
        floor = max(0, start - _MAX_PATH)
        while start > floor and text[start - 1] in _PATH_CHARS:
            start -= 1
        if start < match.start() and not _SCRATCH_DIR.search(text[start:match.end()]):
            return True
    return False


def patch_script_reason(command: str, cwd: str | None = None) -> str:
    """Name of the offending script (or 'inline code') when the command runs a source-patching script, else ''."""
    if not isinstance(command, str):
        return ""
    cwd = _base_dir(command, cwd)
    for segment in _SEGMENTS.split(command[:200_000]):
        parsed = parse_command(segment)
        if not parsed or parsed[0].lower().removesuffix(".exe") not in _INTERPRETERS:
            continue
        scripts = _script_files(_tokens(segment), cwd)
        for path in scripts:
            if _is_throwaway(path) and _writes_source(_read_script(path)):
                return os.path.basename(path)
        if not scripts and _INLINE_FLAG.search(segment) and _writes_source(_norm(command)):
            return "inline code"
    return ""
