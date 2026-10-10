#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================================
GRAVITYGUARD TELEMETRY ANALYTICS & AUDIT DASHBOARD
============================================================================
Streaming analytics, multi-source log aggregation, weekly/monthly trend deltas,
zero-memory bloat JSONL processing, log rotation, and rule candidates.
Zero external dependencies.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Callable, Dict, Generator, List, Optional, Set, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_ENGINE_DIR = str(Path(__file__).resolve().parent.parent / "engine")
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)
try:
    from gravityguard_engine.state_lock import StateLock
except ImportError:
    class StateLock:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass
        def acquire(self):
            return True
        def release(self):
            pass


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

    # Repository archive directory
    repo_root = Path(__file__).resolve().parent.parent
    archive_dir = repo_root / "archives" / "audit-logs"
    if archive_dir.is_dir():
        for af in archive_dir.glob("*.jsonl"):
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
        seen_keys: Set[str] = set()
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

                        # Deduplicate across merged files (composite key) only if multiple sources
                        if needs_dedup:
                            eid = ev.get("eventId")
                            ts = ev.get("timestamp")
                            seq = ev.get("auditSeq")
                            dedup_key = f"{eid}::{ts}::{seq}" if eid else f"{ts}::{seq}"
                            if dedup_key in seen_keys:
                                continue
                            if len(seen_keys) >= MAX_SEEN_KEYS:
                                seen_keys.clear()
                            seen_keys.add(dedup_key)

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
                if tgt and len(self._pending_warnings[(cid, tgt)]) < 20:
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
                self.candidate_targets[r_id][t_base] += 1
                if len(self.candidate_sessions[r_id]) < 500:
                    self.candidate_sessions[r_id].add(cid)

        self.recovery_rate = (self.total_recovered / self.total_blocked * 100) if self.total_blocked > 0 else 100.0

        if self._attempts_counter:
            tot_atts = sum(self._attempts_counter.values())
            half = tot_atts // 2
            running = 0
            med = 1.0
            for att_val in sorted(self._attempts_counter.keys()):
                running += self._attempts_counter[att_val]
                if running >= half:
                    med = float(att_val)
                    break
            self.median_attempts = med
        else:
            self.median_attempts = 1.0

        self.avg_duration_s = (self._total_duration_ms / self._duration_count / 1000) if self._duration_count > 0 else 0.0


def render_period_comparison(curr: AggregatedMetrics, prev: AggregatedMetrics):
    """Renders a comparative view between the current period and previous period."""
    print("\n📅 DÖNEMSEL TREND VE GELİŞİM KARŞILAŞTIRMASI (Period-over-Period Delta)")
    print("-" * 80)
    print(f"  Dönemler : [Şu An: {curr.label}] vs [Önceki: {prev.label}]")
    print("  " + "-" * 78)

    def calc_delta(c_val: float, p_val: float) -> str:
        if p_val == 0:
            return f"+{c_val:.0f} (Yeni)" if c_val > 0 else "0.0"
        diff = c_val - p_val
        pct = (diff / p_val) * 100
        sign = "+" if pct >= 0 else ""
        return f"{sign}{pct:.1f}% ({c_val} vs {p_val})"

    print(f"  Toplam İşlem (Total Events)       : {calc_delta(curr.total, prev.total)}")
    print(f"  Engellenenler (Blocked Violations): {calc_delta(curr.total_blocked, prev.total_blocked)}")
    print(f"  Uyarılar (Warnings)               : {calc_delta(curr.total_warning, prev.total_warning)}")
    print(f"  İyileşme Oranı (Recovery Rate)    : %{curr.recovery_rate:.1f} vs %{prev.recovery_rate:.1f} (Delta: {curr.recovery_rate - prev.recovery_rate:+.1f} puan)")

    # Rules with notable changes
    all_rules = set(curr.rule_counts.keys()) | set(prev.rule_counts.keys())
    deltas = []
    for r in all_rules:
        c_cnt = curr.rule_counts.get(r, 0)
        p_cnt = prev.rule_counts.get(r, 0)
        if c_cnt > 0 or p_cnt > 0:
            deltas.append((r, c_cnt, p_cnt, c_cnt - p_cnt))
    deltas.sort(key=lambda x: abs(x[3]), reverse=True)

    if deltas:
        print("\n  🔍 EN ÇOK DEĞİŞİM GÖSTEREN KURALLAR:")
        print(f"  {'Kural':<26} | {'Mevcut':<7} | {'Önceki':<7} | {'Değişim':<10}")
        print("  " + "-" * 58)
        for r, c, p, diff in deltas[:5]:
            sign = "+" if diff >= 0 else ""
            print(f"  {r:<26} | {c:>7} | {p:>7} | {sign}{diff:>8}")


