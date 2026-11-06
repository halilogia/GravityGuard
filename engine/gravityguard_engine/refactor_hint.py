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


def _declaration_units(content: str) -> List[Tuple[str, str, int]]:
    lines = content.splitlines()
    starts = [(i, m) for i, line in enumerate(lines) if (m := _DECL_RE.match(line))]
    units = []
    for idx, (line_no, match) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        kind = "işlevini" if match["kind"] in ("function", "func", "fn") else "sınıfını"
        units.append((match["name"], kind, end - line_no))
    return units


def build_refactor_hint(content: str, file_path: str, limit: int = 2) -> str:
    """'Öneri: ...' sentence for the biggest movable units of `file_path`, or '' when none is worth moving."""
    stem, ext = os.path.splitext(os.path.basename(file_path))
    ext = ext.lower()
    if ext == ".py":
        units = _python_units(content)
    elif ext in _CODE_SUFFIXES:
        units = _declaration_units(content)
    else:
        return ""
    big = sorted((u for u in units if u[2] >= _MIN_UNIT_LOC), key=lambda u: -u[2])[:limit]
    if not big:
        return ""
    folder = os.path.dirname(file_path.replace("\\", "/"))
    base = os.path.basename(file_path)
    tips = []
    for name, kind, loc in big:
        suggested = "/".join(p for p in (folder, f"{stem}_{_snake(name)}{ext}") if p)
        tips.append(f"'{base}' içindeki '{name}' {kind} ({loc} satır) '{suggested}' altına taşıyarak")
    return "Öneri: " + " ve ".join(tips) + " dosyayı hafifletin."
