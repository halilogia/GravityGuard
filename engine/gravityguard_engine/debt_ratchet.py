"""Technical Debt Ratchet & Warning Governance Module.
Implements the Clean-as-You-Code ratchet mechanism:
- Existing monolithic files (> threshold LOC) are locked as accepted legacy debt.
- Any positive line addition (regression > 0) to an already bloated file is strictly BLOCKED at Stop Hook / Pre-Commit.
- Any line reduction permanently lowers the baseline (ratchet clicks forward).
- A file's first-seen baseline is taken from git HEAD (not from its current, possibly already bloated, content),
  so new or freshly bloated files cannot be "grandfathered" by simply being evaluated late.
"""

from __future__ import annotations
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from typing import Dict, Any, Iterator, Tuple, List, Optional, Set

from .refactor_hint import build_refactor_hint

DEFAULT_RATCHET_THRESHOLD: int = 500
MAX_RATCHET_FILE_BYTES: int = 2_000_000
_LOCK_TIMEOUT_S: float = 2.0
_LOCK_STALE_S: float = 10.0

EXCLUDED_RATCHET_DIRS: Set[str] = {
    "node_modules", ".git", ".svn", "venv", ".venv", "env",
    "__pycache__", "dist", "build", "bin", "obj", ".next",
    "vendor", ".playwright-mcp", "cache", "temp", "tmp",
    ".idea", ".vscode", "coverage", ".gravityguard"
}

EXEMPT_SUFFIXES = (
    ".md", ".json", ".yaml", ".yml", ".toml", ".txt", ".csv", ".tsv", ".lock", ".map", ".min.js", ".min.css",
    ".svg", ".ico", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".wasm",
)

SCAN_SOURCE_SUFFIXES = (
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs", ".java", ".kt", ".cs", ".c", ".h",
    ".cpp", ".hpp", ".gd", ".rb", ".php", ".swift", ".lua", ".vue", ".svelte",
)


def _warn(message: str) -> None:
    sys.stderr.write(f"[GravityGuard DebtRatchet] {message}\n")


def is_test_or_exempt_file(file_path: str) -> bool:
    """Checks if a file is a test file or explicitly exempt from architectural ratchet.

    Pass a project-relative path: absolute paths would make a parent folder named ``test`` exempt everything.
    """
    normalized = file_path.replace("\\", "/").lower()
    basename = os.path.basename(normalized)
    parts = normalized.split("/")

    if normalized.startswith("../"):
        return True
    if any(part in EXCLUDED_RATCHET_DIRS for part in parts[:-1]):
        return True

    # Test directory or naming
    if "/tests/" in f"/{normalized}" or "/test/" in f"/{normalized}":
        return True
    if basename.startswith("test_") or basename.endswith(("_test.py", ".test.ts", ".spec.ts", ".test.js", ".spec.js")):
        return True

    # Translation tables are data: every new rule adds one line per language
    if any(part in {"i18n", "locales", "locale"} for part in parts[:-1]):
        return True

    # Documentation, data & binary assets
    return basename.endswith(EXEMPT_SUFFIXES)


def get_ratchet_store_path(project_root: str) -> str:
    """Returns the absolute path to .gravityguard/debt_ratchet.json."""
    return os.path.join(project_root, ".gravityguard", "debt_ratchet.json")


def _empty_store() -> Dict[str, Any]:
    return {"version": 1, "threshold": DEFAULT_RATCHET_THRESHOLD, "files": {}}


def load_debt_ratchet(project_root: str) -> Dict[str, Any]:
    """Loads the debt ratchet store safely. Returns a valid dict structure.

    A corrupt store is moved aside to ``debt_ratchet.json.corrupt`` instead of being silently overwritten,
    so a broken file cannot quietly re-grandfather every bloated file.
    """
    store_path = get_ratchet_store_path(project_root)
    if not os.path.isfile(store_path):
        return _empty_store()

    try:
        with open(store_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("files"), dict):
            data["files"] = {k: v for k, v in data["files"].items() if isinstance(v, dict)}
            return data
        err: Any = "unexpected structure"
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as read_err:
        err = read_err

    _warn(f"Corrupt store at {store_path}: {err}; moved to .corrupt")
    try:
        os.replace(store_path, store_path + ".corrupt")
    except OSError as move_err:
        _warn(f"Could not move corrupt store aside: {move_err}")
    return _empty_store()


