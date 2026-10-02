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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    except (IOError, OSError):
        return runtime_dir / "governance.json"
    return runtime_dir / "governance.json"


def get_test_evidence_file_path(project_root: Optional[Path] = None) -> Path:
    override_dir = os.environ.get("GRAVITYGUARD_LOG_DIR")
    if override_dir:
        return Path(override_dir) / "test_evidence_state.json"
    if project_root is None:
        project_root = Path.cwd()
    runtime_dir = project_root / ".gravityguard" / "runtime"
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
    except (IOError, OSError):
        return runtime_dir / "test_evidence_state.json"
    return runtime_dir / "test_evidence_state.json"


def load_governance_state(
    project_root: Optional[Path] = None,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Loads unified governance state (tracking test_obligations, doc_obligations, and session stop_retries).
    Falls back gracefully to legacy test_evidence_state.json if governance.json does not exist.
    """
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
            "resolution_intents": [],
            "sessions": {}
        }

    data.setdefault("version", 2)
    data.setdefault("sessions", {})
    data.setdefault("test_obligations", {"pending": {}})
    data.setdefault("doc_obligations", {"pending": {}})
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
    for cat in ("test_obligations", "doc_obligations"):
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
        for cat in ("test_obligations", "doc_obligations"):
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


def get_session_stop_retries(project_root: Optional[Path] = None, conversation_id: Optional[str] = None) -> int:
    state = load_governance_state(project_root)
    cid = conversation_id or "default"
    session = state.get("sessions", {}).get(cid, {})
    return session.get("stop_retries", state.get("stop_retries", 0))


def increment_session_stop_retries(project_root: Optional[Path] = None, conversation_id: Optional[str] = None) -> int:
    state = load_governance_state(project_root)
    cid = conversation_id or "default"
    session = state.setdefault("sessions", {}).setdefault(cid, {"stop_retries": 0})
    session["stop_retries"] = session.get("stop_retries", 0) + 1
    state["stop_retries"] = session["stop_retries"]
    save_governance_state(state, project_root)
    return session["stop_retries"]


def reset_session_stop_retries(project_root: Optional[Path] = None, conversation_id: Optional[str] = None) -> None:
    state = load_governance_state(project_root)
    cid = conversation_id or "default"
    if cid in state.get("sessions", {}):
        state["sessions"][cid]["stop_retries"] = 0
    state["stop_retries"] = 0
    save_governance_state(state, project_root)


def load_test_evidence_state(project_root: Optional[Path] = None) -> Dict[str, Any]:
    gov = load_governance_state(project_root)
    return {"version": 1, "pending": gov.get("test_obligations", {}).get("pending", {})}


def save_test_evidence_state(state: Dict[str, Any], project_root: Optional[Path] = None) -> None:
    gov = load_governance_state(project_root)
    gov.setdefault("test_obligations", {})["pending"] = state.get("pending", {})
    save_governance_state(gov, project_root)


def record_pending_test_evidence(
    target_file: str,
    candidate_path: Optional[str],
    expected_name: str,
    reason: str,
    project_root: Optional[Path] = None,
    conversation_id: Optional[str] = None
) -> None:
    norm = target_file.replace("\\", "/")
    state = load_governance_state(project_root)
    entry = {
        "candidate_path": candidate_path.replace("\\", "/") if candidate_path else None,
        "expected_name": expected_name,
        "timestamp": time.time(),
        "reason": reason
    }
    state.setdefault("test_obligations", {}).setdefault("pending", {})[norm] = entry
    cid = conversation_id or "default"
    state.setdefault("sessions", {}).setdefault(cid, {}).setdefault("test_obligations", {}).setdefault("pending", {})[norm] = entry
    save_governance_state(state, project_root)


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

    state = load_governance_state(project_root)
    pending = state.get("test_obligations", {}).get("pending", {})
    resolved = []

    for prod_path, entry in list(pending.items()):
        cand = (entry.get("candidate_path") or "").lower()
        exp = (entry.get("expected_name") or "").lower()
        prod_stem = Path(prod_path).stem.lower()

        matched = False
        if prod_path.lower() == norm_test or norm_test.endswith(prod_path.lower()):
            matched = True
        elif cand and (norm_test.endswith(cand) or cand.endswith(norm_test) or Path(cand).name == Path(norm_test).name):
            matched = True
        elif exp and (norm_test.endswith(exp) or Path(norm_test).name == exp):
            matched = True
        elif base_stem == prod_stem or base_stem.replace("-", "_") == prod_stem.replace("-", "_"):
            matched = True

        if matched:
            resolved.append(prod_path)
            del pending[prod_path]
            for s_id, s_data in state.get("sessions", {}).items():
                s_pending = s_data.get("test_obligations", {}).get("pending", {})
                if prod_path in s_pending:
                    del s_pending[prod_path]

    if resolved:
        reset_session_stop_retries(project_root, conversation_id)
        save_governance_state(state, project_root)
    return resolved


def get_unresolved_test_evidence(
    project_root: Optional[Path] = None,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    state = load_governance_state(project_root)
    if conversation_id and conversation_id in state.get("sessions", {}):
        sess_pending = state["sessions"][conversation_id].get("test_obligations", {}).get("pending")
        if sess_pending is not None:
            return sess_pending
    return state.get("test_obligations", {}).get("pending", {})


def clear_test_evidence_state(project_root: Optional[Path] = None) -> None:
    state = load_governance_state(project_root)
    state.setdefault("test_obligations", {})["pending"] = {}
    save_governance_state(state, project_root)


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

    state = load_governance_state(project_root)
    entry = {
        "required_docs": required_docs,
        "timestamp": time.time(),
        "reason": reason
    }
    state.setdefault("doc_obligations", {}).setdefault("pending", {})[norm] = entry
    cid = conversation_id or "default"
    state.setdefault("sessions", {}).setdefault(cid, {}).setdefault("doc_obligations", {}).setdefault("pending", {})[norm] = entry
    save_governance_state(state, project_root)


def resolve_pending_doc_obligations(
    doc_file: str,
    project_root: Optional[Path] = None,
    conversation_id: Optional[str] = None
) -> List[str]:
    norm_doc = doc_file.replace("\\", "/").lower()
    doc_name = Path(norm_doc).name

    state = load_governance_state(project_root)
    pending = state.get("doc_obligations", {}).get("pending", {})
    resolved = []

    for prod_path, entry in list(pending.items()):
        reqs = [r.lower() for r in entry.get("required_docs", ["changelog.md"])]
        if any(doc_name == req or norm_doc.endswith(req) for req in reqs):
            remaining = [r for r in entry.get("required_docs", []) if r.lower() != doc_name and not norm_doc.endswith(r.lower())]
            if not remaining:
                resolved.append(prod_path)
                del pending[prod_path]
                for s_id, s_data in state.get("sessions", {}).items():
                    s_pending = s_data.get("doc_obligations", {}).get("pending", {})
                    if prod_path in s_pending:
                        del s_pending[prod_path]
            else:
                entry["required_docs"] = remaining

    if resolved:
        reset_session_stop_retries(project_root, conversation_id)
        save_governance_state(state, project_root)
    return resolved


def get_unresolved_doc_obligations(
    project_root: Optional[Path] = None,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    state = load_governance_state(project_root)
    if conversation_id and conversation_id in state.get("sessions", {}):
        sess_pending = state["sessions"][conversation_id].get("doc_obligations", {}).get("pending")
        if sess_pending is not None:
            return sess_pending
    return state.get("doc_obligations", {}).get("pending", {})


def clear_doc_obligations(project_root: Optional[Path] = None) -> None:
    state = load_governance_state(project_root)
    state.setdefault("doc_obligations", {})["pending"] = {}
    save_governance_state(state, project_root)


def clear_governance_state(project_root: Optional[Path] = None) -> None:
    save_governance_state({
        "version": 2,
        "test_obligations": {"pending": {}},
        "doc_obligations": {"pending": {}},
        "resolution_intents": [],
        "sessions": {}
    }, project_root)


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


def record_resolution_intent(
    kind: str,
    target_file: str,
    project_root: Optional[Path] = None,
    conversation_id: Optional[str] = None
) -> None:
    """
    Records an intent to resolve doc or test obligations once physical disk modification occurs.
    Two-Phase Commit Phase 1: Captures baseline pre-modification digest without resolving prematurely.
    """
    root = project_root or Path.cwd()
    norm = target_file.replace("\\", "/")
    raw_path = Path(target_file)
    target_path = raw_path if raw_path.is_absolute() else (root / raw_path)

    pre_hash, pre_mtime, pre_size = compute_file_digest(target_path)
    state = load_governance_state(project_root)
    intents = state.setdefault("resolution_intents", [])

    intents = [
        it for it in intents
        if not (it.get("kind") == kind and it.get("target_path") == str(target_path))
    ]
    intents.append({
        "kind": kind,
        "target_file": norm,
        "target_path": str(target_path),
        "pre_hash": pre_hash,
        "pre_mtime": pre_mtime,
        "pre_size": pre_size,
        "timestamp": time.time(),
        "conversation_id": conversation_id or "default"
    })
    state["resolution_intents"] = intents
    save_governance_state(state, project_root)


def reconcile_obligations_on_disk(
    project_root: Optional[Path] = None,
    conversation_id: Optional[str] = None,
    cfg: Optional[dict] = None
) -> Tuple[List[str], List[str]]:
    """
    Physical disk verification for pending test and doc obligations.
    Two-Phase Commit:
    1. Evaluates staged resolution_intents against disk snapshot (hash, mtime, size change).
       Only if the file was physically created or modified on disk is the resolution committed.
    2. Fallback disk verification: checks pending obligations where files were updated out-of-band.
    Returns (resolved_tests, resolved_docs).
    """
    cid = conversation_id or "default"
    root = project_root or Path.cwd()

    state = load_governance_state(project_root)
    intents = state.get("resolution_intents", [])
    remaining_intents = []

    resolved_docs: List[str] = []
    resolved_tests: List[str] = []

    for intent in intents:
        target_path_str = intent.get("target_path")
        if not target_path_str:
            continue
        p = Path(target_path_str)
        curr_hash, curr_mtime, curr_size = compute_file_digest(p)
        pre_hash = intent.get("pre_hash")
        pre_mtime = intent.get("pre_mtime")
        pre_size = intent.get("pre_size", 0)

        physically_modified = False
        if pre_hash is None:
            # File did not exist when intent was recorded; now exists on disk
            if curr_hash is not None:
                physically_modified = True
        else:
            # File existed; check if hash, size, or mtime changed
            if curr_hash != pre_hash or curr_size != pre_size or (
                curr_mtime is not None and pre_mtime is not None and curr_mtime > pre_mtime
            ):
                physically_modified = True

        if physically_modified:
            kind = intent.get("kind")
            target_f = intent.get("target_file", str(p))
            intent_cid = intent.get("conversation_id", cid)
            if kind == "doc":
                res = resolve_pending_doc_obligations(target_f, root, intent_cid)
                resolved_docs.extend(res)
            elif kind == "test":
                res = resolve_pending_test_evidence(target_f, root, intent_cid)
                resolved_tests.extend(res)
        else:
            # Keep intent if fresh (< 3600s)
            if (time.time() - intent.get("timestamp", 0)) < 3600:
                remaining_intents.append(intent)

    if len(remaining_intents) != len(intents):
        state = load_governance_state(project_root)
        state["resolution_intents"] = remaining_intents
        save_governance_state(state, project_root)

    active_intent_paths = {
        Path(intent["target_path"]).resolve()
        for intent in remaining_intents
        if intent.get("target_path")
    }

    # 2. Existing fallback: check pending obligations directly against disk mtime
    pending_docs = get_unresolved_doc_obligations(root, cid)
    for prod_file, doc_info in list(pending_docs.items()):
        req_docs = doc_info.get("required_docs", ["CHANGELOG.md"])
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
            try:
                if doc_path.stat().st_mtime < (ts - 5):
                    all_satisfied = False
                    break
            except OSError:
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

        ts = test_info.get("timestamp", 0)
        if candidate and os.path.isfile(candidate):
            try:
                if os.path.getmtime(candidate) >= (ts - 5):
                    res = resolve_pending_test_evidence(candidate, root, cid)
                    resolved_tests.extend(res)
            except OSError:
                continue

    return resolved_tests, resolved_docs
