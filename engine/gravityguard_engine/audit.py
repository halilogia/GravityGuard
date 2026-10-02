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
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from .project_context import extract_project_info
from .state_lock import StateLock


def _resolve_log_dir() -> str:
    """
    Resolves the audit-log directory.
    GRAVITYGUARD_LOG_DIR lets the test suite / CI redirect the audit stream to a
    temp directory. Without it, test runs append to ~/.gemini/logs.
    """
    override = os.environ.get("GRAVITYGUARD_LOG_DIR", "").strip()
    if override:
        return os.path.expanduser(override)
    return os.path.expanduser(r"~/.gemini/logs")


def _generate_event_id() -> str:
    """Generates a unique, timestamp-prefixed event ID for causal chaining."""
    now_ms = int(time.time() * 1000)
    suffix = uuid.uuid4().hex[:8]
    return f"evt_{now_ms}_{suffix}"


def log_event(
    action: str,
    status: str,
    target_file: str,
    reason: str,
    rule_id: str = "SRP",
    outcome_override: Optional[str] = None,
    conversation_id: Optional[str] = None
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
    now_dt = datetime.now()
    now_iso = now_dt.isoformat()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    conv_id = (
        conversation_id
        or os.environ.get("ANTIGRAVITY_CONVERSATION_ID")
        or os.environ.get("CONVERSATION_ID")
        or "default"
    )
    norm_target = target_file.replace("\\\\", "/").replace("\\", "/").lower() if target_file else ""
    target_prefix = f"{conv_id}::{norm_target}::"
    tracking_key = f"{conv_id}::{norm_target}::{rule_id}" if norm_target else ""

    try:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "srp_guardian_live.json")
        permanent_log_path = os.path.join(log_dir, "gravityguard_permanent_audit.jsonl")
        audit_lock_path = Path(log_dir) / ".audit.lock"

        current_data: Dict[str, Any] = {
            "activeGuard": "GravityGuard",
            "status": "ONLINE",
            "events": [],
            "activeViolations": {},
            "effectiveness": {
                "totalBlocked": 0,
                "totalRecovered": 0,
                "recoveryRate": 100.0,
                "ruleStats": {}
            }
        }

        outcome = outcome_override
        parent_violation_id: Optional[str] = None
        resolved_rule_id: Optional[str] = None
        recovery_attempts: Optional[int] = None
        resolution_ms: Optional[float] = None

        # Lock acquisition for concurrency safety across hook processes
        lock = StateLock(audit_lock_path, timeout=2.0)
        lock_acquired = False
        try:
            lock.acquire()
            lock_acquired = True
        except Exception as lock_err:
            sys.stderr.write(f"[GravityGuard Audit Lock Warning] {lock_err}\n")

        try:
            if os.path.exists(log_path):
                try:
                    with open(log_path, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                        if isinstance(loaded, dict):
                            current_data = loaded
                except (json.JSONDecodeError, OSError) as read_err:
                    current_data = {
                        "activeGuard": "GravityGuard",
                        "status": "ONLINE",
                        "events": [],
                        "activeViolations": {},
                        "effectiveness": {
                            "totalBlocked": 0,
                            "totalRecovered": 0,
                            "recoveryRate": 100.0,
                            "ruleStats": {}
                        }
                    }

            active_violations = current_data.setdefault("activeViolations", {})
            if not isinstance(active_violations, dict):
                active_violations = {}
                current_data["activeViolations"] = active_violations

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
                    matching_keys = [k for k in list(active_violations.keys()) if k.startswith(target_prefix)] if norm_target else []
                    if matching_keys:
                        prev = active_violations.pop(matching_keys[0])
                        outcome = "RECOVERED"
                        parent_violation_id = prev.get("eventId")
                        resolved_rule_id = prev.get("ruleId")
                        recovery_attempts = prev.get("attempts", 1)
                        try:
                            first_dt = datetime.fromisoformat(prev.get("firstTimestamp", now_iso))
                            resolution_ms = round((now_dt - first_dt).total_seconds() * 1000, 1)
                        except Exception as dt_err:
                            resolution_ms = None
                        # Remove any other open violations for this target
                        for other_k in matching_keys[1:]:
                            active_violations.pop(other_k, None)
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

            event = {
                "eventId": event_id,
                "timestamp": now_str,
                "action": action,
                "status": status,
                "ruleId": rule_id,
                "resolvedRuleId": resolved_rule_id,
                "target": target_file,
                "reason": reason,
                "outcome": outcome,
                "parentViolationId": parent_violation_id,
                "recoveryAttempts": recovery_attempts,
                "resolutionMs": resolution_ms
            }

            events = current_data.get("events", [])
            if not isinstance(events, list):
                events = []
            events.insert(0, event)
            current_data["events"] = events[:50]  # keep last 50
            current_data["lastCheck"] = now_str

            # Update live effectiveness summary & rule statistics
            all_ev = current_data.get("events", [])
            blocked_ev = [e for e in all_ev if e.get("status") == "BLOCKED" and e.get("outcome") != "REPEATED_VIOLATION"]
            recovered_ev = [e for e in all_ev if e.get("outcome") == "RECOVERED"]
            b_count = len(blocked_ev)
            r_count = len(recovered_ev)
            rec_rate = round((r_count / b_count * 100), 1) if b_count > 0 else 100.0

            rule_stats: Dict[str, Dict[str, Any]] = {}
            for b in blocked_ev:
                r_id = b.get("ruleId", "UNKNOWN")
                st = rule_stats.setdefault(r_id, {"blocked": 0, "recovered": 0, "recoveryRate": 0.0, "attempts": []})
                st["blocked"] += 1
            for r in recovered_ev:
                res_id = r.get("resolvedRuleId") or r.get("ruleId", "UNKNOWN")
                if res_id not in ("PASS", "CLEAN"):
                    st = rule_stats.setdefault(res_id, {"blocked": 0, "recovered": 0, "recoveryRate": 0.0, "attempts": []})
                    st["recovered"] += 1
                    att = r.get("recoveryAttempts")
                    if isinstance(att, (int, float)):
                        st["attempts"].append(att)

            for r_id, st in rule_stats.items():
                st["recoveryRate"] = round((st["recovered"] / st["blocked"] * 100), 1) if st["blocked"] > 0 else 0.0
                if st["attempts"]:
                    st["medianAttempts"] = sorted(st["attempts"])[len(st["attempts"]) // 2]
                else:
                    st["medianAttempts"] = 1.0

            current_data["effectiveness"] = {
                "totalBlocked": b_count,
                "totalRecovered": r_count,
                "recoveryRate": rec_rate,
                "ruleStats": rule_stats
            }

            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(current_data, f, indent=2, ensure_ascii=False)

            # Permanent Audit & Telemetry Archive (JSONL for product R&D and effectiveness analysis)
            proj_name, proj_root = extract_project_info(target_file)
            ext = os.path.splitext(target_file)[1].lower() if target_file else ""
            model_id = os.environ.get("ANTIGRAVITY_MODEL", os.environ.get("MODEL_NAME", "unknown"))

            telemetry_event = {
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
                "model": model_id,
                "reason": reason,
                "outcome": outcome,
                "parentViolationId": parent_violation_id,
                "recoveryAttempts": recovery_attempts,
                "resolutionMs": resolution_ms
            }

            with open(permanent_log_path, "a", encoding="utf-8") as af:
                af.write(json.dumps(telemetry_event, ensure_ascii=False) + "\n")
        finally:
            if lock_acquired:
                try:
                    lock.release()
                except Exception as rel_err:
                    sys.stderr.write(f"[GravityGuard Audit Lock Release Warning] {rel_err}\n")
    except Exception as exc:
        sys.stderr.write(f"[GravityGuard Event Error] {exc}\n")

    return event_id

