#!/usr/bin/env python3
"""
GravityGuard Engine — Architectural Rules & Modularity Subsystem.
Implements:
- G3: Compiler & Linter Bypass Warnings (WARN)
- G4: Layer Boundaries & Import Matrix (BLOCK)
- OE_SPIKE: Over-engineering & Premature Abstraction (WARN)
- Cumulative Growth & Micro-Chunking Prevention (WARN)
- ARCH_FILE_GROWTH: Large File & Creep Detection (WARN)
- SRP: Single Responsibility Principle & God Module Analysis (BLOCK)
Zero external dependencies.
"""
import ast
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .audit import _resolve_log_dir
from .project_context import DEFAULT_COMPLEXITY_THRESHOLDS, load_gravityguard_config


# --- G3: COMPILER & LINTER BYPASS (WARN ONLY) ---
def check_g3_compiler_bypass(added_text: str) -> List[str]:
    """
    Detects newly added compiler/linter suppressions.
    Returns list of matched bypass descriptions.
    Never blocks; only produces warning events.
    """
    if not added_text.strip():
        return []

    bypass_rules = [
        (r"@ts-ignore\b", "@ts-ignore"),
        (r"@ts-nocheck\b", "@ts-nocheck"),
        (r"eslint-disable(?:-next-line)?\b", "eslint-disable"),
        (r"#\s*noqa(?::\s*[\w\d,\s]+)?\b", "# noqa"),
        (r"#\s*type:\s*ignore\b", "# type: ignore"),
    ]

    detected = []
    for pattern, name in bypass_rules:
        if re.search(pattern, added_text):
            detected.append(name)

    return detected


# --- G4: IMPORT MATRIX (BLOCK) ---
def check_g4_import_matrix(target_file: str, added_text: str) -> Tuple[bool, str]:
    """
    Enforces architectural layer boundaries defined in .gravityguard.json.
    Supports Python relative imports and TypeScript side-effect/dynamic imports.
    Uses exact path segment matching to prevent false positives.
    """
    if not added_text.strip():
        return False, ""

    cfg = load_gravityguard_config(target_file)
    if not cfg or "layers" not in cfg:
        return False, ""

    normalized_path = target_file.replace("\\", "/").lower()
    layers = cfg.get("layers", {})

    # 1. Python imports (static & dynamic)
    py_from_imports = re.findall(r"^\s*from\s+([\.\w]+)\s+import", added_text, re.MULTILINE)
    py_direct_imports = re.findall(r"^\s*import\s+([^\n#;]+)", added_text, re.MULTILINE)
    py_dynamic_imports = re.findall(r"\b(?:__import__|importlib\.import_module)\s*\(\s*[\"']([^\"']+)[\"']", added_text)

    # 2. TypeScript/JavaScript imports (static, dynamic, side-effects, backticks)
    ts_from_imports = re.findall(r"^\s*import\s+.*?from\s+[\"']([^\"']+)[\"']", added_text, re.MULTILINE)
    ts_side_effect_imports = re.findall(r"^\s*import\s+[\"']([^\"']+)[\"']", added_text, re.MULTILINE)
    ts_dynamic_imports = re.findall(r"\bimport\s*\(\s*[`\"']([^`\"']+)[\"'`]\s*\)", added_text)
    ts_require_imports = re.findall(r"\brequire\s*\(\s*[`\"']([^`\"']+)[\"'`]\s*\)", added_text)

    # 3. String concatenation evasion detection: e.g. require('../net' + 'work/client')
    concat_calls = re.findall(r"\b(?:require|import)\s*\(\s*([\"'`][^\"'`]+[\"'`](?:\s*\+\s*[\"'`][^\"'`]+[\"'`])+)\s*\)", added_text)
    ts_concatenated_imports = []
    for call_arg in concat_calls:
        parts = re.findall(r"[\"'`]([^\"'`]+)[\"'`]", call_arg)
        if parts:
            ts_concatenated_imports.append("".join(parts))

    imported_modules: Set[str] = set()
    for imp in py_from_imports + py_dynamic_imports:
        if imp:
            imported_modules.add(imp.lower())
    for imp_line in py_direct_imports:
        for part in imp_line.split(","):
            mod = part.strip().split()[0] if part.strip() else ""
            if mod:
                imported_modules.add(mod.lower())
    for imp in ts_from_imports + ts_side_effect_imports + ts_dynamic_imports + ts_require_imports + ts_concatenated_imports:
        if imp:
            imported_modules.add(imp.lower())

    if not imported_modules:
        return False, ""

    for layer_name, layer_cfg in layers.items():
        layer_marker = f"/{layer_name.lower()}/"
        if layer_marker in normalized_path or normalized_path.startswith(f"{layer_name.lower()}/"):
            forbidden_list = layer_cfg.get("forbiddenImports", [])
            for forbidden in forbidden_list:
                forbidden_clean = forbidden.lower().strip()
                forb_segs = [s.strip(".") for s in re.split(r"[\./\\]", forbidden_clean) if s.strip(".")]
                if not forb_segs:
                    continue

                for imported in imported_modules:
                    imp_segs = [s.strip(".") for s in re.split(r"[\./\\]", imported) if s.strip(".")]
                    if not imp_segs:
                        continue

                    f_len = len(forb_segs)
                    matched = False
                    for i in range(len(imp_segs) - f_len + 1):
                        if imp_segs[i:i + f_len] == forb_segs:
                            matched = True
                            break

                    if matched:
                        return True, (
                            f"Katman Mimari İhlali (ARCH01_LAYER_VIOLATION): '{layer_name}' katmanındaki "
                            f"bir dosya doğrudan '{forbidden}' katmanını import edemez! "
                            f"(Tespit edilen import: '{imported}'). Araya bir controller/servis katmanı koyun."
                        )

    return False, ""


