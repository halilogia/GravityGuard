"""GravityGuard Engine — governance.json paths, locked transactions, load/save and stop-retry circuit-breaker."""
import hashlib
import json
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .state_lock import StateLock, StateLockTimeout


def get_governance_file_path(project_root: Optional[Path] = None) -> Path:
    override_dir = os.environ.get("GRAVITYGUARD_LOG_DIR")
    if override_dir:
        return Path(override_dir) / "governance.json"
    if project_root is None:
        project_root = Path.cwd()
    runtime_dir = project_root / ".gravityguard" / "runtime"
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
    except (IOError, OSError) as err:
        _err = err
        return runtime_dir / "governance.json"
    return runtime_dir / "governance.json"


def get_governance_lock_path(project_root: Optional[Path] = None) -> Path:
    override_dir = os.environ.get("GRAVITYGUARD_LOG_DIR")
    if override_dir:
        return Path(override_dir) / "governance.lock"
    if project_root is None:
        project_root = Path.cwd()
    runtime_dir = project_root / ".gravityguard" / "runtime"
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
    except (IOError, OSError) as err:
        _err = err
        return runtime_dir / "governance.lock"
    return runtime_dir / "governance.lock"


def get_test_evidence_file_path(project_root: Optional[Path] = None) -> Path:
    override_dir = os.environ.get("GRAVITYGUARD_LOG_DIR")
    if override_dir:
        return Path(override_dir) / "test_evidence_state.json"
    if project_root is None:
        project_root = Path.cwd()
    runtime_dir = project_root / ".gravityguard" / "runtime"
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
    except (IOError, OSError) as err:
        _err = err
        return runtime_dir / "test_evidence_state.json"
    return runtime_dir / "test_evidence_state.json"


_txn_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar("_txn_context", default=None)


@contextmanager
def governance_transaction(
    project_root: Optional[Path] = None,
    timeout: float = 5.0
):
    """
    Context manager providing atomic read-modify-write transactions for governance state.
    Acquires an exclusive OS-level file lock across processes and handles re-entrancy
    cleanly within the same execution context.
    """
    root = project_root or Path.cwd()
    norm_root = str(root.resolve()).lower()

    active = _txn_context.get()
    if active is not None and active.get("root") == norm_root:
        # Re-entrant transaction in the same thread / context: reuse existing in-memory state
        yield active["state"]
        return

    env_timeout = os.environ.get("GRAVITYGUARD_LOCK_TIMEOUT")
    if env_timeout:
        try:
            timeout = float(env_timeout)
        except (ValueError, TypeError) as err:
            _err = err

    lock_path = get_governance_lock_path(project_root)
    lock = StateLock(lock_path, timeout=timeout)
    if not lock.acquire():
        raise StateLockTimeout(f"Governance state lock timeout ({timeout}s): {lock_path}")

    try:
        state = load_governance_state(project_root)
        token = _txn_context.set({"root": norm_root, "state": state})
        try:
            yield state
            save_governance_state(state, project_root)
        finally:
            _txn_context.reset(token)
    finally:
        lock.release()


