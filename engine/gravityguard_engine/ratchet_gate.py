"""
GravityGuard Engine — ARCH_RATCHET_GROWTH_DENY: a source file over ratchetLoc may not gain more than a small edit.

The rule is a delta rule (net growth above +SMALL_EDIT_LOC in one edit, or any growth past HARD_CAP_LOC), so it needs
neither git nor a stored baseline and holds in plain folders. The same call seeds the baseline from the on-disk size before the write, which is
what the Stop hook later compares the disk against (growth that bypassed this hook, e.g. through a shell).
Shrinking or net-zero edits always pass, so a refactor is never blocked.
"""
import os
import sys

from .debt_ratchet import (
    SCAN_SOURCE_SUFFIXES,
    count_clean_lines,
    evaluate_file_ratchet,
    is_test_or_exempt_file,
    to_project_rel_path,
)
from .refactor_hint import build_refactor_hint

RULE_ID = "ARCH_RATCHET_GROWTH_DENY"
SMALL_EDIT_LOC = 20  # a single edit may add this many net lines to an over-threshold file
HARD_CAP_LOC = 800   # above this size any net growth is denied


def _exemption_path(project_root: str, file_path: str) -> str:
    """Project-relative path, or the file's own trailing path when the root resolved elsewhere (cwd fallback).

    A "../x" or absolute path would otherwise count as exempt and silently switch the rule off.
    """
    rel = to_project_rel_path(project_root, file_path)
    if rel.startswith("../") or os.path.isabs(rel):
        rel = "/".join(file_path.replace("\\", "/").split("/")[-2:])
    return rel


def check_ratchet_growth(project_root: str, target_file: str, old_content: str, projected_content: str, threshold: int) -> str:
    """Denial text when the write adds net lines to an existing source file that ends over `threshold`, else ''.

    A brand-new file has no baseline to regress from. Seeding the baseline never raises or fails the write.
    """
    rel = _exemption_path(project_root, target_file)
    if not old_content.strip() or not rel.lower().endswith(SCAN_SOURCE_SUFFIXES) or is_test_or_exempt_file(rel):
        return ""
    old_loc, new_loc = count_clean_lines(old_content), count_clean_lines(projected_content)
    if old_loc > threshold:
        try:
            evaluate_file_ratchet(project_root, target_file, content=old_content, threshold=threshold)
        except (OSError, ValueError) as err:  # bookkeeping must not take the write guard down
            sys.stderr.write(f"[GravityGuard PreTool] ratchet baseline seed failed: {err}\n")
    growth = new_loc - old_loc
    if new_loc <= threshold or growth <= 0 or (growth <= SMALL_EDIT_LOC and new_loc <= HARD_CAP_LOC):
        return ""
    return (
        f"Ratchet Büyüme Engeli: '{rel}' bu yazımla {old_loc} satırdan {new_loc} satıra (+{growth}) çıkıyor, "
        f"sınır {threshold} satır (küçük düzeltme +{SMALL_EDIT_LOC}, mutlak tavan {HARD_CAP_LOC}). "
        f"Yeni özelliği yeni bir modüle yazın; "
        f"eski dosyadan taşıdığınız bloğu silip yerine import/çağrı koyan TEK bir düzenleme yapın (net satır ≤ 0). "
        f"{build_refactor_hint(projected_content, rel)}"
    ).strip()
