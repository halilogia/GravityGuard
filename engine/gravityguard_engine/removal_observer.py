"""Stop-time observation of deleted files, independent of how they were deleted.

Shell deletions (`rm`, `git rm`, an IDE) never pass through the PreToolUse hook, so they leave no audit trail. Git sees
them all: this module reads the deletions from the worktree at Stop, reports each one once, and judges deleted tests by
their subject. A test whose subject (same-named source, or a module it imports) was deleted too is a legitimate feature
removal; a test deleted while its subject remains is test sabotage and is flagged.
"""
import fnmatch
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Set

from .test_evidence import _TEST_FILE_PATTERNS

STATE_FILE = Path(".gravityguard") / "runtime" / "removal_state.json"
_TEST_DIRS = {"tests", "test", "__tests__"}
_CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs")
_RESOLVE_SUFFIXES = ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", "/index.ts", "/index.tsx", "/index.js")
_JS_IMPORT = re.compile(r"""(?:from|import|require)\s*\(?\s*['"]((?:\.{1,2}/|@/)[^'"]+)['"]""")
_PY_IMPORT = re.compile(r"^\s*from\s+([\w.]+)\s+import\b", re.MULTILINE)


def _git(root: Path, *args: str) -> Optional[bytes]:
    try:
        proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def deleted_paths(root: Path) -> List[str]:
    """Project-relative, forward-slash paths deleted in the worktree or the index (relative to HEAD)."""
    found: Set[str] = set()
    for args in (("ls-files", "--deleted", "-z"), ("diff", "--cached", "--name-only", "--diff-filter=D", "-z")):
        out = _git(root, *args)
        if out:
            found.update(p.decode("utf-8", "replace") for p in out.split(b"\0") if p)
    return sorted(found)


def is_test_path(path: str) -> bool:
    parts = [p.lower() for p in path.replace("\\", "/").split("/")]
    name = parts[-1]
    return any(fnmatch.fnmatch(name, pat) for pat in _TEST_FILE_PATTERNS) or bool(_TEST_DIRS & set(parts[:-1]))


def _norm_stem(path: str) -> str:
    return Path(path).stem.lower().replace("-", "_")


def _subject_stem(test_path: str) -> str:
    stem = _norm_stem(test_path)
    stem = re.sub(r"\.(test|spec)$", "", stem)
    return re.sub(r"^test_|_test$", "", stem)


def _imports_deleted_module(root: Path, test_path: str, deleted: Set[str], source_stems: Set[str]) -> bool:
    raw = _git(root, "show", f"HEAD:{test_path}")
    if raw is None:
        return False
    text = raw.decode("utf-8", "replace")
    base = Path(test_path).parent
    for spec in _JS_IMPORT.findall(text):
        target = (Path("src") / spec[2:]) if spec.startswith("@/") else (base / spec)
        norm = os.path.normpath(str(target)).replace("\\", "/")
        # TS ESM imports spell the output extension ("./x.js") while the source on disk is x.ts.
        bare = re.sub(r"\.(?:js|jsx|mjs)$", "", norm)
        if any(stem + suffix in deleted for stem in {norm, bare} for suffix in _RESOLVE_SUFFIXES):
            return True
    return any(m.split(".")[-1].lower().replace("-", "_") in source_stems for m in _PY_IMPORT.findall(text))


def suspicious_test_deletions(root: Path, tests: List[str], deleted: Set[str]) -> List[str]:
    """Deleted tests whose subject is still present: the feature stayed, only its safety net went."""
    source_stems = {_norm_stem(p) for p in deleted if not is_test_path(p) and p.lower().endswith(_CODE_SUFFIXES)}
    return [
        t for t in tests
        if _subject_stem(t) not in source_stems and not _imports_deleted_module(root, t, deleted, source_stems)
    ]


def _load_seen(root: Path) -> Set[str]:
    try:
        data = json.loads((root / STATE_FILE).read_text(encoding="utf-8"))
        return {p for p in data.get("reported", []) if isinstance(p, str)}
    except (OSError, ValueError, AttributeError):
        return set()


def _save_seen(root: Path, paths: Set[str]) -> None:
    target = root / STATE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps({"reported": sorted(paths)}), encoding="utf-8")
    os.replace(tmp, target)


def observe_removals(root: Path) -> Dict[str, List[str]]:
    """Deletions not reported before, split into `deleted` (all new) and `suspicious_tests` (subject still present).

    The reported set is pruned to what is still deleted, so a restored or committed deletion is forgotten and a path
    deleted again later is reported again. Raises OSError when the state cannot be written; the caller logs it.
    """
    current = deleted_paths(root)
    fresh = [p for p in current if p not in _load_seen(root)]
    _save_seen(root, set(current))
    tests = [p for p in fresh if is_test_path(p) and p.lower().endswith(_CODE_SUFFIXES)]
    return {"deleted": fresh, "suspicious_tests": suspicious_test_deletions(root, tests, set(current))}
