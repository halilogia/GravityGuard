"""Measurement-only quality signals: suppression markers in a "fix" and single-implementation abstractions.

Neither signal blocks. Evasion markers are attached to a recovery so the UI can tell a real fix from a silenced one;
OE_SINGLE_IMPL runs in shadow mode unless a project opts into warnings.
"""
import re
from typing import List, Optional, Tuple

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


_TS_INTERFACE = re.compile(r"\binterface\s+([A-Za-z_]\w*)")
_TS_ABSTRACT = re.compile(r"\babstract\s+class\s+([A-Za-z_]\w*)")
_TS_IMPLEMENTS = re.compile(r"\bclass\s+\w+(?:\s+extends\s+([A-Za-z_]\w*))?(?:\s+implements\s+([\w\s,]+?))?\s*\{")
_PY_BASE = re.compile(r"^\s*class\s+([A-Za-z_]\w*)\s*\(([^)]*\b(?:ABC|Protocol)\b[^)]*)\)\s*:", re.MULTILINE)
_PY_CLASS = re.compile(r"^\s*class\s+\w+\s*\(([^)]*)\)\s*:", re.MULTILINE)


def check_single_implementation(added_text: str, is_python: bool) -> Tuple[bool, str]:
    """Flags an abstraction added together with exactly one implementation of it.

    An interface, abstract class, ABC or Protocol with a single implementer is indirection without a second caller.
    Only abstractions declared in the same change are judged; an existing contract that gains its first implementer is
    left alone.
    """
    if not added_text:
        return False, ""
    single: List[str] = []
    if is_python:
        bases = [m.group(1) for m in _PY_BASE.finditer(added_text)]
        if bases:
            parents = [p.strip() for m in _PY_CLASS.finditer(added_text) for p in m.group(1).split(",")]
            single = [b for b in bases if parents.count(b) == 1]
    else:
        contracts = _TS_INTERFACE.findall(added_text) + _TS_ABSTRACT.findall(added_text)
        if contracts:
            uses: List[str] = []
            for m in _TS_IMPLEMENTS.finditer(added_text):
                if m.group(1):
                    uses.append(m.group(1))
                if m.group(2):
                    uses.extend(x.strip() for x in m.group(2).split(",") if x.strip())
            single = [c for c in contracts if uses.count(c) == 1]
    if not single:
        return False, ""
    names = ", ".join(single)
    return True, (
        f"Tek uygulamalı soyutlama: {names} yalnızca bir sınıf tarafından uygulanıyor. "
        f"İkinci bir kullanım yoksa soyutlamayı kaldırıp sınıfı doğrudan kullanın."
    )


def oe_single_impl_mode(cfg: Optional[dict]) -> str:
    """'warn' only when the project opts in; the rule observes in shadow mode otherwise."""
    if isinstance(cfg, dict):
        entry = (cfg.get("rules") or {}).get("OE_SINGLE_IMPL")
        mode = entry.get("mode") if isinstance(entry, dict) else entry
        if mode in ("warn", "off"):
            return mode
    return "shadow"
