#!/usr/bin/env python3
"""
GravityGuard Engine — Audit & Telemetry Subsystem.
Manages live security event monitor (srp_guardian_live.json)
and permanent append-only audit stream (gravityguard_permanent_audit.jsonl).
Supports causal event chaining (parentViolationId, resolvedRuleId, outcome, recoveryAttempts, resolutionMs)
with cross-process lock protection (StateLock).
Zero external dependencies.
"""
import json
import os
import re
import sys
import time
import uuid
import copy
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Set

from .project_context import extract_project_info
from .state_lock import StateLock

from .audit_redaction import _SECRET_PATTERNS, _SENSITIVE_DICT_KEYS, redact_record, redact_secrets
from .audit_journal import (
    _commit_fallback_spool,
    _find_committed_event_ids,
    _generate_event_id,
    _get_journal_last_seq,
    _is_durable_mode,
    _prepare_fallback_spool,
    _read_last_journal_entry,
    _repair_journal_tail,
    _resolve_log_dir,
)
from .audit_state import (
    _apply_event_to_live_state,
    _recompute_effectiveness_rates,
    _rebuild_live_state_from_permanent_audit,
    _replay_missing_journal_events,
    NON_RECOVERING_RULES,
    DETERRENCE_RULES,
)
from .audit_spool import (
    _load_and_reconcile_live_state,
    _replay_spool_events,
    _write_fallback_spool_event,
)


def detect_agent_name(conv_id: Any = None) -> str:
    cid = str(
        conv_id
        or os.environ.get("ANTIGRAVITY_CONVERSATION_ID")
        or os.environ.get("CONVERSATION_ID")
        or ""
    )
    if cid.startswith("claude:"):
        return "Claude Code"
    elif cid.startswith("codex:"):
        return "Codex"
    elif cid.startswith("opencode:"):
        return "OpenCode"
    elif cid.startswith("cli:") or cid.startswith("agy-cli:") or os.environ.get("AGY_CLI") or os.environ.get("ANTIGRAVITY_CLI"):
        return "Antigravity CLI"
    elif cid.startswith("sdk:") or cid.startswith("agy-sdk:") or os.environ.get("ANTIGRAVITY_SDK") or os.environ.get("AGY_SDK"):
        return "Antigravity SDK"
    return "Antigravity IDE"


