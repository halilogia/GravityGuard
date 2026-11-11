#!/usr/bin/env python3
"""
GravityGuard Engine — Main Dispatcher & Rule Orchestration Subsystem.
Zero external dependencies.
"""
import contextlib  # noqa: F401
import io  # noqa: F401
import json
import os
import re  # noqa: F401
import sys
import time
from pathlib import Path
from typing import List, Tuple, Optional, Dict  # noqa: F401

from .quality_signals import find_evasion_markers
from .architecture_rules import (  # noqa: F401
    analyze_python_srp, check_arch_file_growth, check_design_icon_rule, check_g3_compiler_bypass,
    check_g7_ts_first, check_pma_horizontal, check_pma_imports, find_design_responsive_violations,
    is_ts_cohesive_monolith, record_and_check_cumulative_growth,
)
from .audit import log_event
from .plugin_rules import apply_plugin_rules
from .doc_automation import doc_obligation_auto, is_knowledge_governed_path, resolve_knowledge_doc  # noqa: F401
from .state_lock import StateLockTimeout
from .diagnostics import read_recent_diagnostics, trigger_background_validation
from .diffing import get_diff_analysis, get_projected_and_old_content, ProjectionError
from .engine_integrity import engine_source_defect, repair_reason, run_lkg  # noqa: F401
from .policy_integrity import MANDATORY_RULES, check_policy_change, is_runtime_control_file  # noqa: F401
from .session_quarantine import forget_denied_target, session_logger
from .shell_rules import check_shell_command
from .token_guard import evaluate_token_guard
from .publication_guard import scan_git_secrets  # noqa: F401
from .removal_observer import observe_removals  # noqa: F401
from .operations import normalize_operation, UnsupportedOperation
from .governance import (  # noqa: F401
    get_session_stop_retries, get_unresolved_doc_obligations, get_unresolved_test_evidence,
    increment_session_stop_retries, reconcile_obligations_on_disk, record_pending_doc_obligation,
    record_pending_test_evidence, record_resolution_intent, reset_session_stop_retries,
    resolve_pending_doc_obligations, resolve_pending_test_evidence,
)
from .write_signals import collect_write_signals  # noqa: F401
from .stop_gate import critical_blockers, note_touched_file, other_stop_roots, ratchet_findings  # noqa: F401
from .ratchet_gate import RULE_ID as RATCHET_GROWTH_RULE_ID, check_ratchet_growth  # noqa: F401
from .project_context import (
    harden_streams_to_utf8, is_doc_governed_target, load_gravityguard_config,
    resolve_complexity_thresholds, resolve_project_root, should_enforce_doc_obligations,
)
from .security_rules import (  # noqa: F401
    check_blind_doc_overwrite, check_escape_hatch_tampering, check_g0_secret_leak,
    check_g1_silent_exception, check_g2_test_integrity, check_unsafe_code_patterns, is_protected_env_file,
)
from .test_evidence import (  # noqa: F401
    evaluate_t0_gate, evaluate_test_evidence, final_test_evidence_warnings, resolve_candidate_test_file,
)
from .delivery_gate import evaluate_ebdg_ui_gate  # noqa: F401
from .hook_output import drop_repeated_warnings, finalize  # noqa: F401
from .stop_dispatcher import (  # noqa: F401
    _SAFE_CONVERSATION_ID, _auto_resolve_changelog, _perform_architecture_sync,
    _perform_task_archiving, _project_relative, handle_stop_hook, is_rule_shadow,
)
from .code_guards import evaluate_code_guards
from .crash_recovery import (  # noqa: F401
    _CRASH_CONTEXT, _audit_guard_unavailable, _audit_recovery, _log_cli_error, _recover_from_crash, run_cli,
)


