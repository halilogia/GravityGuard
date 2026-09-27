#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Commit oncesi: repo motorunu canli plugin kopyasina senkronize eder.

NEDEN:
    GravityGuard'in motoru iki yerde durur:
      repo  : engine/gravity-validator.py   (GitHub kaynagi)
      plugin: ~/.gemini/config/plugins/srp-swarm-guardian/scripts/gravity-validator.py
              (Antigravity hook'unun calistirdigi CANLI dosya)

    Kopyayi yok etmek mumkun degil. Bu script, commit aninda tek kural uygular:
    "repo'ya giren surum canliya da girer".

    HANGI DOSYALARIN senkronize edilecegi TEK YERDE tanimlidir
    (sync_plugin.PAIRS) ve burada ice aktarilir. Onceki surum bu listeyi iki
    dosyada ayri ayri tasiyordu; isim degistiginde otomatik senkron eski adi
    geri getirmeye devam etti ve canli plugin'de bayat bir kopya birikiyordu.
    Yani ayni hatayi ureten sey, senkronu iki yerde tanimlamaktti.

TASARIM KARARI - neden commit'i ENGELLEMEZ:
    Bu bir kolayliktir, guvenlik siniri DEGILDIR. Plugin klasoru olmayan bir
    makinede commit'in durmasi yanlis olur. Bu yuzden:
      - Basarili senkron      -> 0 (commit devam eder)
      - Hic fark yok          -> 0 (sessiz, commit devam eder)
      - Senkron CAGISILAMAZ   -> 0 + aciklama (commit YINE devam eder)
      - Kaynakta Python sozdizimi bozuksa -> 1 (commit durur; bozuk kod canli
        korumaya sizmamali)

    Cikis kodlari:
      0 -> commit devam etsin
      1 -> commit DURDUR (yalnizca kaynak bozuksa)

KURULUM (pre-commit zaten bagliyor):
    .git/hooks/pre-commit icinde:
        TOPLEVEL=$(git rev-parse --show-toplevel)
        [ -f "$TOPLEVEL/tools/autosync_plugin.py" ] && python "$TOPLEVEL/tools/autosync_plugin.py"
"""
from __future__ import annotations

import ast
import hashlib
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sync_plugin import BACKUP_DIR, PAIRS, PLUGIN_DIR  # noqa: E402

PREFIX = "[autosync] "


def md5(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


def main() -> int:
    # Script tools/ icinde; repo koku bir seviye yukarisi.
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 1) Ortam uygun mu? Degilse sessizce cik - commit engellenmez.
    if not os.path.isdir(PLUGIN_DIR):
        print(PREFIX + "plugin klasoru yok, senkron atlandi (commit etkilenmez).")
        return 0

    # 2) Kaynak dosyalarin sozdizimini ONCE kontrol et.
    #    Bozuksa commit'i durdur; bozuk kod canli koruma zincirine girmemeli.
    for repo_rel, plug_rel, _desc in PAIRS:
        src = os.path.join(repo, repo_rel.replace("/", os.sep))
        if not os.path.isfile(src):
            continue
        try:
            with open(src, "r", encoding="utf-8", errors="replace") as fh:
                ast.parse(fh.read(), filename=src)
        except SyntaxError as exc:
            print(PREFIX + "HATA: %s bozuk -> satir %s: %s" % (repo_rel, exc.lineno, exc.msg))
            print(PREFIX + "Bozuk kod canli korumaya sizmasin diye commit durduruldu.")
            return 1

    # 3) Fark var mi?
    drifted = []
    for repo_rel, plug_rel, _desc in PAIRS:
        src = os.path.join(repo, repo_rel.replace("/", os.sep))
        dst = os.path.join(PLUGIN_DIR, plug_rel.replace("/", os.sep))
        if not os.path.isfile(src):
            continue
        if not os.path.isfile(dst):
            drifted.append((src, dst, plug_rel, "YENI"))
            continue
        if md5(src) != md5(dst):
            drifted.append((src, dst, plug_rel, "DRIFT"))

    if not drifted:
        return 0  # Sessiz: her commit'te gurultu yapma.

    # 4) Senkronize et.
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    ok, failed = [], []
    for src, dst, plug_rel, kind in drifted:
        base = os.path.basename(dst)
        try:
            if os.path.isfile(dst):
                shutil.copy2(dst, os.path.join(BACKUP_DIR, "%s.autosync-%s.bak" % (base, stamp)))
            shutil.copy2(src, dst)
            if md5(src) == md5(dst):
                ok.append((base, kind, os.path.getsize(dst)))
            else:
                failed.append(base)
        except OSError as exc:
            failed.append("%s (%s)" % (base, exc))

    for base, kind, size in ok:
        print(PREFIX + "%s %s -> %d B (dogrulandi)" % (kind, base, size))
    for base in failed:
        print(PREFIX + "UYARI: %s senkronlanamadi (yedek: %s)" % (base, BACKUP_DIR))

    if ok:
        print(PREFIX + "Canli plugin guncellendi. Antigravity'yi yeniden yukleyin.")
    # Kopyalama hatasi olsa bile commit DEVAM eder (kolaylik, kapi degil).
    return 0


if __name__ == "__main__":
    sys.exit(main())