def render_effectiveness_analytics(m: AggregatedMetrics):
    print("\n🎯 ETKİNLİK VE AJAN KURTARMA ANALİZİ (EFFECTIVENESS ANALYTICS)")
    print("-" * 80)
    print(f"  Toplam Engellenen İlk Müdahale (Blocked Root) : {m.total_blocked}")
    print(f"  Ajan Tarafından Düzeltilen (Recovered)       : {m.total_recovered} (İyileşme Oranı: %{m.recovery_rate:.1f})")
    print(f"  Medyan Düzeltme Denemesi (Friction Delta)     : {m.median_attempts} deneme")
    if m.avg_duration_s > 0:
        print(f"  Ortalama Çözümleme Süresi (Time-to-Resolve)  : {m.avg_duration_s:.1f} saniye")

    if m.rule_blocked:
        print("\n  🛡️  KURAL BAZLI ETKİNLİK VE DEĞER TABLOSU:")
        print("  " + "-" * 82)
        print(f"  {'Kural':<24} | {'Engelleme':<9} | {'Kurtarma':<8} | {'Oran':<6} | {'Sınıf':<22}")
        print("  " + "-" * 82)

        for rule, b_cnt in m.rule_blocked.most_common():
            r_cnt = m.rule_recovered.get(rule, 0)
            rate = (r_cnt / b_cnt * 100) if b_cnt > 0 else 0.0
            if b_cnt < 10:
                classification = f"⚪ YETERSİZ VERİ (n={b_cnt})"
            elif b_cnt < 30:
                classification = f"🟡 ÖN SİNYAL (n={b_cnt})"
            elif rate >= 85.0:
                classification = f"🏆 YÜKSEK DEĞER (n={b_cnt})"
            elif rate < 50.0:
                classification = f"⚡ SÜRTÜNME (n={b_cnt})"
            else:
                classification = f"🟢 DENGELİ (n={b_cnt})"
            print(f"  {rule:<24} | {b_cnt:>9} | {r_cnt:>8} | %{rate:>4.1f} | {classification}")

    # Advisory Follow-up Rate (Temporal Action Proxy)
    if m.total_warning > 0:
        print("\n  ⚠️  TAVSİYE KURALLARI VE DÜZENLEME TAKİP ORANI (Advisory Follow-up Rate):")
        print("  " + "-" * 82)
        print("  Not: Bu metrik doğrudan nedensellik kanıtı değil, zamansal bir vekildir")
        print("       (temporal action proxy); uyarının ardından aynı oturumda dosyaya onaylı")
        print("       bir düzenleme gelip gelmediğini ölçer.")
        print("  " + "-" * 82)
        print(f"  {'Kural':<24} | {'Uyarı':<6} | {'Takip Eden Onay':<15} | {'Takip Oranı':<11} | {'Durum':<18}")
        print("  " + "-" * 82)
        for w_rule, w_cnt in m.warn_rules.most_common():
            heeded = m.advisory_heeded.get(w_rule, 0)
            action_rate = (heeded / w_cnt * 100) if w_cnt > 0 else 0.0
            if w_cnt < 10:
                status_desc = f"⚪ Yetersiz Veri (n={w_cnt})"
            elif w_cnt < 30:
                status_desc = f"🟡 Ön Sinyal (n={w_cnt})"
            elif action_rate < 25.0:
                status_desc = "⚠️ Düşük Takip"
            elif action_rate >= 75.0:
                status_desc = "✅ Yüksek Takip"
            else:
                status_desc = "🟢 Dengeli"
            print(f"  {w_rule:<24} | {w_cnt:>6} | {heeded:>15} | %{action_rate:>9.1f} | {status_desc}")

    # Shadow Mode Observations
    if m.total_shadow > 0:
        print("\n  🧪 GÖLGE MODU GÖZLEMLERİ (Shadow Observation Mode):")
        print("  " + "-" * 82)
        for s_rule, s_cnt in m.shadow_rules.most_common():
            print(f"  • {s_rule:<24} : {s_cnt} sessiz gözlem (Ajan akışı kesintiye uğramadan ölçüldü)")


