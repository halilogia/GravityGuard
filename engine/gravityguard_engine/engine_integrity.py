"""Engine self-protection: a guard that breaks itself must neither wedge the agent nor fail open.

Three layers, all stdlib-only so they keep working when the rest of the engine is broken:
1. ``engine_source_defect``: refuse a write that would leave an engine source file unusable (syntax error or a global name
   that is used but never defined — the exact defect that once made every tool call fail with GUARD_UNAVAILABLE).
2. ``run_lkg``: when the working-tree engine crashes, validate with the last committed ("last-known-good") engine, so
   protection stays fully on instead of denying everything or allowing everything.
3. ``repair_reason``: if even that is unavailable, allow *only* writes to engine source files so the defect can be fixed.
"""
import ast
import builtins
import json
import os
import re
import subprocess
import symtable
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

ENGINE_PKG_DIR = Path(__file__).resolve().parent
ENGINE_ROOT = ENGINE_PKG_DIR.parent
PLUGIN_DIR = ENGINE_ROOT.parent / "plugin"
LKG_ENV = "GRAVITYGUARD_LKG_ACTIVE"
LKG_KEEP = 3
LKG_TIMEOUT_SECONDS = 60

_MODULE_DUNDERS = frozenset({
    "__name__", "__file__", "__doc__", "__package__", "__spec__", "__loader__", "__builtins__", "__path__",
    "__debug__", "__annotations__", "__class__", "__qualname__", "__module__", "__cached__",
})
_WRITE_TOOL = re.compile(r"edit|write|replace|patch", re.IGNORECASE)
_PATH_KEY = re.compile(r"file|path", re.IGNORECASE)
_DECISIONS = ("allow", "deny", "continue")


def is_engine_source(path: Any) -> bool:
    """True for Python files of the engine package, its validator entrypoint and the provider hook adapters."""
    try:
        resolved = Path(str(path)).resolve()
    except (OSError, ValueError):
        return False
    if resolved.suffix != ".py":
        return False
    return (
        ENGINE_PKG_DIR in resolved.parents
        or resolved == ENGINE_ROOT / "gravity-validator.py"
        or PLUGIN_DIR in resolved.parents
    )


def _has_star_import(source: str) -> bool:
    return any(isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names) for n in ast.walk(ast.parse(source)))


def undefined_globals(source: str, filename: str = "<engine>") -> List[str]:
    """Names that are read as globals somewhere in ``source`` but never bound at module level (nor builtins)."""
    if _has_star_import(source):
        return []  # cannot know what a wildcard import provides
    top = symtable.symtable(source, filename, "exec")
    defined = set(_MODULE_DUNDERS) | set(dir(builtins))
    for sym in top.get_symbols():
        if sym.is_assigned() or sym.is_imported() or sym.is_namespace():
            defined.add(sym.get_name())
    missing: set = set()

    def walk(table, is_module: bool) -> None:
        for sym in table.get_symbols():
            if is_module:
                continue
            if sym.is_declared_global() and sym.is_assigned():
                defined.add(sym.get_name())
        for child in table.get_children():
            walk(child, False)

    def scan(table, is_module: bool) -> None:
        for sym in table.get_symbols():
            name = sym.get_name()
            referenced_global = sym.is_referenced() and (sym.is_global() or (is_module and not sym.is_local()))
            if referenced_global and name not in defined and not sym.is_assigned():
                missing.add(name)
        for child in table.get_children():
            scan(child, False)

    walk(top, True)
    scan(top, True)
    return sorted(missing)


def engine_source_defect(path: Any, projected: Any) -> str:
    """Reason a write must be refused, or '' when the resulting engine file is sound (or is not an engine file)."""
    if not isinstance(projected, str) or not is_engine_source(path):
        return ""
    try:
        compile(projected, str(path), "exec")
    except SyntaxError as exc:
        return f"SyntaxError (satır {exc.lineno}): {exc.msg}"
    except ValueError as exc:
        return f"derlenemiyor: {exc}"
    missing = undefined_globals(projected, str(path))
    if missing:
        return "tanımsız ad(lar): " + ", ".join(missing[:5]) + " — önce tanımı/ithalatı ekleyin, sonra kullanın"
    return ""


