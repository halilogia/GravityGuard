# -*- coding: utf-8 -*-
"""Telemetry veri katmani: log kesfi, akis okuma, metrik toplama. telemetry_dashboard.py tarafindan re-export edilir."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, Generator, List, Optional, Set, Tuple


def parse_iso_datetime(ts_str: str) -> Optional[datetime]:
    """Parses various ISO timestamp formats safely into a datetime object normalized to UTC."""
    if not ts_str or not isinstance(ts_str, str):
        return None
    cleaned = ts_str.strip().replace("Z", "+00:00")
    local_tz = datetime.now().astimezone().tzinfo
    if len(cleaned) == 10 and cleaned.count("-") == 2:
        try:
            return datetime.fromisoformat(cleaned).replace(tzinfo=local_tz).astimezone(timezone.utc)
        except (ValueError, TypeError):
            return None
    try:
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=local_tz).astimezone(timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except (ValueError, TypeError):
        try:
            dt = datetime.strptime(cleaned[:19], "%Y-%m-%dT%H:%M:%S")
            return dt.replace(tzinfo=local_tz).astimezone(timezone.utc)
        except (ValueError, TypeError):
            return None


def resolve_default_permanent_log_path() -> str:
    """Finds the default active permanent audit JSONL file dynamically."""
    override = os.environ.get("GRAVITYGUARD_LOG_DIR", "").strip() or os.environ.get("GRAVITYGUARD_AUDIT_DIR", "").strip()
    if override:
        p = Path(override) / "gravityguard_permanent_audit.jsonl"
        if p.is_file():
            return str(p)

    user_sub = Path(os.path.expanduser("~/.gemini/logs/gravityguard/gravityguard_permanent_audit.jsonl"))
    if user_sub.is_file():
        return str(user_sub)

    user_log = Path(os.path.expanduser("~/.gemini/logs/gravityguard_permanent_audit.jsonl"))
    if user_log.is_file():
        return str(user_log)

    repo_archive = Path(__file__).resolve().parent.parent / "archives" / "audit-logs" / "gravityguard_permanent_audit.jsonl"
    if repo_archive.is_file():
        return str(repo_archive)

    return str(user_log)


def discover_all_log_paths(
    project_dir: Optional[str] = None,
    explicit_source: Optional[str] = None,
    projects_root: Optional[str] = None
) -> List[Path]:
    """
    Discovers all accessible GravityGuard audit log sources:
    - Explicit file or folder provided via CLI
    - User Antigravity global logs (~/.gemini/logs)
    - Claude Code / local project logs (.gravityguard/logs)
    - Projects under projects_root
    - Historical repository archives (archives/audit-logs)
    """
    found: List[Path] = []
    seen: Set[str] = set()

    def add_if_exists(p: Path):
        norm = str(p.resolve()) if p.exists() else str(p)
        if p.is_file() and norm not in seen:
            found.append(p)
            seen.add(norm)
        elif p.is_dir():
            for sub in p.glob("**/*.jsonl"):
                s_norm = str(sub.resolve())
                if s_norm not in seen:
                    found.append(sub)
                    seen.add(s_norm)

    if explicit_source:
        add_if_exists(Path(explicit_source))

    # Env overrides
    for env_var in ("GRAVITYGUARD_LOG_DIR", "GRAVITYGUARD_AUDIT_DIR"):
        v = os.environ.get(env_var, "").strip()
        if v:
            add_if_exists(Path(v))

    # Global user locations
    private_archives = Path.home() / ".gravityguard" / "maintenance"
    if private_archives.is_dir():
        for archived in private_archives.glob("*/gravityguard_permanent_audit.jsonl"):
            add_if_exists(archived)
        for archived in private_archives.glob("snapshots/gravityguard_permanent_audit_*.jsonl"):
            add_if_exists(archived)
    add_if_exists(Path(os.path.expanduser("~/.gemini/logs/gravityguard_permanent_audit.jsonl")))
    add_if_exists(Path(os.path.expanduser("~/.gemini/logs/gravityguard/gravityguard_permanent_audit.jsonl")))

    # Project-local locations (e.g. Claude Code or repo root)
    if project_dir:
        add_if_exists(Path(project_dir) / ".gravityguard" / "logs" / "gravityguard_permanent_audit.jsonl")
    curr_proj = Path.cwd() / ".gravityguard" / "logs" / "gravityguard_permanent_audit.jsonl"
    add_if_exists(curr_proj)

    # Scan projects_root for multi-project logs
    if projects_root and os.path.isdir(projects_root):
        pr_path = Path(projects_root)
        for sub_log in pr_path.glob("**/.gravityguard/logs/*.jsonl"):
            add_if_exists(sub_log)

    # Repository archive directory (historical base log; skip timestamped archive snapshots to prevent duplicate counts)
    repo_root = Path(__file__).resolve().parent.parent
    archive_dir = repo_root / "archives" / "audit-logs"
    if archive_dir.is_dir():
        for af in archive_dir.glob("*.jsonl"):
            if "_20" in af.name:
                # Timestamped snapshot created by rotation/backup; active log already contains these
                continue
            add_if_exists(af)

    return found


class LogStreamReader:
    """Streams JSONL records without holding the entire corpus in memory."""

    def __init__(self, paths: List[Path]):
        self.paths = [p for p in paths if p.is_file()]
        self.corrupted_lines_count = 0
        self.total_lines_scanned = 0

    def stream_events(
        self,
        since_dt: Optional[datetime] = None,
        until_dt: Optional[datetime] = None,
        project_filter: Optional[str] = None,
        rule_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        needs_dedup = len(self.paths) > 1
        seen_keys: Dict[str, bool] = {}
        MAX_SEEN_KEYS = 50000

        for path in self.paths:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        self.total_lines_scanned += 1
                        stripped = line.strip()
                        if not stripped:
                            continue
                        try:
                            ev = json.loads(stripped)
                        except Exception:
                            self.corrupted_lines_count += 1
                            continue

                        if not isinstance(ev, dict):
                            self.corrupted_lines_count += 1
                            continue
                        if ev.get("recordType") == "audit_checkpoint":
                            continue

                        # Deduplicate across merged files (composite key) only if multiple sources
                        if needs_dedup:
                            eid = ev.get("eventId")
                            ts = ev.get("timestamp")
                            seq = ev.get("auditSeq")
                            dedup_key = f"{eid}::{ts}::{seq}" if eid else f"{ts}::{seq}"
                            if dedup_key in seen_keys:
                                continue
                            if len(seen_keys) >= MAX_SEEN_KEYS:
                                # FIFO eviction: prune oldest key instead of wiping all deduplication state
                                seen_keys.pop(next(iter(seen_keys)))
                            seen_keys[dedup_key] = True

                        # Filter by timestamp window
                        ev_dt = parse_iso_datetime(ev.get("timestamp", ""))
                        if since_dt and ev_dt and ev_dt < since_dt:
                            continue
                        if until_dt and ev_dt and ev_dt > until_dt:
                            continue

                        # Filter by project
                        if project_filter:
                            p_name = (ev.get("project") or "").lower()
                            if project_filter.lower() not in p_name:
                                continue

                        # Filter by rule
                        if rule_filter:
                            r_name = ev.get("ruleId") or ev.get("resolvedRuleId") or ""
                            if rule_filter.lower() not in r_name.lower():
                                continue

                        # Filter by status
                        if status_filter and ev.get("status") != status_filter:
                            continue

                        yield ev
            except Exception as read_err:
                sys.stderr.write(f"[GravityGuard Log Read Error: {path}] {read_err}\n")


def format_bar(val: int, max_val: int, width: int = 24) -> str:
    if max_val <= 0:
        return ""
    filled = int((val / max_val) * width)
    return "█" * filled + "░" * (width - filled)


class AggregatedMetrics:
    """Aggregates metrics directly from an event stream with O(1) memory footprint."""

    def __init__(self, events_or_stream: Any, label: str = "Tüm Zamanlar"):
        self.label = label
        self.total = 0
        self.status_counts: Counter[str] = Counter()
        self.rule_counts: Counter[str] = Counter()
        self.project_counts: Counter[str] = Counter()
        self.ext_counts: Counter[str] = Counter()

        self.total_blocked = 0
        self.total_recovered = 0
        self.total_repeated = 0
        self.total_shadow = 0
        self.total_warning = 0
        self.total_approved = 0

        self.rule_blocked: Counter[str] = Counter()
        self.rule_recovered: Counter[str] = Counter()
        self.shadow_rules: Counter[str] = Counter()
        self.warn_rules: Counter[str] = Counter()

        self._attempts_counter: Counter[int] = Counter()
        self._total_duration_ms: float = 0.0
        self._duration_count: int = 0

        self.recent_interventions: List[Dict[str, Any]] = []
        self._max_recent = 10

        # Advisory Follow-up Rate tracking
        self._pending_warnings: Dict[Tuple[str, str], List[Tuple[str, str]]] = defaultdict(list)
        self.advisory_heeded: Counter[str] = Counter()

        # Learning Ledger Candidates
        self.candidate_rule_counts: Counter[str] = Counter()
        self.candidate_targets: Dict[str, Counter[str]] = defaultdict(Counter)
        self.candidate_sessions: Dict[str, Set[str]] = defaultdict(set)

        self._consume(events_or_stream)

    def _consume(self, stream: Any) -> None:
        for ev in stream:
            self.total += 1
            st = ev.get("status", "UNKNOWN")
            out = ev.get("outcome")
            r_id = ev.get("ruleId") or "UNKNOWN"
            res_id = ev.get("resolvedRuleId") or r_id
            proj = ev.get("project") or "Diğer / Bilinmeyen"
            ext = ev.get("fileExt") or "(Uzantısız)"

            self.status_counts[st] += 1
            self.rule_counts[r_id] += 1
            self.project_counts[proj] += 1
            self.ext_counts[ext] += 1

            cid = ev.get("conversationId") or ev.get("session_id") or "default"
            tgt = (ev.get("target") or "").replace("\\", "/").lower()
            ts = ev.get("timestamp", "")

            if st == "BLOCKED" and out != "REPEATED_VIOLATION":
                self.total_blocked += 1
                self.rule_blocked[r_id] += 1
            elif out == "REPEATED_VIOLATION":
                self.total_repeated += 1
            elif out == "RECOVERED":
                self.total_recovered += 1
                self.rule_recovered[res_id] += 1
                att = ev.get("recoveryAttempts")
                if isinstance(att, (int, float)):
                    self._attempts_counter[int(att)] += 1
                dur = ev.get("resolutionMs")
                if isinstance(dur, (int, float)):
                    self._total_duration_ms += float(dur)
                    self._duration_count += 1
            elif st == "SHADOW_TRIGGER":
                self.total_shadow += 1
                self.shadow_rules[r_id] += 1
            elif st == "WARNING":
                self.total_warning += 1
                self.warn_rules[r_id] += 1
                if tgt and len(self._pending_warnings) < 2000:
                    if len(self._pending_warnings[(cid, tgt)]) < 20:
                        self._pending_warnings[(cid, tgt)].append((r_id, ts))
            elif st == "APPROVED":
                self.total_approved += 1
                if tgt and (cid, tgt) in self._pending_warnings:
                    pending = self._pending_warnings.pop((cid, tgt))
                    for w_rule, w_ts in pending:
                        if ts >= w_ts:
                            self.advisory_heeded[w_rule] += 1

            if st in ("BLOCKED", "WARNING"):
                if len(self.recent_interventions) < self._max_recent:
                    self.recent_interventions.append(ev)
                else:
                    self.recent_interventions.pop(0)
                    self.recent_interventions.append(ev)

                self.candidate_rule_counts[r_id] += 1
                t_base = os.path.basename(ev.get("target") or "bilinmeyen")
                if len(self.candidate_targets[r_id]) < 200:
                    self.candidate_targets[r_id][t_base] += 1
                if len(self.candidate_sessions[r_id]) < 500:
                    self.candidate_sessions[r_id].add(cid)

        self.recovery_rate = (self.total_recovered / self.total_blocked * 100) if self.total_blocked > 0 else 100.0

        if self._attempts_counter and sum(self._attempts_counter.values()) > 0:
            tot_atts = sum(self._attempts_counter.values())
            if tot_atts % 2 == 1:
                target_rank = (tot_atts + 1) // 2
                running = 0
                for att_val in sorted(self._attempts_counter.keys()):
                    running += self._attempts_counter[att_val]
                    if running >= target_rank:
                        self.median_attempts = float(att_val)
                        break
            else:
                r1 = tot_atts // 2
                r2 = r1 + 1
                val1 = None
                val2 = None
                running = 0
                for att_val in sorted(self._attempts_counter.keys()):
                    running += self._attempts_counter[att_val]
                    if val1 is None and running >= r1:
                        val1 = float(att_val)
                    if val2 is None and running >= r2:
                        val2 = float(att_val)
                        break
                self.median_attempts = ((val1 if val1 is not None else 1.0) + (val2 if val2 is not None else 1.0)) / 2.0
        else:
            self.median_attempts = 1.0

        self.avg_duration_s = (self._total_duration_ms / self._duration_count / 1000) if self._duration_count > 0 else 0.0

