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
- ARCH_PMA_*: Pragmatic Modular Architecture boundary detector (BLOCK)
Zero external dependencies.
"""
from html.parser import HTMLParser
import json
import os
import posixpath
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .audit import _resolve_log_dir
from .project_context import DEFAULT_COMPLEXITY_THRESHOLDS, load_gravityguard_config
# Python SRP analysis lives in srp_python.py; re-exported so existing imports (dispatcher, gravity-validator) keep working.
from . import srp_python
COHESIVE_MODULE_PATTERNS = srp_python.COHESIVE_MODULE_PATTERNS
analyze_python_srp = srp_python.analyze_python_srp
analyze_python_srp_regex_fallback = srp_python.analyze_python_srp_regex_fallback
is_cohesive_module_by_filename = srp_python.is_cohesive_module_by_filename
is_py_cohesive_monolith = srp_python.is_py_cohesive_monolith
_get_base_name = srp_python._get_base_name
_is_exempt_class_ast = srp_python._is_exempt_class_ast


# --- DESIGN_ICON_RULE: STANDARD EMOJI / ICON USAGE (STRICT DENY) ---
def find_design_icon_violations(
    target_file: str,
    projected_content: str,
    added_line_numbers: Optional[Set[int]] = None
) -> List[Dict[str, Any]]:
    """
    Find emoji/icon violations in the target file.
    If added_line_numbers is provided, only inspect newly added/modified lines in projected_content.
    Otherwise, inspect all lines in projected_content.
    Returns list of dicts: {'line': int, 'icons': List[str], 'snippet': str}
    """
    norm = target_file.replace("\\", "/").lower()
    parts = norm.split("/")
    name = parts[-1]
    if not name.endswith((".ts", ".tsx", ".js", ".jsx", ".html", ".vue", ".svelte", ".css", ".py", ".gd", ".gdshader")):
        return []
    from .icon_exemptions import is_emoji_pattern_line, is_icon_exempt_path
    if is_icon_exempt_path(parts): return []
    if any(marker in name for marker in ("test_", "_test.", ".test.", "spec.")):
        return []

    icon_regex = re.compile(r"[\U00010000-\U0010ffff\u2600-\u27bf\u231a\u231b\u23e9-\u23f3\u23f8-\u23fa][\ufe0e\ufe0f]?")
    violations: List[Dict[str, Any]] = []
    lines = projected_content.splitlines()
    for idx, line in enumerate(lines, 1):
        if added_line_numbers is not None and idx not in added_line_numbers:
            continue
        found = [] if is_emoji_pattern_line(line) else icon_regex.findall(line)
        if found:
            distinct_icons = list(dict.fromkeys(found))
            snippet = line.strip()
            if len(snippet) > 80:
                snippet = snippet[:77] + "..."
            violations.append({
                "line": idx,
                "icons": distinct_icons,
                "snippet": snippet
            })
    return violations


def check_design_icon_rule(target_file: str, added_text: str) -> List[str]:
    """Return distinct added icons in source files, preserving encounter order."""
    norm = target_file.replace("\\", "/").lower()
    parts = norm.split("/")
    name = parts[-1]
    if not name.endswith((".ts", ".tsx", ".js", ".jsx", ".html", ".vue", ".svelte", ".css", ".py", ".gd", ".gdshader")):
        return []
    if any(part in {"doc", "docs", "documentation", "test", "tests", "__tests__"} for part in parts[:-1]):
        return []
    if any(marker in name for marker in ("test_", "_test.", ".test.", "spec.")):
        return []

    # Include hourglasses outside the main symbol ranges and optional presentation selectors.
    icons = re.findall(r"[\U00010000-\U0010ffff\u2600-\u27bf\u231a\u231b\u23e9-\u23f3\u23f8-\u23fa][\ufe0e\ufe0f]?", added_text)
    return list(dict.fromkeys(icons))


# --- G7: TYPESCRIPT FIRST ENFORCEMENT & MANDATORY JS DETECTOR (BLOCK + FEEDBACK) ---
_MANDATORY_JS_DIRS: Set[str] = {
    "dist", "build", "out", ".next", ".nuxt", ".svelte-kit", ".output",
    "node_modules", "vendor", "coverage", "bundle", "bundles",
    "doc", "docs", "documentation", "test", "tests", "__tests__",
    "migrations", "seeders",
}

_MANDATORY_JS_SUFFIXES: Tuple[str, ...] = (
    ".min.js", ".bundle.js", ".chunk.js", ".umd.js", ".esm.js", ".cjs.js",
    ".config.js", ".config.cjs", ".config.mjs",
    ".conf.js", ".conf.cjs", ".conf.mjs",
    ".eslintrc.js", ".eslintrc.cjs", ".prettierrc.js", ".prettierrc.cjs", ".babelrc.js", ".babelrc.cjs", ".stylelintrc.js", ".stylelintrc.cjs",
    ".test.js", ".test.cjs", ".test.mjs",
    ".spec.js", ".spec.cjs", ".spec.mjs",
    ".worker.js", ".sw.js",
)

_MANDATORY_JS_EXACT_NAMES: Set[str] = {
    "gulpfile.js", "gulpfile.mjs", "gulpfile.cjs",
    "gruntfile.js", "gruntfile.cjs",
    "jakefile.js", "brocfile.js",
    "sw.js", "service-worker.js", "firebase-messaging-sw.js",
}

_TS_MANDATORY_FEEDBACK_RE = re.compile(
    r"(?://|/\*)\s*@(?:ts-mandatory|gravityguard-js-reason)\s*:\s*([^\n\r\*]+)",
    re.IGNORECASE,
)

_TRIVIAL_FEEDBACK_REASONS: Set[str] = {
    "test", "bypass", "none", "zorunlu", "gerekiyor", "js", "javascript", "ok", "allow",
}


def extract_js_mandatory_feedback(content: str) -> Optional[str]:
    """
    Extracts a validated AI mandatory-JS justification from the first 10 lines of a file.
    Syntax: // @ts-mandatory: <at least 15 chars of concrete technical reason>
    """
    if not content:
        return None
    head = "\n".join(content.splitlines()[:10])
    m = _TS_MANDATORY_FEEDBACK_RE.search(head)
    if not m:
        return None
    reason = m.group(1).strip()
    if len(reason) < 15 or reason.lower() in _TRIVIAL_FEEDBACK_REASONS:
        return None
    return reason


def record_js_mandatory_feedback(
    target_file: str,
    reason: str,
    conversation_id: str = "default",
) -> None:
    """Persists AI feedback for mandatory JS exemptions so GravityGuard can audit and learn new patterns."""
    from datetime import datetime, timezone
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "file": target_file.replace("\\", "/"),
        "reason": reason,
        "conversationId": conversation_id,
    }
    try:
        log_dir = _resolve_log_dir()
        os.makedirs(log_dir, exist_ok=True)
        feedback_path = os.path.join(log_dir, "gravityguard_js_feedback.jsonl")
        with open(feedback_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        sys.stderr.write(f"[GravityGuard JS Feedback Log Warning] {exc}\n")


def evaluate_g7_ts_first(
    target_file: str,
    projected_content: str = "",
) -> Tuple[bool, str, Optional[str]]:
    """
    Evaluates whether a JavaScript file (.js, .jsx, .cjs, .mjs) violates the G7 TypeScript-First standard.
    Returns (is_blocked, deny_message, feedback_reason).
    - Deterministic mandatory JS files (configs, dotfiles, build outputs, workers, test runners, migrations) -> allowed.
    - Explicit technical justification via `// @ts-mandatory: <reason>` in first 10 lines -> allowed + feedback logged.
    - All other raw JS application/module files -> BLOCKED (DENY).
    """
    norm = target_file.replace("\\", "/").lower()
    norm_rel = re.sub(r"^.*?/\.gemini/antigravity/scratch/[^/]+", "", norm)
    parts = [p for p in norm_rel.split("/") if p]
    if not parts:
        return False, "", None
    name = parts[-1]

    if not name.endswith((".js", ".jsx", ".cjs", ".mjs")):
        return False, "", None

    # 1. Deterministic directory exemptions (build output, vendor, docs, test runners, migrations)
    if any(part in _MANDATORY_JS_DIRS for part in parts[:-1]):
        return False, "", None

    # 2. Deterministic filename & suffix exemptions (configs, rc files, minified/bundled, workers, tests)
    if name in _MANDATORY_JS_EXACT_NAMES or name.startswith("workbox-") or name.endswith(_MANDATORY_JS_SUFFIXES):
        return False, "", None

    # 3. Check for AI Mandatory-JS Feedback Header in the first 10 lines
    feedback = extract_js_mandatory_feedback(projected_content)
    if feedback:
        return False, "", feedback

    ext = name.rsplit(".", 1)[-1]
    stem = name.rsplit(".", 1)[0]
    suggested_ext = ".tsx" if ext == "jsx" else ".ts"
    return (
        True,
        (
            f"G7 TypeScript-First İhlali: '{name}' dosyası saf JavaScript (.{ext}) olarak yazılamaz! "
            f"Ekosistem standardı gereği uygulama ve modül kodları tip güvenli TypeScript ('{stem}{suggested_ext}') olarak yazılmalıdır. "
            f"EĞER bu dosyanın teknik bir zorunluluk nedeniyle kesinlikle .{ext} kalması gerekiyorsa, "
            f"dosyanın ilk 5 satırı içine şu geri bildirim bildirimini ekleyerek GravityGuard'a bildirin: "
            f"// @ts-mandatory: <en az 15 karakterlik somut teknik gerekçe>"
        ),
        None,
    )


def check_g7_ts_first(target_file: str, projected_content: str = "") -> Optional[str]:
    """Backwards-compatible wrapper around evaluate_g7_ts_first returning Optional[str]."""
    is_blocked, msg, _ = evaluate_g7_ts_first(target_file, projected_content)
    return msg if is_blocked else None


# --- DESIGN_SCROLLBAR_RULE: DEFAULT WEBKIT / BROWSER SCROLLBAR BAN (WARN ONLY) ---
def check_design_scrollbar_rule(target_file: str, added_text: str) -> List[str]:
    """
    Checks that web files (html, css, vue, svelte, tsx) with scrolling containers do not rely
    on default browser scrollbars. Requires sleek custom scrollbar definitions (scrollbar-width,
    ::-webkit-scrollbar, ::-webkit-scrollbar-button { display: none }).
    """
    norm = target_file.replace("\\", "/").lower()
    parts = norm.split("/")
    name = parts[-1]
    if not name.endswith((".html", ".css", ".vue", ".svelte", ".tsx", ".jsx")):
        return []
    if any(part in {"doc", "docs", "documentation", "test", "tests", "__tests__"} for part in parts[:-1]):
        return []
    if any(marker in name for marker in ("test_", "_test.", ".test.", "spec.")):
        return []

    violations = []
    if re.search(r"\boverflow(?:-[xy])?\s*:\s*(?:scroll|auto)\b", added_text, re.IGNORECASE):
        if not re.search(r"::-webkit-scrollbar|scrollbar-width", added_text, re.IGNORECASE):
            violations.append("varsayılan tarayıcı kaydırma çubuğu (custom scrollbar eksik)")
    return violations


# --- DESIGN_RESPONSIVE_RULE: MOBILE / PHONE VIEWPORT & FLUID LAYOUT (STRICT DENY & WARN) ---
class ResponsiveHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.has_head = False
        self.head_line = 1
        self.has_html = False
        self.has_doctype = False
        self.viewports: List[Tuple[int, str]] = []

    def handle_decl(self, decl: str) -> None:
        if "doctype html" in decl.lower():
            self.has_doctype = True

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attrs_dict = {k.lower(): (v or "") for k, v in attrs if k}
        line, _ = self.getpos()

        t_lower = tag.lower()
        if t_lower == "html":
            self.has_html = True
        elif t_lower == "head":
            self.has_head = True
            self.head_line = line
        elif t_lower == "meta":
            if attrs_dict.get("name", "").strip().lower() == "viewport":
                content = attrs_dict.get("content", "").strip().lower()
                self.viewports.append((line, content))


def is_valid_viewport_directive(content: str) -> bool:
    """Verifies that the viewport meta content specifies width=device-width and initial-scale=1."""
    clean = content.replace(" ", "")
    if "width=device-width" not in clean:
        return False
    scale_match = re.search(r"initial-scale\s*=\s*([0-9.]+)", content)
    if not scale_match:
        return False
    try:
        val = float(scale_match.group(1))
        return val == 1.0
    except ValueError:
        return False


def find_design_responsive_violations(
    target_file: str,
    projected_content: str,
    added_line_numbers: Optional[Set[int]] = None
) -> List[Dict[str, Any]]:
    """
    Evaluates Mobile / Phone Responsive Design requirements:
    1. Full HTML documents must include a valid <meta name="viewport" content="width=device-width, initial-scale=1.0"> in <head> (STRICT DENY).
    2. Large fixed pixel widths (>=1000px) in CSS declarations without fluid constraints (WARN).
    """
    norm = target_file.replace("\\", "/").lower()
    parts = norm.split("/")
    name = parts[-1]

    if any(part in {"doc", "docs", "documentation", "test", "tests", "__tests__", "node_modules", ".git"} for part in parts[:-1]):
        return []
    if any(marker in name for marker in ("test_", "_test.", ".test.", "spec.")):
        return []

    violations: List[Dict[str, Any]] = []
    lines = projected_content.splitlines()

    # 1. Full HTML Viewport Meta Check (DENY if missing in full document)
    if name.endswith((".html", ".htm")):
        parser = ResponsiveHTMLParser()
        try:
            parser.feed(projected_content)
            parser.close()
        except Exception:
            return violations

        if parser.has_doctype or parser.has_head or parser.has_html:
            valid_found = False
            for line_no, content in parser.viewports:
                if is_valid_viewport_directive(content):
                    valid_found = True
                    break

            if not valid_found:
                snippet = lines[parser.head_line - 1].strip() if 0 < parser.head_line <= len(lines) else "<head>"
                violations.append({
                    "rule": "INVALID_VIEWPORT",
                    "severity": "DENY",
                    "line": parser.head_line,
                    "snippet": snippet,
                    "message": "Mobil viewport sözleşmesi ihlali: <head> içinde '<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">' etiketi zorunludur! Bu etiket olmadan mobil tarayıcılar masaüstü 980px zoom simülasyonuna düşer.",
                    "suggestion": '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
                })

    # 2. Large Fixed Width Overflow Risk Check (WARN)
    if name.endswith((".css", ".html", ".htm", ".vue", ".svelte")):
        fixed_width_pattern = re.compile(
            r"\b(width|min-width|inline-size|min-inline-size)\s*:\s*([1-9][0-9]{3,})px\b",
            re.IGNORECASE
        )
        for idx, line in enumerate(lines, 1):
            if added_line_numbers is not None and idx not in added_line_numbers:
                continue
            trimmed = line.strip()
            if trimmed.startswith("/*") or trimmed.startswith("//") or trimmed.startswith("*"):
                continue

            m = fixed_width_pattern.search(line)
            if m:
                prop = m.group(1)
                val = int(m.group(2))
                if val >= 1000:
                    snippet = trimmed
                    if len(snippet) > 80:
                        snippet = snippet[:77] + "..."
                    violations.append({
                        "rule": "LARGE_FIXED_WIDTH",
                        "severity": "WARN",
                        "line": idx,
                        "snippet": snippet,
                        "message": f"Mobilde yatay taşma riski: '{prop}: {val}px' büyük sabit piksel genişliği tespit edildi.",
                        "suggestion": "Sabit piksel yerine 'max-width: 100%', 'min()', 'clamp()' veya fluid flex/grid düzeni kullanın."
                    })

    return violations


# --- DESIGN_RAW_CONTROLS_RULE: RAW BROWSER CONTROLS BAN (STRICT LINE-TARGETED DENY) ---
def find_design_raw_controls_violations(
    target_file: str,
    projected_content: str,
    added_line_numbers: Optional[Set[int]] = None
) -> List[Dict[str, Any]]:
    """
    Enforces styled controls over unstyled raw browser elements:
    - Raw unstyled <input type="file"> (must use custom class/label wrapper or ::file-selector-button).
    - Raw unstyled scrollbars (overflow: scroll/auto without custom scrollbar CSS).
    - Raw unstyled <input type="number"> (must hide native stepper arrows via appearance: textfield).
    Returns list of violation dicts with exact line number and snippet.
    """
    norm = target_file.replace("\\", "/").lower()
    parts = norm.split("/")
    name = parts[-1]

    if not name.endswith((".html", ".htm", ".css", ".vue", ".svelte", ".tsx", ".jsx")):
        return []
    if any(part in {"doc", "docs", "documentation", "test", "tests", "__tests__", "node_modules", ".git"} for part in parts[:-1]):
        return []
    if any(marker in name for marker in ("test_", "_test.", ".test.", "spec.")):
        return []

    violations: List[Dict[str, Any]] = []
    lines = projected_content.splitlines()

    # 1. Raw file input check in HTML/templates
    if name.endswith((".html", ".htm", ".vue", ".svelte", ".tsx", ".jsx")):
        raw_file_pattern = re.compile(r'<input\s+[^>]*type=["\']file["\']', re.IGNORECASE)
        styled_pattern = re.compile(r'(class=["\'][^"\']*(?:custom-file|hidden|sr-only|file-input)[^"\']*["\']|style=["\'][^"\']*display\s*:\s*none)', re.IGNORECASE)
        for idx, line in enumerate(lines, 1):
            if added_line_numbers is not None and idx not in added_line_numbers:
                continue
            if raw_file_pattern.search(line):
                if not styled_pattern.search(line) and "file-selector-button" not in projected_content:
                    snippet = line.strip()
                    if len(snippet) > 80:
                        snippet = snippet[:77] + "..."
                    violations.append({
                        "line": idx,
                        "type": "RAW_FILE_INPUT",
                        "snippet": snippet,
                        "message": "Ham varsayılan dosya seçme butonu tespit edildi (<input type=\"file\">). Zero-Bloat standardı gereği gizlenip özel butonla tetiklenmeli veya '::file-selector-button' ile minimalist olarak stillendirilmelidir."
                    })

    # 2. Raw number spinner check in HTML/templates
    if name.endswith((".html", ".htm", ".vue", ".svelte", ".tsx", ".jsx")):
        raw_num_pattern = re.compile(r'<input\s+[^>]*type=["\']number["\']', re.IGNORECASE)
        styled_num = re.compile(r'class=["\'][^"\']*(?:no-spin|custom-number|stepper)[^"\']*["\']', re.IGNORECASE)
        has_spinner_css = bool(re.search(r'::-webkit-inner-spin-button\s*\{[^}]*display\s*:\s*none', projected_content, re.IGNORECASE))
        if not has_spinner_css:
            for idx, line in enumerate(lines, 1):
                if added_line_numbers is not None and idx not in added_line_numbers:
                    continue
                if raw_num_pattern.search(line) and not styled_num.search(line):
                    snippet = line.strip()
                    if len(snippet) > 80:
                        snippet = snippet[:77] + "..."
                    violations.append({
                        "line": idx,
                        "type": "RAW_NUMBER_SPINNER",
                        "snippet": snippet,
                        "message": "Ham tarayıcı sayı arttırma oku (number spinner) tespit edildi (<input type=\"number\">). '::-webkit-inner-spin-button { display: none }' ve 'appearance: textfield' ile gizlenmelidir."
                    })

    return violations


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
                            f"Katman Mimari İhlali: '{layer_name}' katmanındaki "
                            f"bir dosya doğrudan '{forbidden}' katmanını import edemez! "
                            f"(Tespit edilen import: '{imported}'). Araya bir controller/servis katmanı koyun."
                        )

    return False, ""


# --- PMA: PRAGMATIC MODULAR ARCHITECTURE BOUNDARY DETECTOR (BLOCK) ---
PMA_HORIZONTAL_DIRS: Tuple[str, ...] = ("controllers", "services", "repositories", "managers")
_PMA_LAYERS: Tuple[str, ...] = ("core", "shared", "features", "pipelines")
_PMA_EXEMPT_DIRS: Set[str] = {"tests", "test", "__tests__", "node_modules", "dist", "build", "vendor", ".venv", "venv", "site-packages"}
_PMA_COMPOSITION_ROOTS: Set[str] = {"main", "app", "index", "__init__", "__main__"}
_PMA_ALIAS_PREFIXES = re.compile(r"^(?:@/|~/|@(?=(?:core|shared|features|pipelines)/)|src/)+")

PMA_HORIZONTAL_MESSAGE = (
    "Hop hemşerim! Bu projede PMA (Pragmatic Modular Architecture) standardı geçerli. "
    "Yatay katmanlar (controllers, services, repositories) YASAKTIR. "
    "Kodunu dikey dilim olarak src/features/<ozellik>/ altına yazmalısın."
)


def _pma_norm(file_path: str) -> str:
    return (file_path or "").replace("\\", "/").lower()


def is_pma_exempt(file_path: str, composition_root_exempt: bool = False) -> bool:
    """Tests, vendor/build output and GravityGuard's own repository never trigger PMA gates."""
    norm = _pma_norm(file_path)
    if not norm:
        return True
    segments = [seg for seg in norm.split("/") if seg]
    dirs, base = segments[:-1], segments[-1]
    if "gravityguard" in dirs or any(d in _PMA_EXEMPT_DIRS for d in dirs):
        return True
    if re.search(r"\.(?:test|spec)\.[a-z0-9]+$", base) or re.match(r"test_.*\.py$|.*_test\.py$", base):
        return True
    if composition_root_exempt and base.split(".")[0] in _PMA_COMPOSITION_ROOTS:
        return True
    return False