# --- OE_SPIKE: OVER-ENGINEERING DETECTION (WARN ONLY) ---
def check_oe_spike(added_text: str, thresholds: Optional[Dict[str, int]] = None) -> Tuple[bool, str]:
    """
    Lightweight heuristic for premature abstraction spikes in small changes.
    Never blocks; only produces an informative warning.
    """
    if thresholds is None:
        thresholds = DEFAULT_COMPLEXITY_THRESHOLDS
    max_loc = thresholds["overEngineeringMaxLoc"]
    min_abstractions = thresholds["overEngineerAbstractions"]

    lines = [line.strip() for line in added_text.splitlines() if line.strip() and not line.strip().startswith(("#", "//", "/*"))]
    loc_count = len(lines)

    if 0 < loc_count <= max_loc:
        abstractions = re.findall(r"\b(?:class|interface|abstract\s+class)\s+([A-Za-z0-9_]+)", added_text)
        if len(abstractions) >= min_abstractions:
            return True, (
                f"Aşırı Soyutlama Uyarısı (OE_SPIKE): Küçük bir kod değişikliğinde ({loc_count} LOC) "
                f"{len(abstractions)} yeni soyutlama ({', '.join(abstractions)}) eklendi. "
                f"YAGNI kuralını gözetin; tekil kullanım için erken soyutlamadan kaçının."
            )

    return False, ""


def _has_declared_cohesion_marker(content: str) -> bool:
    """True when the file declares itself a deliberate monolith."""
    if re.search(
        r"(?://|/\*|#)\s*srp\s*:\s*(?:allow-monolith|cohesive-monolith|bypass|noqa)\b",
        content, re.IGNORECASE
    ):
        return True
    return bool(re.search(r"#\s*noqa\s*:\s*srp\b", content, re.IGNORECASE))


def record_and_check_cumulative_growth(
    target_file: str,
    added_clean_count: int,
    threshold: int = 200,
    window_seconds: int = 900
) -> Tuple[bool, int]:
    """
    Tracks cumulative LOC additions to existing files within an active session window (15 minutes).
    Thwarts the 'Micro-Chunking' evasion tactic where an agent adds 199 lines repeatedly.
    """
    if added_clean_count <= 0 or not target_file or not os.path.isabs(target_file):
        return False, 0

    log_dir = _resolve_log_dir()
    delta_file = os.path.join(log_dir, "gravityguard_session_deltas.json")
    now = time.time()

    data = {}
    try:
        if os.path.exists(delta_file):
            with open(delta_file, "r", encoding="utf-8") as f:
                data = json.load(f)
    except (json.JSONDecodeError, OSError):
        data = {}

    norm_target = os.path.normpath(target_file).lower()
    file_records = data.get(norm_target, [])
    valid_records = [r for r in file_records if isinstance(r, dict) and now - r.get("ts", 0) <= window_seconds]

    current_total = sum(r.get("added", 0) for r in valid_records) + added_clean_count
    valid_records.append({"ts": now, "added": added_clean_count})
    data[norm_target] = valid_records

    # Prune stale records (> 1 hour)
    pruned_data = {}
    for path, recs in data.items():
        recent = [r for r in recs if isinstance(r, dict) and now - r.get("ts", 0) <= 3600]
        if recent:
            pruned_data[path] = recent

    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(delta_file, "w", encoding="utf-8") as f:
            json.dump(pruned_data, f, indent=2)
    except OSError as e:
        sys.stderr.write(f"[GravityGuard Session Delta Error] {e}\n")

    if current_total >= threshold:
        return True, current_total
    return False, current_total


