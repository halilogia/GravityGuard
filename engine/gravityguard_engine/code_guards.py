#!/usr/bin/env python3
"""
GravityGuard Engine — PreToolUse Code Guards (G1..G7, PMA, Ratchet, SRP).
Executes static code quality, security, and architectural guards on source edits.
Zero external dependencies.
"""
import json
import re
import sys
from pathlib import Path
from typing import Callable, List, Optional, Set, Tuple

from .architecture_rules import (
    analyze_python_srp,
    check_arch_file_growth,
    check_g3_compiler_bypass,
    check_pma_horizontal,
    check_pma_imports,
    is_ts_cohesive_monolith,
    record_and_check_cumulative_growth,
)
from .ratchet_gate import RULE_ID as RATCHET_GROWTH_RULE_ID, check_ratchet_growth
from .security_rules import (
    check_escape_hatch_tampering,
    check_g1_silent_exception,
    check_g2_test_integrity,
    check_unsafe_code_patterns,
)
from .stop_dispatcher import is_rule_shadow
from .write_signals import collect_write_signals


def evaluate_code_guards(
    target_file: str,
    file_lower: str,
    is_test_file: bool,
    is_python: bool,
    is_ts: bool,
    old_full_content: str,
    projected_content: str,
    added_lines: List[str],
    added_text: str,
    added_line_numbers: Set[int],
    p_root: Path,
    cfg: Optional[dict],
    complexity_thresholds: dict,
    log_fn: Callable,
    all_warnings: List[Tuple[str, str]],
) -> None:
    """Executes Guards 1..7 on code mutations and exits on blocking violations."""
    if not is_test_file:
        g1_violated, g1_reason = check_g1_silent_exception(
            added_lines, added_text, added_line_numbers, projected_content, is_python, is_ts
        )
        if g1_violated:
            if is_rule_shadow("G1_SILENT_EXCEPTION", cfg):
                log_fn("SHADOW_TRIGGER", target_file, f"[SHADOW] {g1_reason}", rule_id="G1_SILENT_EXCEPTION")
            else:
                log_fn("BLOCKED", target_file, g1_reason, rule_id="G1_SILENT_EXCEPTION")
                print(json.dumps({
                    "decision": "deny",
                    "reason": f"🛑 [G1_SILENT_EXCEPTION]: '{target_file}' - {g1_reason}"
                }))
                sys.exit(0)

    if is_test_file:
        g2_violated, g2_reason, g2_warn = check_g2_test_integrity(
            added_text, old_full_content, projected_content, is_test_file
        )
        if g2_warn:
            if is_rule_shadow("G2_TEST_INTEGRITY", cfg):
                log_fn("SHADOW_TRIGGER", target_file, f"[SHADOW] {g2_warn}", rule_id="G2_TEST_INTEGRITY")
            else:
                log_fn("WARNING", target_file, g2_warn, rule_id="G2_TEST_INTEGRITY")
                all_warnings.append(("G2_TEST_INTEGRITY", g2_warn))
        if g2_violated:
            if is_rule_shadow("G2_TEST_INTEGRITY", cfg):
                log_fn("SHADOW_TRIGGER", target_file, f"[SHADOW] {g2_reason}", rule_id="G2_TEST_INTEGRITY")
            else:
                log_fn("BLOCKED", target_file, g2_reason, rule_id="G2_TEST_INTEGRITY")
                print(json.dumps({
                    "decision": "deny",
                    "reason": f"🛑 [G2_TEST_INTEGRITY]: '{target_file}' - {g2_reason}"
                }))
                sys.exit(0)

    tamper_violated, tamper_reason = check_escape_hatch_tampering(added_text, old_full_content)
    if tamper_violated:
        if is_rule_shadow("G2_SECURITY_TAMPERING", cfg):
            log_fn("SHADOW_TRIGGER", target_file, f"[SHADOW] {tamper_reason}", rule_id="G2_SECURITY_TAMPERING")
        else:
            log_fn("BLOCKED", target_file, tamper_reason, rule_id="G2_SECURITY_TAMPERING")
            print(json.dumps({
                "decision": "deny",
                "reason": f"🛑 [G2_SECURITY_TAMPERING]: '{target_file}' - {tamper_reason}"
            }))
            sys.exit(0)

    g3_matches = check_g3_compiler_bypass(added_text)
    if g3_matches:
        warn_msg = f"Yeni linter/derleyici susturması eklendi ({', '.join(g3_matches)}). Hatanın kök nedenini çözmeyi değerlendirin."
        if is_rule_shadow("G3_COMPILER_BYPASS", cfg):
            log_fn("SHADOW_TRIGGER", target_file, f"[SHADOW] {warn_msg}", rule_id="G3_COMPILER_BYPASS")
        else:
            log_fn("WARNING", target_file, warn_msg, rule_id="G3_COMPILER_BYPASS")
            all_warnings.append(("G3_COMPILER_BYPASS", warn_msg))

    _lower_target = target_file.replace("\\", "/").lower()
    if not _lower_target.endswith((".md", ".txt", ".rst")) and "/tests/" not in _lower_target and not _lower_target.rsplit("/", 1)[-1].startswith("test_"):
        unsafe_hits = check_unsafe_code_patterns(added_text)
        if unsafe_hits:
            unsafe_msg = f"Yeni kodda riskli yapı tespit edildi: {'; '.join(unsafe_hits)}. Gerekçesiz bırakmayın veya güvenli alternatifi kullanın."
            if is_rule_shadow("SEC_UNSAFE_PATTERN", cfg):
                log_fn("SHADOW_TRIGGER", target_file, f"[SHADOW] {unsafe_msg}", rule_id="SEC_UNSAFE_PATTERN")
            else:
                log_fn("WARNING", target_file, unsafe_msg, rule_id="SEC_UNSAFE_PATTERN")
                all_warnings.append(("SEC_UNSAFE_PATTERN", unsafe_msg))

    pma_hits = []
    pma_h_violated, pma_h_reason = check_pma_horizontal(target_file)
    if pma_h_violated:
        pma_hits.append(("ARCH_PMA_HORIZONTAL_DENY", pma_h_reason))
    pma_i_violated, pma_i_rule, pma_i_reason = check_pma_imports(target_file, added_text)
    if pma_i_violated:
        pma_hits.append((pma_i_rule, pma_i_reason))
    for pma_rule, pma_reason in pma_hits:
        if is_rule_shadow(pma_rule, cfg):
            log_fn("SHADOW_TRIGGER", target_file, f"[SHADOW] {pma_reason}", rule_id=pma_rule)
        else:
            log_fn("BLOCKED", target_file, pma_reason, rule_id=pma_rule)
            print(json.dumps({
                "decision": "deny",
                "reason": f"🛑 [{pma_rule}]: '{target_file}' - {pma_reason}"
            }))
            sys.exit(0)

    growth_msg = check_ratchet_growth(str(p_root), target_file, old_full_content, projected_content, complexity_thresholds["ratchetLoc"])
    if growth_msg:
        if is_rule_shadow(RATCHET_GROWTH_RULE_ID, cfg):
            log_fn("SHADOW_TRIGGER", target_file, f"[SHADOW] {growth_msg}", rule_id=RATCHET_GROWTH_RULE_ID)
        else:
            log_fn("BLOCKED", target_file, growth_msg, rule_id=RATCHET_GROWTH_RULE_ID)
            print(json.dumps({"decision": "deny", "reason": f"[{RATCHET_GROWTH_RULE_ID}]: '{target_file}' - {growth_msg}"}))
            sys.exit(0)

    added_clean_lines = [l for l in added_lines if l.strip() and not l.strip().startswith(("#", "//", "/*", "*"))]
    single_write_thresh = complexity_thresholds.get("singleWriteLoc", 200) if complexity_thresholds else 200
    is_cumul, cum_loc = record_and_check_cumulative_growth(target_file, len(added_clean_lines), threshold=single_write_thresh)

    arch_triggered, arch_msg = check_arch_file_growth(
        target_file=target_file,
        old_full_content=old_full_content,
        projected_content=projected_content,
        added_lines=added_lines,
        is_test_file=is_test_file,
        thresholds=complexity_thresholds,
        cumulative_loc=cum_loc if is_cumul else 0
    )
    if arch_triggered:
        if is_rule_shadow("ARCH_FILE_GROWTH", cfg):
            log_fn("SHADOW_TRIGGER", target_file, f"[SHADOW] {arch_msg}", rule_id="ARCH_FILE_GROWTH")
        else:
            log_fn("WARNING", target_file, arch_msg, rule_id="ARCH_FILE_GROWTH")
            all_warnings.append(("ARCH_FILE_GROWTH", arch_msg))

    for signal_id, signal_msg in collect_write_signals(str(p_root), target_file, projected_content, complexity_thresholds, is_python, is_ts):
        if is_rule_shadow(signal_id, cfg):
            log_fn("SHADOW_TRIGGER", target_file, f"[SHADOW] {signal_msg}", rule_id=signal_id)
        else:
            log_fn("WARNING", target_file, signal_msg, rule_id=signal_id)
            all_warnings.append((signal_id, signal_msg))

    if not is_test_file:
        if file_lower.endswith((".html", ".htm")):
            from .web_srp_analyzer import analyze_html_srp
            is_violation, rule_id, reason_msg, web_warnings = analyze_html_srp(projected_content, file_path=target_file)
            for wid, wmsg in web_warnings:
                if is_rule_shadow(wid, cfg):
                    log_fn("SHADOW_TRIGGER", target_file, f"[SHADOW] {wmsg}", rule_id=wid)
                else:
                    log_fn("WARNING", target_file, wmsg, rule_id=wid)
                    all_warnings.append((wid, wmsg))
            if is_violation:
                if is_rule_shadow(rule_id, cfg):
                    log_fn("SHADOW_TRIGGER", target_file, f"[SHADOW] {reason_msg}", rule_id=rule_id)
                else:
                    log_fn("BLOCKED", target_file, reason_msg, rule_id=rule_id)
                    print(json.dumps({
                        "decision": "deny",
                        "reason": f"🛑 [{rule_id}]: '{target_file}' - {reason_msg}"
                    }))
                    sys.exit(0)

        elif is_python:
            is_violation, reason = analyze_python_srp(projected_content, file_path=target_file, thresholds=complexity_thresholds)
            if is_violation:
                if is_rule_shadow("SRP_BOUNDARY", cfg):
                    log_fn("SHADOW_TRIGGER", target_file, f"[SHADOW] {reason}", rule_id="SRP_BOUNDARY")
                else:
                    log_fn("BLOCKED", target_file, reason, rule_id="SRP_BOUNDARY")
                    print(json.dumps({
                        "decision": "deny",
                        "reason": f"🛑 [SRP_BOUNDARY]: '{target_file}' - {reason}"
                    }))
                    sys.exit(0)

        elif is_ts:
            tab_matches = len(re.findall(r"activeTab\s*===", projected_content))
            card_matches = len(re.findall(r"glass-card", projected_content))
            grid_blocks = len(re.findall(r"display:\s*'grid'", projected_content))
            scroll_ids = len(re.findall(r"scrollToSection\s*\(", projected_content))
            multi_job = (tab_matches >= 2 and card_matches >= 3) or (scroll_ids >= 3 and grid_blocks >= 3)

            if multi_job and not is_ts_cohesive_monolith(projected_content):
                reason_msg = (
                    f"SRP İhlali: Dosya {tab_matches} sekme, {card_matches} kart ve {grid_blocks} grid bloğu içeriyor. "
                    f"Her sekmeyi / kartı ayrı bir bileşen dosyasına bölün."
                )
                if is_rule_shadow("SRP_BOUNDARY", cfg):
                    log_fn("SHADOW_TRIGGER", target_file, f"[SHADOW] {reason_msg}", rule_id="SRP_BOUNDARY")
                else:
                    log_fn("BLOCKED", target_file, reason_msg, rule_id="SRP_BOUNDARY")
                    print(json.dumps({
                        "decision": "deny",
                        "reason": f"🛑 [SRP_BOUNDARY]: '{target_file}' - {reason_msg}"
                    }))
                    sys.exit(0)
