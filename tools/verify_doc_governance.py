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
from typing import List, Tuple

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


def is_governed_code_file(path_str: str) -> bool:
    p = path_str.replace("\\", "/").lower()

    # Exclude tests, temporary/runtime dirs, and docs
    if any(m in p for m in ["/tests/", "/test/", "test_", ".test.", ".spec.", ".gravityguard/", "archives/"]):
        return False
    if p.endswith((".md", ".txt", ".json", ".lock", ".svg", ".png", ".jpg", ".ico")):
        # Only plugin/hooks.json or rules/*.md might be governed, but hooks.json is handled below
        if not p.endswith("plugin/hooks.json"):
            return False

    parts = [part.lower() for part in Path(p).parts]
    governed_roots = {"engine", "src", "plugin", "rules", "tools"}
    return any(g in parts for g in governed_roots)


def verify_doc_governance(staged_only: bool = True) -> Tuple[bool, List[str]]:
    files = get_staged_files() if staged_only else (get_staged_files() or get_working_tree_files())
    if not files:
        return True, ["Staged veya değiştirilmiş dosya bulunamadı; denetim temiz."]

    git_root = get_git_root()
    staged_code_files = [f for f in files if is_governed_code_file(f)]
    
    if not staged_code_files:
        return True, ["Staged dosyalar arasında motor veya davranış kodu bulunamadı; dokümantasyon zorunluluğu yok."]

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