# --- ARCH_FILE_GROWTH: LARGE FILE & RAPID GROWTH DETECTION (WARN ONLY) ---
def check_arch_file_growth(
    target_file: str,
    old_full_content: str,
    projected_content: str,
    added_lines: List[str],
    is_test_file: bool = False,
    thresholds: Optional[Dict[str, int]] = None,
    cumulative_loc: int = 0
) -> Tuple[bool, str]:
    """
    Lightweight heuristic to prevent monolithic file accumulation.
    Never blocks; produces an informative warning to guide AI toward modularity.
    Exempts test files, minified/vendor or explicitly exempted cohesive modules.
    """
    if is_test_file:
        return False, ""

    if is_cohesive_module_by_filename(target_file):
        return False, ""

    if thresholds is None:
        thresholds = DEFAULT_COMPLEXITY_THRESHOLDS
    monolith_loc = thresholds["monolithLoc"]
    single_write_loc = thresholds["singleWriteLoc"]
    creep_base_loc = thresholds["creepBaseLoc"]
    creep_added_loc = thresholds["creepAddedLoc"]

    old_lines = [line for line in old_full_content.splitlines() if line.strip()]
    proj_lines = [line for line in projected_content.splitlines() if line.strip()]
    added_clean = [line for line in added_lines if line.strip() and not line.strip().startswith(("#", "//", "/*", "*"))]

    old_loc = len(old_lines)
    projected_loc = len(proj_lines)
    added_count = len(added_clean)

    reasons = []
    if old_loc < monolith_loc <= projected_loc:
        reasons.append(
            f"toplam satır sayısı {monolith_loc} sınırını aşıyor ({projected_loc} LOC)"
        )
    elif not old_full_content.strip():
        # A new module's size is the result of modularisation, not accumulation
        pass
    else:
        if old_loc >= creep_base_loc and added_count >= creep_added_loc:
            reasons.append(
                f"{creep_base_loc}+ satırlık mevcut dosyaya belirgin ekleme yapıldı "
                f"({old_loc} -> {projected_loc} LOC, +{added_count} LOC)"
            )
        elif added_count >= single_write_loc:
            reasons.append(
                f"tek seferde büyük kod bloğu eklendi (+{added_count} LOC)"
            )
        elif cumulative_loc >= single_write_loc:
            reasons.append(
                f"kümülatif oturum büyümesi eşiği aşıldı (son 15 dakikada peş peşe toplam +{cumulative_loc} LOC)"
            )

        if reasons and _has_declared_cohesion_marker(projected_content):
            reasons = []

    if reasons:
        reason_str = "; ".join(reasons)
        basename = os.path.basename(target_file) if target_file else "dosya"
        return True, (
            f"Modülerlik Uyarısı (ARCH_FILE_GROWTH): '{basename}' için {reason_str}. "
            f"Yeni sorumlulukları aynı büyük dosyada biriktirmek yerine ilgili sorumlulukları "
            f"bağımsız ve cohesive modüllere ayırmayı değerlendirin."
        )

    return False, ""


# --- EXISTING SRP VALIDATION ENGINE (Cohesive Module & AST) ---
def is_ts_cohesive_monolith(content: str) -> bool:
    if re.search(r"(?://|/\*)\s*srp:\s*(?:allow-monolith|cohesive-monolith|bypass|noqa)\b", content, re.IGNORECASE):
        return True

    tab_switches = len(re.findall(r"activeTab\s*===", content))
    scroll_ids = len(re.findall(r"scrollToSection\s*\(", content))
    card_groups = len(re.findall(r"glass-card", content))
    grid_blocks = len(re.findall(r"display:\s*'grid'", content))
    section_markers = len(re.findall(r"(?:/\*|<!--)\s*(?:SECTION|BLOCK|TAB|PART)\b", content, re.IGNORECASE))

    multi_section = tab_switches >= 2 or scroll_ids >= 3 or section_markers >= 2
    multi_card = card_groups >= 3 and grid_blocks >= 3

    return not (multi_section or multi_card)


def is_py_cohesive_monolith(content: str) -> bool:
    if re.search(r"#\s*(?:srp:\s*(?:allow-monolith|cohesive-monolith|bypass|noqa)|noqa:\s*srp)\b", content, re.IGNORECASE):
        return True
    return False


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


