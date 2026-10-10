#!/usr/bin/env python3
"""
GravityGuard Engine — Governance State & Obligation Tracking Subsystem.
Manages unified governance.json state:
- test_obligations (pending/resolved)
- doc_obligations (pending/resolved under docs/KNOWLEDGE.md §6)
- session stop_retries circuit-breaker
- physical disk reconciliation (Two-Phase Commit verification)
Zero external dependencies.
"""
import hashlib
import json
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .state_lock import StateLock, StateLockTimeout
from .test_evidence import is_exempt_from_test_evidence, resolve_candidate_test_file


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
            "review_invocations": [],
            "resolution_intents": [],
            "sessions": {}
        }

    data.setdefault("version", 2)
    data.setdefault("sessions", {})
    data.setdefault("test_obligations", {"pending": {}})
    data.setdefault("doc_obligations", {"pending": {}})
    data.setdefault("review_obligations", {"pending": {}})
    data.setdefault("review_invocations", [])
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
    except (IOError, OSError):
        return


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


def load_test_evidence_state(project_root: Optional[Path] = None) -> Dict[str, Any]:
    gov = load_governance_state(project_root)
    return {"version": 1, "pending": gov.get("test_obligations", {}).get("pending", {})}


def save_test_evidence_state(state: Dict[str, Any], project_root: Optional[Path] = None) -> None:
    with governance_transaction(project_root) as gov:
        gov.setdefault("test_obligations", {})["pending"] = state.get("pending", {})


def record_pending_test_evidence(
    target_file: str,
    candidate_path: Optional[str],
    expected_name: str,
    reason: str,
    project_root: Optional[Path] = None,
    conversation_id: Optional[str] = None
) -> None:
    norm = target_file.replace("\\", "/")
    root = project_root or Path.cwd()
    cand_h = None
    if candidate_path:
        cand_p = Path(candidate_path)
        if not cand_p.is_absolute():
            cand_p = root / cand_p
        cand_h, _, _ = compute_file_digest(cand_p)

    with governance_transaction(project_root) as state:
        entry = {
            "candidate_path": candidate_path.replace("\\", "/") if candidate_path else None,
            "baseline_hash": cand_h,
            "expected_name": expected_name,
            "timestamp": time.time(),
            "reason": reason
        }
        state.setdefault("test_obligations", {}).setdefault("pending", {})[norm] = entry
        cid = conversation_id or "default"
        state.setdefault("sessions", {}).setdefault(cid, {}).setdefault("test_obligations", {}).setdefault("pending", {})[norm] = entry


def resolve_pending_test_evidence(
    test_file: str,
    project_root: Optional[Path] = None,
    conversation_id: Optional[str] = None
) -> List[str]:
    norm_test = test_file.replace("\\", "/").lower()
    test_path_obj = Path(norm_test)
    test_stem = test_path_obj.stem.lower()

    base_stem = test_stem
    if base_stem.startswith("test_"):
        base_stem = base_stem[5:]
    if base_stem.endswith((".test", ".spec", "_test")):
        for sfx in (".test", ".spec", "_test"):
            if base_stem.endswith(sfx):
                base_stem = base_stem[:-len(sfx)]
                break

    resolved = []

    def _matches(prod_path: str, entry: dict) -> bool:
        cand = (entry.get("candidate_path") or "").lower()
        exp = (entry.get("expected_name") or "").lower()
        prod_stem = Path(prod_path).stem.lower()

        if prod_path.lower() == norm_test or norm_test.endswith(prod_path.lower()):
            return True
        if cand and (norm_test.endswith(cand) or cand.endswith(norm_test) or Path(cand).name == Path(norm_test).name):
            return True
        if exp and (norm_test.endswith(exp) or Path(norm_test).name == exp):
            return True
        if base_stem == prod_stem or base_stem.replace("-", "_") == prod_stem.replace("-", "_"):
            return True
        return False

    with governance_transaction(project_root) as state:
        cid = conversation_id
        if cid and cid in state.get("sessions", {}):
            session = state["sessions"][cid]
            pending = session.get("test_obligations", {}).get("pending", {})
            for prod_path, entry in list(pending.items()):
                if _matches(prod_path, entry):
                    resolved.append(prod_path)
                    del pending[prod_path]
                    # Prune from global pending only if no other session holds it
                    still_held = any(
                        s_id != cid and prod_path in s_data.get("test_obligations", {}).get("pending", {})
                        for s_id, s_data in state.get("sessions", {}).items()
                    )
                    if not still_held:
                        state.get("test_obligations", {}).get("pending", {}).pop(prod_path, None)
        else:
            pending = state.get("test_obligations", {}).get("pending", {})
            for prod_path, entry in list(pending.items()):
                if _matches(prod_path, entry):
                    resolved.append(prod_path)
                    del pending[prod_path]
                    for s_id, s_data in state.get("sessions", {}).items():
                        s_data.get("test_obligations", {}).get("pending", {}).pop(prod_path, None)

        if resolved:
            reset_session_stop_retries(project_root, conversation_id)
    return resolved


