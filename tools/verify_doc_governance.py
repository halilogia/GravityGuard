#!/usr/bin/env python3
"""
============================================================================
GRAVITYGUARD DOC GOVERNANCE VERIFIER (docs/KNOWLEDGE.md §6)
============================================================================
Enforces the "Same-Commit Rule" during git pre-commit:
Any commit altering engine behavior, rules, or core plugin code must include
an update to `CHANGELOG.md` (and `docs/KNOWLEDGE.md` if standing invariants change).

Usage:
    python tools/verify_doc_governance.py [--check] [--all]
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

# The path policy is the engine's (gravityguard_engine/doc_policy.py): the Stop-time tracker and this commit gate must
# never disagree about which files owe a CHANGELOG entry. The engine is found relative to THIS file, so the script can
# also be run from another repository's pre-commit hook (cwd = that repository).
_ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from gravityguard_engine.doc_policy import is_doc_governed_path  # noqa: E402
from gravityguard_engine.project_context import load_gravityguard_config, should_enforce_doc_obligations  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def get_git_root() -> Path:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True, stderr=subprocess.DEVNULL)
        return Path(out.strip())
    except Exception:
        return Path.cwd()


def get_staged_files() -> List[str]:
    try:
        out = subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True, stderr=subprocess.DEVNULL)
        return [line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()]
    except Exception:
        return []


def get_working_tree_files() -> List[str]:
    try:
        out = subprocess.check_output(["git", "diff", "--name-only"], text=True, stderr=subprocess.DEVNULL)
        return [line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()]
    except Exception:
        return []


def is_governed_code_file(path_str: str, cfg: Optional[dict] = None, project_root: Optional[Path] = None) -> bool:
    return is_doc_governed_path(path_str, cfg, project_root)


def has_substantive_changes(file_path: str, staged_only: bool = True) -> bool:
    """
    Checks if diff contains actual executable code modifications,
    ignoring comments-only and blank-line-only edits.
    """
    try:
        cmd = ["git", "diff", "--cached" if staged_only else "HEAD", "-U0", "--", file_path]
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
        changed_lines = [
            line[1:].strip()
            for line in out.splitlines()
            if (line.startswith("+") and not line.startswith("+++")) or (line.startswith("-") and not line.startswith("---"))
        ]
        substantive = [
            l for l in changed_lines
            if l and not l.startswith(("#", "//", "/*", "*", "'''", '"""'))
        ]
        return len(substantive) > 0
    except Exception:
        return True


def verify_doc_governance(staged_only: bool = True) -> Tuple[bool, List[str]]:
    files = get_staged_files() if staged_only else (get_staged_files() or get_working_tree_files())
    if not files:
        return True, ["Staged veya değiştirilmiş dosya bulunamadı; denetim temiz."]

    git_root = get_git_root()
    cfg = load_gravityguard_config("", git_root)
    if not should_enforce_doc_obligations(cfg=cfg):
        return True, ["Dokümantasyon denetimi bu projede kapalı (.gravityguard.json → governance.enforceDocObligations); atlandı."]
    staged_code_files = [
        f for f in files
        if is_governed_code_file(str(git_root / f), cfg, git_root) and has_substantive_changes(f, staged_only=staged_only)
    ]
    
    if not staged_code_files:
        return True, ["Staged dosyalar arasında motor veya davranış kodu değişikliği bulunamadı; dokümantasyon zorunluluğu yok."]

    # Check if CHANGELOG.md is among the staged/changed files
    has_changelog = any(f.lower().endswith("changelog.md") for f in files)
    
    violations = []
    if not has_changelog:
        violations.append(
            "🛑 [DOC GOVERNANCE ERROR] docs/KNOWLEDGE.md §6 Same-Commit Rule İhlali:\n"
            "   Aşağıdaki motor/davranış dosyaları değiştirildi ancak 'CHANGELOG.md' staged dosyalar arasında yok:\n"
            + "\n".join(f"     - {f}" for f in staged_code_files)
            + "\n\n   👉 Lütfen yapılan değişikliği ve gerekçesini CHANGELOG.md dosyasına ekleyip commit'e dahil edin:\n"
            "      git add CHANGELOG.md"
        )

    # Check if docs/KNOWLEDGE.md was updated and if brain/knowledge.md exists to mirror
    if any(f.lower().endswith("docs/knowledge.md") for f in files):
        knowledge_src = git_root / "docs" / "KNOWLEDGE.md"
        brain_mirror = git_root / "brain" / "knowledge.md"
        if brain_mirror.parent.exists():
            try:
                if knowledge_src.exists():
                    brain_mirror.write_text(knowledge_src.read_text(encoding="utf-8"), encoding="utf-8")
                    violations.append("ℹ️ [DOC MIRROR] 'docs/KNOWLEDGE.md' senkronize edildi -> 'brain/knowledge.md'")
            except Exception as e:
                violations.append(f"⚠️ [DOC MIRROR WARNING] brain/knowledge.md kopyalanamadı: {e}")

    is_clean = len([v for v in violations if v.startswith("🛑")]) == 0
    return is_clean, violations


def main():
    staged_only = "--all" not in sys.argv
    is_clean, messages = verify_doc_governance(staged_only=staged_only)

    for msg in messages:
        print(msg)

    if not is_clean:
        sys.exit(1)

    print("✅ [DOC GOVERNANCE OK] Dokümantasyon yükümlülükleri (docs/KNOWLEDGE.md §6) eksiksiz doğrulandı.")
    sys.exit(0)


if __name__ == "__main__":
    main()