def save_debt_ratchet(project_root: str, data: Dict[str, Any]) -> None:
    """Saves the debt ratchet store atomically (unique temp file + os.replace)."""
    store_path = get_ratchet_store_path(project_root)
    temp_path = ""
    try:
        os.makedirs(os.path.dirname(store_path), exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix="debt_ratchet.", suffix=".tmp", dir=os.path.dirname(store_path))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, store_path)
    except OSError as write_err:
        _warn(f"Failed to save store to {store_path}: {write_err}")
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError as cleanup_err:
                _warn(f"Temp cleanup error: {cleanup_err}")


@contextlib.contextmanager
def _store_lock(project_root: str) -> Iterator[None]:
    """Best-effort inter-process lock around the store's read-modify-write cycle.

    Never blocks the hook: after the timeout it proceeds unlocked (a stale lock is broken first).
    """
    lock_path = get_ratchet_store_path(project_root) + ".lock"
    held = False
    try:
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        deadline = time.monotonic() + _LOCK_TIMEOUT_S
        while not held:
            try:
                os.close(os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                held = True
            except FileExistsError:
                if _break_stale_lock(lock_path):
                    continue
                if time.monotonic() >= deadline:
                    _warn("Lock timeout; proceeding without lock")
                    break
                time.sleep(0.05)
    except OSError as lock_err:
        _warn(f"Lock unavailable: {lock_err}")
    try:
        yield
    finally:
        if held:
            try:
                os.remove(lock_path)
            except OSError as release_err:
                _warn(f"Lock release failed: {release_err}")


def _break_stale_lock(lock_path: str) -> bool:
    try:
        if time.time() - os.path.getmtime(lock_path) > _LOCK_STALE_S:
            os.remove(lock_path)
            return True
    except OSError as stale_err:
        _warn(f"Stale lock check failed: {stale_err}")
    return False


def to_project_rel_path(project_root: str, file_path: str) -> str:
    """Converts a file path to forward-slash normalized project-relative path."""
    try:
        rel = os.path.relpath(file_path, project_root)
        return rel.replace("\\", "/")
    except ValueError:
        return file_path.replace("\\", "/")


def count_clean_lines(content: str) -> int:
    """Counts non-empty lines in a string."""
    return sum(1 for line in content.splitlines() if line.strip())


def _measure_file(file_path: str) -> Optional[int]:
    """LOC of a file on disk, or None if missing, unreadable or too large to be hand-written source."""
    try:
        if not os.path.isfile(file_path) or os.path.getsize(file_path) > MAX_RATCHET_FILE_BYTES:
            return None
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return count_clean_lines(f.read())
    except OSError as read_err:
        _warn(f"Cannot read {file_path}: {read_err}")
        return None


def _head_loc(project_root: str, rel_path: str) -> Optional[int]:
    """LOC of the file at git HEAD: 0 if it is new, None if git/HEAD is unavailable."""
    try:
        head = subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=project_root,
                              capture_output=True, timeout=5)
        if head.returncode != 0:
            return None
        res = subprocess.run(["git", "show", f"HEAD:./{rel_path}"], cwd=project_root,
                             capture_output=True, timeout=5)
    except (subprocess.SubprocessError, OSError) as git_err:
        _warn(f"git HEAD lookup failed for {rel_path}: {git_err}")
        return None
    if res.returncode != 0:
        return 0
    return count_clean_lines(res.stdout.decode("utf-8", errors="ignore"))


def _entry_baseline(entry: Dict[str, Any], default: int) -> int:
    try:
        return int(entry.get("baseline_loc", default))
    except (TypeError, ValueError):
        return default


def _first_seen_baseline(project_root: str, rel_path: str, current_loc: int, threshold: int) -> int:
    """Baseline for a file the store has never seen: its HEAD size (floored at the threshold), else its current size."""
    head_loc = _head_loc(project_root, rel_path)
    if head_loc is None:
        return current_loc
    return min(current_loc, max(head_loc, threshold))


