"""GravityGuard Engine — pending test-evidence and doc obligation records on governance.json."""
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .audit import detect_agent_name
from .governance_state import compute_file_digest, governance_transaction, load_governance_state, reset_session_stop_retries


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
    conversation_id: Optional[str] = None,
    agent: Optional[str] = None
) -> None:
    norm = target_file.replace("\\", "/")
    root = project_root or Path.cwd()
    cand_h = None
    if candidate_path:
        cand_p = Path(candidate_path)
        if not cand_p.is_absolute():
            cand_p = root / cand_p
        cand_h, _, _ = compute_file_digest(cand_p)

    agent_name = agent or detect_agent_name(conversation_id)
    with governance_transaction(project_root) as state:
        entry = {
            "candidate_path": candidate_path.replace("\\", "/") if candidate_path else None,
            "baseline_hash": cand_h,
            "expected_name": expected_name,
            "timestamp": time.time(),
            "reason": reason,
            "agent": agent_name
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
        if "codex" in prod_path.lower() and "codex" in norm_test:
            return True
        if "webview" in prod_path.lower() and "webview" in norm_test:
            return True
        if "audit" in prod_path.lower() and ("audit" in norm_test or "agent_identity" in norm_test):
            return True
        if ("stream" in prod_path.lower() or "live" in prod_path.lower()) and ("agent_identity" in norm_test or "stream" in norm_test or "live" in norm_test):
            return True
        if "obligations" in prod_path.lower() and "obligations" in norm_test:
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
    conversation_id: Optional[str] = None,
    agent: Optional[str] = None
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
        agent_name = agent or detect_agent_name(conversation_id)
        entry = {
            "required_docs": required_docs,
            "baseline_hashes": baseline_hashes,
            "timestamp": time.time(),
            "reason": reason,
            "agent": agent_name, "root": str(root)  # docs are verified where the code edit was governed
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

