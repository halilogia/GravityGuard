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
import ast
import json
import os
import posixpath
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .audit import _resolve_log_dir
from .project_context import DEFAULT_COMPLEXITY_THRESHOLDS, load_gravityguard_config


# --- DESIGN_ICON_RULE: STANDARD EMOJI / ICON USAGE (WARN ONLY) ---
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
    "rc.js", "rc.cjs", "rc.mjs",
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
                    f"PMA Derin Import İhlali (ARCH_PMA_DEEP_IMPORT): 'features/{feature}' dilimi, "
                    f"'features/{dest_feature}' diliminin iç dosyasını import ediyor ('{spec}'). "
                    f"Diğer dilimlere yalnızca public API (features/{dest_feature} veya features/{dest_feature}/index) üzerinden erişilir."
                )
        elif layer == "core":
            if dest_layer in ("features", "pipelines") or (dest_layer == "shared" and re.match(r"ui(?:/|$)", rest)):
                target_name = "shared/ui" if dest_layer == "shared" else dest_layer
                return True, "ARCH_PMA_CORE_PURITY", (
                    f"PMA Core Saflık İhlali (ARCH_PMA_CORE_PURITY): src/core/ altındaki dosya '{target_name}' "
                    f"import edemez ('{spec}'). Core 0 dış bağımlılıkla saf kalmalıdır."
                )
        elif dest_layer == "features":
            return True, "ARCH_PMA_SHARED_PURITY", (
                f"PMA Shared Saflık İhlali (ARCH_PMA_SHARED_PURITY): src/shared/ altındaki dosya "
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
        # New file creation: do not bypass if initial size exceeds monolith or single-write threshold
        if projected_loc >= monolith_loc:
            reasons.append(
                f"yeni oluşturulan dosya başlangıç monolit sınırını ({monolith_loc} LOC) aşıyor ({projected_loc} LOC)"
            )
        elif added_count >= single_write_loc:
            reasons.append(
                f"yeni dosyaya tek seferde büyük kod bloğu yazıldı (+{added_count} LOC)"
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
