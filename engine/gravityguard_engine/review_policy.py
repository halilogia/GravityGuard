#!/usr/bin/env python3
"""
GravityGuard Engine — Review Policy Subsystem.

Decides *whether* a code change must be reviewed by an independent specialist
before the session may stop. Review is opt-in per project and path-based, so a
two-line comment tweak is not dragged through a reviewer while a real change to
governed source is.

This module owns the decision only. Recording the obligation and verifying the
resulting receipt live in ``review_governance``; the two are deliberately split
so the trigger can be tested without touching state.
"""
import fnmatch
import re
import time
import uuid
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

#: File suffixes that are never production code, so never review-triggering on
#: their own. A `.json` config can change behaviour, but review of config is a
#: different policy question; excluding it here avoids the reviewer firing on
#: every lockfile or fixture.
_CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".gd", ".cs", ".go", ".rs", ".java")

#: Default exemptions, applied when the project does not set its own list.
DEFAULT_REVIEW_EXEMPT_PATTERNS = (
    "tests/**",
    "test/**",
    "**/tests/**",
    "**/test/**",
    "**/*_test.py",
    "**/test_*.py",
    "**/*.test.ts",
    "**/*.test.tsx",
    "**/*.spec.ts",
)

#: Security & governance sensitive patterns where review is mandatory regardless of scale.
SECURITY_SENSITIVE_PATTERNS = (
    "engine/**",
    "**/engine/**",
    "plugin/**",
    "**/plugin/**",
    ".gravityguard/**",
    "**/.gravityguard/**",
    "*security*",
    "**/*security*",
    "*auth*",
    "**/*auth*",
    "*secret*",
    "**/*secret*",
    "*token*",
    "**/*token*",
    "*permission*",
    "**/*permission*",
    "*hook*",
    "**/*hook*",
)

#: Dependency manifests that trigger review on modification.
DEPENDENCY_MANIFEST_PATTERNS = (
    "package.json",
    "package-lock.json",
    "requirements.txt",
    "pyproject.toml",
    "Cargo.toml",
    "Cargo.lock",
    "go.mod",
    "go.sum",
    "Gemfile",
    "Gemfile.lock",
)

DEFAULT_MIN_FILES = 5
DEFAULT_MIN_LINES = 120


def _relative_posix(target_file: str, project_root: Optional[Path]) -> str:
    """Project-relative, forward-slash path for glob matching (best effort)."""
    norm = target_file.replace("\\", "/")
    if project_root is not None:
        try:
            root = str(project_root.resolve()).replace("\\", "/").rstrip("/")
            low = norm.lower()
            if low.startswith(root.lower() + "/"):
                return norm[len(root) + 1:]
        except OSError as err:
            # A root that cannot be resolved only costs us a nicer relative
            # path; the absolute path still matches the same globs.
            _resolve_err = err
    return norm


def _matches_any(rel_path: str, patterns: List[str]) -> bool:
    low = rel_path.lower()
    for pattern in patterns:
        if not isinstance(pattern, str) or not pattern:
            continue
        if fnmatch.fnmatch(low, pattern.lower()):
            return True
        # A pattern without a leading directory should also match at any depth.
        if "/" not in pattern and fnmatch.fnmatch(low.split("/")[-1], pattern.lower()):
            return True
    return False


def is_review_enabled(cfg: Optional[dict]) -> bool:
    """Review governance is opt-in, mirroring ``governance.enforceDocObligations``."""
    if isinstance(cfg, dict) and isinstance(cfg.get("review"), dict):
        return bool(cfg["review"].get("enabled", False))
    return False


def should_require_review(
    target_file: str,
    cfg: Optional[dict] = None,
    project_root: Optional[Path] = None,
) -> bool:
    """True when writing ``target_file`` must be followed by an independent review.

    Rules, in order:
    1. Review must be enabled in ``.gravityguard.json`` (``review.enabled``).
    2. A test file never triggers review.
    3. Only production code suffixes trigger review.
    4. Any ``review.exemptPatterns`` glob (project-relative) suppresses review.
    """
    if not target_file or not is_review_enabled(cfg):
        return False

    file_lower = target_file.replace("\\", "/").lower()
    if not file_lower.endswith(_CODE_SUFFIXES):
        return False

    rel = _relative_posix(target_file, project_root)
    rel_lower = rel.lower()

    # Test files (child of a tests/ dir, or a test_*/ *_test.* name).
    parts = rel_lower.split("/")
    if any(part in ("tests", "test", "__tests__") for part in parts[:-1]):
        return False
    name = parts[-1] if parts else rel_lower
    if name.startswith("test_") or name.endswith(("_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")):
        return False

    review_cfg = cfg.get("review", {}) if isinstance(cfg, dict) else {}
    exempt = review_cfg.get("exemptPatterns")
    if not isinstance(exempt, list):
        exempt = list(DEFAULT_REVIEW_EXEMPT_PATTERNS)
    if _matches_any(rel, exempt):
        return False

    return True