def _apply_ratchet(
    data: Dict[str, Any],
    project_root: str,
    rel_path: str,
    current_loc: int,
    threshold: int,
    record: bool,
) -> Tuple[bool, int, int, str, bool]:
    """Core rule engine on an already-loaded store. Returns (is_regression, baseline, delta, msg, dirty)."""
    files_map = data.setdefault("files", {})

    if current_loc <= threshold:
        dirty = record and rel_path in files_map
        if dirty:
            del files_map[rel_path]
        return False, current_loc, 0, "", dirty

    file_entry = files_map.get(rel_path)
    if not file_entry:
        baseline_loc = _first_seen_baseline(project_root, rel_path, current_loc, threshold)
        if record:
            files_map[rel_path] = {"baseline_loc": baseline_loc, "threshold": threshold, "status": "legacy_debt"}
    else:
        baseline_loc = _entry_baseline(file_entry, threshold)

    if current_loc > baseline_loc:
        delta = current_loc - baseline_loc
        msg = (
            f"Ratchet Regresyonu: '{rel_path}' dosyasının kabul edilen borç tavanı ({baseline_loc} LOC) aşıldı "
            f"({current_loc} LOC, +{delta} satır yeni borç). "
            f"Mevcut monolitik dosyaya yeni kod yığmak yerine ilgili mantığı yeni/ayrık bir modüle çıkarın."
        )
        return True, baseline_loc, delta, msg, record and not file_entry

    if current_loc < baseline_loc and file_entry:
        delta = current_loc - baseline_loc  # negative
        if record:
            file_entry["baseline_loc"] = current_loc
            file_entry["status"] = "improved"
        msg = f"Ratchet İyileşmesi: '{rel_path}' borcu düşürüldü ({baseline_loc} -> {current_loc} LOC, {delta} satır). Yeni tavan kilitlendi."
        return False, current_loc, delta, msg, record

    return False, baseline_loc, 0, "", record and not file_entry


def evaluate_file_ratchet(
    project_root: str,
    file_path: str,
    content: Optional[str] = None,
    threshold: int = DEFAULT_RATCHET_THRESHOLD,
    auto_record_baseline: bool = True
) -> Tuple[bool, int, int, str]:
    """
    Evaluates a file against the Debt Ratchet.
    Returns:
        (is_regression, baseline_loc, delta, message)

    Rules:
    - If current_loc <= threshold: Not in debt.
    - If current_loc > threshold:
      - If first time seen: baseline = LOC at git HEAD (floored at threshold; new files start at threshold);
        outside git, baseline = current_loc (legacy debt accepted).
      - If current_loc > baseline_loc: REGRESSION! (Blocked at Stop Hook & Pre-Commit).
      - If current_loc < baseline_loc: RATIO IMPROVEMENT! Baseline lowered (ratchet clicks forward).
    With auto_record_baseline=False the store is never written (use for speculative PreToolUse checks).
    """
    rel_path = to_project_rel_path(project_root, file_path)
    if is_test_or_exempt_file(rel_path):
        return False, 0, 0, ""

    current_loc = count_clean_lines(content) if content is not None else _measure_file(file_path)
    if current_loc is None:
        return False, 0, 0, ""

    lock = _store_lock(project_root) if auto_record_baseline else contextlib.nullcontext()
    with lock:
        data = load_debt_ratchet(project_root)
        is_reg, baseline, delta, msg, dirty = _apply_ratchet(
            data, project_root, rel_path, current_loc, threshold, auto_record_baseline)
        if dirty:
            save_debt_ratchet(project_root, data)
    return is_reg, baseline, delta, msg


def evaluate_changed_files_ratchet(
    project_root: str,
    changed_files: List[str],
    threshold: int = DEFAULT_RATCHET_THRESHOLD
) -> List[Tuple[str, int, int, str]]:
    """
    Evaluates a list of changed files for ratchet regressions with a single store load/save.
    Returns list of (rel_path, baseline_loc, delta, message) for files with regressions.
    """
    candidates = []
    for fp in dict.fromkeys(changed_files):
        full_path = fp if os.path.isabs(fp) else os.path.join(project_root, fp)
        rel = to_project_rel_path(project_root, full_path)
        if is_test_or_exempt_file(rel):
            continue
        loc = _measure_file(full_path)
        if loc is not None:
            candidates.append((rel, loc))
    if not candidates:
        return []

    regressions = []
    with _store_lock(project_root):
        data = load_debt_ratchet(project_root)
        any_dirty = False
        for rel, loc in candidates:
            is_reg, base_loc, delta, msg, dirty = _apply_ratchet(data, project_root, rel, loc, threshold, True)
            any_dirty = any_dirty or dirty
            if is_reg:
                regressions.append((rel, base_loc, delta, msg))
        if any_dirty:
            save_debt_ratchet(project_root, data)
    return regressions