def render_dashboard(
    m: AggregatedMetrics,
    sources: List[Path],
    corrupt_lines: int = 0,
    prev_m: Optional[AggregatedMetrics] = None,
):
    print("=" * 80)
    print("           GRAVITYGUARD GÜVENLİK VE MİMARİ TELEMETRİ MERKEZİ            ")
    print(f"           Rapor Dönemi: {m.label}")
    print("=" * 80)

    if corrupt_lines > 0:
        print(f"⚠️  DİKKAT: {corrupt_lines} bozuk/geçersiz JSONL satırı filtrelendi.")

    if m.total == 0:
        print("\n[!] Seçilen dönem veya filtrelerde telemetri kaydı bulunamadı.\n")
        print("=" * 80)
        return

    blocked = m.status_counts.get("BLOCKED", 0)
    warnings = m.status_counts.get("WARNING", 0)
    approved = m.status_counts.get("APPROVED", 0)

    print(f"\n📊 GENEL ÖZET (Toplam Denetlenen İşlem: {m.total})")
    print("-" * 80)
    print(f"  ✅ ONAYLANAN (APPROVED)  : {approved:<5} %{(approved / m.total * 100):.1f}")
    print(f"  🛑 ENGELLENEN (BLOCKED)  : {blocked:<5} %{(blocked / m.total * 100):.1f}")
    print(f"  ⚠️  UYARI ALAN (WARNING)  : {warnings:<5} %{(warnings / m.total * 100):.1f}")

    if prev_m:
        render_period_comparison(m, prev_m)

    render_effectiveness_analytics(m)

    print("\n🛡️  KURAL BAZLI İHLAL VE GÜVENLİK DAĞILIMI (Top Rules)")
    print("-" * 80)
    top_rules = m.rule_counts.most_common(12)
    max_rule_cnt = top_rules[0][1] if top_rules else 1
    for rule, cnt in top_rules:
        pct = (cnt / m.total) * 100
        bar = format_bar(cnt, max_rule_cnt, width=20)
        status_tag = "🛑" if "BLOCK" in rule or rule in {"G0_SECRET_LEAK", "G1_SILENT_EXCEPTION", "G2_TEST_INTEGRITY", "G2_SECURITY_TAMPERING", "G4_IMPORT_MATRIX", "SRP_BOUNDARY"} else "⚠️"
        print(f"  {status_tag} {rule:<25} | {cnt:>4} adet ({pct:>5.1f}%) | {bar}")

    print("\n📁 PROJE DAĞILIMI (Ajanın En Çok Kod Yazdığı Projeler)")
    print("-" * 80)
    top_projects = m.project_counts.most_common(8)
    max_proj_cnt = top_projects[0][1] if top_projects else 1
    for proj, cnt in top_projects:
        pct = (cnt / m.total) * 100
        bar = format_bar(cnt, max_proj_cnt, width=16)
        print(f"  📦 {proj:<24} | {cnt:>4} işlem (%{pct:>4.1f}) | {bar}")

    print("\n📝 DOSYA TÜRÜ DAĞILIMI")
    print("-" * 80)
    for ext, cnt in m.ext_counts.most_common(6):
        pct = (cnt / m.total) * 100
        print(f"  📄 {ext:<12} : {cnt:>4} (%{pct:>4.1f})")

    print("\n🚨 SON 5 GÜVENLİK / MİMARİ MÜDAHALESİ (Canlı Hadiseler)")
    print("-" * 80)
    blocked_or_warned = list(reversed(m.recent_interventions))[:5]
    if not blocked_or_warned:
        print("  [✓] Yakın zamanda engellenen veya uyarılan işlem yok.")
    else:
        for idx, ev in enumerate(blocked_or_warned, 1):
            ts = ev.get("timestamp", "")[:19]
            st = ev.get("status", "")
            icon = "🛑" if st == "BLOCKED" else "⚠️"
            target = os.path.basename(ev.get("target", ""))
            rule = ev.get("ruleId", "")
            reason = ev.get("reason", "").replace("\n", " ")
            if len(reason) > 75:
                reason = reason[:72] + "..."
            print(f"  {idx}. [{ts}] {icon} {st:<7} [{rule}] Dosya: {target}")
            print(f"     Neden: {reason}")

    print("=" * 80)
    src_display = ", ".join(str(s) for s in sources[:3])
    if len(sources) > 3:
        src_display += f" (+{len(sources) - 3} kaynak)"
    print(f"Log Kaynağı ({len(sources)} adet): {src_display}")
    print("=" * 80)


