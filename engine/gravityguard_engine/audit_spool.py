#!/usr/bin/env python3
"""
GravityGuard Engine — Audit Spool & Live Projection Reconciliation Helpers.
Handles fallback spool writing, crash-safe spool replay, and journal-to-live-state reconciliation.
Zero external dependencies.
"""
import json
import os
import sys
from typing import Dict, Any, List

from .project_context import extract_project_info
from .audit_redaction import redact_record
from .audit_journal import (
    _commit_fallback_spool,
    _find_committed_event_ids,
    _get_journal_last_seq,
    _read_last_journal_entry,
)
from .audit_state import (
    _apply_event_to_live_state,
    _rebuild_live_state_from_permanent_audit,
    _replay_missing_journal_events,
)


def _write_fallback_spool_event(
    fallback_spool_path: str,
    event_id: str,
    now_iso: str,
    action: str,
    status: str,
    rule_id: str,
    resolved_rule_id: Any,
    target_file: str,
    conv_id: str,
    agent_name: str,
    reason: str,
    outcome: Any,
) -> None:
    """Buffers an audit event into the fallback spool when the lock cannot be acquired."""
    try:
        proj_name, proj_root = extract_project_info(target_file)
        ext = os.path.splitext(target_file)[1].lower() if target_file else ""
        model_id = os.environ.get("ANTIGRAVITY_MODEL", os.environ.get("MODEL_NAME", "unknown"))
        spool_event = {
            "auditSeq": -1,
            "eventId": event_id,
            "timestamp": now_iso,
            "action": action,
            "status": status,
            "ruleId": rule_id,
            "resolvedRuleId": resolved_rule_id,
            "target": target_file,
            "project": proj_name,
            "projectRoot": proj_root,
            "fileExt": ext,
            "conversationId": conv_id,
            "agent": agent_name,
            "model": model_id,
            "reason": reason,
            "outcome": outcome or status,
            "parentViolationId": None,
            "recoveryAttempts": 1,
            "resolutionMs": None,
        }
        spool_event = redact_record(spool_event)
        with open(fallback_spool_path, "a", encoding="utf-8") as sf:
            sf.write(json.dumps(spool_event, ensure_ascii=False) + "\n")
            sf.flush()
    except Exception as spool_err:
        sys.stderr.write(f"[GravityGuard Audit Spool Error] {spool_err}\n")


def _load_and_reconcile_live_state(log_path: str, permanent_log_path: str) -> Dict[str, Any]:
    """Loads live state JSON and reconciles sequence drift against the canonical permanent journal."""
    current_data = None
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    current_data = loaded
        except (json.JSONDecodeError, OSError) as read_err:
            sys.stderr.write(
                f"[GravityGuard State Corrupt Warning] {read_err}; attempting rebuild from permanent log\n"
            )
            current_data = None

    if current_data is None:
        return _rebuild_live_state_from_permanent_audit(permanent_log_path)

    live_seq = current_data.get("lastAuditSeq")
    journal_last_seq = _get_journal_last_seq(permanent_log_path)
    last_record = _read_last_journal_entry(permanent_log_path)
    if (
        last_record
        and last_record.get("recordType") == "audit_checkpoint"
        and current_data.get("maintenanceId") != last_record.get("eventId")
    ):
        current_data = _rebuild_live_state_from_permanent_audit(permanent_log_path)
        live_seq = current_data.get("lastAuditSeq")
    if live_seq is None:
        if journal_last_seq > 0:
            sys.stderr.write(
                f"[GravityGuard Uninitialized Projection] Missing lastAuditSeq with non-empty journal ({journal_last_seq}); rebuilding projection from canonical journal\n"
            )
            current_data = _rebuild_live_state_from_permanent_audit(permanent_log_path)
        else:
            current_data["lastAuditSeq"] = 0
    elif live_seq < journal_last_seq:
        _replay_missing_journal_events(current_data, permanent_log_path, from_seq=live_seq)
    elif live_seq > journal_last_seq:
        sys.stderr.write(
            f"[GravityGuard Projection Ahead Of Journal] live ({live_seq}) > journal ({journal_last_seq}); reconciling projection from canonical journal\n"
        )
        current_data = _rebuild_live_state_from_permanent_audit(permanent_log_path)

    return current_data


def _replay_spool_events(
    current_data: Dict[str, Any],
    spooled_events: List[Dict[str, Any]],
    spool_processing_files: List[str],
    permanent_log_path: str,
    journal_seq: int,
    is_durable: bool,
) -> int:
    """Replays buffered fallback spool events into the canonical journal and live state."""
    spool_writes_succeeded = True
    candidate_spool_ids = {sp.get("eventId") for sp in spooled_events if sp.get("eventId")}
    committed_spool_ids = _find_committed_event_ids(permanent_log_path, candidate_spool_ids)

    for sp_ev in spooled_events:
        sp_eid = sp_ev.get("eventId")
        if sp_eid and sp_eid in committed_spool_ids:
            continue

        sp_seq = journal_seq + 1
        sp_ev["auditSeq"] = sp_seq
        sp_redacted = redact_record(sp_ev)
        write_ok = False
        try:
            with open(permanent_log_path, "a", encoding="utf-8") as af:
                af.write(json.dumps(sp_redacted, ensure_ascii=False) + "\n")
                af.flush()
                if is_durable:
                    try:
                        os.fsync(af.fileno())
                    except (OSError, AttributeError) as sync_err:
                        sys.stderr.write(f"[GravityGuard Durability Sync Warning] {sync_err}\n")
            write_ok = True
        except Exception as spool_write_err:
            spool_writes_succeeded = False
            sys.stderr.write(f"[GravityGuard Spool Replay Write Error] {spool_write_err}\n")

        if write_ok:
            journal_seq = sp_seq
            if sp_eid:
                committed_spool_ids.add(sp_eid)

            _apply_event_to_live_state(current_data, sp_redacted)

            sp_live = {
                "eventId": sp_ev.get("eventId"),
                "auditSeq": journal_seq,
                "timestamp": sp_ev.get("timestamp"),
                "action": sp_ev.get("action"),
                "status": sp_ev.get("status"),
                "ruleId": sp_ev.get("ruleId"),
                "resolvedRuleId": sp_ev.get("resolvedRuleId"),
                "target": sp_ev.get("target"),
                "reason": sp_ev.get("reason"),
                "outcome": sp_ev.get("outcome"),
                "parentViolationId": sp_ev.get("parentViolationId"),
                "recoveryAttempts": sp_ev.get("recoveryAttempts"),
                "resolutionMs": sp_ev.get("resolutionMs"),
            }
            ev_list = current_data.get("events", [])
            if not isinstance(ev_list, list):
                ev_list = []
                current_data["events"] = ev_list
            ev_list.insert(0, redact_record(sp_live))
            if len(ev_list) > 50:
                ev_list.pop()

    if spool_processing_files and spool_writes_succeeded:
        _commit_fallback_spool(spool_processing_files)

    return journal_seq
