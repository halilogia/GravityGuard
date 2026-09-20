#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GravityGuard motor dosyalarini canli plugin kopyasina senkronize eder.

NEDEN VAR:
    Ayni kod iki yerde duruyor:
      - Repo  : GravityGuard/engine/gravity-validator.py  (GitHub'a giden kaynak)
      - Plugin: ~/.gemini/config/plugins/.../scripts/srp-validator.py  (Antigravity'nin
                hook ile calistirdigi CANLI kopya)

    Kopyayi yok etmek mumkun degil (plugin klasoru ile repo klasoru ayri ayri
    yasamak zorunda). Bu script, "biri guncellenip digeri unutulur ve koruma
    sessizce eskir" riskini tek komuta indirir.

KULLANIM:
    python tools/sync_plugin.py --check    # sadece fark var mi? (kopyalamaz)
    python tools/sync_plugin.py            # senkronize et (yedek alir)
    python tools/sync_plugin.py --dry-run  # ne yapacagini yazar, dokunmaz

CIKIS KODU:
    0 -> senkron / --dry-run basarili
    1 -> --check modunda fark bulundu  (drift)
    2 -> hata (kaynak yok, syntax bozuk, plugin klasoru yok)
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import os
import shutil
import sys
import time

# (repo tarafi, plugin tarafi, aciklama)
PAIRS = [
    ("engine/gravity-validator.py", "scripts/srp-validator.py", "Ana dogrulama motoru"),
    ("engine/async_runner.py", "scripts/async_runner.py", "Arka plan statik analiz calistiricisi"),
]

PLUGIN_DIR = os.path.join(
    os.path.expanduser("~"), ".gemini", "config", "plugins", "srp-swarm-guardian"
)
BACKUP_DIR = os.path.join(os.path.expanduser("~"), ".git-hook-backups", "plugin-sync")


def md5(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


def repo_root() -> str:
    """Bu script'in bulundugu yerden repo kokunu bulur (tools/ -> repo)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def syntax_ok(path: str) -> tuple[bool, str]:
    """Dosya gecerli Python mu? (ast.parse - hic dosya uretmez)."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            ast.parse(fh.read(), filename=path)
        return True, ""
    except SyntaxError as exc:
        return False, "satir %s: %s" % (exc.lineno, exc.msg)


def main() -> int:
    ap = argparse.ArgumentParser(description="Repo motorunu canli plugin'e senkronize et")
    ap.add_argument("--check", action="store_true", help="Sadece fark var mi kontrol et, kopyalama")
    ap.add_argument("--dry-run", action="store_true", help="Ne yapilacagini yaz, hicbir sey degistirme")
    args = ap.parse_args()

    root = repo_root()
    print("Repo kok : %s" % root)
    print("Plugin   : %s" % PLUGIN_DIR)
    print()

    if not os.path.isdir(PLUGIN_DIR):
        print("HATA: plugin klasoru bulunamadi: %s" % PLUGIN_DIR)
        return 2

    drifted = []
    errors = []
    stamp = time.strftime("%Y%m%d-%H%M%S")

    for repo_rel, plug_rel, desc in PAIRS:
        src = os.path.join(root, repo_rel.replace("/", os.sep))
        dst = os.path.join(PLUGIN_DIR, plug_rel.replace("/", os.sep))

        print("-" * 68)
        print("%s  (%s)" % (os.path.basename(repo_rel), desc))
        print("  kaynak: %s" % repo_rel)
        print("  hedef : scripts/%s" % os.path.basename(plug_rel))

        if not os.path.isfile(src):
            print("  HATA  : kaynak dosya yok")
            errors.append(repo_rel)
            continue

        ok, msg = syntax_ok(src)
        if not ok:
            print("  HATA  : kaynakta Python sozdizimi bozuk -> %s" % msg)
            errors.append(repo_rel)
            continue
        print("  sozdizimi: GECERLI")

        if not os.path.isfile(dst):
            print("  durum : hedef YOK (ilk kurulum)")
            drifted.append((src, dst, repo_rel, plug_rel, stamp, "YENI"))
            continue

        h_src, h_dst = md5(src), md5(dst)
        sz_src, sz_dst = os.path.getsize(src), os.path.getsize(dst)

        if h_src == h_dst:
            print("  durum : SENKRON (%d B)" % sz_src)
            continue

        print("  durum : FARKLI  <- drift")
        print("          repo  : %7d B  %s" % (sz_src, h_src[:8]))
        print("          plugin: %7d B  %s" % (sz_dst, h_dst[:8]))
        drifted.append((src, dst, repo_rel, plug_rel, stamp, "DRIFT"))

    print("-" * 68)
    print()

    if errors:
        print("SONUC: %d dosyada hata var, senkronizasyon YAPILMADI." % len(errors))
        return 2

    if not drifted:
        print("SONUC: Her sey senkron. Yapilacak is yok.")
        return 0

    print("SONUC: %d dosya guncellenmeli:" % len(drifted))
    for _, _, repo_rel, plug_rel, _, kind in drifted:
        print("   [%s] %s -> %s" % (kind, repo_rel, plug_rel))
    print()

    if args.check:
        print("(--check modu: hicbir sey degistirilmedi)")
        return 1

    if args.dry_run:
        print("(--dry-run modu: hicbir sey degistirilmedi)")
        return 0

    os.makedirs(BACKUP_DIR, exist_ok=True)
    print("Yedekler: %s" % BACKUP_DIR)
    print()

    failed = []
    for src, dst, repo_rel, plug_rel, st, kind in drifted:
        base = os.path.basename(dst)
        if os.path.isfile(dst):
            bak = os.path.join(BACKUP_DIR, "%s.pluginsync-%s.bak" % (base, st))
            shutil.copy2(dst, bak)
            print("  yedek  : %s" % os.path.basename(bak))

        try:
            shutil.copy2(src, dst)
        except OSError as exc:
            print("  HATA   : kopyalanamadi -> %s" % exc)
            failed.append(plug_rel)
            continue

        if md5(src) == md5(dst):
            print("  OK     : %s  (%d B, dogrulandi)" % (base, os.path.getsize(dst)))
        else:
            print("  HATA   : kopya sonrasi icerik uyusmuyor -> %s" % base)
            failed.append(plug_rel)

    print()
    if failed:
        print("SONUC: %d dosya dogrulanamadi." % len(failed))
        return 2

    print("SONUC: Senkronizasyon tamam. Degisiklik icin Antigravity'yi yeniden yuklemen")
    print("       gerekebilir (plugin hook'lari yeniden okunmali).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