def render_rule_candidates(m: AggregatedMetrics):
    print("=" * 80)
    print("      GRAVITYGUARD KURAL ADAYLARI & ÖĞRENME DEFTERİ (Learning Ledger)    ")
    print(f"      Dönem: {m.label}")
    print("=" * 80)

    total_violations = sum(m.candidate_rule_counts.values())
    if total_violations == 0:
        print("\n[✓] Telemetri verilerinde bu dönemde ihlal veya uyarı kaydı yok.")
        print("    Mevcut politikalar sistemle tam uyumlu çalışıyor.\n")
        print("=" * 80)
        return

    rule_counter = m.candidate_rule_counts
    rule_targets = m.candidate_targets
    rule_sessions = m.candidate_sessions

    MIN_THRESHOLD = 3
    candidates = []

    # 1. G4 Import Matrix Analysis
    g4_count = rule_counter.get("G4_IMPORT_MATRIX", 0)
    if g4_count >= MIN_THRESHOLD:
        targets = rule_targets["G4_IMPORT_MATRIX"].most_common(3)
        sessions = rule_sessions["G4_IMPORT_MATRIX"]
        candidates.append({
            "id": "CAND-G4-BOUNDARY-REFINEMENT",
            "rule": "G4_IMPORT_MATRIX",
            "count": g4_count,
            "rate": (g4_count / total_violations) * 100 if total_violations else 0,
            "session_count": len(sessions),
            "targets": [t[0] for t in targets],
            "diagnosis": f"Ajanın katmanlar arası sınır ihlali yaptığı gözlemlendi ({len(sessions)} farklı oturumda).",
            "recommendation": ".gravityguard.json içerisindeki 'layers' matrisini gözden geçirin veya ilgili modülü paylaşılan (shared) katmana taşıyın."
        })

    # 2. T1 Test Evidence Analysis
    t1_count = rule_counter.get("T1_MISSING_RELATED_TEST", 0) + rule_counter.get("T1_FINAL_UNRESOLVED", 0)
    if t1_count >= MIN_THRESHOLD:
        t1_targets = (rule_targets.get("T1_MISSING_RELATED_TEST", Counter()) + rule_targets.get("T1_FINAL_UNRESOLVED", Counter())).most_common(3)
        t1_sess = rule_sessions["T1_MISSING_RELATED_TEST"] | rule_sessions["T1_FINAL_UNRESOLVED"]
        candidates.append({
            "id": "CAND-T1-EXEMPTION-EXPANSION",
            "rule": "T1_MISSING_RELATED_TEST",
            "count": t1_count,
            "rate": (t1_count / total_violations) * 100 if total_violations else 0,
            "session_count": len(t1_sess),
            "targets": [t[0] for t in t1_targets],
            "diagnosis": f"Üretim dosyaları için test dosyası bulunamadı ({len(t1_sess)} oturumda tekrarlandı).",
            "recommendation": "Bu dosyalar konfigürasyon/şema niteliğindeyse 'exemptPatterns' listesine ekleyin; iş mantığı içeriyorsa test süitine dahil edin."
        })

    # 3. Growth / Monolith Analysis
    growth_count = rule_counter.get("ARCH_FILE_GROWTH", 0)
    if growth_count >= MIN_THRESHOLD:
        targets = rule_targets["ARCH_FILE_GROWTH"].most_common(3)
        g_sess = rule_sessions["ARCH_FILE_GROWTH"]
        candidates.append({
            "id": "CAND-SRP-MODULARIZATION",
            "rule": "ARCH_FILE_GROWTH",
            "count": growth_count,
            "rate": (growth_count / total_violations) * 100 if total_violations else 0,
            "session_count": len(g_sess),
            "targets": [t[0] for t in targets],
            "diagnosis": f"Tek seferde 200+ satır ekleme veya kümülatif büyüme uyarıları alındı ({len(g_sess)} oturum).",
            "recommendation": "Dosyayı srp-modularizer ile alt bileşenlere ayırın ya da bilinçli bir büyüme ise 'srp: allow-monolith' etiketi ekleyin."
        })

    # 4. G1 Silent Exception Analysis
    g1_count = rule_counter.get("G1_SILENT_EXCEPTION", 0)
    if g1_count >= MIN_THRESHOLD:
        targets = rule_targets["G1_SILENT_EXCEPTION"].most_common(3)
        g1_sess = rule_sessions["G1_SILENT_EXCEPTION"]
        candidates.append({
            "id": "CAND-G1-EXCEPTION-STANDARDS",
            "rule": "G1_SILENT_EXCEPTION",
            "count": g1_count,
            "rate": (g1_count / total_violations) * 100 if total_violations else 0,
            "session_count": len(g1_sess),
            "targets": [t[0] for t in targets],
            "diagnosis": f"Ajanın sessiz hata yutma (except: pass / catch {{}}) teşebbüsleri engellendi ({len(g1_sess)} oturum).",
            "recommendation": "Ajan promptunda hata yakalama disiplinini vurgulayın veya loglama zorunluluğu getirin."
        })

    # 5. G2 Tampering Analysis
    g2_count = rule_counter.get("G2_SECURITY_TAMPERING", 0) + rule_counter.get("G2_TEST_INTEGRITY", 0)
    if g2_count >= MIN_THRESHOLD:
        g2_targets = (rule_targets.get("G2_SECURITY_TAMPERING", Counter()) + rule_targets.get("G2_TEST_INTEGRITY", Counter())).most_common(3)
        g2_sess = rule_sessions["G2_SECURITY_TAMPERING"] | rule_sessions["G2_TEST_INTEGRITY"]
        candidates.append({
            "id": "CAND-G2-TAMPERING-ALERT",
            "rule": "G2_SECURITY_TAMPERING",
            "count": g2_count,
            "rate": (g2_count / total_violations) * 100 if total_violations else 0,
            "session_count": len(g2_sess),
            "targets": [t[0] for t in g2_targets],
            "diagnosis": f"Test silme, test atlatma veya escape-hatch enjeksiyon denemesi tespit edildi ({len(g2_sess)} oturum).",
            "recommendation": "Kural atlatma denemelerine karşı denetimi sıkılaştırın ve prompt kurallarını güncelleyin."
        })

    print(f"\n📋 BULUNAN KURAL ADAYLARI ({len(candidates)} Öneri - Eşik: >= {MIN_THRESHOLD} ihlal)")
    print("-" * 80)
    if not candidates:
        print(f"   [i] Hiçbir kural ihlali belirlenen eşiği (>={MIN_THRESHOLD}) aşmadı. Sistem stabil.")
    for c in candidates:
        print(f"\n🔹 [{c['id']}] (Tetiklenme: {c['count']} kez | İhlal Oranı: %{c['rate']:.1f} | {c['session_count']} oturum)")
        print(f"   Etkilenen Dosyalar : {', '.join(c['targets'])}")
        print(f"   Teşhis             : {c['diagnosis']}")
        print(f"   Önerilen Aksiyon   : {c['recommendation']}")

    print("\n" + "=" * 80)
    print("Not: Kural adayları insan denetimi (Human-in-the-Loop) içindir; otonom kural gevşetme yapılmaz.")
    print("=" * 80)


