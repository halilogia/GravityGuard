"""
GravityGuard Engine — warn-only signals evaluated on every source write (read-only: nothing is recorded here).

Returns (rule_id, message) pairs; the dispatcher applies shadow mode and logging uniformly.
- ARCH_RATCHET_REGRESSION_WARN: the write pushes an over-threshold file past its accepted ceiling (debt_ratchet.py)"""
import sys
from typing import Dict, List, Tuple

from .debt_ratchet import evaluate_file_ratchet
from .refactor_hint import build_refactor_hint

RATCHET_WARN_RULE_ID = "ARCH_RATCHET_REGRESSION_WARN"


def collect_write_signals(
    project_root: str, target_file: str, projected_content: str, thresholds: Dict[str, int], is_python: bool, is_ts: bool,
) -> List[Tuple[str, str]]:
    signals: List[Tuple[str, str]] = []
    try:
        is_reg, _, _, message = evaluate_file_ratchet(
            project_root, target_file, content=projected_content, threshold=thresholds["ratchetLoc"], auto_record_baseline=False)
        if is_reg and message:
            signals.append((RATCHET_WARN_RULE_ID, f"{message} {build_refactor_hint(projected_content, target_file)}".strip()))
    except Exception as err:  # a failing advisory signal must never take the write guard down
        sys.stderr.write(f"[GravityGuard PreTool] write signal error: {err}\n")
    return signals