def log_event(
    action: str,
    status: str,
    target_file: str,
    reason: str,
    rule_id: str = "SRP",
    outcome_override: Optional[str] = None,
    conversation_id: Optional[str] = None,
    evasion_markers: Optional[List[str]] = None
) -> str:
    """
    Logs an event to the live monitor stream (last 50 events)
    and the permanent append-only audit log for telemetry analysis.
    Implements rule-isolated causal outcome chaining (BLOCKED -> RECOVERED / REPEATED_VIOLATION).
    Uses StateLock for concurrency-safe live state updates and audit appending.
    Returns the unique eventId.
    """
    event_id = _generate_event_id()
    log_dir = _resolve_log_dir()
    now_dt = datetime.now().astimezone()
    now_iso = now_dt.isoformat()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    conv_id = (
        conversation_id
        or os.environ.get("ANTIGRAVITY_CONVERSATION_ID")
        or os.environ.get("CONVERSATION_ID")
        or "default"
    )
    agent_name = detect_agent_name(conv_id)
    norm_target = target_file.replace("\\\\", "/").replace("\\", "/").lower() if target_file else ""
    target_prefix = f"{conv_id}::{norm_target}::"
    tracking_key = f"{conv_id}::{norm_target}::{rule_id}" if norm_target else ""

    try:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "srp_guardian_live.json")
        permanent_log_path = os.path.join(log_dir, "gravityguard_permanent_audit.jsonl")
        fallback_spool_path = os.path.join(log_dir, "gravityguard_audit_fallback.jsonl")
        audit_lock_path = Path(log_dir) / ".audit.lock"

        outcome = outcome_override
        parent_violation_id: Optional[str] = None
        resolved_rule_id: Optional[str] = None
        recovery_attempts: Optional[int] = None
        resolution_ms: Optional[float] = None

        lock = StateLock(audit_lock_path, timeout=2.0)
        lock_acquired = False
        try:
            lock_acquired = lock.acquire()
        except Exception as lock_err:
            sys.stderr.write(f"[GravityGuard Audit Lock Warning] {lock_err}\n")

        if not lock_acquired:
            sys.stderr.write(f"[GravityGuard Audit Lock Timeout] Could not acquire audit lock for {log_path}; buffering event in fallback spool to prevent data loss\n")
            _write_fallback_spool_event(
                fallback_spool_path, event_id, now_iso, action, status,
                rule_id, resolved_rule_id, target_file, conv_id, agent_name, reason, outcome
            )
            return event_id

        try:
            _repair_journal_tail(permanent_log_path)
            spool_processing_files, spooled_events = _prepare_fallback_spool(log_dir)
            current_data = _load_and_reconcile_live_state(log_path, permanent_log_path)

            active_violations = current_data.setdefault("activeViolations", {})
            if not isinstance(active_violations, dict):
                active_violations = {}
                current_data["activeViolations"] = active_violations

            eff = current_data.setdefault("effectiveness", {})
            if not isinstance(eff, dict):
                eff = {
                    "totalBlocked": 0,
                    "totalRecovered": 0,
                    "recoveryRate": 100.0,
                    "ruleStats": {}
                }
                current_data["effectiveness"] = eff

            eff.setdefault("totalBlocked", 0)
            eff.setdefault("totalRecovered", 0)
            eff.setdefault("recoveryRate", 100.0)
            rule_stats = eff.setdefault("ruleStats", {})
            if not isinstance(rule_stats, dict):
                rule_stats = {}
                eff["ruleStats"] = rule_stats

            extra_recovery_events: List[Dict[str, Any]] = []

            if outcome is None:
                if status == "BLOCKED":
                    if tracking_key and tracking_key in active_violations:
                        prev = active_violations[tracking_key]
                        attempts = prev.get("attempts", 1) + 1
                        prev["attempts"] = attempts
                        prev["lastTimestamp"] = now_iso
                        outcome = "REPEATED_VIOLATION"
                        parent_violation_id = prev.get("eventId")
                        recovery_attempts = attempts
                    else:
                        outcome = "BLOCKED"
                        parent_violation_id = None
                        recovery_attempts = 1
                        eff["totalBlocked"] = eff.get("totalBlocked", 0) + 1
                        b_rule = rule_id or "UNKNOWN"
                        st = rule_stats.setdefault(b_rule, {"blocked": 0, "recovered": 0, "recoveryRate": 0.0, "attempts": []})
                        st["blocked"] = st.get("blocked", 0) + 1
                        if tracking_key:
                            active_violations[tracking_key] = {
                                "eventId": event_id,
                                "ruleId": rule_id,
                                "firstTimestamp": now_iso,
                                "lastTimestamp": now_iso,
                                "attempts": 1,
                                "status": "BLOCKED"
                            }
                elif status == "APPROVED":
                    can_recover = bool(norm_target) and rule_id not in NON_RECOVERING_RULES
                    matching_keys = [k for k in list(active_violations.keys()) if k.startswith(target_prefix)] if can_recover else []
                    if matching_keys:
                        resolved_items = []
                        for m_key in matching_keys:
                            p_info = active_violations.pop(m_key, None)
                            if p_info:
                                resolved_items.append(p_info)

                        if resolved_items:
                            primary = resolved_items[0]
                            outcome = "RECOVERED"
                            parent_violation_id = primary.get("eventId")
                            resolved_rule_id = primary.get("ruleId")
                            recovery_attempts = primary.get("attempts", 1)
                            try:
                                first_dt = datetime.fromisoformat(primary.get("firstTimestamp", now_iso)).astimezone()
                                resolution_ms = round((now_dt - first_dt).total_seconds() * 1000, 1)
                            except Exception:
                                resolution_ms = None

                            eff["totalRecovered"] = eff.get("totalRecovered", 0) + 1
                            p_rule = resolved_rule_id or "UNKNOWN"
                            p_st = rule_stats.setdefault(p_rule, {"blocked": 0, "recovered": 0, "recoveryRate": 0.0, "attempts": []})
                            p_st["recovered"] = p_st.get("recovered", 0) + 1
                            if recovery_attempts is not None:
                                p_st.setdefault("attempts", []).append(recovery_attempts)
                            if evasion_markers:
                                p_st["evasionSuspect"] = p_st.get("evasionSuspect", 0) + 1

                            for additional in resolved_items[1:]:
                                add_r_id = additional.get("ruleId")
                                add_e_id = _generate_event_id()
                                add_attempts = additional.get("attempts", 1)
                                try:
                                    add_first_dt = datetime.fromisoformat(additional.get("firstTimestamp", now_iso)).astimezone()
                                    add_res_ms = round((now_dt - add_first_dt).total_seconds() * 1000, 1)
                                except Exception:
                                    add_res_ms = None

                                add_ev = {
                                    "eventId": add_e_id,
                                    "timestamp": now_str,
                                    "action": action,
                                    "status": "APPROVED",
                                    "ruleId": rule_id,
                                    "resolvedRuleId": add_r_id,
                                    "target": target_file,
                                    "reason": f"Multi-rule resolution: {add_r_id} cleared by approved edit",
                                    "outcome": "RECOVERED",
                                    "agent": agent_name,
                                    "conversationId": conv_id,
                                    "parentViolationId": additional.get("eventId"),
                                    "recoveryAttempts": add_attempts,
                                    "resolutionMs": add_res_ms
                                }
                                extra_recovery_events.append(add_ev)

                                eff["totalRecovered"] = eff.get("totalRecovered", 0) + 1
                                add_rule = add_r_id or "UNKNOWN"
                                add_st = rule_stats.setdefault(add_rule, {"blocked": 0, "recovered": 0, "recoveryRate": 0.0, "attempts": []})
                                add_st["recovered"] = add_st.get("recovered", 0) + 1
                                if add_attempts is not None:
                                    add_st.setdefault("attempts", []).append(add_attempts)
                    else:
                        outcome = "CLEAN"
                elif status == "SHADOW_TRIGGER":
                    outcome = "SHADOW_OBSERVED"
                elif status == "WARNING":
                    outcome = "WARNING"
                    matching_keys = [k for k in active_violations if k.startswith(target_prefix)] if norm_target else []
                    if matching_keys:
                        parent_violation_id = active_violations[matching_keys[0]].get("eventId")
                else:
                    outcome = status

            journal_seq = current_data.get("lastAuditSeq", 0)
            is_durable = _is_durable_mode()
            journal_seq = _replay_spool_events(
                current_data, spooled_events, spool_processing_files,
                permanent_log_path, journal_seq, is_durable
            )

            current_data["lastAuditSeq"] = journal_seq
            next_seq = journal_seq + 1

            event = {
                "eventId": event_id,
                "auditSeq": next_seq,
                "timestamp": now_str,
                "action": action,
                "status": status,
                "ruleId": rule_id,
                "resolvedRuleId": resolved_rule_id,
                "target": target_file,
                "reason": reason,
                "outcome": outcome,
                "agent": agent_name,
                "conversationId": conv_id,
                "parentViolationId": parent_violation_id,
                "recoveryAttempts": recovery_attempts,
                "resolutionMs": resolution_ms
            }
            evasion_suspect = outcome == "RECOVERED" and bool(evasion_markers)
            if evasion_suspect:
                event["evasionSuspect"] = True
                event["evasionMarkers"] = list(evasion_markers or [])

            proj_name, proj_root = extract_project_info(target_file)
            ext = os.path.splitext(target_file)[1].lower() if target_file else ""
            model_id = os.environ.get("ANTIGRAVITY_MODEL", os.environ.get("MODEL_NAME", "unknown"))

            telemetry_event = {
                "auditSeq": next_seq,
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
                "outcome": outcome,
                "parentViolationId": parent_violation_id,
                "recoveryAttempts": recovery_attempts,
                "resolutionMs": resolution_ms
            }
            if evasion_suspect:
                telemetry_event["evasionSuspect"] = True
                telemetry_event["evasionMarkers"] = list(evasion_markers or [])

            extra_telemetry_events: List[Dict[str, Any]] = []
            curr_extra_seq = next_seq
            for add_ev in extra_recovery_events:
                curr_extra_seq += 1
                add_ev["auditSeq"] = curr_extra_seq
                add_telemetry = {
                    "auditSeq": curr_extra_seq,
                    "eventId": add_ev["eventId"],
                    "timestamp": now_iso,
                    "action": action,
                    "status": "APPROVED",
                    "ruleId": rule_id,
                    "resolvedRuleId": add_ev["resolvedRuleId"],
                    "target": target_file,
                    "project": proj_name,
                    "projectRoot": proj_root,
                    "fileExt": ext,
                    "conversationId": conv_id,
                    "agent": agent_name,
                    "model": model_id,
                    "reason": add_ev["reason"],
                    "outcome": "RECOVERED",
                    "parentViolationId": add_ev["parentViolationId"],
                    "recoveryAttempts": add_ev["recoveryAttempts"],
                    "resolutionMs": add_ev["resolutionMs"]
                }
                extra_telemetry_events.append(add_telemetry)

            final_audit_seq = curr_extra_seq

            event = redact_record(event)
            telemetry_event = redact_record(telemetry_event)
            extra_recovery_events = [redact_record(x) for x in extra_recovery_events]
            extra_telemetry_events = [redact_record(x) for x in extra_telemetry_events]

            try:
                with open(permanent_log_path, "a", encoding="utf-8") as af:
                    af.write(json.dumps(telemetry_event, ensure_ascii=False) + "\n")
                    for add_tel in extra_telemetry_events:
                        af.write(json.dumps(add_tel, ensure_ascii=False) + "\n")
                    af.flush()
                    if is_durable:
                        try:
                            os.fsync(af.fileno())
                        except (OSError, AttributeError) as sync_err:
                            sys.stderr.write(f"[GravityGuard Durability Sync Warning] {sync_err}\n")
            except OSError as perm_err:
                sys.stderr.write(f"[GravityGuard Permanent Journal Error] {perm_err}; buffering to fallback spool\n")
                try:
                    with open(fallback_spool_path, "a", encoding="utf-8") as sf:
                        sf.write(json.dumps(telemetry_event, ensure_ascii=False) + "\n")
                        for add_tel in extra_telemetry_events:
                            sf.write(json.dumps(add_tel, ensure_ascii=False) + "\n")
                        sf.flush()
                except Exception as spool_err:
                    sys.stderr.write(f"[GravityGuard Emergency Spool Write Error] {spool_err}\n")

            current_data["lastAuditSeq"] = final_audit_seq
            events = current_data.get("events", [])
            if not isinstance(events, list):
                events = []
            events.insert(0, event)
            for add_ev in extra_recovery_events:
                events.insert(1, add_ev)
            current_data["events"] = events[:50]
            current_data["lastCheck"] = now_str

            _recompute_effectiveness_rates(current_data)

            tmp_log_path = Path(log_path).with_suffix(".tmp")
            with open(tmp_log_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(current_data, ensure_ascii=False, separators=(",", ":")))
                f.flush()
                if is_durable:
                    try:
                        os.fsync(f.fileno())
                    except (OSError, AttributeError) as sync_err:
                        sys.stderr.write(f"[GravityGuard Durability Sync Warning] {sync_err}\n")
            tmp_log_path.replace(Path(log_path))
        finally:
            if lock_acquired:
                try:
                    lock.release()
                except Exception as rel_err:
                    sys.stderr.write(f"[GravityGuard Audit Lock Release Warning] {rel_err}\n")
    except Exception as exc:
        sys.stderr.write(f"[GravityGuard Event Error] {exc}\n")

    return event_id