def export_markdown_report(m: AggregatedMetrics, out_path: str, prev_m: Optional[AggregatedMetrics] = None):
    """Exports structured markdown report for documentation and team digests."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# 🛡️ GravityGuard Telemetri ve Denetim Raporu",
        f"",
        f"- **Rapor Dönemi**: {m.label}",
        f"- **Oluşturulma Tarihi**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Toplam Denetlenen İşlem**: {m.total}",
        f"",
        f"## 📊 Genel Metrikler",
        f"",
        f"| Durum | Adet | Oran |",
        f"| :--- | :--- | :--- |",
    ]
    if m.total > 0:
        app_cnt = m.status_counts.get('APPROVED', 0)
        blk_cnt = m.status_counts.get('BLOCKED', 0)
        wrn_cnt = m.status_counts.get('WARNING', 0)
        lines.append(f"| ✅ Onaylanan (APPROVED) | {app_cnt} | %{(app_cnt / m.total * 100):.1f} |")
        lines.append(f"| 🛑 Engellenen (BLOCKED) | {blk_cnt} | %{(blk_cnt / m.total * 100):.1f} |")
        lines.append(f"| ⚠️ Uyarı Alan (WARNING) | {wrn_cnt} | %{(wrn_cnt / m.total * 100):.1f} |")

    lines.extend([
        f"",
        f"## 🎯 Etkinlik ve Kurtarma",
        f"",
        f"- **Engellenen Kök İhlaller**: {m.total_blocked}",
        f"- **Ajan Tarafından Düzeltilen**: {m.total_recovered} (İyileşme Oranı: %{m.recovery_rate:.1f})",
        f"- **Medyan Düzeltme Denemesi**: {m.median_attempts}",
        f"- **Ortalama Çözüm Süresi**: {m.avg_duration_s:.1f} sn",
        f"",
    ])

    if m.rule_blocked:
        lines.extend([
            f"### Kural Bazlı Engelleme ve İyileşme",
            f"",
            f"| Kural | Engelleme | Kurtarma | Oran |",
            f"| :--- | :--- | :--- | :--- |",
        ])
        for r, b in m.rule_blocked.most_common():
            rec = m.rule_recovered.get(r, 0)
            rate = (rec / b * 100) if b > 0 else 0.0
            lines.append(f"| `{r}` | {b} | {rec} | %{rate:.1f} |")
        lines.append("")

    if prev_m:
        lines.extend([
            f"## 📅 Dönemsel Karşılaştırma",
            f"",
            f"- **Önceki Dönem**: {prev_m.label}",
            f"- **Olay Sayısı Değişimi**: {m.total} vs {prev_m.total}",
            f"- **Engelleme Oranı Değişimi**: %{m.recovery_rate:.1f} vs %{prev_m.recovery_rate:.1f}",
            f"",
        ])

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ Markdown raporu kaydedildi: {out_path}")


def export_json_report(m: AggregatedMetrics, out_path: str):
    """Exports structured machine-readable JSON metrics."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "reportPeriod": m.label,
        "generatedAt": datetime.now().isoformat(),
        "totalEvents": m.total,
        "statusCounts": dict(m.status_counts),
        "ruleCounts": dict(m.rule_counts),
        "projectCounts": dict(m.project_counts),
        "fileExtCounts": dict(m.ext_counts),
        "effectiveness": {
            "totalBlocked": m.total_blocked,
            "totalRecovered": m.total_recovered,
            "recoveryRate": m.recovery_rate,
            "medianAttempts": m.median_attempts,
            "avgDurationSeconds": m.avg_duration_s,
            "ruleBlocked": dict(m.rule_blocked),
            "ruleRecovered": dict(m.rule_recovered),
        },
        "shadowRules": dict(m.shadow_rules),
        "warningRules": dict(m.warn_rules),
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"✅ JSON raporu kaydedildi: {out_path}")


