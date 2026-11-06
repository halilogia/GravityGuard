"""
GravityGuard Engine — Python SRP analysis (BLOCK rule SRP_BOUNDARY).

Two checks, both tuned to avoid blocking legitimate small files:
- UI + Network imports in one file ("Sorumluluk Çakışması"), only once the file is big enough to need a split;
  `urllib.parse` / `http.HTTPStatus` style imports are not network use.
- God module: >= 4 independent business classes, where data holders (dataclass / NamedTuple / TypedDict / Enum /
  exceptions / pydantic models) and tiny helper classes do not count.
The warn-only counterpart for what this check cannot see (procedural monoliths) is srp_signals.py.
"""
import ast
import os
import re
from typing import Dict, Optional, Set, Tuple

from .project_context import DEFAULT_COMPLEXITY_THRESHOLDS
from .refactor_hint import build_refactor_hint

_UI_PACKAGES = re.compile(r"^(?:tkinter|customtkinter|pyqt\d?|pyside\d?|wx|kivy)$")
_NET_PACKAGES = {"requests", "aiohttp", "httpx", "websockets", "websocket", "socket", "urllib3"}
# Only these submodules of a stdlib package perform I/O; urllib.parse / urllib.error / http (status codes) do not.
_NET_SUBMODULES = {"urllib": {"request"}, "http": {"client", "server"}}

EXEMPT_BASE_NAMES = {
    "Exception", "BaseException", "Error",
    "Panel", "Operator", "PropertyGroup", "Menu", "Header", "UIList",
    "BaseModel", "BaseSettings", "Schema", "Model",
    "Enum", "IntEnum", "StrEnum", "Flag", "IntFlag",
    "NamedTuple", "TypedDict",
    "Protocol", "ABC",
}
EXEMPT_DECORATORS = {"dataclass", "pydantic_dataclass", "define", "frozen", "s", "attrs"}

COHESIVE_MODULE_PATTERNS: Set[str] = {
    "_models.py", "models.py",
    "_types.py", "types.py",
    "_events.py", "events.py",
    "_schemas.py", "schemas.py", "schema.py",
    "_dtos.py", "dtos.py",
    "_interfaces.py", "interfaces.py",
    "_protocols.py", "protocols.py",
    "_properties.py", "properties.py",
    "_operators.py", "operators.py",
    "_constants.py", "constants.py",
    "_exceptions.py", "exceptions.py",
}


def is_py_cohesive_monolith(content: str) -> bool:
    return bool(re.search(r"#\s*(?:srp:\s*(?:allow-monolith|cohesive-monolith|bypass|noqa)|noqa:\s*srp)\b", content, re.IGNORECASE))


def is_cohesive_module_by_filename(file_path: str) -> bool:
    if not file_path:
        return False
    base_name = os.path.basename(file_path.replace("\\", "/")).lower()
    return any(base_name == pat or base_name.endswith(pat) for pat in COHESIVE_MODULE_PATTERNS)


def is_test_path(file_path: str) -> bool:
    normalized = "/" + (file_path or "").replace("\\", "/").lower().lstrip("/")
    base = os.path.basename(normalized)
    return "/tests/" in normalized or "/test/" in normalized or base.startswith("test_") or base in {"conftest.py"} \
        or base.endswith("_test.py")


def _get_base_name(node: ast.expr) -> str:
    """Name of a base class / decorator, seeing through `Protocol[T]` (subscript) and `dataclass(frozen=True)` (call)."""
    while isinstance(node, (ast.Subscript, ast.Call)):
        node = node.value if isinstance(node, ast.Subscript) else node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_exempt_class_ast(cls_node: ast.ClassDef, file_path: str) -> bool:
    for base in cls_node.bases:
        base_name = _get_base_name(base)
        if base_name in EXEMPT_BASE_NAMES or base_name.endswith(("Error", "Exception")):
            return True

    for dec in cls_node.decorator_list:
        if _get_base_name(dec) in EXEMPT_DECORATORS:
            return True

    file_lower = file_path.lower().replace("\\", "/")
    if ("bpy" in file_lower or "blender" in file_lower or "addon" in file_lower) and cls_node.name.startswith(("OBJECT_OT_", "MESH_OT_", "VIEW3D_PT_", "WM_OT_")):
        return True

    return False


