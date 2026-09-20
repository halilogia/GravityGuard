import sys
import json
import os
import re
import ast
import time
import difflib
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Tuple, List, Optional, Set, Dict, Any

# ============================================================================
# 1. LOGGING & AUDIT STREAM (srp_guardian_live.json)
# ============================================================================

def log_event(action: str, status: str, target_file: str, reason: str, rule_id: str = "SRP"):
    log_dir = os.path.expanduser(r"~/.gemini/logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "srp_guardian_live.json")
        
        current_data = {"activeGuard": "GravityGuard", "status": "ONLINE", "events": []}
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    current_data = json.load(f)
            except Exception:
                pass
                
        event = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "status": status,
            "ruleId": rule_id,
            "target": target_file,
            "reason": reason
        }
        
        events = current_data.get("events", [])
        events.insert(0, event)
        current_data["events"] = events[:50]  # keep last 50
        current_data["lastCheck"] = event["timestamp"]
        
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(current_data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ============================================================================
# 2. DIFF & CONTENT SIMULATION (No Git Command Required - Zero Dependencies)
# ============================================================================

def get_projected_and_old_content(target_file: str, tool_name: str, args: dict) -> Tuple[str, str]:
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


def get_diff_analysis(old_content: str, projected_content: str) -> Tuple[List[str], str, Set[int]]:
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


def extract_diff_and_projected(target_file: str, tool_name: str, args: dict) -> Tuple[str, str, str]:
    """Compatibility alias for old signature."""
    old_c, proj_c = get_projected_and_old_content(target_file, tool_name, args)
    added_lines, added_text, _ = get_diff_analysis(old_c, proj_c)
    return old_c, added_text, proj_c


# ============================================================================
# 3. HIGH-CONFIDENCE GUARDS (Phase 1.1 Hardened)
# ============================================================================

# --- G1: SILENT EXCEPTION (BLOCK) ---
def check_g1_silent_exception(
    added_lines: List[str],
    added_text: str,
    added_line_numbers: Set[int],
    projected_content: str,
    is_python: bool,
    is_ts: bool
) -> Tuple[bool, str]:
    """
    Detects newly introduced empty catch/except blocks.
    Strictly diff-safe: Only flags handlers created or modified in this change.
    Pre-existing handlers in unchanged lines are never flagged.
    Does NOT block recovery fallbacks like 'return None' or 'return []'.
    """
    if not added_text.strip():
        return False, ""

    if is_python:
        # 1. Regex check on newly added text lines
        py_empty_pattern = re.compile(
            r"except(?:\s+[^:]+)?:\s*(?:\r?\n\s*)+(?:pass|\.\.\.)(?!\w)",
            re.MULTILINE
        )
        if py_empty_pattern.search(added_text):
            return True, "Yeni eklenen boş exception handler tespit edildi ('except: pass' / 'except: ...'). Hatalar loglanmalı veya fırlatılmalıdır."

        # 2. AST inspection on projected content: verify line numbers intersect with added_line_numbers
        try:
            tree = ast.parse(projected_content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    is_empty = False
                    if len(node.body) == 1:
                        first = node.body[0]
                        if isinstance(first, ast.Pass):
                            is_empty = True
                        elif (
                            isinstance(first, ast.Expr) and
                            isinstance(first.value, ast.Constant) and
                            first.value.value is Ellipsis
                        ):
                            is_empty = True
                    if is_empty:
                        start_line = node.lineno
                        end_line = getattr(node, "end_lineno", node.lineno)
                        handler_lines = set(range(start_line, end_line + 1))
                        # Trigger only if this handler is part of newly added/modified lines
                        if handler_lines.intersection(added_line_numbers):
                            return True, "Yeni eklenen boş exception handler (AST: except pass/ellipsis). Sessizce yutulan hatalar yasaktır."
        except (SyntaxError, ValueError):
            tree = None

    if is_ts:
        # Regex for TypeScript/JavaScript empty catch blocks:
        # catch { } OR catch (e) { } OR catch (err) { \n }
        ts_empty_pattern = re.compile(
            r"catch\s*(?:\([^)]*\))?\s*\{\s*\}",
            re.MULTILINE
        )
        if ts_empty_pattern.search(added_text):
            return True, "Yeni eklenen boş catch bloğu tespit edildi ('catch {}'). Hatalar sessizce yutulamaz."

    return False, ""


# --- G2: TEST INTEGRITY (BLOCK / WARN) ---
def check_g2_test_integrity(
    added_text: str,
    old_full_content: str,
    projected_content: str,
    is_test_file: bool
) -> Tuple[bool, str, Optional[str]]:
    """
    Guards test suite integrity:
    G2-A: Newly added .skip, pytest.mark.skip, xit, xdescribe -> BLOCK
          .only -> WARN (not high confidence sabotage)
          pytest.mark.xfail -> ALLOW (valid intentional test annotation)
    G2-C: Outright deletion of an existing test case -> BLOCK
    Returns: (is_blocked, block_reason, warn_reason_or_None)
    """
    if not is_test_file:
        return False, "", None

    warn_reason: Optional[str] = None

    # G2-A: Newly added disabling mechanisms (BLOCK)
    # Notice: pytest.mark.xfail is completely removed from BLOCK.
    disablers = [
        (r"\.skip\s*\(", ".skip()"),
        (r"\bxit\s*\(", "xit()"),
        (r"\bxdescribe\s*\(", "xdescribe()"),
        (r"@pytest\.mark\.skip\b", "@pytest.mark.skip"),
        (r"@unittest\.skip\b", "@unittest.skip"),
    ]

    for pattern, name in disablers:
        if re.search(pattern, added_text):
            return True, f"Test devre dışı bırakma hilesi tespit edildi ({name}). Testleri susturmak yerine hatayı düzeltin.", None

    # .only is treated as warning rather than block
    if re.search(r"\.only\s*\(", added_text):
        warn_reason = "Test dosyasında '.only()' kullanımı tespit edildi (Tüm diğer testleri göz ardı eder). Geçici debug sonrası kaldırmayı unutmayın."

    # G2-C: Test case deletion verification across full file
    if old_full_content.strip():
        py_tests_old = re.findall(r"^\s*def\s+(test_\w+)\s*\(", old_full_content, re.MULTILINE)
        js_tests_old = re.findall(r"^\s*(?:it|test)(?:\.\w+)*\s*\(\s*[\"']([^\"']+)[\"']", old_full_content, re.MULTILINE)
        old_counts = Counter(py_tests_old + js_tests_old)

        if old_counts:
            py_tests_proj = re.findall(r"^\s*def\s+(test_\w+)\s*\(", projected_content, re.MULTILINE)
            js_tests_proj = re.findall(r"^\s*(?:it|test)(?:\.\w+)*\s*\(\s*[\"']([^\"']+)[\"']", projected_content, re.MULTILINE)
            proj_counts = Counter(py_tests_proj + js_tests_proj)

            deleted = []
            for test_name, old_qty in old_counts.items():
                proj_qty = proj_counts.get(test_name, 0)
                if proj_qty < old_qty:
                    deleted.append(test_name)

            if deleted:
                sample_deleted = deleted[:2]
                return True, f"Mevcut test senaryosu silindi: {', '.join(sample_deleted)}. Var olan testleri silmek yasaktır.", None

    return False, "", warn_reason


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
def load_gravityguard_config(target_file: str) -> Optional[dict]:
    """Traverse upward looking for .gravityguard.json config."""
    try:
        current_dir = Path(target_file).parent if os.path.isfile(target_file) else Path(target_file)
    except (ValueError, OSError):
        current_dir = Path(os.getcwd())

    for _ in range(6):  # up to 6 levels up
        cfg_file = current_dir / ".gravityguard.json"
        if cfg_file.is_file():
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return None
        if current_dir.parent == current_dir:
            break
        current_dir = current_dir.parent

    # Check cwd as fallback
    cwd_cfg = Path(os.getcwd()) / ".gravityguard.json"
    if cwd_cfg.is_file():
        try:
            with open(cwd_cfg, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    return None


def check_g4_import_matrix(target_file: str, added_text: str) -> Tuple[bool, str]:
    """
    Enforces architectural layer boundaries defined in .gravityguard.json.
    Supports Python relative imports (e.g. from .network import ..., from ..network.client import ...)
    and TypeScript side-effect imports (import '../network').
    Uses exact path segment matching to prevent false positives (e.g. 'networking' vs 'network').
    """
    if not added_text.strip():
        return False, ""

    cfg = load_gravityguard_config(target_file)
    if not cfg or "layers" not in cfg:
        return False, ""

    normalized_path = target_file.replace("\\", "/").lower()
    layers = cfg.get("layers", {})

    # 1. Python imports
    py_from_imports = re.findall(r"^\s*from\s+([\.\w]+)\s+import", added_text, re.MULTILINE)
    py_direct_imports = re.findall(r"^\s*import\s+([^\n#;]+)", added_text, re.MULTILINE)

    # 2. TypeScript/JavaScript imports
    ts_from_imports = re.findall(r"^\s*import\s+.*?from\s+[\"']([^\"']+)[\"']", added_text, re.MULTILINE)
    ts_side_effect_imports = re.findall(r"^\s*import\s+[\"']([^\"']+)[\"']", added_text, re.MULTILINE)
    ts_require_imports = re.findall(r"\brequire\s*\(\s*[\"']([^\"']+)[\"']\s*\)", added_text, re.MULTILINE)

    imported_modules: Set[str] = set()
    for imp in py_from_imports:
        if imp:
            imported_modules.add(imp.lower())
    for imp_line in py_direct_imports:
        for part in imp_line.split(","):
            mod = part.strip().split()[0] if part.strip() else ""
            if mod:
                imported_modules.add(mod.lower())
    for imp in ts_from_imports + ts_side_effect_imports + ts_require_imports:
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

                    # Exact path segment or contiguous subsequence match
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
def check_oe_spike(added_text: str) -> Tuple[bool, str]:
    """
    Lightweight heuristic for premature abstraction spikes in small changes.
    Never blocks; only produces an informative warning.
    Criteria: small change (< 50 LOC) introducing 2+ new abstractions (classes/interfaces).
    """
    lines = [line.strip() for line in added_text.splitlines() if line.strip() and not line.strip().startswith(("#", "//", "/*"))]
    loc_count = len(lines)

    if 0 < loc_count <= 50:
        abstractions = re.findall(r"\b(?:class|interface|abstract\s+class)\s+([A-Za-z0-9_]+)", added_text)
        if len(abstractions) >= 2:
            return True, (
                f"Aşırı Soyutlama Uyarısı (OE_SPIKE): Küçük bir kod değişikliğinde ({loc_count} LOC) "
                f"{len(abstractions)} yeni soyutlama ({', '.join(abstractions)}) eklendi. "
                f"YAGNI kuralını gözetin; tekil kullanım için erken soyutlamadan kaçının."
            )

    return False, ""


# ============================================================================
# 4. EXISTING SRP VALIDATION ENGINE (Cohesive Module & AST)
# ============================================================================

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


# ============================================================================
# 5. MAIN DISPATCHER & RULE ORCHESTRATOR
# ============================================================================

def validate_gravityguard():
    start_time = time.perf_counter()

    raw_input = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not raw_input.strip():
        print(json.dumps({"decision": "allow"}))
        sys.exit(0)
        
    try:
        payload = json.loads(raw_input)
    except Exception:
        print(json.dumps({"decision": "allow"}))
        sys.exit(0)

    tool_call = payload.get("toolCall", {})
    args = tool_call.get("args", {})
    target_file = args.get("TargetFile") or args.get("target_file") or args.get("file_path") or ""
    tool_name = tool_call.get("name", "edit")
    
    # 1. Normalize path
    normalized_path = target_file.replace("\\\\", "/").replace("\\", "/")
    file_lower = normalized_path.lower()

    # 2. Path classification
    is_test_file = any(m in file_lower for m in ["/tests/", "/test/", "/__tests__/", "test_", "_test.", ".spec.", ".test."])
    is_vendor_or_cache = any(m in file_lower for m in [
        "/node_modules/", "/venv/", "/.venv/", "/env/", "/.env/", "/dist/", "/build/",
        "/.git/", "/__pycache__/", "/runs/", "/scratch/", "/brain/", "/.gemini/"
    ])
    is_data_or_doc = file_lower.endswith((
        ".json", ".css", ".scss", ".md", ".txt", ".yaml", ".yml", ".toml", ".ini",
        ".lock", ".svg", ".png", ".jpg", ".blend", ".gitignore"
    ))

    # Fast-pass for vendor, cache, and non-code assets
    if is_vendor_or_cache or (is_data_or_doc and not file_lower.endswith((".py", ".ts", ".tsx", ".js", ".jsx"))):
        if target_file:
            log_event(tool_name, "APPROVED", target_file, "Exempt file (Vendor/Cache/Asset)", rule_id="EXEMPT")
        print(json.dumps({"decision": "allow"}))
        sys.exit(0)

    # 3. Extract projected and old content, compute exact diff
    old_full_content, projected_content = get_projected_and_old_content(target_file, tool_name, args)
    added_lines, added_text, added_line_numbers = get_diff_analysis(old_full_content, projected_content)

    is_python = file_lower.endswith(".py")
    is_ts = file_lower.endswith((".ts", ".tsx", ".js", ".jsx"))

    # ========================================================================
    # GUARD 1: G1 — SILENT EXCEPTION (BLOCK)
    # ========================================================================
    if not is_test_file:
        g1_violated, g1_reason = check_g1_silent_exception(
            added_lines, added_text, added_line_numbers, projected_content, is_python, is_ts
        )
        if g1_violated:
            log_event(tool_name, "BLOCKED", target_file, g1_reason, rule_id="G1_SILENT_EXCEPTION")
            print(json.dumps({
                "decision": "deny",
                "reason": f"🛑 [G1_SILENT_EXCEPTION]: '{target_file}' - {g1_reason}"
            }))
            sys.exit(0)

    # ========================================================================
    # GUARD 2: G2 — TEST INTEGRITY (BLOCK / WARN)
    # ========================================================================
    if is_test_file:
        g2_violated, g2_reason, g2_warn = check_g2_test_integrity(
            added_text, old_full_content, projected_content, is_test_file
        )
        if g2_warn:
            log_event(tool_name, "WARNING", target_file, g2_warn, rule_id="G2_TEST_INTEGRITY")
        if g2_violated:
            log_event(tool_name, "BLOCKED", target_file, g2_reason, rule_id="G2_TEST_INTEGRITY")
            print(json.dumps({
                "decision": "deny",
                "reason": f"🛑 [G2_TEST_INTEGRITY]: '{target_file}' - {g2_reason}"
            }))
            sys.exit(0)

    # ========================================================================
    # GUARD 3: G3 — COMPILER & LINTER BYPASS (WARN ONLY)
    # ========================================================================
    g3_matches = check_g3_compiler_bypass(added_text)
    if g3_matches:
        warn_msg = f"Yeni linter/derleyici susturması eklendi ({', '.join(g3_matches)}). Hatanın kök nedenini çözmeyi değerlendirin."
        log_event(tool_name, "WARNING", target_file, warn_msg, rule_id="G3_COMPILER_BYPASS")

    # ========================================================================
    # GUARD 4: G4 — IMPORT MATRIX (BLOCK)
    # ========================================================================
    g4_violated, g4_reason = check_g4_import_matrix(target_file, added_text)
    if g4_violated:
        log_event(tool_name, "BLOCKED", target_file, g4_reason, rule_id="G4_IMPORT_MATRIX")
        print(json.dumps({
            "decision": "deny",
            "reason": f"🛑 [G4_IMPORT_MATRIX]: '{target_file}' - {g4_reason}"
        }))
        sys.exit(0)

    # ========================================================================
    # GUARD 5: OE_SPIKE — OVER-ENGINEERING (WARN ONLY)
    # ========================================================================
    oe_triggered, oe_msg = check_oe_spike(added_text)
    if oe_triggered:
        log_event(tool_name, "WARNING", target_file, oe_msg, rule_id="OE_SPIKE")

    # ========================================================================
    # GUARD 6: EXISTING SRP (Single Responsibility Principle)
    # ========================================================================
    if not is_test_file:
        if is_python:
            is_violation, reason = analyze_python_srp(projected_content, file_path=target_file)
            if is_violation:
                log_event(tool_name, "BLOCKED", target_file, reason, rule_id="SRP_BOUNDARY")
                print(json.dumps({
                    "decision": "deny",
                    "reason": f"🛑 [SRP_BOUNDARY]: '{target_file}' - {reason}"
                }))
                sys.exit(0)

        elif is_ts:
            tab_matches = len(re.findall(r"activeTab\s*===", projected_content))
            card_matches = len(re.findall(r"glass-card", projected_content))
            grid_blocks = len(re.findall(r"display:\s*'grid'", projected_content))
            scroll_ids = len(re.findall(r"scrollToSection\s*\(", projected_content))
            multi_job = (tab_matches >= 2 and card_matches >= 3) or (scroll_ids >= 3 and grid_blocks >= 3)
            
            if multi_job and not is_ts_cohesive_monolith(projected_content):
                reason_msg = f"SRP İhlali: Dosya {tab_matches} sekme, {card_matches} kart ve {grid_blocks} grid bloğu içeriyor."
                log_event(tool_name, "BLOCKED", target_file, reason_msg, rule_id="SRP_BOUNDARY")
                print(json.dumps({
                    "decision": "deny",
                    "reason": f"🛑 [SRP_BOUNDARY]: '{target_file}' - {reason_msg}"
                }))
                sys.exit(0)

    # ========================================================================
    # PASS / APPROVED
    # ========================================================================
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    log_event(tool_name, "APPROVED", target_file, f"All Guards Passed ({elapsed_ms:.1f}ms)", rule_id="PASS")
    print(json.dumps({"decision": "allow"}))
    sys.exit(0)


if __name__ == "__main__":
    validate_gravityguard()