def is_review_exempt_file(target_file: str, cfg: Optional[dict] = None, project_root: Optional[Path] = None) -> bool:
    """Inverse helper used by the final diff guard to skip non-code paths."""
    if not target_file:
        return True
    file_lower = target_file.replace("\\", "/").lower()
    if not file_lower.endswith(_CODE_SUFFIXES):
        return True
    return not should_require_review(target_file, cfg, project_root)


def default_review_id(prefix: str = "rev") -> str:
    """A fresh, filesystem-safe review id (no dependency on the caller)."""
    return f"{prefix}-{int(time.time())}-{uuid.uuid4().hex[:8]}"


def check_review_risk_triggers(
    changed_files: Iterable[str],
    cfg: Optional[dict] = None,
    project_root: Optional[Path] = None,
    total_lines_changed: int = 0,
) -> Tuple[bool, str]:
    """Evaluates whether a candidate change set crosses risk thresholds for Self-Review.

    Under ChatGPT's R1.1 Risk-Gated model:
    - Routine / small changes (<5 files, <120 lines, non-security) return False (SKIP).
    - Changes touching security/engine, dependencies, or large volume return True.
    """
    if not is_review_enabled(cfg):
        return False, "disabled"

    review_cfg = cfg.get("review", {}) if isinstance(cfg, dict) else {}

    # Strict / Force-All override (e.g. testing or explicit strict mode)
    if review_cfg.get("forceAll", False) or review_cfg.get("mode") == "strict":
        return True, "force-all"

    # If risk-gated mode is explicitly disabled, require on all changes
    if review_cfg.get("riskGated") is False:
        return True, "all-changes"

    files_list = list(changed_files)
    if not files_list:
        return False, "no-files"

    root = project_root

    # 1. Security & Governance sensitive paths (regardless of line count)
    for f in files_list:
        rel = _relative_posix(f, root)
        if _matches_any(rel, list(SECURITY_SENSITIVE_PATTERNS)):
            return True, f"Güvenlik/yönetişim modülü değişti: {rel}"

    # 2. Dependency / package manifests
    for f in files_list:
        rel = _relative_posix(f, root)
        if _matches_any(rel, list(DEPENDENCY_MANIFEST_PATTERNS)):
            return True, f"Dış bağımlılık / paket manifestosu değişti: {rel}"

    # 3. Scale threshold (number of files)
    min_files = review_cfg.get("minFiles", DEFAULT_MIN_FILES)
    if len(files_list) >= min_files:
        return True, f"Büyük değişiklik: {len(files_list)} dosya etkilendi (eşik: {min_files})"

    # 4. Scale threshold (number of lines)
    min_lines = review_cfg.get("minLines", DEFAULT_MIN_LINES)
    if total_lines_changed >= min_lines:
        return True, f"Büyük değişiklik: ~{total_lines_changed} satır (eşik: {min_lines})"

    # 5. Low risk -> Skip review
    return False, "Düşük riskli yerel değişiklik (Review atlandı)"



# ---------------------------------------------------------------------------
# Zero-context review: risk classification (pure, no I/O)
# ---------------------------------------------------------------------------
RISK_LOW = "LOW_RISK"
RISK_MEDIUM = "MEDIUM_RISK"
RISK_HIGH = "HIGH_RISK"
RISK_ORDER = {RISK_LOW: 0, RISK_MEDIUM: 1, RISK_HIGH: 2}

DEFAULT_MAX_FIX_TURNS = 2
DEFAULT_HIGH_LINES = 150
DEFAULT_MEDIUM_LINES = 30

_DOC_SUFFIXES = (".md", ".mdx", ".txt", ".rst")
_LOCKFILE_NAMES = (
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "cargo.lock",
    "poetry.lock", "go.sum", "gemfile.lock", "composer.lock",
)
_PUBLIC_API_PATTERNS = (
    "api/**", "**/api/**", "openapi*", "**/openapi*",
    "*.proto", "**/*.proto", "*.d.ts", "**/*.d.ts", "index.ts", "**/index.ts",
)
_COMMENT_PREFIXES = ("#", "//", "/*", "*", "*/", "--", "<!--")
_NEW_FUNCTION_RE = re.compile(
    r"^\s*(?:(?:async\s+)?def|function|class|fn|func)\s+\w+"
    r"|^\s*export\s+(?:default\s+)?(?:async\s+)?(?:function|class)\s+\w+"
    r"|^\s*(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?\([^)]*\)\s*=>"
)


