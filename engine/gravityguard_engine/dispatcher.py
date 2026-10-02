#!/usr/bin/env python3
"""
GravityGuard Engine — Main Dispatcher & Rule Orchestration Subsystem.
Zero external dependencies.
"""
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import List, Tuple


from .architecture_rules import (
    analyze_python_srp,
    check_arch_file_growth,
    check_g3_compiler_bypass,
    check_g4_import_matrix,
    check_oe_spike,
    is_ts_cohesive_monolith,
    record_and_check_cumulative_growth,
)
from .audit import log_event
from .diagnostics import read_recent_diagnostics, trigger_background_validation
from .diffing import get_diff_analysis, get_projected_and_old_content
from .governance import (
    get_session_stop_retries,
    get_unresolved_doc_obligations,
    get_unresolved_test_evidence,
    increment_session_stop_retries,
    reconcile_obligations_on_disk,
    record_pending_doc_obligation,
    record_pending_test_evidence,
    reset_session_stop_retries,
    resolve_pending_doc_obligations,
    resolve_pending_test_evidence,
)

from .project_context import (
    harden_streams_to_utf8,
    is_doc_governed_target,
    load_gravityguard_config,
    resolve_complexity_thresholds,
    resolve_project_root,
    should_enforce_doc_obligations,
)
from .security_rules import (
    check_escape_hatch_tampering,
    check_g0_secret_leak,
    check_g1_silent_exception,
    check_g2_test_integrity,
)
from .test_evidence import (
    evaluate_test_evidence,
    resolve_candidate_test_file,
)


