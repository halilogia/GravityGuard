#!/usr/bin/env python3
"""
GravityGuard Engine — Audit & Telemetry Subsystem.
Manages live security event monitor (srp_guardian_live.json)
and permanent append-only audit stream (gravityguard_permanent_audit.jsonl).
Zero external dependencies.
"""
import json
import os
import sys
from datetime import datetime
from typing import Optional

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


def log_event(
    action: str,
    status: str,
    target_file: str,
    reason: str,
    rule_id: str = "SRP"
) -> None:
    """
    Logs an event to the live monitor stream (last 50 events)
    and the permanent append-only audit log for telemetry analysis.
    """
    log_dir = _resolve_log_dir()
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "srp_guardian_live.json")

        current_data = {"activeGuard": "GravityGuard", "status": "ONLINE", "events": []}
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        current_data = loaded
            except (json.JSONDecodeError, OSError):
                current_data = {"activeGuard": "GravityGuard", "status": "ONLINE", "events": []}

        event = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "status": status,
            "ruleId": rule_id,
            "target": target_file,
            "reason": reason
        }

        events = current_data.get("events", [])
        if not isinstance(events, list):
            events = []
        events.insert(0, event)
        current_data["events"] = events[:50]  # keep last 50
        current_data["lastCheck"] = event["timestamp"]

        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(current_data, f, indent=2, ensure_ascii=False)

        # Permanent Audit & Telemetry Archive (JSONL for product R&D and failure analysis)
        permanent_log_path = os.path.join(log_dir, "gravityguard_permanent_audit.jsonl")

        proj_name, proj_root = extract_project_info(target_file)
        ext = os.path.splitext(target_file)[1].lower() if target_file else ""
        conv_id = os.environ.get("ANTIGRAVITY_CONVERSATION_ID", os.environ.get("CONVERSATION_ID", ""))
        model_id = os.environ.get("ANTIGRAVITY_MODEL", os.environ.get("MODEL_NAME", "unknown"))

        telemetry_event = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "status": status,
            "ruleId": rule_id,
            "target": target_file,
            "project": proj_name,
            "projectRoot": proj_root,
            "fileExt": ext,
            "conversationId": conv_id,
            "model": model_id,
            "reason": reason
        }

        try:
            with open(permanent_log_path, "a", encoding="utf-8") as af:
                af.write(json.dumps(telemetry_event, ensure_ascii=False) + "\n")
        except OSError as log_err:
            sys.stderr.write(f"[GravityGuard Archive Error] {log_err}\n")
    except Exception as exc:
        sys.stderr.write(f"[GravityGuard Event Error] {exc}\n")
