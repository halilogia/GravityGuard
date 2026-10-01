#!/usr/bin/env python3
"""
============================================================================
GRAVITYGUARD TELEMETRY ANALYTICS DASHBOARD
============================================================================
Reads `gravityguard_permanent_audit.jsonl` and aggregates security metrics,
violation distributions, project heatmaps, and adversarial bypass telemetry.
"""

import os
import sys
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def resolve_permanent_log_path() -> str:
    """Finds the permanent audit JSONL file."""
    repo_archive = Path(r"C:\Users\Halil Emre\Desktop\GitHub\Public\GravityGuard\archives\audit-logs\gravityguard_permanent_audit.jsonl")
    if repo_archive.is_file():
        return str(repo_archive)

    user_log = Path(os.path.expanduser(r"~/.gemini/logs\gravityguard_permanent_audit.jsonl"))
    if user_log.is_file():
        return str(user_log)

    return str(repo_archive)


def load_telemetry_events(log_path: str):
    """Loads and parses JSONL records safely."""
    events = []
    if not os.path.exists(log_path):
        return events

    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception as e:
                # Malformed telemetry line, skip
                continue
    return events


def format_bar(val: int, max_val: int, width: int = 24) -> str:
    if max_val <= 0:
        return ""
    filled = int((val / max_val) * width)
    return "█" * filled + "░" * (width - filled)


def render_dashboard(events):
    print("=" * 80)
    print("           GRAVITYGUARD GÜVENLİK VE MİMARİ TELEMETRİ MERKEZİ            ")
    print("=" * 80)

    if not events:
        print("\n[!] Henüz telemetri kaydı bulunamadı. Gardiyan aktif olarak çalışmaya başladıkça")
        print("    tüm hook çağrıları 'gravityguard_permanent_audit.jsonl' dosyasına işlenecektir.\n")
        print("=" * 80)
        return

    total = len(events)
    status_counts = Counter(e.get("status", "UNKNOWN") for e in events)
    rule_counts = Counter(e.get("ruleId", "UNKNOWN") for e in events)
    project_counts = Counter(e.get("project") or "Diğer / Bilinmeyen" for e in events)
    ext_counts = Counter(e.get("fileExt") or "(Uzantısız)" for e in events)

    blocked = status_counts.get("BLOCKED", 0)
    warnings = status_counts.get("WARNING", 0)
    approved = status_counts.get("APPROVED", 0)

    print(f"\n📊 GENEL ÖZET (Toplam Denetlenen İşlem: {total})")
    print("-" * 80)
    print(f"  ✅ ONAYLANAN (APPROVED)  : {approved:<5} %{(approved / total * 100):.1f}")
    print(f"  🛑 ENGELLENEN (BLOCKED)  : {blocked:<5} %{(blocked / total * 100):.1f}")
    print(f"  ⚠️  UYARI ALAN (WARNING)  : {warnings:<5} %{(warnings / total * 100):.1f}")

    print("\n🛡️  KURAL BAZLI İHLAL VE GÜVENLİK DAĞILIMI (Top Rules)")
    print("-" * 80)
    top_rules = rule_counts.most_common(12)
    max_rule_cnt = top_rules[0][1] if top_rules else 1
    for rule, cnt in top_rules:
        pct = (cnt / total) * 100
        bar = format_bar(cnt, max_rule_cnt, width=20)
        status_tag = "🛑" if "BLOCK" in rule or rule in {"G0_SECRET_LEAK", "G1_SILENT_EXCEPTION", "G2_TEST_INTEGRITY", "G2_SECURITY_TAMPERING", "G4_IMPORT_MATRIX", "SRP_BOUNDARY"} else "⚠️"
        print(f"  {status_tag} {rule:<25} | {cnt:>4} adet ({pct:>5.1f}%) | {bar}")

    print("\n📁 PROJE DAĞILIMI (Ajanın En Çok Kod Yazdığı Projeler)")
    print("-" * 80)
    top_projects = project_counts.most_common(8)
    max_proj_cnt = top_projects[0][1] if top_projects else 1
    for proj, cnt in top_projects:
        pct = (cnt / total) * 100
        bar = format_bar(cnt, max_proj_cnt, width=16)
        print(f"  📦 {proj:<24} | {cnt:>4} işlem (%{pct:>4.1f}) | {bar}")

    print("\n📝 DOSYA TÜRÜ DAĞILIMI")
    print("-" * 80)
    for ext, cnt in ext_counts.most_common(6):
        pct = (cnt / total) * 100
        print(f"  📄 {ext:<12} : {cnt:>4} (%{pct:>4.1f})")

    print("\n🚨 SON 5 GÜVENLİK / MİMARİ MÜDAHALESİ (Canlı Hadiseler)")
    print("-" * 80)
    blocked_or_warned = [e for e in reversed(events) if e.get("status") in ("BLOCKED", "WARNING")][:5]
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
    print("Log Kaynağı: " + resolve_permanent_log_path())
    print("=" * 80)


def main():
    log_path = resolve_permanent_log_path()
    events = load_telemetry_events(log_path)
    render_dashboard(events)


if __name__ == "__main__":
    main()
