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
import os
import time
from pathlib import Path
from typing import List, Optional, Tuple

from .test_evidence import is_exempt_from_test_evidence, resolve_candidate_test_file
from .governance_state import _txn_context, compute_file_digest, get_governance_file_path, get_governance_lock_path, get_session_stop_retries, get_test_evidence_file_path, governance_transaction, increment_session_stop_retries, load_governance_state, reset_session_stop_retries, save_governance_state  # noqa: F401 (re-export)
from .governance_obligations import _visible_pending, clear_doc_obligations, clear_test_evidence_state, get_unresolved_doc_obligations, get_unresolved_test_evidence, load_test_evidence_state, record_pending_doc_obligation, record_pending_test_evidence, resolve_pending_doc_obligations, resolve_pending_test_evidence, save_test_evidence_state  # noqa: F401 (re-export)


def clear_governance_state(project_root: Optional[Path] = None) -> None:
    with governance_transaction(project_root) as state:
        state["version"] = 2
        state["test_obligations"] = {"pending": {}}
        state["doc_obligations"] = {"pending": {}}
        state["review_obligations"] = {"pending": {}}
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
                doc_path = (Path(doc_info.get("root") or root) / req).resolve()
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
