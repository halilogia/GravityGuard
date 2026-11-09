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
            return False  # Display-only fallback; never mutate without the real lock.
        def release(self):
            pass


_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)
from telemetry_data import (  # noqa: E402,F401
    AggregatedMetrics,
    LogStreamReader,
    discover_all_log_paths,
    format_bar,
    parse_iso_datetime,
    resolve_default_permanent_log_path,
)
from telemetry_render import (  # noqa: E402,F401
    export_json_report,
    export_markdown_report,
    render_dashboard,
    render_effectiveness_analytics,
    render_period_comparison,
    render_rule_candidates,
)


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

    archive_dir = Path.home() / ".gravityguard" / "maintenance" / "snapshots"
    archive_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"gravityguard_permanent_audit_{timestamp}.jsonl"
    target_archive = archive_dir / archive_name

    # Safe snapshot under StateLock: Must synchronize on the exact same .audit.lock file as audit.py!
    audit_lock_path = active_path.parent / ".audit.lock"
    lock = StateLock(audit_lock_path, timeout=5.0)
    lock_acquired = lock.acquire()
    if not lock_acquired:
        print(f"[!] Hata: .audit.lock kilidi zaman aşımına uğradı ({audit_lock_path}). Yazma çakışmasını önlemek için arşivleme durduruldu.")
        return

    try:
        shutil.copy2(active_path, target_archive)
    finally:
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