def perform_log_rotation(threshold_mb: float = 10.0) -> None:
    """
    Checks active log file size and snapshots to archives if it exceeds threshold.
    Guards sequence continuity (lastAuditSeq) and live projection state.
    """
    active_path = Path(resolve_default_permanent_log_path())
    if not active_path.is_file():
        print(f"[i] Rotasyon yapılacak aktif log bulunamadı: {active_path}")
        return

    size_mb = active_path.stat().st_size / (1024 * 1024)
    print(f"Aktif Log: {active_path} ({size_mb:.2f} MB - Eşik: {threshold_mb:.2f} MB)")

    if size_mb < threshold_mb:
        print(f"✅ Dosya boyutu eşik değerin ({threshold_mb:.1f} MB) altında. Rotasyona gerek yok.")
        return

    archive_dir = Path(__file__).resolve().parent.parent / "archives" / "audit-logs"
    archive_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"gravityguard_permanent_audit_{timestamp}.jsonl"
    target_archive = archive_dir / archive_name

    # Safe snapshot under StateLock: Never wipe or truncate active journal!
    lock = StateLock(str(active_path.parent), timeout=5.0)
    lock_acquired = lock.acquire()
    try:
        shutil.copy2(active_path, target_archive)
    finally:
        if lock_acquired:
            lock.release()

    print(f"🎉 Arşivleme başarıyla tamamlandı (StateLock korumalı):")
    print(f"   Arşivlenen dosya : {target_archive} ({size_mb:.2f} MB)")
    print(f"   Aktif dosya      : {active_path} (Sıra numarası ve canlı projeksiyon güvenliği için korundu)")
    print(f"   [Güvenlik Notu] Kalıcı denetim günlüğü, auditSeq bütünlüğünü korumak için sıfırlanmaz.")


