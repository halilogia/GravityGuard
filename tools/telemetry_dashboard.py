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


def render_rule_candidates(events):
    print("=" * 80)
    print("      GRAVITYGUARD KURAL ADAYLARI & ÖĞRENME DEFTERİ (Learning Ledger)    ")
    print("=" * 80)

    if not events:
        print("\n[!] Yeterli telemetri verisi bulunamadı.\n")
        print("=" * 80)
        return

    violations = [e for e in events if e.get("status") in ("BLOCKED", "WARNING")]
    if not violations:
        print("\n[✓] Telemetri verilerinde henüz ihlal veya uyarı kaydı yok.")
        print("    Mevcut politikalar sistemle tam uyumlu çalışıyor.\n")
        print("=" * 80)
        return

    rule_counter = Counter(e.get("ruleId") for e in violations)
    rule_targets = defaultdict(list)
    for e in violations:
        r_id = e.get("ruleId", "UNKNOWN")
        target = os.path.basename(e.get("target", "bilinmeyen"))
        rule_targets[r_id].append(target)

    candidates = []

    # 1. G4 Import Matrix Analysis
    g4_count = rule_counter.get("G4_IMPORT_MATRIX", 0)
    if g4_count > 0:
        targets = Counter(rule_targets["G4_IMPORT_MATRIX"]).most_common(3)
        candidates.append({
            "id": "CAND-G4-BOUNDARY-REFINEMENT",
            "rule": "G4_IMPORT_MATRIX",
            "count": g4_count,
            "targets": [t[0] for t in targets],
            "diagnosis": "Ajanın belirli katmanlar arasında sıkça sınır ihlali yaptığı gözlemlendi.",
            "recommendation": ".gravityguard.json içerisindeki 'layers' matrisini gözden geçirin veya ilgili modülü paylaşılan (shared) katmana taşıyın."
        })

    # 2. T1 Test Evidence Analysis
    t1_count = rule_counter.get("T1_MISSING_RELATED_TEST", 0) + rule_counter.get("T1_FINAL_UNRESOLVED", 0)
    if t1_count > 0:
        targets = Counter(rule_targets.get("T1_MISSING_RELATED_TEST", []) + rule_targets.get("T1_FINAL_UNRESOLVED", [])).most_common(3)
        candidates.append({
            "id": "CAND-T1-EXEMPTION-EXPANSION",
            "rule": "T1_MISSING_RELATED_TEST",
            "count": t1_count,
            "targets": [t[0] for t in targets],
            "diagnosis": "Belirli üretim dosyaları için eşleşen test dosyası bulunamadı veya oturum sonuna kadar eklenmedi.",
            "recommendation": "Bu dosyalar konfigürasyon/şema niteliğindeyse 'exemptPatterns' listesine ekleyin; iş mantığı içeriyorsa test süitine dahil edin."
        })

    # 3. Growth / Monolith Analysis
    growth_count = rule_counter.get("ARCH_FILE_GROWTH", 0)
    if growth_count > 0:
        targets = Counter(rule_targets["ARCH_FILE_GROWTH"]).most_common(3)
        candidates.append({
            "id": "CAND-SRP-MODULARIZATION",
            "rule": "ARCH_FILE_GROWTH",
            "count": growth_count,
            "targets": [t[0] for t in targets],
            "diagnosis": "Mevcut dosyalara tek seferde 180+ satır ekleme veya kümülatif büyüme uyarıları alındı.",
            "recommendation": "Dosyayı srp-modularizer ile alt bileşenlere ayırın ya da bilinçli bir büyüme ise 'srp: allow-monolith' etiketi ekleyin."
        })

    # 4. G1 Silent Exception Analysis
    g1_count = rule_counter.get("G1_SILENT_EXCEPTION", 0)
    if g1_count > 0:
        targets = Counter(rule_targets["G1_SILENT_EXCEPTION"]).most_common(3)
        candidates.append({
            "id": "CAND-G1-EXCEPTION-STANDARDS",
            "rule": "G1_SILENT_EXCEPTION",
            "count": g1_count,
            "targets": [t[0] for t in targets],
            "diagnosis": "Ajanın sessiz hata yutma (except: pass / catch {}) teşebbüsleri engellendi.",
            "recommendation": "Ajan promptunda hata yakalama disiplinini (#kodla direktifi) vurgulayın veya loglama zorunluluğu getirin."
        })

    # 5. G2 Tampering Analysis
    g2_count = rule_counter.get("G2_SECURITY_TAMPERING", 0) + rule_counter.get("G2_TEST_INTEGRITY", 0)
    if g2_count > 0:
        candidates.append({
            "id": "CAND-G2-TAMPERING-ALERT",
            "rule": "G2_SECURITY_TAMPERING",
            "count": g2_count,
            "targets": [t[0] for t in Counter(rule_targets.get("G2_SECURITY_TAMPERING", []) + rule_targets.get("G2_TEST_INTEGRITY", [])).most_common(3)],
            "diagnosis": "Test silme, test atlatma veya yapay escape-hatch enjeksiyon denemesi tespit edildi.",
            "recommendation": "Kural atlatma denemelerine karşı red-teaming denetimini sıkılaştırın ve prompt kurallarını güncelleyin."
        })

    print(f"\n📋 BULUNAN KURAL ADAYLARI ({len(candidates)} Öneri)")
    print("-" * 80)
    for c in candidates:
        print(f"\n🔹 [{c['id']}] (Tetiklenme: {c['count']} kez | Kural: {c['rule']})")
        print(f"   Etkilenen Dosyalar : {', '.join(c['targets'])}")
        print(f"   Teşhis             : {c['diagnosis']}")
        print(f"   Önerilen Aksiyon   : {c['recommendation']}")

    print("\n" + "=" * 80)
    print("Not: Kural adayları insan denetimi (Human-in-the-Loop) içindir; otonom kural gevşetme yapılmaz.")
    print("=" * 80)


def main():
    log_path = resolve_permanent_log_path()
    events = load_telemetry_events(log_path)
    if "--candidates" in sys.argv:
        render_rule_candidates(events)
    else:
        render_dashboard(events)


if __name__ == "__main__":
    main()