def load_governance_state(
    project_root: Optional[Path] = None,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Loads unified governance state (tracking test_obligations, doc_obligations, and session stop_retries).
    Falls back gracefully to legacy test_evidence_state.json if governance.json does not exist.
    """
    root = project_root or Path.cwd()
    norm_root = str(root.resolve()).lower()
    active = _txn_context.get()
    if active is not None and active.get("root") == norm_root:
        return active["state"]

    path = get_governance_file_path(project_root)
    legacy_path = get_test_evidence_file_path(project_root)

    data = None
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
        except (IOError, OSError, json.JSONDecodeError, ValueError):
            data = None

    if data is None and legacy_path.exists():
        try:
            with open(legacy_path, "r", encoding="utf-8") as f:
                legacy = json.load(f)
                if isinstance(legacy, dict):
                    pending = legacy.get("pending", {}) if isinstance(legacy.get("pending"), dict) else {}
                    data = {
                        "version": 2,
                        "test_obligations": {"pending": pending},
                        "doc_obligations": {"pending": {}},
                        "sessions": {}
                    }
        except (IOError, OSError, json.JSONDecodeError, ValueError):
            data = None

    if data is None or not isinstance(data, dict):
        data = {
            "version": 2,
            "test_obligations": {"pending": {}},
            "doc_obligations": {"pending": {}},
            "review_obligations": {"pending": {}},
            "resolution_intents": [],
            "sessions": {}
        }

    data.setdefault("version", 2)
    data.setdefault("sessions", {})
    data.setdefault("test_obligations", {"pending": {}})
    data.setdefault("doc_obligations", {"pending": {}})
    data.setdefault("review_obligations", {"pending": {}})
    data.setdefault("resolution_intents", [])

    now = time.time()
    # Prune stale resolution intents (> 1 hour)
    intents = data.get("resolution_intents", [])
    if isinstance(intents, list):
        data["resolution_intents"] = [
            it for it in intents
            if isinstance(it, dict) and (now - it.get("timestamp", now)) < 3600
        ]

    # Prune stale global pending (> 1 hour)
    for cat in ("test_obligations", "doc_obligations", "review_obligations"):
        pending = data.get(cat, {}).get("pending", {})
        if isinstance(pending, dict):
            data[cat]["pending"] = {
                k: v for k, v in pending.items()
                if isinstance(v, dict) and (now - v.get("timestamp", now)) < 3600
            }

    # Prune stale session pending
    for s_id, s_data in list(data["sessions"].items()):
        if not isinstance(s_data, dict):
            continue
        for cat in ("test_obligations", "doc_obligations", "review_obligations"):
            if cat in s_data and isinstance(s_data[cat], dict) and "pending" in s_data[cat]:
                pending = s_data[cat]["pending"]
                if isinstance(pending, dict):
                    s_data[cat]["pending"] = {
                        k: v for k, v in pending.items()
                        if isinstance(v, dict) and (now - v.get("timestamp", now)) < 3600
                    }

    return data


def save_governance_state(state: Dict[str, Any], project_root: Optional[Path] = None) -> None:
    """
    Saves unified governance state to governance.json and syncs test_evidence_state.json for compatibility.
    """
    path = get_governance_file_path(project_root)
    legacy_path = get_test_evidence_file_path(project_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write governance.json atomically
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        tmp.replace(path)

        # Sync legacy test_evidence_state.json atomically
        legacy_state = {
            "version": 1,
            "pending": state.get("test_obligations", {}).get("pending", {})
        }
        legacy_tmp = legacy_path.with_suffix(".tmp")
        with open(legacy_tmp, "w", encoding="utf-8") as f:
            json.dump(legacy_state, f, indent=2, ensure_ascii=False)
        legacy_tmp.replace(legacy_path)
    except (IOError, OSError) as exc:
        raise OSError("Governance state could not be persisted") from exc


def compute_file_digest(file_path: Path) -> Tuple[Optional[str], Optional[float], int]:
    """
    Computes (sha256_hex, mtime, size) for a file if it exists, or (None, None, 0) if absent.
    Zero external dependencies.
    """
    if not file_path.is_file():
        return None, None, 0
    try:
        stat = file_path.stat()
        mtime = stat.st_mtime
        size = stat.st_size
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest(), mtime, size
    except (IOError, OSError):
        return None, None, 0


def get_session_stop_retries(project_root: Optional[Path] = None, conversation_id: Optional[str] = None) -> int:
    """Stop retries of ONE conversation. The project-wide ``stop_retries`` is a display value only (the live monitor
    shows it); reading it here let another session's retries open or close this session's circuit breaker."""
    state = load_governance_state(project_root)
    cid = conversation_id or "default"
    session = state.get("sessions", {}).get(cid, {})
    value = session.get("stop_retries", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def increment_session_stop_retries(project_root: Optional[Path] = None, conversation_id: Optional[str] = None) -> int:
    with governance_transaction(project_root) as state:
        cid = conversation_id or "default"
        session = state.setdefault("sessions", {}).setdefault(cid, {"stop_retries": 0})
        session["stop_retries"] = session.get("stop_retries", 0) + 1
        state["stop_retries"] = session["stop_retries"]
        return session["stop_retries"]


def reset_session_stop_retries(project_root: Optional[Path] = None, conversation_id: Optional[str] = None) -> None:
    with governance_transaction(project_root) as state:
        cid = conversation_id or "default"
        if cid in state.get("sessions", {}):
            state["sessions"][cid]["stop_retries"] = 0
        state["stop_retries"] = 0