def is_test_path(rel_path: str) -> bool:
    parts = rel_path.replace("\\", "/").lower().split("/")
    name = parts[-1]
    return (
        any(part in ("tests", "test", "__tests__") for part in parts[:-1])
        or name.startswith("test_")
        or name.endswith(("_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"))
    )


def is_comment_line(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith(_COMMENT_PREFIXES)


def is_review_governance_enabled(cfg: Optional[dict]) -> bool:
    """Zero-context review gate is opt-in: ``reviewGovernance.enabled`` in .gravityguard.json."""
    section = cfg.get("reviewGovernance") if isinstance(cfg, dict) else None
    return isinstance(section, dict) and bool(section.get("enabled", False))


def get_review_governance_config(cfg: Optional[dict]) -> dict:
    """Normalized ``reviewGovernance`` settings with safe defaults."""
    section = cfg.get("reviewGovernance") if isinstance(cfg, dict) else None
    section = section if isinstance(section, dict) else {}

    def _int(key: str, default: int, minimum: int = 0) -> int:
        value = section.get(key, default)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= minimum else default

    min_risk = section.get("minRisk", RISK_HIGH)
    if min_risk not in RISK_ORDER:
        min_risk = RISK_HIGH
    return {
        "enabled": bool(section.get("enabled", False)),
        "minRisk": min_risk,
        "maxFixTurns": _int("maxFixTurns", DEFAULT_MAX_FIX_TURNS),
        "highLines": _int("highLines", DEFAULT_HIGH_LINES, 1),
        "mediumLines": _int("mediumLines", DEFAULT_MEDIUM_LINES, 1),
        "stagedOnly": bool(section.get("stagedOnly", False)),
        # False (default): no reviewer result yet never locks the user out (status local_passed_ai_unavailable).
        # True: orchestrated mode (e.g. AgentObservatory) - Stop stays blocked until a reviewer result arrives.
        "requireReviewer": bool(section.get("requireReviewer", False)),
    }


def classify_file_risk(
    rel_path: str,
    added_lines: List[str],
    removed_lines: List[str],
    deleted: bool = False,
    high_lines: int = DEFAULT_HIGH_LINES,
    medium_lines: int = DEFAULT_MEDIUM_LINES,
) -> Tuple[str, str]:
    """Risk level and reason for one changed file.

    HIGH: security/engine/public-API paths, deleted tests, or a large code change.
    MEDIUM: ordinary production change over ``medium_lines``, new functions, manifests.
    LOW: docs, lockfiles, comment/whitespace-only edits, small code edits.
    """
    rel = rel_path.replace("\\", "/")
    name = rel.lower().split("/")[-1]
    is_test = is_test_path(rel)

    if name in _LOCKFILE_NAMES:
        return RISK_LOW, "kilit dosyası"
    if name.endswith(_DOC_SUFFIXES) and name not in DEPENDENCY_MANIFEST_PATTERNS:
        return RISK_LOW, "dokümantasyon"
    if deleted and is_test:
        return RISK_HIGH, "test dosyası silindi"

    changed = len(added_lines) + len(removed_lines)
    if not any(not is_comment_line(line) for line in (*added_lines, *removed_lines)):
        return RISK_LOW, "yalnızca yorum/boşluk değişikliği"

    if not is_test:
        if _matches_any(rel, list(SECURITY_SENSITIVE_PATTERNS)):
            return RISK_HIGH, "güvenlik/motor çekirdeği yolu"
        if _matches_any(rel, list(_PUBLIC_API_PATTERNS)):
            return RISK_HIGH, "public API kontratı"
    if changed > high_lines and name.endswith(_CODE_SUFFIXES):
        return RISK_HIGH, f"{changed} satırlık kod değişimi (> {high_lines})"
    if changed > medium_lines:
        return RISK_MEDIUM, f"{changed} satır değişti (> {medium_lines})"
    if any(_NEW_FUNCTION_RE.match(line) for line in added_lines):
        return RISK_MEDIUM, "yeni fonksiyon/sınıf"
    if name in DEPENDENCY_MANIFEST_PATTERNS:
        return RISK_MEDIUM, "bağımlılık manifestosu"
    return RISK_LOW, "küçük değişiklik"


def risk_meets_threshold(risk: str, minimum: str) -> bool:
    return RISK_ORDER.get(risk, 0) >= RISK_ORDER.get(minimum, RISK_ORDER[RISK_HIGH])