def main():
    parser = argparse.ArgumentParser(description="GravityGuard Telemetri ve Güvenlik Denetim Merkezi")
    parser.add_argument("--all", action="store_true", help="Tüm keşfedilen log kaynaklarını birleştir (Antigravity + Claude Code + arşivler)")
    parser.add_argument("--source", type=str, default="", help="Özel log dosyası veya klasörü yolu")
    parser.add_argument("--projects-root", type=str, default="", help="Birden fazla projeyi keşfetmek için ana çalışma alanı kök dizini")
    parser.add_argument("--project", type=str, default="", help="Yalnızca belirli projeyi filtrele")
    parser.add_argument("--rule", type=str, default="", help="Yalnızca belirli kuralı filtrele")
    parser.add_argument("--status", type=str, default="", help="Duruma göre filtrele (APPROVED, BLOCKED, WARNING)")
    parser.add_argument("--since", type=str, default="", help="Başlangıç tarihi (YYYY-MM-DD veya ISO)")
    parser.add_argument("--until", type=str, default="", help="Bitiş tarihi (YYYY-MM-DD veya ISO)")
    parser.add_argument("--days", type=int, default=0, help="Son N günü filtrele")
    parser.add_argument("--weekly", "-w", action="store_true", help="Son 7 gün ve önceki 7 günle karşılaştırmalı analiz")
    parser.add_argument("--monthly", "-m", action="store_true", help="Son 30 gün ve önceki 30 günle karşılaştırmalı analiz")
    parser.add_argument("--candidates", action="store_true", help="Kural geliştirme ve optimizasyon önerilerini göster")
    parser.add_argument("--export-md", type=str, default="", help="Markdown raporunu belirtilen dosyaya kaydet")
    parser.add_argument("--export-json", type=str, default="", help="JSON raporunu belirtilen dosyaya kaydet")
    parser.add_argument("--rotate", action="store_true", help="Log rotasyonu yap (büyük logları arşivle)")
    parser.add_argument("--threshold-mb", type=float, default=10.0, help="Log rotasyon eşiği MB (varsayılan: 10.0)")

    args = parser.parse_args()

    if args.rotate:
        perform_log_rotation(threshold_mb=args.threshold_mb)
        return

    # Determine log sources
    if args.all:
        sources = discover_all_log_paths(explicit_source=args.source, projects_root=args.projects_root)
    elif args.source:
        p = Path(args.source)
        sources = [p] if p.is_file() else list(p.glob("**/*.jsonl"))
    else:
        sources = [Path(resolve_default_permanent_log_path())]

    reader = LogStreamReader(sources)

    now = datetime.now(timezone.utc)
    since_dt: Optional[datetime] = None
    until_dt: Optional[datetime] = None
    label = "Tüm Zamanlar"

    prev_since_dt: Optional[datetime] = None
    prev_until_dt: Optional[datetime] = None
    prev_label = ""

    if args.weekly:
        since_dt = now - timedelta(days=7)
        until_dt = now
        label = "Son 7 Gün"
        prev_since_dt = now - timedelta(days=14)
        prev_until_dt = now - timedelta(days=7)
        prev_label = "Önceki 7 Gün"
    elif args.monthly:
        since_dt = now - timedelta(days=30)
        until_dt = now
        label = "Son 30 Gün"
        prev_since_dt = now - timedelta(days=60)
        prev_until_dt = now - timedelta(days=30)
        prev_label = "Önceki 30 Gün"
    elif args.days > 0:
        since_dt = now - timedelta(days=args.days)
        until_dt = now
        label = f"Son {args.days} Gün"
    else:
        if args.since:
            since_dt = parse_iso_datetime(args.since)
            label = f">= {args.since}"
        if args.until:
            until_dt = parse_iso_datetime(args.until)
            label += f" <= {args.until}"

    # Stream current period events without list buffering (O(1) memory)
    curr_metrics = AggregatedMetrics(
        reader.stream_events(
            since_dt=since_dt,
            until_dt=until_dt,
            project_filter=args.project,
            rule_filter=args.rule,
            status_filter=args.status,
        ),
        label=label,
    )

    # Stream previous period if comparative
    prev_metrics: Optional[AggregatedMetrics] = None
    if prev_since_dt and prev_until_dt:
        prev_metrics = AggregatedMetrics(
            reader.stream_events(
                since_dt=prev_since_dt,
                until_dt=prev_until_dt,
                project_filter=args.project,
                rule_filter=args.rule,
                status_filter=args.status,
            ),
            label=prev_label,
        )

    # Render view
    if args.candidates:
        render_rule_candidates(curr_metrics)
    else:
        render_dashboard(
            curr_metrics,
            sources=sources,
            corrupt_lines=reader.corrupted_lines_count,
            prev_m=prev_metrics,
        )

    # Exports
    if args.export_md:
        export_markdown_report(curr_metrics, args.export_md, prev_m=prev_metrics)
    if args.export_json:
        export_json_report(curr_metrics, args.export_json)


if __name__ == "__main__":
    main()
