"""
GravityGuard Engine — refactoring blueprint for block / regression messages.

Names the one or two biggest top-level classes / functions of a file and a sibling module path to move them to, so an
agent that was just told "split this" does not burn retries guessing where. Python is read with the AST, TypeScript /
JavaScript / Go / Rust by declaration lines; anything unparsable yields an empty hint (the message simply has no tip).
"""
import ast
import os
import re
from typing import List, Tuple

from .refactor_cluster import block_candidates, python_candidates

_MIN_UNIT_LOC = 15
_DECL_RE = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:abstract\s+)?(?:pub\s+)?"
    r"(?P<kind>class|function|func|fn|struct|interface)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
)
_CODE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs", ".gd")


def _snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).replace("-", "_").lower()


def _python_units(content: str) -> List[Tuple[str, str, int]]:
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return []
    units = []
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "sınıfını" if isinstance(node, ast.ClassDef) else "işlevini"
            units.append((node.name, kind, getattr(node, "end_lineno", node.lineno) - node.lineno + 1))
    return units


def _declaration_blocks(content: str) -> List[Tuple[str, bool, int, str]]:
    """(name, is_function, loc, text) per top-level declaration line to the next one."""
    lines = content.splitlines()
    starts = [(i, m) for i, line in enumerate(lines) if (m := _DECL_RE.match(line))]
    blocks = []
    for idx, (line_no, match) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        blocks.append((match["name"], match["kind"] in ("function", "func", "fn"), end - line_no, "\n".join(lines[line_no:end])))
    return blocks


def _declaration_units(content: str) -> List[Tuple[str, str, int]]:
    return [(name, "işlevini" if is_func else "sınıfını", loc) for name, is_func, loc, _ in _declaration_blocks(content)]


def build_refactor_hint(content: str, file_path: str, limit: int = 2) -> str:
    """'Öneri: ...' sentence for the best clusters / movable units of `file_path`, or '' when none is worth moving."""
    stem, ext = os.path.splitext(os.path.basename(file_path))
    ext = ext.lower()
    if ext == ".py":
        units, smart = _python_units(content), python_candidates(content, file_path)
    elif ext in _CODE_SUFFIXES:
        units, smart = _declaration_units(content), block_candidates(_declaration_blocks(content), content, file_path)
    else:
        return ""
    covered = set().union(*(c[2] for c in smart)) if smart else set()
    base = os.path.basename(file_path)
    folder = os.path.dirname(file_path.replace("\\", "/"))
    ranked = [(loc, text, True) for loc, text, _ in smart]
    for name, kind, loc in units:
        if loc >= _MIN_UNIT_LOC and name not in covered:
            suggested = "/".join(p for p in (folder, f"{stem}_{_snake(name)}{ext}") if p)
            ranked.append((loc, f"'{base}' içindeki '{name}' {kind} ({loc} satır) '{suggested}' altına taşıyarak", False))
    top = sorted(ranked, key=lambda c: -c[0])[:limit]
    if not top:
        return ""
    sentences = [text for _, text, is_smart in top if is_smart]
    legacy = [text for _, text, is_smart in top if not is_smart]
    if legacy:
        sentences.append(" ve ".join(legacy) + " dosyayı hafifletin.")
    return "Öneri: " + " ".join(sentences)
