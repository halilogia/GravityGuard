"""
GravityGuard — documentation governance policy (docs/KNOWLEDGE.md §6): which files create a documentation obligation.

ONE definition, used by the Stop-time obligation tracker (`dispatcher`, via `project_context.is_doc_governed_target`) and
by the commit-time verifier (`tools/verify_doc_governance.py`). Two copies of this list drifted once (`scripts` was
governed at Stop but not at commit, `tools` the other way round); a policy that differs between the two gates is a
policy someone will find the gap in.

Standard library only: this module runs inside the pre-tool hook and inside the git pre-commit hook.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Iterable, List, Optional

# Top-level or nested directory names whose code files owe a CHANGELOG entry when changed. Projects add their own
# directories with `governance.docObligationPatterns` in `.gravityguard.json` (matched against the project-relative path).
DEFAULT_GOVERNED_DIRS = frozenset({"engine", "src", "plugin", "rules", "scripts", "tools"})

_TEST_DIR_NAMES = frozenset({"tests", "test", "__tests__"})
_SKIPPED_PATH_MARKERS = (
    "/.gravityguard/", "/logs/", "/scratch/", "/brain/", "/dist/", "/node_modules/", "/.git/", "/archives/",
)
_NON_CODE_SUFFIXES = (".md", ".txt", ".json", ".lock", ".svg", ".png", ".jpg", ".jpeg", ".ico")
# Behaviour-bearing non-code files: a changed hook table changes what the guard does.
_ALWAYS_GOVERNED_SUFFIXES = ("plugin/hooks.json",)


def _is_test_file(path: Path) -> bool:
    name = path.name.lower()
    parents = {part.lower() for part in path.parent.parts}
    return bool(
        parents & _TEST_DIR_NAMES
        or name.startswith("test_")
        or "_test." in name
        or name.endswith("_test.py")
        or ".test." in name
        or ".spec." in name
    )


def relative_posix(path_str: str, project_root: Optional[Path] = None) -> str:
    """Lower-cased forward-slash path relative to the project root; the path as given when it is outside the root or
    no root is known."""
    norm = str(path_str).replace("\\", "/")
    if project_root is not None:
        try:
            rel = Path(norm).resolve().relative_to(Path(project_root).resolve())
            return rel.as_posix().lower()
        except (ValueError, OSError):
            pass
    return norm.lower()


def _pattern_variants(pattern: str) -> List[str]:
    """`fnmatch`'s `*` already crosses `/`; what it lacks is an OPTIONAL `**/`, so `a/**/*.gd` must also match `a/x.gd`."""
    pat = pattern.replace("\\", "/").lower()
    if pat.startswith("./"):
        pat = pat[2:]
    variants = [pat]
    if "/**/" in pat:
        variants.append(pat.replace("/**/", "/"))
    if pat.startswith("**/"):
        variants.append(pat[3:])
    return variants


def matches_any_pattern(rel_path: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        if not isinstance(pattern, str) or not pattern.strip():
            continue
        if any(fnmatch.fnmatch(rel_path, variant) for variant in _pattern_variants(pattern.strip())):
            return True
    return False


def governed_dirs(governance: Optional[dict]) -> frozenset:
    """The default directories, unless the project replaces them with `governance.docGovernedDirs` (a list of directory
    names). A project whose `tools/` or `scripts/` hold throwaway helpers, or whose code lives in `core/` and `ui/`,
    names its own; a malformed value degrades to the defaults."""
    configured = governance.get("docGovernedDirs") if isinstance(governance, dict) else None
    if isinstance(configured, list) and all(isinstance(d, str) and d.strip() for d in configured):
        return frozenset(d.strip().lower() for d in configured)
    return DEFAULT_GOVERNED_DIRS


def is_doc_governed_path(path_str: str, cfg: Optional[dict] = None, project_root: Optional[Path] = None) -> bool:
    """Does changing this file create a documentation obligation?

    Tests, caches, runtime dirs and non-code files never do. Otherwise it does when a directory of the project-relative
    path is one of the governed directories (`DEFAULT_GOVERNED_DIRS`, or `governance.docGovernedDirs` when set), or the
    relative path matches a `governance.docObligationPatterns` glob (added on top of the directories).
    With a project root the directory check looks only inside the project (a checkout that happens to live under
    `/home/me/src/` must not govern everything); without one it falls back to the path as given.
    """
    rel = relative_posix(path_str, project_root)
    path = Path(rel)
    if _is_test_file(path):
        return False
    probe = "/" + rel.lstrip("/")
    if any(marker in probe for marker in _SKIPPED_PATH_MARKERS):
        return False
    if rel.endswith(_ALWAYS_GOVERNED_SUFFIXES):
        return True
    if rel.endswith(_NON_CODE_SUFFIXES):
        return False

    governance = cfg.get("governance") if isinstance(cfg, dict) else None
    if any(part in governed_dirs(governance) for part in path.parent.parts):
        return True

    if isinstance(governance, dict):
        patterns = governance.get("docObligationPatterns", [])
        if isinstance(patterns, list):
            if matches_any_pattern(rel, patterns):
                return True
            # Absolute patterns written for the old matcher (`*/core/*`) keep working.
            absolute = str(path_str).replace("\\", "/").lower()
            if absolute != rel and matches_any_pattern(absolute, patterns):
                return True
    return False
