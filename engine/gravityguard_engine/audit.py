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
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Set

from .project_context import extract_project_info
from .state_lock import StateLock


# Centralized secret & sensitive credential redaction patterns
_SECRET_PATTERNS = [
    # Anthropic API keys (sk-ant-...) - more specific, must precede generic sk-
    (re.compile(r"\b(sk-ant-[a-zA-Z0-9_\-]{20,})\b"), r"sk-ant-***[REDACTED]***"),
    # OpenAI & generic sk- API keys (sk-...)
    (re.compile(r"\b(sk-[a-zA-Z0-9_\-]{20,})\b"), r"sk-***[REDACTED]***"),
    # GitHub Personal Access Tokens and OAuth tokens
    (re.compile(r"\b((?:ghp|gho|ghu|ghs|ghr|github_pat)_[a-zA-Z0-9_]{20,})\b"), r"ghp_***[REDACTED]***"),
    # AWS Access Key IDs
    (re.compile(r"\b((?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16})\b"), r"AKIA***[REDACTED]***"),
    # JWT tokens (must precede Bearer to preserve specific JWT token identification)
    (re.compile(r"\b(eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,})\b"), r"[REDACTED_JWT]"),
    # Bearer tokens
    (re.compile(r"(?i)\b(bearer\s+)([a-zA-Z0-9_\-\.]{20,})\b"), r"\1***[REDACTED]***"),
    # URL / URI basic auth credentials (user:password@)
    (re.compile(r"://([^:\s]+):([^@\s]+)@"), r"://\1:***@"),
    # Quoted string assignments in JSON or code: "api_key": "..." or 'api_key': '...'
    (re.compile(r"""(?i)(["']?(?:api_?key|access_?token|auth_?token|secret_?key|password|passwd|private_?key|credential|client_?secret)["']?\s*[:=]\s*")([^"\r\n]{4,})(")"""), r"\1***[REDACTED]***\3"),
    (re.compile(r"""(?i)(["']?(?:api_?key|access_?token|auth_?token|secret_?key|password|passwd|private_?key|credential|client_?secret)["']?\s*[:=]\s*')([^'\r\n]{4,})(')"""), r"\1***[REDACTED]***\3"),
    # Unquoted key-value assignments
    (re.compile(r"""(?i)(["']?(?:api_?key|access_?token|auth_?token|secret_?key|password|passwd|private_?key|credential|client_?secret)["']?\s*[:=]\s*)([^\s"',\}\]]{6,})"""), r"\1***[REDACTED]***"),
    # RSA / OpenSSH / EC Private Keys
    (re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+ PRIVATE KEY-----"), r"[REDACTED_PRIVATE_KEY]"),
]

_SENSITIVE_DICT_KEYS = {
    "api_key", "apikey", "secret", "secret_key", "password", "passwd",
    "token", "access_token", "auth_token", "private_key", "credential",
    "credentials", "authorization", "client_secret"
}


def redact_secrets(val: str) -> str:
    """Scans and scrubs sensitive API keys, tokens, and credentials from a text string."""
    if not isinstance(val, str) or not val:
        return val
    redacted = val
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_record(record: Any) -> Any:
    """Recursively redacts secrets across all fields in a dictionary, list, or primitive."""
    if isinstance(record, dict):
        scrubbed = {}
        for k, v in record.items():
            k_norm = str(k).lower().strip().replace("-", "_")
            if k_norm in _SENSITIVE_DICT_KEYS:
                scrubbed[k] = "[REDACTED_CREDENTIAL]"
            else:
                scrubbed[k] = redact_record(v)
        return scrubbed
    elif isinstance(record, list):
        return [redact_record(item) for item in record]
    elif isinstance(record, str):
        return redact_secrets(record)
    return record


def _prepare_fallback_spool(log_dir: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Atomically renames the fallback spool and recovers orphaned processing files.
    Two-phase protocol: files are only deleted after verified append to canonical journal.
    """
    processing_files: List[str] = []
    spool_events: List[Dict[str, Any]] = []

    fallback_spool_path = os.path.join(log_dir, "gravityguard_audit_fallback.jsonl")

    # 1. Recover any orphaned .processing files from previous crashes
    try:
        if os.path.isdir(log_dir):
            for fname in os.listdir(log_dir):
                if fname.startswith("gravityguard_audit_fallback.processing."):
                    processing_files.append(os.path.join(log_dir, fname))
                elif fname.startswith("gravityguard_audit_spool.") and fname.endswith(".jsonl"):
                    sp_full = os.path.join(log_dir, fname)
                    p_id = f"gravityguard_audit_fallback.processing.{os.getpid()}_{uuid.uuid4().hex[:8]}"
                    p_path = os.path.join(log_dir, p_id)
                    try:
                        os.replace(sp_full, p_path)
                        processing_files.append(p_path)
                    except Exception as ren_sp_err:
                        sys.stderr.write(f"[GravityGuard Spool Multi-Process Recovery Notice: {fname}] {ren_sp_err}\n")
    except Exception as scan_err:
        sys.stderr.write(f"[GravityGuard Spool Recovery Scan Notice] {scan_err}\n")

    # 2. Atomically rename active fallback spool if it exists and has content
    if os.path.exists(fallback_spool_path):
        try:
            if os.path.getsize(fallback_spool_path) > 0:
                p_id = f"gravityguard_audit_fallback.processing.{os.getpid()}_{uuid.uuid4().hex[:8]}"
                p_path = os.path.join(log_dir, p_id)
                os.replace(fallback_spool_path, p_path)
                processing_files.append(p_path)
            else:
                try:
                    os.remove(fallback_spool_path)
                except OSError as empty_rm_err:
                    sys.stderr.write(f"[GravityGuard Spool Empty Clean Notice] {empty_rm_err}\n")
        except Exception as rename_err:
            sys.stderr.write(f"[GravityGuard Spool Rename Warning] {rename_err}\n")

    # 3. Read events from all processing files (do NOT delete yet!)
    for p_path in processing_files:
        try:
            with open(p_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped:
                        try:
                            ev = json.loads(stripped)
                            if isinstance(ev, dict):
                                spool_events.append(ev)
                        except Exception as json_parse_err:
                            sys.stderr.write(f"[GravityGuard Spool Parse Warning: {p_path}] {json_parse_err}\n")
        except Exception as read_err:
            sys.stderr.write(f"[GravityGuard Spool Read Error: {p_path}] {read_err}\n")

    return processing_files, spool_events


def _commit_fallback_spool(processing_files: List[str]) -> None:
    """
    Second phase of spool protocol: deletes processing files ONLY after
    they have been successfully written and flushed to the canonical journal.
    """
    for p_path in processing_files:
        try:
            if os.path.exists(p_path):
                os.remove(p_path)
        except Exception as rm_err:
            sys.stderr.write(f"[GravityGuard Spool Commit Warning: {p_path}] {rm_err}\n")


def _find_committed_event_ids(permanent_log_path: str, candidate_ids: Set[str]) -> Set[str]:
    """
    Checks the canonical permanent audit journal directly to discover which candidate
    eventIds are already persistently committed. Guarantees true idempotency independent
    of the sliding 50-event live memory window.
    """
    committed: Set[str] = set()
    if not candidate_ids or not os.path.exists(permanent_log_path):
        return committed

    try:
        with open(permanent_log_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                for cid in candidate_ids:
                    if cid not in committed and cid in line_str:
                        try:
                            rec = json.loads(line_str)
                            if isinstance(rec, dict) and rec.get("eventId") == cid:
                                committed.add(cid)
                        except (json.JSONDecodeError, ValueError) as parse_err:
                            sys.stderr.write(f"[GravityGuard Idempotency Parse Warning] {parse_err}\n")
                if len(committed) == len(candidate_ids):
                    break
    except Exception as err:
        sys.stderr.write(f"[GravityGuard Idempotency Scan Warning] {err}\n")

    return committed




def _resolve_log_dir() -> str:
    """
    Resolves the audit-log directory.
    GRAVITYGUARD_LOG_DIR lets the test suite / CI redirect the audit stream to a
    temp directory. Without it, test runs append to ~/.gemini/logs.
    GRAVITYGUARD_AUDIT_DIR relocates the audit stream only (the Claude Code adapter sets it to a project-local folder);
    GRAVITYGUARD_LOG_DIR wins when both are set.
    """
    for var in ("GRAVITYGUARD_LOG_DIR", "GRAVITYGUARD_AUDIT_DIR"):
        override = os.environ.get(var, "").strip()
        if override:
            return os.path.expanduser(override)
    return os.path.expanduser(r"~/.gemini/logs")


def _generate_event_id() -> str:
    """Generates a unique, timestamp-prefixed event ID for causal chaining."""
    now_ms = int(time.time() * 1000)
    suffix = uuid.uuid4().hex[:8]
    return f"evt_{now_ms}_{suffix}"


def _is_durable_mode() -> bool:
    """Checks whether hardware fsync durability mode is requested."""
    return os.environ.get("GRAVITYGUARD_DURABILITY", "normal").strip().lower() == "durable"


def _read_last_journal_entry(permanent_log_path: str) -> Optional[Dict[str, Any]]:
    """Reads the last valid JSON entry from the permanent audit log."""
    if not os.path.exists(permanent_log_path):
        return None
    try:
        with open(permanent_log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size == 0:
                return None
            chunk_size = min(size, 8192)
            f.seek(size - chunk_size)
            chunk = f.read(chunk_size).decode("utf-8", errors="ignore")
            lines = [l.strip() for l in chunk.strip().splitlines() if l.strip()]
            for line in reversed(lines):
                try:
                    return json.loads(line)
                except Exception:
                    continue
    except Exception as err:
        sys.stderr.write(f"[GravityGuard Journal Read Error] {err}\n")
    return None


def _repair_journal_tail(permanent_log_path: str) -> None:
    """
    Repairs a torn or partial tail in the permanent audit journal (WAL).
    If a process crashes or loses power mid-write, the last line may be truncated
    or unparseable JSON. Truncates the file back to the last valid newline boundary.
    """
    if not os.path.exists(permanent_log_path):
        return
    try:
        with open(permanent_log_path, "rb+") as f:
            f.seek(0, os.SEEK_END)
            total_size = f.tell()
            if total_size == 0:
                return

            chunk_size = min(total_size, 16384)
            f.seek(total_size - chunk_size)
            chunk = f.read(chunk_size)

            lines = chunk.splitlines(keepends=True)
            if not lines:
                return

            last_line = lines[-1]
            stripped = last_line.strip()
            if stripped:
                try:
                    json.loads(stripped.decode("utf-8"))
                    # Complete valid JSON! If trailing newline delimiter was omitted, append it
                    if not (last_line.endswith(b"\n") or last_line.endswith(b"\r")):
                        f.seek(0, os.SEEK_END)
                        f.write(b"\n")
                        f.flush()
                    return
                except Exception as parse_err:
                    # Broken / partial JSON: fall through to truncate
                    sys.stderr.write(f"[GravityGuard WAL Tail Notice] Incomplete trailing JSON: {parse_err}\n")
            elif last_line.endswith(b"\n") or last_line.endswith(b"\r"):
                # Clean trailing whitespace/newline
                return

            sys.stderr.write("[GravityGuard WAL Repair] Torn journal tail detected; repairing to last valid newline\n")

            valid_offset = 0
            found_valid = False
            curr_offset = total_size - len(last_line)
            for prev_line in reversed(lines[:-1]):
                p_strip = prev_line.strip()
                if not p_strip:
                    curr_offset -= len(prev_line)
                    continue
                try:
                    json.loads(p_strip.decode("utf-8"))
                    found_valid = True
                    valid_offset = curr_offset
                    break
                except Exception:
                    curr_offset -= len(prev_line)

            if not found_valid and chunk_size < total_size:
                f.seek(0)
                all_data = f.read()
                all_lines = all_data.splitlines(keepends=True)
                accum = 0
                for line in all_lines:
                    l_str = line.strip()
                    if l_str:
                        try:
                            json.loads(l_str.decode("utf-8"))
                            accum += len(line)
                            valid_offset = accum
                        except Exception:
                            break
                    else:
                        accum += len(line)
                        valid_offset = accum
            elif not found_valid:
                valid_offset = 0

            f.seek(valid_offset)
            f.truncate()
            f.flush()
    except Exception as err:
        sys.stderr.write(f"[GravityGuard WAL Tail Repair Error] {err}\n")


def _get_journal_last_seq(permanent_log_path: str) -> int:
    """
    Returns the highest auditSeq in the permanent audit journal.
    If the journal has entries without explicit auditSeq (legacy logs),
    counts non-empty lines to establish the initial monotonic sequence.
    """
    if not os.path.exists(permanent_log_path):
        return 0
    last_entry = _read_last_journal_entry(permanent_log_path)
    if last_entry and "auditSeq" in last_entry and isinstance(last_entry["auditSeq"], int):
        return last_entry["auditSeq"]
    count = 0
    try:
        with open(permanent_log_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.strip():
                    count += 1
    except Exception as err:
        sys.stderr.write(f"[GravityGuard Journal Count Error] {err}\n")
    return count


def _apply_event_to_live_state(state: Dict[str, Any], ev: Dict[str, Any]) -> None:
    """
    Applies a single permanent audit record to a live monitor state projection.
    Updates cumulative effectiveness counters, per-rule stats, and active violations.
    """
    eff = state.setdefault("effectiveness", {})
    if not isinstance(eff, dict):
        eff = {
            "totalBlocked": 0,
            "totalRecovered": 0,
            "recoveryRate": 100.0,
            "ruleStats": {}
        }
        state["effectiveness"] = eff
    eff.setdefault("totalBlocked", 0)
    eff.setdefault("totalRecovered", 0)
    eff.setdefault("recoveryRate", 100.0)
    rule_stats = eff.setdefault("ruleStats", {})
    if not isinstance(rule_stats, dict):
        rule_stats = {}
        eff["ruleStats"] = rule_stats

    active_violations = state.setdefault("activeViolations", {})
    if not isinstance(active_violations, dict):
        active_violations = {}
        state["activeViolations"] = active_violations

    st = ev.get("status")
    out = ev.get("outcome")
    r_id = ev.get("ruleId") or "UNKNOWN"
    res_id = ev.get("resolvedRuleId") or r_id
    c_id = ev.get("conversationId", "default")
    target = (ev.get("target") or "").replace("\\\\", "/").replace("\\", "/").lower()
    t_key = f"{c_id}::{target}::{r_id}" if target else ""

    if st == "BLOCKED" and out != "REPEATED_VIOLATION":
        eff["totalBlocked"] = eff.get("totalBlocked", 0) + 1
        rst = rule_stats.setdefault(r_id, {"blocked": 0, "recovered": 0, "recoveryRate": 0.0, "attempts": []})
        rst["blocked"] = rst.get("blocked", 0) + 1
        if t_key:
            active_violations[t_key] = {
                "eventId": ev.get("eventId"),
                "ruleId": r_id,
                "firstTimestamp": ev.get("timestamp"),
                "lastTimestamp": ev.get("timestamp"),
                "attempts": 1,
                "status": "BLOCKED"
            }
    elif out == "REPEATED_VIOLATION":
        if t_key and t_key in active_violations:
            active_violations[t_key]["attempts"] = ev.get("recoveryAttempts", active_violations[t_key].get("attempts", 1) + 1)
            active_violations[t_key]["lastTimestamp"] = ev.get("timestamp")
    elif out == "RECOVERED":
        eff["totalRecovered"] = eff.get("totalRecovered", 0) + 1
        rst = rule_stats.setdefault(res_id, {"blocked": 0, "recovered": 0, "recoveryRate": 0.0, "attempts": []})
        rst["recovered"] = rst.get("recovered", 0) + 1
        att = ev.get("recoveryAttempts")
        if isinstance(att, (int, float)):
            rst.setdefault("attempts", []).append(att)
        # Clear matching active violation
        matching = [k for k in list(active_violations.keys()) if k.startswith(f"{c_id}::{target}::")]
        for mk in matching:
            if active_violations[mk].get("ruleId") == res_id:
                active_violations.pop(mk, None)
                break

    seq = ev.get("auditSeq")
    if isinstance(seq, int) and seq > state.get("lastAuditSeq", 0):
        state["lastAuditSeq"] = seq


def _recompute_effectiveness_rates(state: Dict[str, Any]) -> None:
    """Recomputes recovery rates and median attempts with invariant checking."""
    eff = state.get("effectiveness", {})
    tot_b = eff.get("totalBlocked", 0)
    tot_r = eff.get("totalRecovered", 0)
    if tot_r > tot_b:
        sys.stderr.write(
            f"[GravityGuard Invariant Violation] recovered ({tot_r}) > blocked ({tot_b}) - telemetry inconsistency detected\n"
        )
    eff["recoveryRate"] = min(100.0, round((tot_r / tot_b * 100), 1)) if tot_b > 0 else 100.0

    rule_stats = eff.get("ruleStats", {})
    for r_id, rst in rule_stats.items():
        b = rst.get("blocked", 0)
        r = rst.get("recovered", 0)
        if r > b:
            sys.stderr.write(
                f"[GravityGuard Invariant Violation] rule {r_id}: recovered ({r}) > blocked ({b})\n"
            )
        rst["recoveryRate"] = min(100.0, round((r / b * 100), 1)) if b > 0 else 100.0
        atts = rst.get("attempts", [])
        rst["medianAttempts"] = sorted(atts)[len(atts) // 2] if atts else 1.0


def _rebuild_live_state_from_permanent_audit(permanent_log_path: str) -> Dict[str, Any]:
    """
    Rebuilds live monitor state from the permanent audit log (JSONL)
    if srp_guardian_live.json is missing or corrupted.
    Treats the permanent append-only audit stream as the durable source of truth.
    """
    state: Dict[str, Any] = {
        "activeGuard": "GravityGuard",
        "status": "ONLINE",
        "events": [],
        "activeViolations": {},
        "effectiveness": {
            "totalBlocked": 0,
            "totalRecovered": 0,
            "recoveryRate": 100.0,
            "ruleStats": {}
        },
        "lastAuditSeq": 0
    }
    if not os.path.exists(permanent_log_path):
        return state

    raw_events: list = []
    try:
        with open(permanent_log_path, "r", encoding="utf-8", errors="ignore") as f:
            for idx, line in enumerate(f, 1):
                line = line.strip()
                if line:
                    try:
                        ev = json.loads(line)
                        if "auditSeq" not in ev or not isinstance(ev["auditSeq"], int):
                            ev["auditSeq"] = idx
                        raw_events.append(ev)
                    except Exception:
                        continue
    except Exception as read_err:
        sys.stderr.write(f"[GravityGuard Permanent Audit Read Error] {read_err}\n")
        return state

    for ev in raw_events:
        _apply_event_to_live_state(state, ev)

    _recompute_effectiveness_rates(state)

    recent_raw = list(raw_events[-50:])
    recent_raw.reverse()
    recent_live = []
    for ev in recent_raw:
        recent_live.append({
            "eventId": ev.get("eventId"),
            "auditSeq": ev.get("auditSeq"),
            "timestamp": ev.get("timestamp"),
            "action": ev.get("action"),
            "status": ev.get("status"),
            "ruleId": ev.get("ruleId"),
            "resolvedRuleId": ev.get("resolvedRuleId"),
            "target": ev.get("target"),
            "reason": ev.get("reason"),
            "outcome": ev.get("outcome"),
            "parentViolationId": ev.get("parentViolationId"),
            "recoveryAttempts": ev.get("recoveryAttempts"),
            "resolutionMs": ev.get("resolutionMs")
        })
    state["events"] = recent_live
    if raw_events:
        state["lastAuditSeq"] = raw_events[-1].get("auditSeq", len(raw_events))

    return state


def _replay_missing_journal_events(
    state: Dict[str, Any],
    permanent_log_path: str,
    from_seq: int
) -> int:
    """
    Replays events from the permanent audit journal with auditSeq > from_seq
    onto the live state projection. Resolves divergence caused by a process crash
    between journal append and live JSON atomic replace.
    Returns the latest auditSeq after replay.
    """
    if not os.path.exists(permanent_log_path):
        return from_seq

    missing_events: list = []
    try:
        with open(permanent_log_path, "r", encoding="utf-8", errors="ignore") as f:
            for idx, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    seq = ev.get("auditSeq", idx)
                    if isinstance(seq, int) and seq > from_seq:
                        ev["auditSeq"] = seq
                        missing_events.append(ev)
                except Exception:
                    continue
    except Exception as err:
        sys.stderr.write(f"[GravityGuard Replay Warning] Could not read permanent log: {err}\n")
        return from_seq

    if not missing_events:
        return from_seq

    sys.stderr.write(
        f"[GravityGuard Projection Replay] Replaying {len(missing_events)} journal events into live state (fromSeq: {from_seq})\n"
    )

    events_list = state.setdefault("events", [])
    if not isinstance(events_list, list):
        events_list = []
        state["events"] = events_list

    for ev in missing_events:
        _apply_event_to_live_state(state, ev)
        live_ev = {
            "eventId": ev.get("eventId"),
            "auditSeq": ev.get("auditSeq"),
            "timestamp": ev.get("timestamp"),
            "action": ev.get("action"),
            "status": ev.get("status"),
            "ruleId": ev.get("ruleId"),
            "resolvedRuleId": ev.get("resolvedRuleId"),
            "target": ev.get("target"),
            "reason": ev.get("reason"),
            "outcome": ev.get("outcome"),
            "parentViolationId": ev.get("parentViolationId"),
            "recoveryAttempts": ev.get("recoveryAttempts"),
            "resolutionMs": ev.get("resolutionMs")
        }
        events_list.insert(0, live_ev)

    state["events"] = events_list[:50]
    _recompute_effectiveness_rates(state)

    latest_seq = missing_events[-1].get("auditSeq", from_seq)
    state["lastAuditSeq"] = latest_seq
    return latest_seq


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
        fallback_spool_path = os.path.join(log_dir, "gravityguard_audit_fallback.jsonl")
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
            lock_acquired = lock.acquire()
        except Exception as lock_err:
            sys.stderr.write(f"[GravityGuard Audit Lock Warning] {lock_err}\n")

        if not lock_acquired:
            sys.stderr.write(f"[GravityGuard Audit Lock Timeout] Could not acquire audit lock for {log_path}; buffering event in fallback spool to prevent data loss\n")
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
                    "model": model_id,
                    "reason": reason,
                    "outcome": outcome or status,
                    "parentViolationId": None,
                    "recoveryAttempts": 1,
                    "resolutionMs": None
                }
                spool_event = redact_record(spool_event)
                with open(fallback_spool_path, "a", encoding="utf-8") as sf:
                    sf.write(json.dumps(spool_event, ensure_ascii=False) + "\n")
                    sf.flush()
            except Exception as spool_err:
                sys.stderr.write(f"[GravityGuard Audit Spool Error] {spool_err}\n")
            return event_id

        try:
            # Repair torn tail if prior process crashed during WAL write
            _repair_journal_tail(permanent_log_path)
            # Two-phase crash-safe fallback spool recovery
            spool_processing_files, spooled_events = _prepare_fallback_spool(log_dir)

            current_data = None
            if os.path.exists(log_path):
                try:
                    with open(log_path, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                        if isinstance(loaded, dict):
                            current_data = loaded
                except (json.JSONDecodeError, OSError) as read_err:
                    sys.stderr.write(f"[GravityGuard State Corrupt Warning] {read_err}; attempting rebuild from permanent log\n")
                    current_data = None

            if current_data is None:
                current_data = _rebuild_live_state_from_permanent_audit(permanent_log_path)
            else:
                live_seq = current_data.get("lastAuditSeq")
                journal_last_seq = _get_journal_last_seq(permanent_log_path)
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
                    matching_keys = [k for k in list(active_violations.keys()) if k.startswith(target_prefix)] if norm_target else []
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
                                first_dt = datetime.fromisoformat(primary.get("firstTimestamp", now_iso))
                                resolution_ms = round((now_dt - first_dt).total_seconds() * 1000, 1)
                            except Exception:
                                resolution_ms = None

                            eff["totalRecovered"] = eff.get("totalRecovered", 0) + 1
                            p_rule = resolved_rule_id or "UNKNOWN"
                            p_st = rule_stats.setdefault(p_rule, {"blocked": 0, "recovered": 0, "recoveryRate": 0.0, "attempts": []})
                            p_st["recovered"] = p_st.get("recovered", 0) + 1
                            if recovery_attempts is not None:
                                p_st.setdefault("attempts", []).append(recovery_attempts)

                            # Create linked recovery events and update ruleStats for each additional resolved rule
                            for additional in resolved_items[1:]:
                                add_r_id = additional.get("ruleId")
                                add_e_id = _generate_event_id()
                                add_attempts = additional.get("attempts", 1)
                                try:
                                    add_first_dt = datetime.fromisoformat(additional.get("firstTimestamp", now_iso))
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

            # Monotonic sequence numbering for Write-Ahead Journaling
            journal_seq = current_data.get("lastAuditSeq", 0)
            is_durable = _is_durable_mode()

            # Replay any fallback spool events that were buffered during previous lock timeouts
            spool_writes_succeeded = True
            candidate_spool_ids = {sp.get("eventId") for sp in spooled_events if sp.get("eventId")}
            committed_spool_ids = _find_committed_event_ids(permanent_log_path, candidate_spool_ids)

            for sp_ev in spooled_events:
                sp_eid = sp_ev.get("eventId")
                if sp_eid and sp_eid in committed_spool_ids:
                    # Idempotency guard: event was already committed to canonical journal
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

                    # Reconcile causal effectiveness and live violations for spooled events ONLY on write success
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
                "parentViolationId": parent_violation_id,
                "recoveryAttempts": recovery_attempts,
                "resolutionMs": resolution_ms
            }

            # Permanent Audit & Telemetry Archive (JSONL for product R&D and effectiveness analysis)
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
                "model": model_id,
                "reason": reason,
                "outcome": outcome,
                "parentViolationId": parent_violation_id,
                "recoveryAttempts": recovery_attempts,
                "resolutionMs": resolution_ms
            }

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
                    "model": model_id,
                    "reason": add_ev["reason"],
                    "outcome": "RECOVERED",
                    "parentViolationId": add_ev["parentViolationId"],
                    "recoveryAttempts": add_ev["recoveryAttempts"],
                    "resolutionMs": add_ev["resolutionMs"]
                }
                extra_telemetry_events.append(add_telemetry)

            final_audit_seq = curr_extra_seq
            is_durable = _is_durable_mode()

            # Centralized Secret Redaction: scrub all records before writing
            event = redact_record(event)
            telemetry_event = redact_record(telemetry_event)
            extra_recovery_events = [redact_record(x) for x in extra_recovery_events]
            extra_telemetry_events = [redact_record(x) for x in extra_telemetry_events]

            # ---------------------------------------------------------
            # 1. WRITE-AHEAD LOGGING (JOURNAL FIRST)
            # Permanent audit stream is canonical source of truth.
            # ---------------------------------------------------------
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

            # ---------------------------------------------------------
            # 2. UPDATE LIVE PROJECTION STATE
            # ---------------------------------------------------------
            current_data["lastAuditSeq"] = final_audit_seq
            events = current_data.get("events", [])
            if not isinstance(events, list):
                events = []
            events.insert(0, event)
            for add_ev in extra_recovery_events:
                events.insert(1, add_ev)
            current_data["events"] = events[:50]  # keep last 50 for UI feed
            current_data["lastCheck"] = now_str

            _recompute_effectiveness_rates(current_data)

            # ---------------------------------------------------------
            # 3. ATOMIC CRASH-CONSISTENT REPLACE (.tmp -> rename)
            # ---------------------------------------------------------
            tmp_log_path = Path(log_path).with_suffix(".tmp")
            with open(tmp_log_path, "w", encoding="utf-8") as f:
                json.dump(current_data, f, indent=2, ensure_ascii=False)
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

