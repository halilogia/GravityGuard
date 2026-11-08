#!/usr/bin/env python3
"""
GravityGuard Engine — Architectural Rules & Modularity Subsystem.
Implements:
- G3: Compiler & Linter Bypass Warnings (WARN)
- G4: Layer Boundaries & Import Matrix (BLOCK)
- ARCH_FILE_GROWTH: +singleWriteLoc LOC in one write or within 15 minutes of an existing file (WARN)
- SRP: Single Responsibility Principle & God Module Analysis (BLOCK)
- ARCH_PMA_*: Pragmatic Modular Architecture boundary detector (BLOCK)
Zero external dependencies.
"""
import json
import os
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


# --- DESIGN_ICON_RULE: STANDARD EMOJI / ICON USAGE (ADVISORY WARNING) ---
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

def evaluate_g7_ts_first(target_file: str, projected_content: str = "") -> Tuple[bool, str]:
    """
    Advisory G7 check: is a JavaScript file (.js, .jsx, .cjs, .mjs) application code that could be TypeScript?
    Returns (flagged, one_line_warning). Configs, build output, workers and test runners are exempt. A file is never denied.
    """
    norm = target_file.replace("\\", "/").lower()
    norm_rel = re.sub(r"^.*?/\.gemini/antigravity/scratch/[^/]+", "", norm)
    parts = [p for p in norm_rel.split("/") if p]
    if not parts:
        return False, ""
    name = parts[-1]

    if not name.endswith((".js", ".jsx", ".cjs", ".mjs")):
        return False, ""

    # Deterministic exemptions: build output, vendor, docs, test runners, migrations; configs, rc files, bundles, workers.
    if any(part in _MANDATORY_JS_DIRS for part in parts[:-1]):
        return False, ""
    if name in _MANDATORY_JS_EXACT_NAMES or name.startswith("workbox-") or name.endswith(_MANDATORY_JS_SUFFIXES):
        return False, ""

    ext = name.rsplit(".", 1)[-1]
    stem = name.rsplit(".", 1)[0]
    suggested_ext = ".tsx" if ext == "jsx" else ".ts"
    return True, f"G7 TypeScript-First Uyarısı: '{name}' saf JavaScript; yeni uygulama kodu için '{stem}{suggested_ext}' tercih edilir."


def check_g7_ts_first(target_file: str, projected_content: str = "") -> Optional[str]:
    """Wrapper around evaluate_g7_ts_first returning the warning text or None."""
    is_flagged, msg = evaluate_g7_ts_first(target_file, projected_content)
    return msg if is_flagged else None


# --- Scrollbar, responsive-viewport and raw-control design rules live in design_rules.py; re-exported ---
from .design_rules import (  # noqa: E402,F401
    ResponsiveHTMLParser, check_design_scrollbar_rule, find_design_raw_controls_violations,
    find_design_responsive_violations, is_valid_viewport_directive,
)


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


# --- PMA boundary rules live in pma_rules.py; re-exported for existing importers ---
from .pma_rules import (  # noqa: E402,F401
    PMA_HORIZONTAL_DIRS, PMA_HORIZONTAL_MESSAGE, _PMA_ALIAS_PREFIXES, _PMA_COMPOSITION_ROOTS, _PMA_EXEMPT_DIRS, _PMA_LAYERS,
    _is_public_api, _pma_destination, _pma_import_specifiers, _pma_norm, _pma_resolve, _pma_target_layer,
    check_pma_horizontal, check_pma_imports, is_pma_exempt,
)


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
    single_write_loc = thresholds["singleWriteLoc"]
    added_count = len([line for line in added_lines if line.strip() and not line.strip().startswith(("#", "//", "/*", "*"))])
    grown = max(added_count, cumulative_loc)  # new files are G5_NEW_FILE_BLOAT_DENY's business
    if not old_full_content.strip() or grown < single_write_loc or _has_declared_cohesion_marker(projected_content):
        return False, ""

    basename = os.path.basename(target_file) if target_file else "dosya"
    return True, f"Modülerlik Uyarısı: '{basename}' dosyasına kısa sürede +{grown} LOC eklendi (sınır {single_write_loc})."


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
