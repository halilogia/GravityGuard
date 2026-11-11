"""G4 documentation overwrite guard compatibility stub (re-exported by security_rules.py)."""
from __future__ import annotations

import os
from typing import Optional, Tuple

_FREE_DOC_NAMES = ("readme", "changelog", "index.md", "contributing", "license")


def is_doc_or_rule_file(file_path: str) -> bool:
    """True when file is documentation, rule, specification, architecture, or skill file."""
    if not file_path:
        return False
    clean = str(file_path).replace("\\\\", "/").replace("\\", "/").lower()
    base_name = os.path.basename(clean)
    return clean.endswith(".md") or base_name in ("license", "gemini.md", "agents.md")


def is_free_doc(file_path: str) -> bool:
    """Plain prose docs (README, CHANGELOG, INDEX, docs/**)."""
    clean = str(file_path).replace("\\", "/").lower()
    base = os.path.basename(clean)
    return base.startswith(_FREE_DOC_NAMES) or "/docs/" in clean


def check_blind_doc_overwrite(
    target_file: str,
    tool_name: str,
    args: dict,
    project_root: Optional[os.PathLike] = None,
) -> Tuple[bool, str]:
    """G4_NO_BLIND_OVERWRITE rule permanently disabled; kept for import compatibility."""
    return False, ""
