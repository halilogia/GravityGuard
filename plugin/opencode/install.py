#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Installs the GravityGuard OpenCode plugin into the global OpenCode plugin directory.

    python plugin/opencode/install.py            # copy plugin + verify engine
    python plugin/opencode/install.py --check    # drift check only, nothing written

Exit codes: 0 ok, 1 drift (--check), 2 error.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "gravityguard_opencode_plugin.ts"
TARGET_DIR = Path.home() / ".config" / "opencode" / "plugins"
TARGET = TARGET_DIR / "gravityguard.ts"
ENGINE = HERE.parent.parent / "engine" / "gravity-validator.py"
ADAPTER = HERE / "gravityguard_opencode_hook.py"
BACKUP_DIR = Path.home() / ".gravityguard" / "maintenance" / "deployment-backups" / "opencode-plugin"


def digest(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="GravityGuard OpenCode plugin installer")
    parser.add_argument("--check", action="store_true", help="only report drift, write nothing")
    args = parser.parse_args()

    for required in (SOURCE, ENGINE, ADAPTER):
        if not required.is_file():
            print(f"HATA: eksik dosya: {required}")
            return 2

    print(f"kaynak : {SOURCE}")
    print(f"hedef  : {TARGET}")
    print(f"motor  : {ENGINE}")

    if TARGET.is_file() and digest(SOURCE) == digest(TARGET):
        print("durum  : SENKRON (kurulu surum kaynakla ayni)")
        return 0

    state = "DRIFT" if TARGET.is_file() else "YENI"
    if args.check:
        print(f"durum  : {state} -> kurulum gerekli")
        return 1

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    if TARGET.is_file():
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup = BACKUP_DIR / f"{TARGET.name}.{time.strftime('%Y%m%d-%H%M%S')}.bak"
        shutil.copy2(TARGET, backup)
        print(f"yedek  : {backup}")

    shutil.copy2(SOURCE, TARGET)
    if digest(SOURCE) != digest(TARGET):
        print("HATA: kopya sonrasi icerik uyusmuyor")
        return 2

    print(f"OK     : {state} -> kuruldu ({TARGET.stat().st_size} B)")
    print("not    : OpenCode'u yeniden baslat (plugin'ler acilista yuklenir)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