def import_kinds(module: str, imported_names: Tuple[str, ...] = ()) -> Set[str]:
    """Which responsibility ('ui' / 'net') an import brings in, matched on the top-level package, never on substrings."""
    parts = module.lower().split(".")
    top = parts[0]
    kinds: Set[str] = set()
    if _UI_PACKAGES.match(top):
        kinds.add("ui")
    if top in _NET_PACKAGES:
        kinds.add("net")
    elif top in _NET_SUBMODULES:
        io_modules = _NET_SUBMODULES[top]
        if (len(parts) > 1 and parts[1] in io_modules) or (len(parts) == 1 and io_modules & {n.lower() for n in imported_names}):
            kinds.add("net")
    return kinds


def collect_import_kinds(tree: ast.AST) -> Set[str]:
    kinds: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                kinds |= import_kinds(alias.name)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            kinds |= import_kinds(node.module or "", tuple(a.name for a in node.names))
    return kinds


def _loc(content: str) -> int:
    return sum(1 for line in content.splitlines() if line.strip())


def analyze_python_srp(content: str, file_path: str = "", thresholds: Optional[Dict[str, int]] = None) -> Tuple[bool, str]:
    if is_py_cohesive_monolith(content) or is_cohesive_module_by_filename(file_path) or is_test_path(file_path):
        return False, "Exempt cohesive module"

    thresholds = thresholds or DEFAULT_COMPLEXITY_THRESHOLDS
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return analyze_python_srp_regex_fallback(content, file_path, thresholds)

    kinds = collect_import_kinds(tree)
    mixed_min_loc = thresholds["srpMixedImportsMinLoc"]
    if {"ui", "net"} <= kinds and _loc(content) >= mixed_min_loc:
        return True, (
            f"Sorumluluk Çakışması: Dosya hem UI (Arayüz) hem de Network (Ağ/HTTP) kütüphanelerini aynı anda barındırıyor "
            f"({_loc(content)} LOC >= {mixed_min_loc})! Ağ kodunu ayrı bir modüle taşıyın. {build_refactor_hint(content, file_path)}"
        ).strip()

    min_class_loc = thresholds["srpMinClassLoc"]
    major_classes = [
        c for c in tree.body
        if isinstance(c, ast.ClassDef) and not _is_exempt_class_ast(c, file_path)
        and (getattr(c, "end_lineno", c.lineno) - c.lineno + 1) >= min_class_loc
    ]

    if len(major_classes) >= 4:
        names = [c.name for c in major_classes]
        return True, (
            f"Çoklu Sorumluluk İhlali (God Module): Dosya {len(major_classes)} bağımsız ana iş sınıfı "
            f"({', '.join(names[:3])}...) barındırıyor! Sınıfları ayrı dosyalara taşıyın. {build_refactor_hint(content, file_path)}"
        ).strip()

    return False, "SRP Compliant"


def analyze_python_srp_regex_fallback(content: str, file_path: str = "", thresholds: Optional[Dict[str, int]] = None) -> Tuple[bool, str]:
    """Used when the projected content does not parse (mid-edit snippet): same rules, regex-level."""
    thresholds = thresholds or DEFAULT_COMPLEXITY_THRESHOLDS
    line_count = _loc(content)

    has_ui = bool(re.search(r"^\s*(?:import|from)\s+(?:tkinter|customtkinter|PyQt\d?|PySide\d?|wx|kivy)\b|from\s+bpy\.types\s+import\s+.*Panel", content, re.IGNORECASE | re.MULTILINE))
    has_net = bool(re.search(r"^\s*(?:import|from)\s+(?:requests|aiohttp|httpx|websockets?|urllib\.request|urllib3|http\.client|http\.server|socket)\b", content, re.IGNORECASE | re.MULTILINE))

    if has_ui and has_net and line_count >= thresholds["srpMixedImportsMinLoc"]:
        return True, "Sorumluluk Çakışması: Dosya hem UI hem de Network kütüphanelerini aynı anda barındırıyor!"

    exempt_markers = tuple(EXEMPT_BASE_NAMES) + ("Error", "Exception")
    class_matches = re.findall(r"^(@\w[^\n]*\n)?class\s+([A-Za-z0-9_]+)(?:\(([^)]*)\))?:", content, re.MULTILINE)
    major_classes = [
        name for decorator, name, bases in class_matches
        if not any(k in bases for k in exempt_markers) and "dataclass" not in decorator
    ]

    if len(major_classes) >= 5:
        return True, (
            f"Çoklu Sınıf İhlali (God Module): Dosya {len(major_classes)} bağımsız ana sınıf "
            f"({', '.join(major_classes[:4])}...) barındırıyor!"
        )

    return False, f"SRP Compliant (Fallback check: {line_count} lines)"
