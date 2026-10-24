#!/usr/bin/env python3
"""
============================================================================
GRAVITYGUARD REMOVAL GOVERNANCE VERIFIER (Git Pre-Commit Gate)
============================================================================
Inspects staged git deletions during `git commit`:
Detects if any test file was deleted while its subject source code remains.
Features can be deleted, but deleting tests while keeping the feature is sabotage.

Usage:
    python tools/verify_removal_governance.py
"""

import sys
import subprocess
from pathlib import Path

_ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from gravityguard_engine.removal_observer import (
    deleted_paths,
    is_test_path,
    suspicious_test_deletions,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def get_git_root() -> Path:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True, stderr=subprocess.DEVNULL)
        return Path(out.strip())
    except Exception:
        return Path.cwd()


def verify_removals() -> int:
    root = get_git_root()
    all_deleted = deleted_paths(root)
    if not all_deleted:
        print("✅ [PRE-COMMIT] Silinen dosya yok; test bütünlüğü temiz.")
        return 0

    tests = [p for p in all_deleted if is_test_path(p)]
    if not tests:
        return 0

    suspicious = suspicious_test_deletions(root, tests, set(all_deleted))
    if suspicious:
        print("🛑 [PRE-COMMIT ERROR] Test Silme İhlali (TEST_DELETED_SUBJECT_REMAINS):")
        print("   Aşağıdaki test dosyaları silindi ancak test ettiği kaynak kod hâlâ duruyor:")
        for t in suspicious:
            print(f"     - {t}")
        print("\n   👉 Özellik gerçekten kaldırıldıysa kodunu da silin; aksi takdirde testi geri getirin.")
        print("      Commit iptal edildi.")
        return 1

    print("✅ [PRE-COMMIT] Silinen testlerin kaynak kodları da kaldırılmış; meşru temizlik doğrulandı.")
    return 0


if __name__ == "__main__":
    sys.exit(verify_removals())
