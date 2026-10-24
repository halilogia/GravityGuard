#!/usr/bin/env python3
"""
============================================================================
GRAVITYGUARD REVIEW GOVERNANCE VERIFIER (Git Pre-Push / GitHub Gate)
============================================================================
Acts as the final release/push gate before code leaves the machine for GitHub:
- Evaluates outgoing git changes against ChatGPT R1.1 Risk-Gated Review Policy.
- Low-risk changes (<5 files, <120 lines, non-security) pass freely without bureaucracy.
- High-risk changes (security paths, dependency changes, scale >=5 files) require
  a verified, non-stale Self-Review record (.gravityguard/self-review/<id>.json).

Usage:
    python tools/verify_review_governance.py
"""

import sys
import subprocess
from pathlib import Path
from typing import List

_ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from gravityguard_engine.project_context import load_gravityguard_config
from gravityguard_engine.review_policy import (
    check_review_risk_triggers,
    is_review_enabled,
)
from gravityguard_engine.review_governance import (
    evaluate_review_obligations,
    record_final_diff_guard,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def get_git_root() -> Path:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True, stderr=subprocess.DEVNULL)
        return Path(out.strip())
    except (OSError, subprocess.SubprocessError) as err:
        sys.stderr.write(f"[GravityGuard] Note: git root fallback: {err}\n")
        return Path.cwd()


def get_outgoing_files(root: Path) -> List[str]:
    """Finds all files modified in outgoing commits or current working tree."""
    files = set()
    # 1. Unpushed commits relative to origin/main or origin/HEAD
    for remote_ref in ["origin/main", "origin/master", "@{u}"]:
        try:
            out = subprocess.check_output(
                ["git", "diff", "--name-only", f"{remote_ref}...HEAD"],
                cwd=str(root),
                text=True,
                stderr=subprocess.DEVNULL
            )
            files.update(line.strip().replace("\\", "/") for line in out.splitlines() if line.strip())
            if files:
                break
        except (OSError, subprocess.SubprocessError) as err:
            sys.stderr.write(f"[GravityGuard] Remote diff check {remote_ref} skipped: {err}\n")

    # 2. Also include staged & uncommitted changes
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=str(root),
            text=True,
            stderr=subprocess.DEVNULL
        )
        files.update(line.strip().replace("\\", "/") for line in out.splitlines() if line.strip())
    except (OSError, subprocess.SubprocessError) as err:
        sys.stderr.write(f"[GravityGuard] HEAD diff check skipped: {err}\n")

    return sorted(files)


def verify_review_governance() -> int:
    root = get_git_root()
    cfg = load_gravityguard_config("", root)

    if not is_review_enabled(cfg):
        print("ℹ️ [PRE-PUSH] Kod inceleme (review) bu projede kapalı; kontrol atlandı.")
        return 0

    changed_files = get_outgoing_files(root)
    if not changed_files:
        print("✅ [PRE-PUSH] Değişiklik yok; kontrol temiz.")
        return 0

    # Calculate total line changes
    total_lines = 0
    for rel in changed_files:
        p = root / rel
        if p.is_file():
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                    total_lines += sum(1 for _ in fp)
            except OSError as io_err:
                sys.stderr.write(f"[GravityGuard] Line count read skipped for {rel}: {io_err}\n")

    is_required, trigger_reason = check_review_risk_triggers(
        changed_files, cfg, root, total_lines_changed=total_lines
    )

    if not is_required:
        print(f"✅ [PRE-PUSH] Düşük riskli değişiklik ({len(changed_files)} dosya); Self-Review muafiyeti sağlandı.")
        return 0

    # High-risk: verify that review obligations are fulfilled
    record_final_diff_guard(root, "pre-push-gate", cfg)
    report = evaluate_review_obligations(root, "pre-push-gate", cfg)

    unresolved = report.get("unresolved", {})
    if unresolved:
        print("🛑 [PRE-PUSH ERROR] Yüksek Riskli Değişiklik - Kod İnceleme Şartı (R1):")
        print(f"   Tetikleyici: {trigger_reason}")
        print("   GitHub'a push etmeden önce aşağıdaki inceleme yükümlülüğü tamamlanmalıdır:")
        for r_id, info in unresolved.items():
            probs = ", ".join(info.get("problems", []))
            print(f"     - İnceleme ID: {r_id} (Eksikler: {probs})")
        print("\n   👉 Lütfen diff'inizi okuyup '.gravityguard/self-review/<id>.json' dosyasını oluşturun.")
        print("      Push iptal edildi.")
        return 1

    print("✅ [PRE-PUSH] Yüksek riskli değişiklik için mühürlü Self-Review kaydı doğrulandı. Push izni verildi.")
    return 0


if __name__ == "__main__":
    sys.exit(verify_review_governance())