def validate_gravityguard() -> None:
    harden_streams_to_utf8()
    start_time = time.perf_counter()

    raw_input = sys.stdin.read() if not sys.stdin.isatty() else ""
    _CRASH_CONTEXT["raw"] = raw_input
    if not raw_input.strip():
        print(json.dumps({"decision": "allow"}))
        sys.exit(0)

    try:
        payload = json.loads(raw_input)
    except (ValueError, RecursionError):
        print(json.dumps({"decision": "deny", "reason": "[TOOL_SCHEMA_UNSUPPORTED]: Invalid JSON payload"}))
        sys.exit(0)

    if not isinstance(payload, dict):
        print(json.dumps({"decision": "deny", "reason": "[TOOL_SCHEMA_UNSUPPORTED]: Expected a JSON object"}))
        sys.exit(0)

    _call = payload.get("toolCall")
    _CRASH_CONTEXT.update(
        stop=bool(payload.get("terminationReason") or "--stop" in sys.argv),
        tool=str(_call.get("name", "")) if isinstance(_call, dict) else "",
        conversation_id=str(payload.get("conversationId", "default")),
    )

    if payload.get("terminationReason") or "--stop" in sys.argv:
        handle_stop_hook(payload)

    tool_call = payload.get("toolCall", {})
    if not isinstance(tool_call, dict):
        print(json.dumps({"decision": "deny", "reason": "[TOOL_SCHEMA_UNSUPPORTED]: Invalid toolCall"}))
        sys.exit(0)
    args = tool_call.get("args", {})
    raw_args = dict(args) if isinstance(args, dict) else {}
    tool_name = tool_call.get("name", "")
    c_id = payload.get("conversationId", "default")

    _log = session_logger(log_event, tool_name, c_id)

    shell_reason = check_shell_command(args, payload.get("cwd"), c_id)
    if shell_reason:
        _log("BLOCKED", "shell", shell_reason, rule_id="SHELL_SECURITY")
        print(json.dumps({"decision": "deny", "reason": shell_reason}))
        sys.exit(0)

    token_warning = ""
    _guard_cwd = payload.get("cwd")
    token_finding = evaluate_token_guard(
        tool_name,
        raw_args,
        cwd=_guard_cwd if isinstance(_guard_cwd, str) else os.getcwd(),
        conversation_id=c_id,
    )
    if token_finding:
        _guard_target = str(
            raw_args.get("Path")
            or raw_args.get("file_path")
            or raw_args.get("CommandLine")
            or raw_args.get("command")
            or ""
        )
        if token_finding.level == "deny":
            _log("BLOCKED", _guard_target, token_finding.reason, rule_id=token_finding.rule_id)
            print(json.dumps({
                "decision": "deny",
                "reason": f"[{token_finding.rule_id}]: {token_finding.reason}",
            }))
            sys.exit(0)
        _log("WARNING", _guard_target, token_finding.reason, rule_id=token_finding.rule_id)
        token_warning = token_finding.reason

    try:
        operation = normalize_operation(tool_name, args)
    except UnsupportedOperation as exc:
        reason = f"[TOOL_SCHEMA_UNSUPPORTED]: {exc}"
        _log("BLOCKED", "", reason, rule_id="TOOL_SCHEMA_UNSUPPORTED")
        print(json.dumps({"decision": "deny", "reason": reason}))
        sys.exit(0)
    if operation is None:
        if token_warning:
            print(json.dumps({"decision": "allow", "reason": token_warning}))
        else:
            print(json.dumps({"decision": "allow"}))
        sys.exit(0)
    target_file = operation.path
    if not os.path.isabs(target_file):
        cwd = payload.get("cwd")
        base = Path(cwd) if isinstance(cwd, str) and os.path.isabs(cwd) else resolve_project_root(payload)
        target_file = str(base / target_file)
    target_file = os.path.realpath(target_file)
    args = {**operation.args, "TargetFile": target_file}

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
    from .path_exemptions import is_vendor_or_cache_path
    is_vendor_or_cache = is_vendor_or_cache_path(file_lower)
    is_data_or_doc = file_lower.endswith((
        ".json", ".css", ".scss", ".md", ".txt", ".yaml", ".yml", ".toml", ".ini",
        ".lock", ".svg", ".gitignore"
    ))
    is_binary_asset = file_lower.endswith((
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".blend", ".exe", ".dll",
        ".so", ".bin", ".wasm", ".zip", ".tar", ".gz"
    ))

    if is_protected_env_file(operation.path) or is_protected_env_file(target_file):
        p_root = resolve_project_root(payload, target_file)
        cfg = load_gravityguard_config(target_file, p_root)
        if not is_rule_shadow("G0_ENV_PROTECTION", cfg):
            _log("BLOCKED", target_file, "Live environment secret file (.env) access denied", rule_id="G0_ENV_PROTECTION")
            print(json.dumps({
                "decision": "deny",
                "reason": (
                    f"🛑 [G0_ENV_PROTECTION]: '{target_file}' dosyası doğrudan yapay zeka ajanları tarafından "
                    f"OKUNAMAZ, DÜZENLENEMEZ veya OLUŞTURULAMAZ! Bu dosya gizli API anahtarları, parolalar ve özel ortam "
                    f"değişkenleri barındırır. Sızıntıyı önlemek için okuma engellenmiştir. Lütfen şablon için "
                    f"'.env.example' dosyasını inceleyin veya ilgili değişkeni kullanıcıya sorun."
                )
            }))
            sys.exit(0)

    if operation.kind == "READ":
        if target_file:
            _log("APPROVED", target_file, "Read tool allowed for non-sensitive file", rule_id="READ_ALLOW")
        print(json.dumps({"decision": "allow"}))
        sys.exit(0)

    if is_runtime_control_file(target_file):
        reason = ("[POLICY_INTEGRITY]: Installed guard hooks, receipts and runtime state require a trusted host action. "
                  "To add a hook, write a proposal to .gravityguard/proposals/hooks/<id>.json "
                  "(docs/operations/hook-proposals.md); the user approves it.")
        _log("BLOCKED", target_file, reason, rule_id="POLICY_INTEGRITY")
        print(json.dumps({"decision": "deny", "reason": reason}))
        sys.exit(0)

    p_root = resolve_project_root(payload, target_file)
    cfg = load_gravityguard_config(target_file, p_root)
    is_blocked, doc_reason = check_blind_doc_overwrite(target_file, tool_name, args, p_root)
    if is_blocked and not is_rule_shadow("G4_NO_BLIND_OVERWRITE", cfg):
        _log("BLOCKED", target_file, "Blind overwrite of existing documentation/rule file forbidden", rule_id="G4_NO_BLIND_OVERWRITE")
        print(json.dumps({"decision": "deny", "reason": doc_reason}))
        sys.exit(0)

    try:
        reconcile_obligations_on_disk(p_root, c_id, cfg)
    except StateLockTimeout as lock_err:
        _log("BLOCKED", target_file, f"State lock timeout: {lock_err}", rule_id="STATE_LOCK_TIMEOUT")
        print(json.dumps({
            "decision": "deny",
            "reason": f"🛑 [STATE_LOCK_TIMEOUT]: Durum dosyası kilit zaman aşımı ({lock_err}). Kayıp güncelleme riskini önlemek için işlem güvenli kilit alınana kadar reddedildi."
        }))
        sys.exit(0)

    try:
        old_full_content, projected_content = get_projected_and_old_content(
            target_file, tool_name, args,
            allow_virtual=os.environ.get("GRAVITYGUARD_TEST_VIRTUAL_FILES") == "1",
        )
    except ProjectionError as exc:
        reason = f"[PROJECTION_UNSUPPORTED]: {exc}"
        _log("BLOCKED", target_file, reason, rule_id="PROJECTION_UNSUPPORTED")
        print(json.dumps({"decision": "deny", "reason": reason}))
        sys.exit(0)
    policy_reason = check_policy_change(target_file, projected_content)
    if policy_reason:
        _log("BLOCKED", target_file, policy_reason, rule_id="POLICY_INTEGRITY")
        print(json.dumps({"decision": "deny", "reason": f"[POLICY_INTEGRITY]: {policy_reason}"}))
        sys.exit(0)
    engine_defect = engine_source_defect(target_file, projected_content)
    if engine_defect:
        reason = f"'{target_file}' bu yazımdan sonra çalışmaz hâle gelir: {engine_defect}. Doğrulama motoru kendi kaynağında bozuk durumda bırakılamaz."
        _log("BLOCKED", target_file, reason, rule_id="ENGINE_SELF_INTEGRITY")
        print(json.dumps({"decision": "deny", "reason": f"🛑 [ENGINE_SELF_INTEGRITY]: {reason}"}))
        sys.exit(0)
    added_lines, added_text, added_line_numbers = get_diff_analysis(old_full_content, projected_content)

    all_warnings: List[Tuple[str, str]] = []
    complexity_thresholds = resolve_complexity_thresholds(cfg)

    should_resolve_doc = False
    if target_file and is_data_or_doc:
        norm_target = target_file.replace("\\", "/").lower()
        if norm_target.endswith(("changelog.md", "knowledge.md", "architecture.md", "readme.md")):
            should_resolve_doc = True

    g0_violated, g0_reason, g0_warn = check_g0_secret_leak(added_text)
    if g0_warn:
        if is_rule_shadow("G0_SECRET_LEAK", cfg):
            _log("SHADOW_TRIGGER", target_file, f"[SHADOW] {g0_warn}", rule_id="G0_SECRET_LEAK")
        else:
            _log("WARNING", target_file, g0_warn, rule_id="G0_SECRET_LEAK")
            all_warnings.append(("G0_SECRET_LEAK", g0_warn))
    if g0_violated:
        if is_rule_shadow("G0_SECRET_LEAK", cfg):
            _log("SHADOW_TRIGGER", target_file, f"[SHADOW] {g0_reason}", rule_id="G0_SECRET_LEAK")
        else:
            _log("BLOCKED", target_file, g0_reason, rule_id="G0_SECRET_LEAK")
            print(json.dumps({"decision": "deny", "reason": f"🛑 [G0_SECRET_LEAK]: '{target_file}' - {g0_reason}"}))
            sys.exit(0)

    if is_binary_asset:
        if target_file:
            forget_denied_target(c_id, target_file)
        if os.environ.get("GRAVITYGUARD_LOG_EXEMPTS", "").lower() in ("1", "true", "yes"):
            _log("APPROVED", target_file, "Exempt file (Binary Asset)", rule_id="EXEMPT")
        print(json.dumps({"decision": "allow"}))
        sys.exit(0)

    is_prose_doc = file_lower.endswith((".md", ".markdown", ".mdx", ".txt"))
    responsive_violations = [] if is_prose_doc else find_design_responsive_violations(target_file, projected_content, added_line_numbers)
    for viol in responsive_violations:
        if viol.get("severity") == "DENY":
            deny_msg = (
                f"Mobil/Telefon tasar\u0131m kural\u0131 ihlali (Sat\u0131r {viol['line']}): {viol['message']}\n"
                f"Hatal\u0131 sat\u0131r: '{viol['snippet']}'\n"
                f"\u00d6neri: {viol['suggestion']}"
            )
            _log('BLOCKED', target_file, deny_msg, rule_id='DESIGN_RESPONSIVE_RULE')
            print(json.dumps({"decision": "deny", "reason": f"\U0001f6d1 [DESIGN_RESPONSIVE_RULE]: '{target_file}:{viol['line']}' - {deny_msg}"}))
            sys.exit(0)
        elif viol.get("severity") == "WARN":
            warn_msg = f"Sat\u0131r {viol['line']}: {viol['message']} \u00d6neri: {viol['suggestion']}"
            _log('WARNING', target_file, warn_msg, rule_id='DESIGN_RESPONSIVE_RULE')
            all_warnings.append(('DESIGN_RESPONSIVE_RULE', warn_msg))

    if not is_prose_doc:
        apply_plugin_rules(target_file, projected_content, added_line_numbers, cfg, _log, all_warnings)

    knowledge_governed = is_knowledge_governed_path(target_file, p_root)
    if is_vendor_or_cache or (is_data_or_doc and not knowledge_governed and not file_lower.endswith((".py", ".ts", ".tsx", ".js", ".jsx"))):
        if should_resolve_doc:
            try:
                record_resolution_intent("doc", target_file, p_root, c_id)
            except StateLockTimeout as lock_err:
                _log("BLOCKED", target_file, f"State lock timeout: {lock_err}", rule_id="STATE_LOCK_TIMEOUT")
                print(json.dumps({
                    "decision": "deny",
                    "reason": f"🛑 [STATE_LOCK_TIMEOUT]: Durum dosyası kilit zaman aşımı ({lock_err}). Kayıp güncelleme riskini önlemek için işlem güvenli kilit alınana kadar reddedildi."
                }))
                sys.exit(0)
        if target_file:
            forget_denied_target(c_id, target_file)
        if target_file and (all_warnings or os.environ.get("GRAVITYGUARD_LOG_EXEMPTS", "").strip().lower() in ("1", "true", "yes")):
            _log("APPROVED", target_file, "Exempt file (Vendor/Cache/Asset)", rule_id="EXEMPT")
        if all_warnings:
            warn_parts = [f"[{wid}] {wmsg}" for wid, wmsg in all_warnings]
            print(json.dumps({"decision": "allow", "reason": " ⚠ ".join(warn_parts)}))
        else:
            print(json.dumps({"decision": "allow"}))
        sys.exit(0)

    is_python = file_lower.endswith(".py")
    is_ts = file_lower.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"))

    evaluate_code_guards(
        target_file=target_file,
        file_lower=file_lower,
        is_test_file=is_test_file,
        is_python=is_python,
        is_ts=is_ts,
        old_full_content=old_full_content,
        projected_content=projected_content,
        added_lines=added_lines,
        added_text=added_text,
        added_line_numbers=added_line_numbers,
        p_root=p_root,
        cfg=cfg,
        complexity_thresholds=complexity_thresholds,
        log_fn=_log,
        all_warnings=all_warnings,
    )

    test_evidence_warnings, test_actions = evaluate_test_evidence(
        target_file=target_file,
        is_test_file=is_test_file,
        added_lines=added_lines,
        added_text=added_text,
        projected_content=projected_content,
        added_line_numbers=added_line_numbers,
        cfg=cfg,
        is_python=is_python,
        is_ts=is_ts,
    )
    for rule_id, warn_msg in test_evidence_warnings:
        _log("WARNING", target_file, warn_msg, rule_id=rule_id)
        all_warnings.append((rule_id, warn_msg))

    pending_doc_record = None
    if should_enforce_doc_obligations(target_file, cfg=cfg, project_root=p_root) and (is_doc_governed_target(target_file, cfg, p_root) or knowledge_governed):
        pending_doc_record = target_file

    diag_warnings = read_recent_diagnostics(target_file)
    for d_rule, d_msg in diag_warnings:
        _log("WARNING", target_file, d_msg, rule_id=d_rule)
        all_warnings.append((d_rule, d_msg))

    try:
        if should_resolve_doc:
            record_resolution_intent("doc", target_file, p_root, c_id)
        if test_actions.get("resolve_test"):
            record_resolution_intent("test", target_file, p_root, c_id)
        if test_actions.get("record_test"):
            tf, cp, en, msg = test_actions["record_test"]
            record_pending_test_evidence(tf, cp, en, msg, p_root, c_id)
            _log("APPROVED", tf, f"Pending test evidence recorded ({en})", rule_id="T1_PENDING")
        if pending_doc_record:
            required_docs = ["CHANGELOG.md"]
            k_doc = resolve_knowledge_doc(p_root) if knowledge_governed else None
            if k_doc:
                required_docs.append(k_doc)
            record_pending_doc_obligation(pending_doc_record, required_docs=required_docs, project_root=p_root, conversation_id=c_id)
            _log("APPROVED", pending_doc_record, f"Pending doc obligation recorded ({', '.join(required_docs)})", rule_id="DOC_OBLIGATION_PENDING")
        note_touched_file(p_root, c_id, target_file)
    except StateLockTimeout as lock_err:
        _log("BLOCKED", target_file, f"State lock timeout: {lock_err}", rule_id="STATE_LOCK_TIMEOUT")
        print(json.dumps({
            "decision": "deny",
            "reason": f"🛑 [STATE_LOCK_TIMEOUT]: Durum dosyası kilit zaman aşımı ({lock_err}). Kayıp güncelleme riskini önlemek için işlem güvenli kilit alınana kadar reddedildi."
        }))
        sys.exit(0)

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    _log("APPROVED", target_file, f"All Guards Passed ({elapsed_ms:.1f}ms)", rule_id="PASS",
         evasion_markers=find_evasion_markers(added_text))
    res_payload = {"decision": "allow"}
    try:
        all_warnings = drop_repeated_warnings(all_warnings, c_id, target_file)
    except Exception as dedupe_err:
        print(f"[GravityGuard] warning dedupe failed: {dedupe_err}", file=sys.stderr)
    if all_warnings:
        res_payload["reason"] = " ⚠ ".join(f"[{rule_id}] {msg}" for rule_id, msg in all_warnings)
    print(json.dumps(res_payload))
    trigger_background_validation(target_file)
    sys.exit(0)