# ---------------------------------------------------------------------------------------------------------------------
# last-known-good (LKG) engine
# ---------------------------------------------------------------------------------------------------------------------
def _git_text(cwd: Path, *args: str) -> str:
    try:
        proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def lkg_root() -> Path:
    return Path(os.path.expanduser("~/.gemini/config/plugins/gravityguard/lkg"))


def _prune_lkg(keep_dir: Path) -> None:
    root = lkg_root()
    others = sorted((d for d in root.iterdir() if d.is_dir() and d != keep_dir), key=lambda d: d.stat().st_mtime, reverse=True)
    for stale in others[LKG_KEEP - 1:]:
        for item in sorted(stale.rglob("*"), reverse=True):
            item.unlink() if item.is_file() else item.rmdir()
        stale.rmdir()


def prepare_lkg() -> Optional[Path]:
    """Path of ``gravity-validator.py`` extracted from the last commit (cached per commit), or None when unavailable."""
    if os.environ.get(LKG_ENV):
        return None  # already running as the fallback: never recurse
    top = _git_text(ENGINE_ROOT, "rev-parse", "--show-toplevel")
    sha = _git_text(ENGINE_ROOT, "rev-parse", "HEAD")
    if not top or not sha:
        return None
    rel = ENGINE_ROOT.resolve().relative_to(Path(top).resolve()).as_posix()
    target = lkg_root() / sha[:12]
    validator = target / rel / "gravity-validator.py"
    if validator.is_file():
        return validator
    try:
        archive = subprocess.run(["git", "archive", "--format=zip", "HEAD", rel], cwd=top, capture_output=True, timeout=30)
        if archive.returncode != 0:
            return None
        target.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile() as handle:
            handle.write(archive.stdout)
            handle.seek(0)
            with zipfile.ZipFile(handle) as bundle:
                bundle.extractall(target)
        _prune_lkg(target)
    except (OSError, subprocess.SubprocessError, zipfile.BadZipFile):
        return None
    return validator if validator.is_file() else None


def run_lkg(raw_payload: str, argv: List[str]) -> Optional[Dict[str, Any]]:
    """Answer produced by the committed engine for the same hook payload, or None if it cannot give a sound one."""
    validator = prepare_lkg()
    if validator is None:
        return None
    env = dict(os.environ)
    env[LKG_ENV] = "1"
    try:
        proc = subprocess.run(
            [sys.executable, str(validator), *argv[1:]], input=raw_payload, capture_output=True, text=True,
            encoding="utf-8", timeout=LKG_TIMEOUT_SECONDS, env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    lines = proc.stdout.strip().splitlines()
    try:
        answer = json.loads(lines[-1]) if lines else None
    except ValueError:
        return None
    if proc.returncode != 0 or not isinstance(answer, dict) or answer.get("decision") not in _DECISIONS:
        return None
    if "GUARD_UNAVAILABLE" in str(answer.get("reason", "")):
        return None  # the fallback failed too: not a verdict
    return answer


# ---------------------------------------------------------------------------------------------------------------------
# break-glass repair
# ---------------------------------------------------------------------------------------------------------------------
def _target_paths(args: Any) -> List[str]:
    if not isinstance(args, dict):
        return []
    return [str(value) for key, value in args.items() if isinstance(value, str) and _PATH_KEY.search(str(key))]


def repair_reason(raw_payload: str) -> str:
    """Non-empty when the call is a write to an engine source file (the only thing allowed while the engine is down)."""
    try:
        payload = json.loads(raw_payload)
    except ValueError:
        return ""
    call = payload.get("toolCall") if isinstance(payload, dict) else None
    if not isinstance(call, dict) or not _WRITE_TOOL.search(str(call.get("name", ""))):
        return ""
    paths = _target_paths(call.get("args"))
    if paths and all(is_engine_source(p) for p in paths):
        return "[GUARD_REPAIR_MODE]: Doğrulama motoru çalışmıyor; yalnızca motor kaynağına yazma izni verildi (doğrulanmadı). Tanımsız adı/hatayı düzeltin."
    return ""
