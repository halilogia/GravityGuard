"""PMA boundary rules: horizontal-layer ban and cross-layer import checks (split from architecture_rules.py)."""
import posixpath
import re
from typing import List, Optional, Set, Tuple


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
    ARCH_PMA_DEEP_IMPORT only (core/shared purity rules were removed).
    Returns (violated, rule_id, message). Composition roots (main/App/index) and tests are exempt.
    """
    if not added_text.strip() or is_pma_exempt(target_file, composition_root_exempt=True):
        return False, "", ""
    importer = _pma_norm(target_file)
    layer, feature = _pma_target_layer(importer)
    if layer != "features":
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
    return False, "", ""


