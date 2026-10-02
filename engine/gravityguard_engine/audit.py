#!/usr/bin/env python3
"""
GravityGuard Engine — Audit & Telemetry Subsystem.
Manages live security event monitor (srp_guardian_live.json)
and permanent append-only audit stream (gravityguard_permanent_audit.jsonl).
Supports causal event chaining (parentViolationId, outcome, recoveryAttempts, resolutionMs).
Zero external dependencies.
"""
import json
import os
import sys
import time
import uuid
from datetime import datetime
from typing import Optional, Dict, Any

from .project_context import extract_project_info


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
    outcome_override: Optional[str] = None
) -> str:
    """
    Logs an event to the live monitor stream (last 50 events)
    and the permanent append-only audit log for telemetry analysis.
    Implements causal outcome chaining (BLOCKED -> RECOVERED / REPEATED_VIOLATION).
    Returns the unique eventId.
    """
    event_id = _generate_event_id()
    log_dir = _resolve_log_dir()
    now_dt = datetime.now()
    now_iso = now_dt.isoformat()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    conv_id = os.environ.get("ANTIGRAVITY_CONVERSATION_ID", os.environ.get("CONVERSATION_ID", "default"))
    norm_target = target_file.replace("\\\\", "/").replace("\\", "/").lower() if target_file else ""
    tracking_key = f"{conv_id}::{norm_target}" if norm_target else ""

    try:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "srp_guardian_live.json")

        current_data: Dict[str, Any] = {
            "activeGuard": "GravityGuard",
            "status": "ONLINE",
            "events": [],
            "activeViolations": {},
            "effectiveness": {"totalBlocked": 0, "totalRecovered": 0, "recoveryRate": 100.0}
        }

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
                    "effectiveness": {"totalBlocked": 0, "totalRecovered": 0, "recoveryRate": 100.0}
                }

        active_violations = current_data.setdefault("activeViolations", {})
        if not isinstance(active_violations, dict):
            active_violations = {}
            current_data["activeViolations"] = active_violations

        outcome = outcome_override
        parent_violation_id: Optional[str] = None
        recovery_attempts: Optional[int] = None
        resolution_ms: Optional[float] = None

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
                if tracking_key and tracking_key in active_violations:
                    prev = active_violations.pop(tracking_key)
                    outcome = "RECOVERED"
                    parent_violation_id = prev.get("eventId")
                    recovery_attempts = prev.get("attempts", 1)
                    try:
                        first_dt = datetime.fromisoformat(prev.get("firstTimestamp", now_iso))
                        resolution_ms = round((now_dt - first_dt).total_seconds() * 1000, 1)
                    except Exception as dt_err:
                        resolution_ms = None
                else:
                    outcome = "CLEAN"
            elif status == "SHADOW_TRIGGER":
                outcome = "SHADOW_OBSERVED"
            elif status == "WARNING":
                outcome = "WARNING"
                if tracking_key and tracking_key in active_violations:
                    parent_violation_id = active_violations[tracking_key].get("eventId")
            else:
                outcome = status

        event = {
            "eventId": event_id,
            "timestamp": now_str,
            "action": action,
            "status": status,
            "ruleId": rule_id,
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

        # Update live effectiveness summary
        all_ev = current_data.get("events", [])
        blocked_ev = [e for e in all_ev if e.get("status") == "BLOCKED" and e.get("outcome") != "REPEATED_VIOLATION"]
        recovered_ev = [e for e in all_ev if e.get("outcome") == "RECOVERED"]
        b_count = len(blocked_ev)
        r_count = len(recovered_ev)
        rec_rate = round((r_count / b_count * 100), 1) if b_count > 0 else 100.0

        current_data["effectiveness"] = {
            "totalBlocked": b_count,
            "totalRecovered": r_count,
            "recoveryRate": rec_rate
        }

        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(current_data, f, indent=2, ensure_ascii=False)

        # Permanent Audit & Telemetry Archive (JSONL for product R&D and effectiveness analysis)
        permanent_log_path = os.path.join(log_dir, "gravityguard_permanent_audit.jsonl")

        proj_name, proj_root = extract_project_info(target_file)
        ext = os.path.splitext(target_file)[1].lower() if target_file else ""
        model_id = os.environ.get("ANTIGRAVITY_MODEL", os.environ.get("MODEL_NAME", "unknown"))

        telemetry_event = {
            "eventId": event_id,
            "timestamp": now_iso,
            "action": action,
            "status": status,
            "ruleId": rule_id,
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

        try:
            with open(permanent_log_path, "a", encoding="utf-8") as af:
                af.write(json.dumps(telemetry_event, ensure_ascii=False) + "\n")
        except OSError as log_err:
            sys.stderr.write(f"[GravityGuard Archive Error] {log_err}\n")
    except Exception as exc:
        sys.stderr.write(f"[GravityGuard Event Error] {exc}\n")

    return event_id