def _pma_target_layer(norm_path: str) -> Tuple[str, str]:
    """('features', 'auth') / ('core', '') / ('', '') for a path living under src/<layer>/."""
    m = re.search(r"(?:^|/)src/(core|shared|features|pipelines)(?:/([^/]+))?", norm_path)
    if not m:
        return "", ""
    feature = (m.group(2) or "") if m.group(1) == "features" else ""
    return m.group(1), feature


def check_pma_horizontal(target_file: str) -> Tuple[bool, str]:
    """ARCH_PMA_HORIZONTAL_DENY: src/controllers|services|repositories|managers/ are forbidden (index files included)."""
    if is_pma_exempt(target_file):
        return False, ""
    m = re.search(r"(?:^|/)src/(" + "|".join(PMA_HORIZONTAL_DIRS) + r")/", _pma_norm(target_file))
    if m:
        return True, f"{PMA_HORIZONTAL_MESSAGE} (ARCH_PMA_HORIZONTAL_DENY: src/{m.group(1)}/)"
    return False, ""


def _pma_import_specifiers(added_text: str) -> List[Tuple[str, bool]]:
    """(specifier, is_python) for every static/dynamic import found in the added text."""
    specs: List[Tuple[str, bool]] = []
    ts_patterns = (
        r"^\s*(?:import|export)\s+[^;\n]*?\s+from\s+[\"']([^\"']+)[\"']",
        r"^\s*import\s+[\"']([^\"']+)[\"']",
        r"\bimport\s*\(\s*[`\"']([^`\"']+)[`\"']\s*\)",
        r"\brequire\s*\(\s*[`\"']([^`\"']+)[`\"']\s*\)",
    )
    for pat in ts_patterns:
        specs.extend((m, False) for m in re.findall(pat, added_text, re.MULTILINE))
    for m in re.findall(r"^\s*from\s+([\.\w]+)\s+import\b", added_text, re.MULTILINE):
        specs.append((m, True))
    for line in re.findall(r"^\s*import\s+([\w\.]+(?:\s*,\s*[\w\.]+)*)\s*(?:#.*)?$", added_text, re.MULTILINE):
        specs.extend((part.strip(), True) for part in line.split(",") if part.strip())
    return specs