def get_session_changed_files(project_root: str) -> List[str]:
    """
    Discovers files modified or added in the working tree via git status.
    Returns absolute paths to existing changed files inside project_root.
    """
    changed: List[str] = []
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=project_root,
                             capture_output=True, text=True, encoding="utf-8", timeout=5)
        res = subprocess.run(["git", "status", "--porcelain", "-z", "--untracked-files=all"], cwd=project_root,
                             capture_output=True, timeout=10)
        if top.returncode != 0 or res.returncode != 0:
            return changed
        git_root = os.path.normpath(top.stdout.strip())
        real_root = os.path.realpath(project_root)
        entries = res.stdout.decode("utf-8", errors="replace").split("\0")
        i = 0
        while i < len(entries):
            entry = entries[i]
            i += 1
            if len(entry) < 4:
                continue
            xy, file_part = entry[:2], entry[3:]
            if "R" in xy or "C" in xy:
                i += 1  # rename/copy records carry the original path as the next NUL field
            if "D" in xy:
                continue
            # realpath on both sides: Windows 8.3 short names (HALILE~1) and git's long form must compare equal
            rel = to_project_rel_path(real_root, os.path.realpath(os.path.join(git_root, file_part)))
            full = os.path.normpath(os.path.join(project_root, rel))
            if not rel.startswith("../") and os.path.isfile(full):
                changed.append(full)
    except (subprocess.SubprocessError, OSError) as err:
        _warn(f"Git status discovery failed: {err}")
    return changed


def scan_project(project_root: str, threshold: int = DEFAULT_RATCHET_THRESHOLD) -> int:
    """Walks the project and registers every source file over the threshold. Returns how many files were scanned."""
    paths: List[str] = []
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d.lower() not in EXCLUDED_RATCHET_DIRS]
        paths.extend(os.path.join(dirpath, n) for n in filenames if n.lower().endswith(SCAN_SOURCE_SUFFIXES))
    evaluate_changed_files_ratchet(project_root, paths, threshold)
    return len(paths)


def get_project_debt_summary(
    project_root: str,
    threshold: int = DEFAULT_RATCHET_THRESHOLD
) -> Dict[str, Any]:
    """
    Aggregates debt stats for every file registered in the ratchet store (see scan_project to register more).
    Entries whose file no longer exists are skipped.
    """
    data = load_debt_ratchet(project_root)

    debt_items = []
    total_debt_loc = 0
    total_regressions = 0

    for rel_path, entry in data.get("files", {}).items():
        current_loc = _measure_file(os.path.join(project_root, rel_path))
        if current_loc is None:
            continue

        baseline_loc = _entry_baseline(entry, threshold)
        debt = max(0, current_loc - threshold)
        regression = max(0, current_loc - baseline_loc)

        if regression > 0:
            total_regressions += 1
            status = "REGRESSION"
        elif current_loc < baseline_loc:
            status = "IMPROVED"
        else:
            status = "LOCKED"

        total_debt_loc += debt
        debt_items.append({
            "path": rel_path,
            "current_loc": current_loc,
            "baseline_loc": baseline_loc,
            "threshold": threshold,
            "debt_loc": debt,
            "regression_loc": regression,
            "status": status
        })

    debt_items.sort(key=lambda x: (x["status"] != "REGRESSION", -x["current_loc"]))

    return {
        "project_root": project_root,
        "threshold": threshold,
        "total_files_with_debt": len(debt_items),
        "total_debt_loc": total_debt_loc,
        "total_regressions": total_regressions,
        "files": debt_items
    }


_ALLOW_MONOLITH_RE = re.compile(r"(?://|/\*|#)\s*srp\s*:\s*(?:allow-monolith|cohesive-monolith|bypass|noqa)\b", re.IGNORECASE)


def check_new_file_bloat(project_root: str, file_path: str, old_content: str, projected_content: str, max_loc: int) -> str:
    """G5_NEW_FILE_BLOAT_DENY: reason text when a brand-new source file is written above `max_loc` lines, else ''.

    The ratchet only sees files the store knows; this stops a monolith at birth, before it touches the disk.
    A file that already has content is never "new" (the ratchet and ARCH_FILE_GROWTH govern it).
    """
    rel = to_project_rel_path(project_root, file_path)
    if old_content.strip() or is_test_or_exempt_file(rel) or not rel.lower().endswith(SCAN_SOURCE_SUFFIXES):
        return ""
    if _ALLOW_MONOLITH_RE.search(projected_content):
        return ""
    loc = count_clean_lines(projected_content)
    if loc <= max_loc:
        return ""
    return (
        f"Yeni Dosya Şişkinliği: '{rel}' sıfırdan {loc} satırla oluşturuluyor (sınır {max_loc}). "
        f"Tek hamlede monolit yazmak yerine kodu sorumluluğa göre alt modüllere bölüp her birini ayrı dosya olarak oluşturun. "
        f"{build_refactor_hint(projected_content, rel)}"
    ).strip()
