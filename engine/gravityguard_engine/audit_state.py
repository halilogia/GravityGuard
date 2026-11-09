"""GravityGuard Engine — live monitor state projection and rebuild from the permanent audit journal."""
import json
import os
import sys
import copy
from typing import Dict, Any


def _apply_event_to_live_state(state: Dict[str, Any], ev: Dict[str, Any]) -> None:
    """
    Applies a single permanent audit record to a live monitor state projection.
    Updates cumulative effectiveness counters, per-rule stats, and active violations.
    """
    if ev.get("recordType") == "audit_checkpoint":
        snapshot = ev.get("snapshot", {})
        if isinstance(snapshot, dict):
            state["effectiveness"] = copy.deepcopy(snapshot.get("effectiveness", {}))
            state["activeViolations"] = copy.deepcopy(snapshot.get("activeViolations", {}))
            state["maintenanceId"] = ev.get("eventId")
            state["lastAuditSeq"] = ev.get("auditSeq", 0)
        return
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
    elif out == "RECOVERED" and ev.get("ruleId") not in NON_RECOVERING_RULES:
        eff["totalRecovered"] = eff.get("totalRecovered", 0) + 1
        rst = rule_stats.setdefault(res_id, {"blocked": 0, "recovered": 0, "recoveryRate": 0.0, "attempts": []})
        rst["recovered"] = rst.get("recovered", 0) + 1
        att = ev.get("recoveryAttempts")
        if isinstance(att, (int, float)):
            rst.setdefault("attempts", []).append(att)
        if ev.get("evasionSuspect"):
            rst["evasionSuspect"] = rst.get("evasionSuspect", 0) + 1
        # Clear matching active violation
        matching = [k for k in list(active_violations.keys()) if k.startswith(f"{c_id}::{target}::")]
        for mk in matching:
            if active_violations[mk].get("ruleId") == res_id:
                active_violations.pop(mk, None)
                break

    seq = ev.get("auditSeq")
    if isinstance(seq, int) and seq > state.get("lastAuditSeq", 0):
        state["lastAuditSeq"] = seq


# Approved records that are not the write itself (a read, a pending-evidence or doc note).
NON_RECOVERING_RULES = frozenset({"READ_ALLOW", "T1_PENDING", "DOC_OBLIGATION_PENDING", "G7_TS_MANDATORY_FEEDBACK", "BRIEFING_SENT"})


DETERRENCE_RULES = {
    "G0_ENV_PROTECTION",
    "G0_SECRET_LEAK",
    "POLICY_INTEGRITY",
    "G2_SECURITY_TAMPERING",
    "SHELL_SECURITY",
}


def _recompute_effectiveness_rates(state: Dict[str, Any]) -> None:
    """Recomputes recovery rates, deterrence rates and median attempts with invariant checking."""
    eff = state.get("effectiveness", {})
    tot_b = eff.get("totalBlocked", 0)
    tot_r = eff.get("totalRecovered", 0)
    rule_stats = eff.get("ruleStats", {})

    tot_security_blocked = 0
    tot_code_b = 0
    tot_code_r = 0

    for r_id, rst in rule_stats.items():
        b = rst.get("blocked", 0)
        r = rst.get("recovered", 0)
        if r_id in DETERRENCE_RULES:
            rst["isDeterrenceRule"] = True
            rst["recoveryRate"] = min(100.0, round(r / b * 100, 1)) if b else 100.0
            rst.pop("deterrenceRate", None)
            tot_security_blocked += b
        else:
            if r > b > 0:
                sys.stderr.write(
                    f"[GravityGuard Invariant Violation] rule {r_id}: recovered ({r}) > blocked ({b})\n"
                )
            rst["recoveryRate"] = min(100.0, round((r / b * 100), 1)) if b > 0 else 100.0
            tot_code_b += b
            tot_code_r += min(r, b)

        atts = rst.get("attempts", [])
        # No recorded attempts means no median; a default of 1 looked like real data.
        rst["medianAttempts"] = sorted(atts)[len(atts) // 2] if atts else None

    # A rejected operation is observable; abandonment or deterrence is not.
    eff.pop("deterrenceRate", None)
    eff.pop("totalDeterred", None)
    eff["totalSecurityBlocked"] = tot_security_blocked
    eff["totalCodeBlocked"] = tot_code_b
    eff["totalCodeRecovered"] = tot_code_r
    eff["codeFixRate"] = min(100.0, round((tot_code_r / tot_code_b * 100), 1)) if tot_code_b > 0 else 100.0
    eff["recoveryRate"] = min(100.0, round(tot_r / tot_b * 100, 1)) if tot_b > 0 else 100.0


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

    recent_raw = [ev for ev in raw_events if ev.get("recordType") != "audit_checkpoint"][-50:]
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