def _pma_resolve(spec: str, is_python: bool, importer_norm: str) -> Optional[str]:
    """Canonical lowercase path of an import, or None when it is a third-party package."""
    spec = spec.strip().lower()
    if is_python:
        dots = len(spec) - len(spec.lstrip("."))
        body = spec[dots:].replace(".", "/")
        if dots:
            base = posixpath.dirname(importer_norm)
            for _ in range(dots - 1):
                base = posixpath.dirname(base)
            return posixpath.normpath(posixpath.join(base, body)) if body else base
        spec = body
    elif spec.startswith("."):
        return posixpath.normpath(posixpath.join(posixpath.dirname(importer_norm), spec))
    stripped = _PMA_ALIAS_PREFIXES.sub("", spec)
    if stripped.split("/")[0] in _PMA_LAYERS:
        return "src/" + stripped
    return None


def _pma_destination(resolved: str) -> Tuple[str, str, str]:
    """(layer, feature, rest) of a resolved import path; rest is what follows the layer/feature segment."""
    m = re.search(r"(?:^|/)src/(core|shared|features|pipelines)(?:/(.*))?$", resolved)
    if not m:
        return "", "", ""
    layer, tail = m.group(1), (m.group(2) or "")
    if layer == "features":
        feature, _, rest = tail.partition("/")
        return layer, feature, rest
    return layer, "", tail


