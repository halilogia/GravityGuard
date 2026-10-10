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
import time
import uuid
from pathlib import Path
from typing import List, Optional

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