def is_cohesive_module_by_filename(file_path: str) -> bool:
    if not file_path:
        return False
    base_name = os.path.basename(file_path.replace("\\", "/")).lower()
    return any(base_name == pat or base_name.endswith(pat) for pat in COHESIVE_MODULE_PATTERNS)


def _get_base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_exempt_class_ast(cls_node: ast.ClassDef, file_path: str) -> bool:
    EXEMPT_BASE_NAMES = {
        "Exception", "BaseException", "Error",
        "Panel", "Operator", "PropertyGroup", "Menu", "Header", "UIList",
        "BaseModel", "Schema",
        "Enum", "IntEnum", "StrEnum",
        "Protocol", "ABC",
    }
    for base in cls_node.bases:
        base_name = _get_base_name(base)
        if base_name in EXEMPT_BASE_NAMES or base_name.endswith("Error") or base_name.endswith("Exception"):
            return True

    for dec in cls_node.decorator_list:
        dec_name = _get_base_name(dec)
        if dec_name in {"dataclass", "pydantic_dataclass"}:
            return True

    file_lower = file_path.lower().replace("\\", "/")
    if ("bpy" in file_lower or "blender" in file_lower or "addon" in file_lower) and cls_node.name.startswith(("OBJECT_OT_", "MESH_OT_", "VIEW3D_PT_", "WM_OT_")):
        return True

    return False


def analyze_python_srp(content: str, file_path: str = "") -> Tuple[bool, str]:
    if is_py_cohesive_monolith(content) or is_cohesive_module_by_filename(file_path):
        return False, "Exempt cohesive module"

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return analyze_python_srp_regex_fallback(content, file_path)
    except Exception:
        # Fall back to regex path to keep guard alive
        try:
            return analyze_python_srp_regex_fallback(content, file_path)
        except Exception:
            raise

    has_ui_imports = False
    has_net_imports = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name.lower()
                if any(pkg in name for pkg in ["tkinter", "pyqt", "pyside", "wx", "kivy"]):
                    has_ui_imports = True
                if any(pkg in name for pkg in ["urllib", "requests", "http.client", "aiohttp", "httpx", "websockets", "socket"]):
                    has_net_imports = True
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").lower()
            if any(pkg in mod for pkg in ["tkinter", "pyqt", "pyside", "wx", "kivy"]):
                has_ui_imports = True
            if any(pkg in mod for pkg in ["urllib", "requests", "http", "aiohttp", "httpx", "websockets", "socket"]):
                has_net_imports = True

    if has_ui_imports and has_net_imports:
        return True, "Sorumluluk Çakışması: Dosya hem UI (Arayüz) hem de Network (Ağ/HTTP) kütüphanelerini aynı anda barındırıyor!"

    top_level_classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    major_classes = [c for c in top_level_classes if not _is_exempt_class_ast(c, file_path)]

    if len(major_classes) >= 4:
        names = [c.name for c in major_classes]
        return True, (
            f"Çoklu Sorumluluk İhlali (God Module): Dosya {len(major_classes)} bağımsız ana iş sınıfı "
            f"({', '.join(names[:3])}...) barındırıyor! Sınıfları ayrı dosyalara taşıyın."
        )

    return False, "SRP Compliant"


def analyze_python_srp_regex_fallback(content: str, file_path: str = "") -> Tuple[bool, str]:
    lines = content.splitlines()
    line_count = len(lines)

    has_ui = bool(re.search(r"\b(import\s+tkinter|import\s+PyQt|from\s+bpy\.types\s+import\s+.*Panel)", content, re.IGNORECASE))
    has_net = bool(re.search(r"\b(import\s+requests|import\s+urllib|import\s+aiohttp|import\s+websockets)", content, re.IGNORECASE))

    if has_ui and has_net:
        return True, "Sorumluluk Çakışması: Dosya hem UI hem de Network kütüphanelerini aynı anda barındırıyor!"

    class_matches = re.findall(r"^class\s+([A-Za-z0-9_]+)(?:\(([^)]*)\))?:", content, re.MULTILINE)
    major_classes = [name for name, bases in class_matches if not any(k in bases for k in ["Exception", "Error", "Panel", "Operator", "Enum", "ABC"])]

    if len(major_classes) >= 5:
        return True, (
            f"Çoklu Sınıf İhlali (God Module): Dosya {len(major_classes)} bağımsız ana sınıf "
            f"({', '.join(major_classes[:4])}...) barındırıyor!"
        )

    return False, f"SRP Compliant (Fallback check: {line_count} lines)"