def _is_public_api(rest: str) -> bool:
    return rest == "" or bool(re.fullmatch(r"(?:index|__init__)(?:\.[a-z0-9]+)?", rest))


def check_pma_imports(target_file: str, added_text: str) -> Tuple[bool, str, str]:
    """
    ARCH_PMA_DEEP_IMPORT / ARCH_PMA_CORE_PURITY / ARCH_PMA_SHARED_PURITY.
    Returns (violated, rule_id, message). Composition roots (main/App/index) and tests are exempt.
    """
    if not added_text.strip() or is_pma_exempt(target_file, composition_root_exempt=True):
        return False, "", ""
    importer = _pma_norm(target_file)
    layer, feature = _pma_target_layer(importer)
    if layer not in ("core", "shared", "features"):
        return False, "", ""

    for spec, is_py in _pma_import_specifiers(added_text):
        resolved = _pma_resolve(spec, is_py, importer)
        if resolved is None:
            continue
        dest_layer, dest_feature, rest = _pma_destination(resolved)
        if not dest_layer:
            continue
        if layer == "features":
            if dest_layer == "features" and dest_feature and dest_feature != feature and not _is_public_api(rest):
                return True, "ARCH_PMA_DEEP_IMPORT", (
                    f"PMA Derin Import İhlali: 'features/{feature}' dilimi, "
                    f"'features/{dest_feature}' diliminin iç dosyasını import ediyor ('{spec}'). "
                    f"Diğer dilimlere yalnızca public API (features/{dest_feature} veya features/{dest_feature}/index) üzerinden erişilir."
                )
        elif layer == "core":
            if dest_layer in ("features", "pipelines") or (dest_layer == "shared" and re.match(r"ui(?:/|$)", rest)):
                target_name = "shared/ui" if dest_layer == "shared" else dest_layer
                return True, "ARCH_PMA_CORE_PURITY", (
                    f"PMA Core Saflık İhlali: src/core/ altındaki dosya '{target_name}' "
                    f"import edemez ('{spec}'). Core 0 dış bağımlılıkla saf kalmalıdır."
                )
        elif dest_layer == "features":
            return True, "ARCH_PMA_SHARED_PURITY", (
                f"PMA Shared Saflık İhlali: src/shared/ altındaki dosya "
                f"'features/' import edemez ('{spec}'). Shared bileşenler özelliklerden bağımsız (agnostic) olmalıdır."
            )
    return False, "", ""


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
                f"Aşırı Soyutlama Uyarısı: Küçük bir kod değişikliğinde ({loc_count} LOC) "
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
        # New file creation: do not bypass if initial size exceeds monolith threshold
        if projected_loc >= monolith_loc:
            reasons.append(
                f"yeni oluşturulan dosya başlangıç monolit sınırını ({monolith_loc} LOC) aşıyor ({projected_loc} LOC)"
            )
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
            f"Modülerlik Uyarısı: '{basename}' için {reason_str}. "
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