def validate_gravityguard() -> None:
    harden_streams_to_utf8()
    start_time = time.perf_counter()

    raw_input = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not raw_input.strip():
        print(json.dumps({"decision": "allow"}))
        sys.exit(0)

    try:
        payload = json.loads(raw_input)
    except Exception:
        print(json.dumps({"decision": "allow"}))
        sys.exit(0)

    # ========================================================================
    # 0. Lifecycle Hook Check: Stop / PostInvocation or CLI --stop flag
    # ========================================================================
    if payload.get("terminationReason") or "--stop" in sys.argv:
        term_reason = payload.get("terminationReason", "")
        if term_reason in ("user_cancel", "cancelled", "user_abort"):
            print(json.dumps({"decision": "allow"}))
            sys.exit(0)

        project_root = resolve_project_root(payload)
        conversation_id = payload.get("conversationId", "default")
        cfg = load_gravityguard_config("", project_root)

        # Defect A fix: Circuit breaker strictly governed by session continuation retries
        session_retries = get_session_stop_retries(project_root, conversation_id)
        if session_retries >= 5:
            log_event(
                "stop", "WARNING", "workspace",
                f"Circuit breaker triggered (retries={session_retries}): allowing stop despite obligations",
                rule_id="STOP_CIRCUIT_BREAKER"
            )
            reset_session_stop_retries(project_root, conversation_id)
            print(json.dumps({"decision": "allow"}))
            sys.exit(0)

        # Defect B fix: Reconcile obligations with physical filesystem verification
        reconcile_obligations_on_disk(project_root, conversation_id, cfg)

        unresolved_tests = get_unresolved_test_evidence(project_root, conversation_id)
        unresolved_docs = get_unresolved_doc_obligations(project_root, conversation_id)

        warn_reasons = []
        if unresolved_tests:
            missing_items = [
                f"'{p}' (beklenen test: {info.get('expected_name', 'test')})"
                for p, info in unresolved_tests.items()
            ]
            t1_warn = (
                f"Test Kanıtı Uyarısı (T1): Oturum tamamlandı ancak şu üretim kodları için "
                f"test kanıtı bulunamadı: {', '.join(missing_items)}"
            )
            log_event("stop", "WARNING", "workspace", t1_warn, rule_id="T1_FINAL_UNRESOLVED")
            warn_reasons.append(t1_warn)

        if unresolved_docs:
            missing_docs = [
                f"'{p}' (gereken: {', '.join(info.get('required_docs', ['CHANGELOG.md']))})"
                for p, info in unresolved_docs.items()
            ]
            doc_warn = (
                f"Dokümantasyon Yükümlülüğü: Motor/kod dosyaları değiştirildi ancak "
                f"dokümantasyon güncellenmedi (docs/KNOWLEDGE.md §6 Same-commit rule): {', '.join(missing_docs)}"
            )
            log_event("stop", "WARNING", "workspace", doc_warn, rule_id="DOC_OBLIGATION_UNRESOLVED")
            warn_reasons.append(doc_warn)

        if warn_reasons:
            increment_session_stop_retries(project_root, conversation_id)
            full_reason = " | ".join(warn_reasons)
            print(json.dumps({"decision": "continue", "reason": full_reason}))
        else:
            reset_session_stop_retries(project_root, conversation_id)
            print(json.dumps({"decision": "allow"}))
        sys.exit(0)

    # ========================================================================
    # PreToolUse Lifecycle Hook Dispatcher
    # ========================================================================
    tool_call = payload.get("toolCall", {})
    args = tool_call.get("args", {})
    target_file = args.get("TargetFile") or args.get("target_file") or args.get("file_path") or ""
    tool_name = tool_call.get("name", "edit")

    # 1. Normalize path
    normalized_path = target_file.replace("\\\\", "/").replace("\\", "/")
    file_lower = normalized_path.lower()

    path_obj = Path(normalized_path)
    file_name_lower = path_obj.name.lower()
    parent_parts_lower = [part.lower() for part in path_obj.parent.parts]

    is_in_test_dir = any(d in parent_parts_lower for d in ("tests", "test", "__tests__"))
    is_test_name = (
        "test_" in file_name_lower or
        "_test" in file_name_lower or
        ".test." in file_name_lower or
        ".spec." in file_name_lower
    )
    is_test_file = is_in_test_dir or is_test_name
    is_vendor_or_cache = any(m in file_lower for m in [
        "/node_modules/", "/venv/", "/.venv/", "/env/", "/.env/", "/dist/", "/build/",
        "/.git/", "/__pycache__/", "/runs/", "/scratch/", "/brain/", "/.gemini/"
    ])
    is_data_or_doc = file_lower.endswith((
        ".json", ".css", ".scss", ".md", ".txt", ".yaml", ".yml", ".toml", ".ini",
        ".lock", ".svg", ".gitignore"
    ))
    is_binary_asset = file_lower.endswith((
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".blend", ".exe", ".dll",
        ".so", ".bin", ".wasm", ".zip", ".tar", ".gz"
    ))

    # Fast-pass for pure binary assets
    if is_binary_asset:
        if target_file:
            log_event(tool_name, "APPROVED", target_file, "Exempt file (Binary Asset)", rule_id="EXEMPT")
        print(json.dumps({"decision": "allow"}))
        sys.exit(0)

    # Reconcile disk state for any obligations satisfied by prior tool writes
    p_root = resolve_project_root(payload, target_file)
    c_id = payload.get("conversationId", "default")
    cfg = load_gravityguard_config(target_file, p_root)
    reconcile_obligations_on_disk(p_root, c_id, cfg)

    # 2. Extract projected and old content, compute exact diff
    old_full_content, projected_content = get_projected_and_old_content(target_file, tool_name, args)
    added_lines, added_text, added_line_numbers = get_diff_analysis(old_full_content, projected_content)

    all_warnings: List[Tuple[str, str]] = []
    complexity_thresholds = resolve_complexity_thresholds(cfg)

    # Check if a documentation file is being edited/written -> defer doc resolution until G0 passes
    should_resolve_doc = False
    if target_file and is_data_or_doc:
        norm_target = target_file.replace("\\", "/").lower()
        if norm_target.endswith(("changelog.md", "knowledge.md", "architecture.md", "readme.md")):
            should_resolve_doc = True

    # ========================================================================
    # GUARD 0: G0 — SECRET LEAK GUARD (BLOCK / WARN)
    # Executed for ALL text files (code, config, docs, vendor, cache)
    # ========================================================================
    g0_violated, g0_reason, g0_warn = check_g0_secret_leak(added_text)
    if g0_warn:
        log_event(tool_name, "WARNING", target_file, g0_warn, rule_id="G0_SECRET_LEAK")
        all_warnings.append(("G0_SECRET_LEAK", g0_warn))
    if g0_violated:
        log_event(tool_name, "BLOCKED", target_file, g0_reason, rule_id="G0_SECRET_LEAK")
        print(json.dumps({
            "decision": "deny",
            "reason": f"🛑 [G0_SECRET_LEAK]: '{target_file}' - {g0_reason}"
        }))
        sys.exit(0)

    # Fast-pass for vendor, cache, and non-code text assets (ONLY AFTER G0 IS CLEAN)
    if is_vendor_or_cache or (is_data_or_doc and not file_lower.endswith((".py", ".ts", ".tsx", ".js", ".jsx"))):
        if should_resolve_doc:
            resolve_pending_doc_obligations(target_file, p_root, c_id)
        if target_file:
            log_event(tool_name, "APPROVED", target_file, "Exempt file (Vendor/Cache/Asset)", rule_id="EXEMPT")
        if all_warnings:
            warn_parts = [f"[{wid}] {wmsg}" for wid, wmsg in all_warnings]
            print(json.dumps({"decision": "allow", "reason": " ⚠ ".join(warn_parts)}))
        else:
            print(json.dumps({"decision": "allow"}))
        sys.exit(0)


    is_python = file_lower.endswith(".py")
    is_ts = file_lower.endswith((".ts", ".tsx", ".js", ".jsx"))

    # ========================================================================
    # GUARD 1: G1 — SILENT EXCEPTION (BLOCK)
    # ========================================================================
    if not is_test_file:
        g1_violated, g1_reason = check_g1_silent_exception(
            added_lines, added_text, added_line_numbers, projected_content, is_python, is_ts
        )
        if g1_violated:
            log_event(tool_name, "BLOCKED", target_file, g1_reason, rule_id="G1_SILENT_EXCEPTION")
            print(json.dumps({
                "decision": "deny",
                "reason": f"🛑 [G1_SILENT_EXCEPTION]: '{target_file}' - {g1_reason}"
            }))
            sys.exit(0)

    # ========================================================================
    # GUARD 2: G2 — TEST INTEGRITY (BLOCK / WARN)
    # ========================================================================
    if is_test_file:
        g2_violated, g2_reason, g2_warn = check_g2_test_integrity(
            added_text, old_full_content, projected_content, is_test_file
        )
        if g2_warn:
            log_event(tool_name, "WARNING", target_file, g2_warn, rule_id="G2_TEST_INTEGRITY")
            all_warnings.append(("G2_TEST_INTEGRITY", g2_warn))
        if g2_violated:
            log_event(tool_name, "BLOCKED", target_file, g2_reason, rule_id="G2_TEST_INTEGRITY")
            print(json.dumps({
                "decision": "deny",
                "reason": f"🛑 [G2_TEST_INTEGRITY]: '{target_file}' - {g2_reason}"
            }))
            sys.exit(0)

    # ========================================================================
    # GUARD 2B: G2_SECURITY_TAMPERING — ESCAPE HATCH INJECTION (BLOCK)
    # ========================================================================
    tamper_violated, tamper_reason = check_escape_hatch_tampering(added_text, old_full_content)
    if tamper_violated:
        log_event(tool_name, "BLOCKED", target_file, tamper_reason, rule_id="G2_SECURITY_TAMPERING")
        print(json.dumps({
            "decision": "deny",
            "reason": f"🛑 [G2_SECURITY_TAMPERING]: '{target_file}' - {tamper_reason}"
        }))
        sys.exit(0)

    # ========================================================================
    # GUARD 3: G3 — COMPILER & LINTER BYPASS (WARN ONLY)
    # ========================================================================
    g3_matches = check_g3_compiler_bypass(added_text)
    if g3_matches:
        warn_msg = f"Yeni linter/derleyici susturması eklendi ({', '.join(g3_matches)}). Hatanın kök nedenini çözmeyi değerlendirin."
        log_event(tool_name, "WARNING", target_file, warn_msg, rule_id="G3_COMPILER_BYPASS")
        all_warnings.append(("G3_COMPILER_BYPASS", warn_msg))

    # ========================================================================
    # GUARD 4: G4 — IMPORT MATRIX (BLOCK)
    # ========================================================================
    g4_violated, g4_reason = check_g4_import_matrix(target_file, added_text)
    if g4_violated:
        log_event(tool_name, "BLOCKED", target_file, g4_reason, rule_id="G4_IMPORT_MATRIX")
        print(json.dumps({
            "decision": "deny",
            "reason": f"🛑 [G4_IMPORT_MATRIX]: '{target_file}' - {g4_reason}"
        }))
        sys.exit(0)

    # ========================================================================
    # GUARD 5: OE_SPIKE — OVER-ENGINEERING (WARN ONLY)
    # ========================================================================
    oe_triggered, oe_msg = check_oe_spike(added_text, complexity_thresholds)
    if oe_triggered:
        log_event(tool_name, "WARNING", target_file, oe_msg, rule_id="OE_SPIKE")
        all_warnings.append(("OE_SPIKE", oe_msg))

    # ========================================================================
    # GUARD 6: ARCH_FILE_GROWTH — LARGE FILE & RAPID GROWTH (WARN ONLY)
    # ========================================================================
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
        log_event(tool_name, "WARNING", target_file, arch_msg, rule_id="ARCH_FILE_GROWTH")
        all_warnings.append(("ARCH_FILE_GROWTH", arch_msg))

    # ========================================================================
    # GUARD 7: EXISTING SRP (Single Responsibility Principle)
    # ========================================================================
    if not is_test_file:
        if is_python:
            is_violation, reason = analyze_python_srp(projected_content, file_path=target_file)
            if is_violation:
                log_event(tool_name, "BLOCKED", target_file, reason, rule_id="SRP_BOUNDARY")
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
                reason_msg = f"SRP İhlali: Dosya {tab_matches} sekme, {card_matches} kart ve {grid_blocks} grid bloğu içeriyor."
                log_event(tool_name, "BLOCKED", target_file, reason_msg, rule_id="SRP_BOUNDARY")
                print(json.dumps({
                    "decision": "deny",
                    "reason": f"🛑 [SRP_BOUNDARY]: '{target_file}' - {reason_msg}"
                }))
                sys.exit(0)

    # ========================================================================
    # GUARD 8: PHASE 2 TEST EVIDENCE AIRBAG (T1, T2, T3) — WARN ONLY
    # ========================================================================
    test_evidence_warnings, test_actions = evaluate_test_evidence(
        target_file=target_file,
        is_test_file=is_test_file,
        added_lines=added_lines,
        added_text=added_text,
        projected_content=projected_content,
        added_line_numbers=added_line_numbers,
        cfg=cfg,
        is_python=is_python,
        is_ts=is_ts
    )
    for rule_id, warn_msg in test_evidence_warnings:
        log_event(tool_name, "WARNING", target_file, warn_msg, rule_id=rule_id)
        all_warnings.append((rule_id, warn_msg))

    # Stage doc obligation if production/engine code is changed and doc governance is enabled
    pending_doc_record = None
    if should_enforce_doc_obligations(target_file, cfg=cfg) and is_doc_governed_target(target_file, cfg):
        pending_doc_record = target_file

    # ========================================================================
    # GUARD 9: STATIC LINTER & COMPILER DIAGNOSTIC FEEDBACK (WARN ONLY)
    # ========================================================================
    diag_warnings = read_recent_diagnostics(target_file)
    for d_rule, d_msg in diag_warnings:
        log_event(tool_name, "WARNING", target_file, d_msg, rule_id=d_rule)
        all_warnings.append((d_rule, d_msg))

    # ========================================================================
    # PASS / APPROVED
    # Two-phase commit: All guards passed. Commit pending governance transitions!
    # ========================================================================
    if should_resolve_doc:
        resolve_pending_doc_obligations(target_file, p_root, c_id)

    if test_actions.get("resolve_test"):
        resolved = resolve_pending_test_evidence(target_file, p_root, c_id)
        if resolved:
            log_event(tool_name, "APPROVED", target_file, f"Resolved pending test evidence for: {', '.join(resolved)}", rule_id="T1_RESOLVED")

    if test_actions.get("record_test"):
        tf, cp, en, msg = test_actions["record_test"]
        record_pending_test_evidence(tf, cp, en, msg, p_root, c_id)
        log_event(tool_name, "APPROVED", tf, f"Pending test evidence recorded ({en})", rule_id="T1_PENDING")

    if pending_doc_record:
        record_pending_doc_obligation(pending_doc_record, project_root=p_root, conversation_id=c_id)


    elapsed_ms = (time.perf_counter() - start_time) * 1000
    log_event(tool_name, "APPROVED", target_file, f"All Guards Passed ({elapsed_ms:.1f}ms)", rule_id="PASS")
    res_payload = {"decision": "allow"}
    if all_warnings:
        res_payload["reason"] = " ⚠ ".join(
            f"[{rule_id}] {msg}" for rule_id, msg in all_warnings
        )
    print(json.dumps(res_payload))
    trigger_background_validation(target_file)
    sys.exit(0)


def run_cli() -> None:
    validate_gravityguard()
