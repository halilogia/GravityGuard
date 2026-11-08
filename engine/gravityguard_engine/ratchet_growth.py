"""PreToolUse side of the debt ratchet: the hard growth lock and the session's touched-file memory.

- ARCH_RATCHET_GROWTH_DENY: a source file that already has at least ``ratchetLoc`` lines may not gain lines
  (net delta > 0 is denied; any refactor or shrink, delta <= 0, is always allowed).
- G5_NEW_FILE_BLOAT_DENY: a brand-new source file above ``newFileMaxLoc`` (see debt_ratchet.check_new_file_bloat).
- Every write to a governed source file also records the file in ``governance.json`` (sessions.<id>.touched_files) and its
  pre-write size in ``debt_baselines.json``, so the Stop hook still sees the file after the agent committed it
  and the ratchet still has a baseline outside git.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .debt_baselines import record_pre_write_baseline
from .debt_ratchet import (
    SCAN_SOURCE_SUFFIXES,
    check_new_file_bloat,
    count_clean_lines,
    is_test_or_exempt_file,
    to_project_rel_path,
)
from .governance import governance_transaction, load_governance_state
from .refactor_hint import build_refactor_hint
from .state_lock import StateLockTimeout

GROWTH_DENY_RULE = "ARCH_RATCHET_GROWTH_DENY"
NEW_FILE_RULE = "G5_NEW_FILE_BLOAT_DENY"
MAX_TOUCHED_FILES = 300


def is_governed_source(rel_path: str) -> bool:
    return rel_path.lower().endswith(SCAN_SOURCE_SUFFIXES) and not is_test_or_exempt_file(rel_path)


def check_ratchet_growth(rel_path: str, old_content: str, projected_content: str, ratchet_loc: int) -> str:
    """Deny text when the write adds lines to a file already at/over `ratchet_loc`, else ''."""
    if not old_content.strip() or not is_governed_source(rel_path):
        return ""
    old_loc = count_clean_lines(old_content)
    delta = count_clean_lines(projected_content) - old_loc
    if old_loc < ratchet_loc or delta <= 0:
        return ""
    return (
        f"Ratchet Büyüme Engeli: '{rel_path}' bu yazımla {old_loc} satırdan {old_loc + delta} satıra (+{delta}) çıkıyor, "
        f"sınır {ratchet_loc} satır. Sınırı aşan dosyaya net satır eklenemez: yeni özelliği yeni bir modüle yazın "
        f"veya dosyayı önce küçültün; eski dosyadan taşıdığınız bloğu silip yerine import/çağrı koyan TEK bir düzenleme "
        f"yapın (net satır ≤ 0). {build_refactor_hint(old_content, rel_path)}"
    ).strip()


def note_touched_file(project_root: Path, conversation_id: str, rel_path: str) -> None:
    """Remember the file in the session so the Stop hook evaluates it even after a commit. Never blocks the write."""
    try:
        with governance_transaction(project_root) as state:
            session = state.setdefault("sessions", {}).setdefault(conversation_id or "default", {"stop_retries": 0})
            touched = [p for p in session.get("touched_files", []) if p != rel_path]
            session["touched_files"] = (touched + [rel_path])[-MAX_TOUCHED_FILES:]
    except (OSError, StateLockTimeout) as err:
        sys.stderr.write(f"[GravityGuard Ratchet] Could not record touched file {rel_path}: {err}\n")


def session_touched_files(project_root: Path, conversation_id: str) -> list[str]:
    """Absolute paths of the session's touched files that still exist."""
    rels = load_governance_state(project_root).get("sessions", {}).get(conversation_id or "default", {}).get("touched_files", [])
    paths = (os.path.normpath(os.path.join(project_root, rel)) for rel in rels if isinstance(rel, str))
    return [p for p in paths if os.path.isfile(p)]


def pre_write_ratchet_denies(
    project_root: str, target_file: str, old_content: str, projected_content: str, thresholds: dict, conversation_id: str,
) -> list[tuple[str, str]]:
    """(rule id, reason) denials for this write; also records the file's baseline and session touch."""
    rel = to_project_rel_path(project_root, target_file)
    denies: list[tuple[str, str]] = []
    new_file_msg = check_new_file_bloat(project_root, target_file, old_content, projected_content, thresholds["newFileMaxLoc"])
    if new_file_msg:
        denies.append((NEW_FILE_RULE, new_file_msg))
    growth_msg = check_ratchet_growth(rel, old_content, projected_content, thresholds["ratchetLoc"])
    if growth_msg:
        denies.append((GROWTH_DENY_RULE, growth_msg))
    if is_governed_source(rel):
        record_pre_write_baseline(
            project_root, rel, count_clean_lines(old_content), count_clean_lines(projected_content), thresholds["ratchetLoc"])
        note_touched_file(Path(project_root), conversation_id, rel)
    return denies