def _visible_pending(state: Dict[str, Any], category: str, conversation_id: Optional[str]) -> Dict[str, Any]:
    """Pending obligations one conversation has to answer for: its own, plus project-wide entries NO session owns.

    The project-wide list is a union kept for the live monitor and for state files written before sessions existed.
    An entry some other session owns is that session's debt and must not block this one; an entry nobody owns (a legacy
    file) still counts for everybody, as before. Without a conversation id the project-wide list is returned.
    """
    global_pending = state.get(category, {}).get("pending", {})
    if not conversation_id:
        return global_pending
    sessions = state.get("sessions", {})
    own_session = sessions.get(conversation_id, {})
    own = own_session.get(category, {}).get("pending") if isinstance(own_session, dict) else None
    owned_elsewhere = set()
    for sid, sdata in sessions.items():
        if sid == conversation_id or not isinstance(sdata, dict):
            continue
        other = sdata.get(category, {}).get("pending")
        if isinstance(other, dict):
            owned_elsewhere.update(other)
    visible = {k: v for k, v in global_pending.items() if k not in owned_elsewhere} if isinstance(global_pending, dict) else {}
    if isinstance(own, dict):
        visible.update(own)
    return visible


def get_unresolved_test_evidence(
    project_root: Optional[Path] = None,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    """Pending test obligations this conversation owes (see ``_visible_pending``)."""
    return _visible_pending(load_governance_state(project_root), "test_obligations", conversation_id)


def clear_test_evidence_state(project_root: Optional[Path] = None) -> None:
    with governance_transaction(project_root) as state:
        state.setdefault("test_obligations", {})["pending"] = {}


def record_pending_doc_obligation(
    target_file: str,
    required_docs: Optional[List[str]] = None,
    reason: Optional[str] = None,
    project_root: Optional[Path] = None,
    conversation_id: Optional[str] = None
) -> None:
    norm = target_file.replace("\\", "/")
    if required_docs is None:
        required_docs = ["CHANGELOG.md"]
    if reason is None:
        reason = f"Motor/kod dosyası değiştirildi ({norm}); docs/KNOWLEDGE.md §6 uyarınca {', '.join(required_docs)} güncellenmelidir."

    root = project_root or Path.cwd()
    baseline_hashes = {}
    for req in required_docs:
        req_p = Path(req)
        if not req_p.is_absolute():
            req_p = root / req_p
        h, _, _ = compute_file_digest(req_p)
        baseline_hashes[req] = h

    with governance_transaction(project_root) as state:
        # A required doc this session already updated before writing the code (docs-first order) counts once.
        touched = state.get("sessions", {}).get(conversation_id or "default", {}).get("docs_touched", {})
        still_required = []
        for req in required_docs:
            stamp = touched.pop(Path(req).name.lower(), None)
            if stamp is None or (time.time() - stamp) >= 3600:
                still_required.append(req)
        if not still_required:
            return
        required_docs = still_required
        entry = {
            "required_docs": required_docs,
            "baseline_hashes": baseline_hashes,
            "timestamp": time.time(),
            "reason": reason
        }
        state.setdefault("doc_obligations", {}).setdefault("pending", {})[norm] = entry
        cid = conversation_id or "default"
        state.setdefault("sessions", {}).setdefault(cid, {}).setdefault("doc_obligations", {}).setdefault("pending", {})[norm] = entry


def resolve_pending_doc_obligations(
    doc_file: str,
    project_root: Optional[Path] = None,
    conversation_id: Optional[str] = None
) -> List[str]:
    norm_doc = doc_file.replace("\\", "/").lower()
    doc_name = Path(norm_doc).name
    resolved = []

    with governance_transaction(project_root) as state:
        cid = conversation_id
        if cid and cid in state.get("sessions", {}):
            session = state["sessions"][cid]
            pending = session.get("doc_obligations", {}).get("pending", {})
            for prod_path, entry in list(pending.items()):
                reqs = [r.lower() for r in entry.get("required_docs", ["changelog.md"])]
                if any(doc_name == req or norm_doc.endswith(req) for req in reqs):
                    remaining = [r for r in entry.get("required_docs", []) if r.lower() != doc_name and not norm_doc.endswith(r.lower())]
                    if not remaining:
                        resolved.append(prod_path)
                        del pending[prod_path]
                        # Prune from global pending only if no other session still holds it
                        still_held = any(
                            s_id != cid and prod_path in s_data.get("doc_obligations", {}).get("pending", {})
                            for s_id, s_data in state.get("sessions", {}).items()
                        )
                        if not still_held:
                            state.get("doc_obligations", {}).get("pending", {}).pop(prod_path, None)
                    else:
                        entry["required_docs"] = remaining
        else:
            pending = state.get("doc_obligations", {}).get("pending", {})
            for prod_path, entry in list(pending.items()):
                reqs = [r.lower() for r in entry.get("required_docs", ["changelog.md"])]
                if any(doc_name == req or norm_doc.endswith(req) for req in reqs):
                    remaining = [r for r in entry.get("required_docs", []) if r.lower() != doc_name and not norm_doc.endswith(r.lower())]
                    if not remaining:
                        resolved.append(prod_path)
                        del pending[prod_path]
                        for s_id, s_data in state.get("sessions", {}).items():
                            s_data.get("doc_obligations", {}).get("pending", {}).pop(prod_path, None)
                    else:
                        entry["required_docs"] = remaining

        if resolved:
            reset_session_stop_retries(project_root, conversation_id)
    return resolved


def get_unresolved_doc_obligations(
    project_root: Optional[Path] = None,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    """Pending documentation obligations this conversation owes (same isolation rule as the test obligations)."""
    return _visible_pending(load_governance_state(project_root), "doc_obligations", conversation_id)


def clear_doc_obligations(project_root: Optional[Path] = None) -> None:
    with governance_transaction(project_root) as state:
        state.setdefault("doc_obligations", {})["pending"] = {}


def clear_governance_state(project_root: Optional[Path] = None) -> None:
    with governance_transaction(project_root) as state:
        state["version"] = 2
        state["test_obligations"] = {"pending": {}}
        state["doc_obligations"] = {"pending": {}}
        state["review_obligations"] = {"pending": {}}
        state["review_invocations"] = []
        state["resolution_intents"] = []
        state["sessions"] = {}
        state["stop_retries"] = 0


def record_resolution_intent(
    kind: str,
    target_file: str,
    project_root: Optional[Path] = None,
    conversation_id: Optional[str] = None
) -> None:
    """
    Records an intent to resolve doc or test obligations once physical disk modification occurs.
    Two-Phase Commit Phase 1: Captures baseline pre-modification digest without resolving prematurely.
    Scoped by conversation_id to avoid multi-conversation intent collisions.
    """
    root = project_root or Path.cwd()
    norm = target_file.replace("\\", "/")
    raw_path = Path(target_file)
    target_path = raw_path if raw_path.is_absolute() else (root / raw_path)

    pre_hash, pre_mtime, pre_size = compute_file_digest(target_path)
    cid = conversation_id or "default"

    with governance_transaction(project_root) as state:
        intents = state.setdefault("resolution_intents", [])
        intents = [
            it for it in intents
            if not (
                it.get("conversation_id") == cid
                and it.get("kind") == kind
                and it.get("target_path") == str(target_path)
            )
        ]
        intents.append({
            "kind": kind,
            "target_file": norm,
            "target_path": str(target_path),
            "pre_hash": pre_hash,
            "pre_mtime": pre_mtime,
            "pre_size": pre_size,
            "timestamp": time.time(),
            "conversation_id": cid
        })
        state["resolution_intents"] = intents


def reconcile_obligations_on_disk(
    project_root: Optional[Path] = None,
    conversation_id: Optional[str] = None,
    cfg: Optional[dict] = None
) -> Tuple[List[str], List[str]]:
    """
    Physical disk verification for pending test and doc obligations.
    Two-Phase Commit:
    1. Evaluates staged resolution_intents against cryptographic disk snapshot (SHA-256 change).
       Only if the file was physically created or modified on disk is the resolution committed.
    2. Fallback disk verification: checks pending obligations where files were updated out-of-band,
       using baseline cryptographic hashes.
    Returns (resolved_tests, resolved_docs).
    """
    cid = conversation_id or "default"
    root = project_root or Path.cwd()

    resolved_docs: List[str] = []
    resolved_tests: List[str] = []

    with governance_transaction(project_root) as state:
        intents = state.get("resolution_intents", [])
        remaining_intents = []

        for intent in intents:
            target_path_str = intent.get("target_path")
            if not target_path_str:
                continue

            intent_cid = intent.get("conversation_id", "default")
            # Session isolation: if reconciling for a specific conversation, only process its intents!
            if conversation_id and intent_cid != conversation_id:
                remaining_intents.append(intent)
                continue

            p = Path(target_path_str)
            curr_hash, curr_mtime, curr_size = compute_file_digest(p)
            pre_hash = intent.get("pre_hash")

            physically_modified = False
            if pre_hash is None:
                # File did not exist when intent was recorded; now exists on disk
                if curr_hash is not None:
                    physically_modified = True
            else:
                # File existed; modification strictly requires content/digest change (mtime alone does NOT qualify)
                if curr_hash != pre_hash:
                    physically_modified = True

            if physically_modified:
                kind = intent.get("kind")
                target_f = intent.get("target_file", str(p))
                if kind == "doc":
                    res = resolve_pending_doc_obligations(target_f, root, intent_cid)
                    resolved_docs.extend(res)
                    if not res:
                        # The doc was updated BEFORE any code debt existed: remember it for the next obligation.
                        touched = state.setdefault("sessions", {}).setdefault(intent_cid, {}).setdefault("docs_touched", {})
                        touched[Path(str(target_f).replace("\\", "/")).name.lower()] = time.time()
                elif kind == "test":
                    res = resolve_pending_test_evidence(target_f, root, intent_cid)
                    resolved_tests.extend(res)
            else:
                # Keep intent if fresh (< 3600s)
                if (time.time() - intent.get("timestamp", 0)) < 3600:
                    remaining_intents.append(intent)

        if len(remaining_intents) != len(intents):
            state["resolution_intents"] = remaining_intents

        active_intent_paths = {
            Path(intent["target_path"]).resolve()
            for intent in remaining_intents
            if intent.get("target_path") and (not conversation_id or intent.get("conversation_id") == conversation_id)
        }

        # 2. Cryptographic baseline & fallback disk verification
        pending_docs = get_unresolved_doc_obligations(root, cid)
        for prod_file, doc_info in list(pending_docs.items()):
            req_docs = doc_info.get("required_docs", ["CHANGELOG.md"])
            baseline_hashes = doc_info.get("baseline_hashes", {})
            ts = doc_info.get("timestamp", 0)
            all_satisfied = True
            for req in req_docs:
                doc_path = (root / req).resolve()
                if doc_path in active_intent_paths:
                    all_satisfied = False
                    break
                if not doc_path.is_file():
                    all_satisfied = False
                    break
                curr_h, _, _ = compute_file_digest(doc_path)
                if req in baseline_hashes:
                    base_h = baseline_hashes[req]
                    if base_h is None:
                        if curr_h is None:
                            all_satisfied = False
                            break
                    else:
                        if curr_h == base_h:
                            all_satisfied = False
                            break
                else:
                    try:
                        if doc_path.stat().st_mtime < (ts - 5):
                            all_satisfied = False
                            break
                    except OSError as err:
                        _mtime_err = err
                        all_satisfied = False
                        break
            if all_satisfied and req_docs:
                res = resolve_pending_doc_obligations(req_docs[0], root, cid)
                resolved_docs.extend(res)

        pending_tests = get_unresolved_test_evidence(root, cid)
        for prod_file, test_info in list(pending_tests.items()):
            if is_exempt_from_test_evidence(prod_file, cfg):
                res = resolve_pending_test_evidence(prod_file, root, cid)
                resolved_tests.extend(res)
                continue

            candidate = test_info.get("candidate_path")
            if not candidate or not os.path.isfile(candidate):
                cand_res, _ = resolve_candidate_test_file(prod_file, cfg)
                if cand_res and os.path.isfile(cand_res):
                    candidate = cand_res

            cand_path_obj = Path(candidate).resolve() if candidate else None
            if cand_path_obj and cand_path_obj in active_intent_paths:
                continue

            curr_h, _, _ = compute_file_digest(cand_path_obj) if cand_path_obj else (None, None, 0)
            ts = test_info.get("timestamp", 0)

            test_satisfied = False
            if cand_path_obj and cand_path_obj.is_file():
                if "baseline_hash" in test_info:
                    base_h = test_info.get("baseline_hash")
                    if base_h is None:
                        # File did not exist at obligation creation time; now created on disk!
                        if curr_h is not None:
                            test_satisfied = True
                    else:
                        # File existed at obligation creation time; hash must have changed!
                        if curr_h != base_h:
                            test_satisfied = True
                else:
                    try:
                        if os.path.getmtime(candidate) >= (ts - 5):
                            test_satisfied = True
                    except OSError as err:
                        _test_mtime_err = err
                        test_satisfied = False

            if test_satisfied:
                res = resolve_pending_test_evidence(candidate, root, cid)
                resolved_tests.extend(res)

    return resolved_tests, resolved_docs
