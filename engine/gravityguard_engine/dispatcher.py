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
from typing import List, Tuple, Optional, Dict


from .architecture_rules import (
    analyze_python_srp,
    check_arch_file_growth,
    check_design_icon_rule,
    check_design_scrollbar_rule,
    check_g3_compiler_bypass,
    check_g4_import_matrix,
    check_g7_ts_first,
    check_pma_horizontal,
    check_pma_imports,
    check_oe_spike,
    is_ts_cohesive_monolith,
    record_and_check_cumulative_growth,
)
from .audit import log_event
from .state_lock import StateLockTimeout
from .diagnostics import read_recent_diagnostics, trigger_background_validation
from .diffing import get_diff_analysis, get_projected_and_old_content, ProjectionError
from .engine_integrity import engine_source_defect, repair_reason, run_lkg
from .policy_integrity import MANDATORY_RULES, check_policy_change, is_runtime_control_file
from .shell_rules import check_shell_command
from .publication_guard import scan_git_secrets
from .removal_observer import observe_removals
from .operations import normalize_operation, UnsupportedOperation
from .governance import (
    get_session_stop_retries,
    get_unresolved_doc_obligations,
    get_unresolved_test_evidence,
    increment_session_stop_retries,
    reconcile_obligations_on_disk,
    record_pending_doc_obligation,
    record_pending_test_evidence,
    record_resolution_intent,
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
    check_blind_doc_overwrite,
    check_escape_hatch_tampering,
    check_g0_secret_leak,
    check_g1_silent_exception,
    check_g2_test_integrity,
    check_unsafe_code_patterns,
    is_protected_env_file,
)
from .test_evidence import (
    evaluate_t0_gate,
    evaluate_test_evidence,
    resolve_candidate_test_file,
)
# Review governance removed

def _project_relative(path: str, root: Path) -> str:
    """Project-relative, forward-slash form of a recorded path (the absolute path when it lies outside the root)."""
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return str(path).replace("\\", "/")


def is_rule_shadow(rule_id: str, cfg: Optional[dict]) -> bool:
    """Checks if a rule is configured in shadow mode (observes without blocking/warning)."""
    if rule_id in MANDATORY_RULES or not isinstance(cfg, dict):
        return False
    rules_cfg = cfg.get("rules", {})
    if isinstance(rules_cfg, dict):
        r_entry = rules_cfg.get(rule_id)
        if isinstance(r_entry, dict) and r_entry.get("mode") == "shadow":
            return True
        if r_entry == "shadow":
            return True
    return False


def _other_stop_roots(payload: dict, primary: Path) -> List[Path]:
    """Other roots of a multi-root window that already keep governance state, for the Stop check.

    A Stop carries no target file, so the primary root is only the first declared workspace; a conversation that edited
    the second root would otherwise end with its obligations unseen. Only roots that already have a state file are
    returned (the check never creates state in a root this conversation did not touch), and obligations are session
    scoped, so another conversation's debt in those roots is not seen either. With the log-directory override
    (tests, isolated runs) the single override root is used as before.
    """
    if os.environ.get("GRAVITYGUARD_LOG_DIR"):
        return []
    workspaces = payload.get("workspacePaths", [])
    if not isinstance(workspaces, list):
        return []
    try:
        seen = {str(primary.resolve()).lower()}
    except OSError:
        seen = set()
    roots: List[Path] = []
    for ws in workspaces:
        if not ws:
            continue
        candidate = Path(str(ws))
        try:
            key = str(candidate.resolve()).lower()
        except OSError:
            continue
        if key in seen or not candidate.is_dir():
            continue
        seen.add(key)
        if (candidate / ".gravityguard" / "runtime" / "governance.json").is_file():
            roots.append(candidate)
    return roots


# A conversation id becomes a directory name below the user's brain folder: only plain identifiers are accepted,
# never separators or `..` (otherwise a crafted id would make the archiver rewrite an arbitrary `tasks.md`).
_SAFE_CONVERSATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


def _perform_task_archiving(project_root: Path, conversation_id: str) -> None:
    try:
        from .task_archiver import archive_completed_tasks
        candidates = [project_root / "tasks.md", project_root / "task.md"]
        if conversation_id and conversation_id != "default" and _SAFE_CONVERSATION_ID.fullmatch(conversation_id):
            candidates.append(Path.home() / ".gemini" / "antigravity" / "brain" / conversation_id / "tasks.md")
        for t_path in candidates:
            if t_path.is_file():
                res = archive_completed_tasks(t_path)
                if res.get("performed") and int(res.get("archived_count", 0)) > 0:
                    log_event(
                        "stop", "APPROVED", str(t_path),
                        f"Archived {res['archived_count']} completed tasks into taskslog.md",
                        rule_id="TASK_ARCHIVE_AUTO",
                        conversation_id=conversation_id
                    )
    except Exception as arch_err:
        log_event(
            "stop", "WARNING", "tasks.md",
            f"Non-fatal error during automatic task archiving: {arch_err}",
            rule_id="TASK_ARCHIVE_ERROR",
            conversation_id=conversation_id
        )


def validate_gravityguard() -> None:
    harden_streams_to_utf8()
    start_time = time.perf_counter()

    raw_input = sys.stdin.read() if not sys.stdin.isatty() else ""
    _CRASH_CONTEXT["raw"] = raw_input  # kept only so a crash can be re-validated by the last-known-good engine (never logged)
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

    # Minimal, non-sensitive call identity for crash telemetry (never the arguments or file contents).
    _call = payload.get("toolCall")
    _CRASH_CONTEXT.update(
        stop=bool(payload.get("terminationReason") or "--stop" in sys.argv),
        tool=str(_call.get("name", "")) if isinstance(_call, dict) else "",
        conversation_id=str(payload.get("conversationId", "default")),
    )

    # ========================================================================
    # 0. Lifecycle Hook Check: Stop / PostInvocation or CLI --stop flag
    # ========================================================================
    if payload.get("terminationReason") or "--stop" in sys.argv:
        term_reason = payload.get("terminationReason", "")
        if term_reason in ("user_cancel", "cancelled", "user_abort"):
            print(json.dumps({"decision": "allow"}))
            sys.exit(0)

        try:
            project_root = resolve_project_root(payload)
            conversation_id = payload.get("conversationId", "default")
            cfg = load_gravityguard_config("", project_root)

            # Mandatory security scans run before the advisory circuit breaker.
            security_findings = []
            for scan_root in [project_root, *_other_stop_roots(payload, project_root)]:
                security_findings.extend(scan_git_secrets(scan_root))
            if security_findings:
                reason = " | ".join(security_findings)
                log_event("stop", "BLOCKED", "workspace", reason, rule_id="FINAL_SECURITY_SCAN", conversation_id=conversation_id)
                print(json.dumps({"decision": "continue", "reason": reason}))
                sys.exit(0)

            # Defect A fix: Circuit breaker strictly governed by session continuation retries
            session_retries = get_session_stop_retries(project_root, conversation_id)
            if session_retries >= 5:
                log_event(
                    "stop", "WARNING", "workspace",
                    f"Circuit breaker triggered (retries={session_retries}): allowing stop despite obligations",
                    rule_id="STOP_CIRCUIT_BREAKER",
                    conversation_id=conversation_id
                )
                reset_session_stop_retries(project_root, conversation_id)
                _perform_task_archiving(project_root, conversation_id)
                print(json.dumps({"decision": "allow"}))
                sys.exit(0)

            # Defect B fix: Reconcile obligations with physical filesystem verification
            reconcile_obligations_on_disk(project_root, conversation_id, cfg)

            unresolved_tests = dict(get_unresolved_test_evidence(project_root, conversation_id))
            unresolved_docs = dict(get_unresolved_doc_obligations(project_root, conversation_id))
            for other_root in _other_stop_roots(payload, project_root):
                other_cfg = load_gravityguard_config("", other_root)
                reconcile_obligations_on_disk(other_root, conversation_id, other_cfg)
                unresolved_tests.update(get_unresolved_test_evidence(other_root, conversation_id))
                unresolved_docs.update(get_unresolved_doc_obligations(other_root, conversation_id))

            warn_reasons = []
            try:
                removals = observe_removals(project_root)
            except OSError as removal_err:
                removals = {"deleted": [], "suspicious_tests": []}
                log_event("stop", "WARNING", "workspace", f"Removal observer state error: {removal_err}", rule_id="REMOVAL_OBSERVER_ERROR", conversation_id=conversation_id)
            if removals["deleted"]:
                names = removals["deleted"]
                shown = ", ".join(names[:8]) + (f" (+{len(names) - 8} more)" if len(names) > 8 else "")
                log_event("stop", "APPROVED", "workspace", f"{len(names)} file(s) deleted outside the hook path: {shown}", rule_id="DELETE_OBSERVED", conversation_id=conversation_id)
            if removals["suspicious_tests"]:
                tests = removals["suspicious_tests"]
                shown = ", ".join(tests[:5]) + (f" (+{len(tests) - 5} more)" if len(tests) > 5 else "")
                removal_warn = (
                    f"Test Silme Uyarısı (TEST_DELETED_SUBJECT_REMAINS): Test dosyası silindi ama test ettiği kod hâlâ duruyor: {shown}. "
                    "Özellik gerçekten kaldırılıyorsa kodunu da sil; değilse testi geri getir. Emin değilsen kullanıcıya sor."
                )
                log_event("stop", "WARNING", "workspace", removal_warn, rule_id="TEST_DELETED_SUBJECT_REMAINS", conversation_id=conversation_id)
                warn_reasons.append(removal_warn)
            if unresolved_tests:
                missing_items = [
                    f"'{p}' (beklenen test: {info.get('expected_name', 'test')})"
                    for p, info in unresolved_tests.items()
                ]
                t1_warn = (
                    f"Test Kanıtı Uyarısı (T1): Oturum tamamlandı ancak şu üretim kodları için "
                    f"test kanıtı bulunamadı: {', '.join(missing_items)}"
                )
                log_event("stop", "WARNING", "workspace", t1_warn, rule_id="T1_FINAL_UNRESOLVED", conversation_id=conversation_id)
                warn_reasons.append(t1_warn)

            # T0: dynamic test run + LCOV gate (opt-in via testEvidence.dynamicExecution)
            t0_findings = evaluate_t0_gate(str(project_root), cfg)
            for t0_rule, t0_msg in t0_findings:
                log_event("stop", "WARNING", "workspace", t0_msg, rule_id=t0_rule, conversation_id=conversation_id)
                warn_reasons.append(t0_msg)

            if unresolved_docs:
                changed = ", ".join(f"'{_project_relative(p, project_root)}'" for p in unresolved_docs)
                needed = sorted({d for info in unresolved_docs.values() for d in info.get("required_docs", ["CHANGELOG.md"])})
                if needed == ["CHANGELOG.md"]:
                    todo = "CHANGELOG.md [Unreleased] bölümüne bu değişikliği anlatan bir girdi ekle."
                else:
                    todo = f"Şu dokümanları güncelle: {', '.join(needed)}."
                policy_ref = " (docs/KNOWLEDGE.md §6)" if (project_root / "docs" / "KNOWLEDGE.md").is_file() else ""
                retries_left = max(0, 5 - (session_retries + 1))
                doc_warn = (
                    f"Dokümantasyon Yükümlülüğü{policy_ref}: Kod değişti ({changed}) ama doküman güncellenmedi. {todo} "
                    f"(Kalan deneme: {retries_left}; sonra devre kesici durdurmaya izin verir.)"
                )
                log_event("stop", "WARNING", "workspace", doc_warn, rule_id="DOC_OBLIGATION_UNRESOLVED", conversation_id=conversation_id)
                warn_reasons.append(doc_warn)

            if warn_reasons:
                increment_session_stop_retries(project_root, conversation_id)
                status_summary = (
                    f"Aşama Durumu: [Kod: ✓] "
                    f"[Test: {'✗' if unresolved_tests or t0_findings else '✓'}] "
                    f"[Doküman: {'✗' if unresolved_docs else '✓'}]"
                )
                full_reason = f"{status_summary} | " + " | ".join(warn_reasons)
                print(json.dumps({"decision": "continue", "reason": full_reason}))
            else:
                reset_session_stop_retries(project_root, conversation_id)
                _perform_task_archiving(project_root, conversation_id)
                print(json.dumps({"decision": "allow"}))
            sys.exit(0)
        except StateLockTimeout as lock_err:
            log_event("stop", "WARNING", "workspace", f"State lock timeout during Stop hook: {lock_err}", rule_id="STATE_LOCK_TIMEOUT", conversation_id=conversation_id)
            print(json.dumps({
                "decision": "continue",
                "reason": f"Durum kilidi zaman aşımı (StateLockTimeout): Oturum durumu güvenli şekilde doğrulanamadığı için henüz sonlandırılamaz ({lock_err})."
            }))
            sys.exit(0)

    # ========================================================================
    # PreToolUse Lifecycle Hook Dispatcher
    # ========================================================================
    tool_call = payload.get("toolCall", {})
    if not isinstance(tool_call, dict):
        print(json.dumps({"decision": "deny", "reason": "[TOOL_SCHEMA_UNSUPPORTED]: Invalid toolCall"}))
        sys.exit(0)
    args = tool_call.get("args", {})
    tool_name = tool_call.get("name", "")
    c_id = payload.get("conversationId", "default")

    def _log(status: str, target: str, reason: str, rule_id: str = "") -> None:
        log_event(tool_name, status, target, reason, rule_id=rule_id, conversation_id=c_id)

    shell_reason = check_shell_command(args)
    if shell_reason:
        _log("BLOCKED", "shell", shell_reason, rule_id="SHELL_SECURITY")
        print(json.dumps({"decision": "deny", "reason": shell_reason}))
        sys.exit(0)


    try:
        operation = normalize_operation(tool_name, args)
    except UnsupportedOperation as exc:
        reason = f"[TOOL_SCHEMA_UNSUPPORTED]: {exc}"
        _log("BLOCKED", "", reason, rule_id="TOOL_SCHEMA_UNSUPPORTED")
        print(json.dumps({"decision": "deny", "reason": reason}))
        sys.exit(0)
    if operation is None:
        print(json.dumps({"decision": "allow"}))
        sys.exit(0)
    target_file = operation.path
    if not os.path.isabs(target_file):
        cwd = payload.get("cwd")
        base = Path(cwd) if isinstance(cwd, str) and os.path.isabs(cwd) else resolve_project_root(payload)
        target_file = str(base / target_file)
    target_file = os.path.realpath(target_file)
    args = {**operation.args, "TargetFile": target_file}

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

    # 1.1 Protect live .env files from being read, created, overwritten, or modified by AI agents
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

    # Fast-pass for view/read tools once protected env files are checked
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

    # 1.2 Prevent blind overwriting of existing documentation, architecture, rule, and skill files
    p_root = resolve_project_root(payload, target_file)
    cfg = load_gravityguard_config(target_file, p_root)
    is_blocked, doc_reason = check_blind_doc_overwrite(target_file, tool_name, args, p_root)
    if is_blocked and not is_rule_shadow("G4_NO_BLIND_OVERWRITE", cfg):
        _log("BLOCKED", target_file, "Blind overwrite of existing documentation/rule file forbidden", rule_id="G4_NO_BLIND_OVERWRITE")
        print(json.dumps({
            "decision": "deny",
            "reason": doc_reason
        }))
        sys.exit(0)

    # Reconcile disk state for any obligations satisfied by prior tool writes
    try:
        reconcile_obligations_on_disk(p_root, c_id, cfg)
    except StateLockTimeout as lock_err:
        _log("BLOCKED", target_file, f"State lock timeout: {lock_err}", rule_id="STATE_LOCK_TIMEOUT")
        print(json.dumps({
            "decision": "deny",
            "reason": f"🛑 [STATE_LOCK_TIMEOUT]: Durum dosyası kilit zaman aşımı ({lock_err}). Kayıp güncelleme riskini önlemek için işlem güvenli kilit alınana kadar reddedildi."
        }))
        sys.exit(0)

    # 2. Extract projected and old content, compute exact diff
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
            print(json.dumps({
                "decision": "deny",
                "reason": f"🛑 [G0_SECRET_LEAK]: '{target_file}' - {g0_reason}"
            }))
            sys.exit(0)

    # A filename suffix cannot exempt incoming text from G0.
    if is_binary_asset:
        if os.environ.get("GRAVITYGUARD_LOG_EXEMPTS", "").lower() in ("1", "true", "yes"):
            _log("APPROVED", target_file, "Exempt file (Binary Asset)", rule_id="EXEMPT")
        print(json.dumps({"decision": "allow"}))
        sys.exit(0)

    # Warn before the asset fast-pass so CSS additions are checked as well.
    # G7: TypeScript First Advisory (WARN ONLY)
    g7_warn = check_g7_ts_first(target_file)
    if g7_warn:
        _log('WARNING', target_file, g7_warn, rule_id='G7_TS_FIRST')
        all_warnings.append(('G7_TS_FIRST', g7_warn))

    design_icons = check_design_icon_rule(target_file, added_text)
    if design_icons:
        warn_msg = f"Tasarım kuralına uymuyor hemen düzelt: kodda standart emoji/ikon kullanımı tespit edildi ({', '.join(design_icons[:5])})."
        _log('WARNING', target_file, warn_msg, rule_id='DESIGN_ICON_RULE')
        all_warnings.append(('DESIGN_ICON_RULE', warn_msg))

    design_scrollbars = check_design_scrollbar_rule(target_file, added_text)
    if design_scrollbars:
        warn_msg = "Tasarım kuralına uymuyor hemen düzelt: webin varsayılan yukarı aşağı kaydırma barları kullanılamaz. Evrensel minimalist / görünmez scrollbar standardı uygulanmalıdır."
        _log('WARNING', target_file, warn_msg, rule_id='DESIGN_SCROLLBAR_RULE')
        all_warnings.append(('DESIGN_SCROLLBAR_RULE', warn_msg))

    # Fast-pass for vendor, cache, and non-code text assets (ONLY AFTER G0 IS CLEAN)
    if is_vendor_or_cache or (is_data_or_doc and not file_lower.endswith((".py", ".ts", ".tsx", ".js", ".jsx"))):
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
        # Benign exempt files (Vendor/Cache/Asset/Docs) are silent by default (like read tools)
        # to prevent log pollution and keep the Live Monitor focused on actual guards, warnings, and code changes.
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

    # ========================================================================
    # GUARD 1: G1 — SILENT EXCEPTION (BLOCK)
    # ========================================================================
    if not is_test_file:
        g1_violated, g1_reason = check_g1_silent_exception(
            added_lines, added_text, added_line_numbers, projected_content, is_python, is_ts
        )
        if g1_violated:
            if is_rule_shadow("G1_SILENT_EXCEPTION", cfg):
                _log("SHADOW_TRIGGER", target_file, f"[SHADOW] {g1_reason}", rule_id="G1_SILENT_EXCEPTION")
            else:
                _log("BLOCKED", target_file, g1_reason, rule_id="G1_SILENT_EXCEPTION")
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
            if is_rule_shadow("G2_TEST_INTEGRITY", cfg):
                _log("SHADOW_TRIGGER", target_file, f"[SHADOW] {g2_warn}", rule_id="G2_TEST_INTEGRITY")
            else:
                _log("WARNING", target_file, g2_warn, rule_id="G2_TEST_INTEGRITY")
                all_warnings.append(("G2_TEST_INTEGRITY", g2_warn))
        if g2_violated:
            if is_rule_shadow("G2_TEST_INTEGRITY", cfg):
                _log("SHADOW_TRIGGER", target_file, f"[SHADOW] {g2_reason}", rule_id="G2_TEST_INTEGRITY")
            else:
                _log("BLOCKED", target_file, g2_reason, rule_id="G2_TEST_INTEGRITY")
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
        if is_rule_shadow("G2_SECURITY_TAMPERING", cfg):
            _log("SHADOW_TRIGGER", target_file, f"[SHADOW] {tamper_reason}", rule_id="G2_SECURITY_TAMPERING")
        else:
            _log("BLOCKED", target_file, tamper_reason, rule_id="G2_SECURITY_TAMPERING")
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
        if is_rule_shadow("G3_COMPILER_BYPASS", cfg):
            _log("SHADOW_TRIGGER", target_file, f"[SHADOW] {warn_msg}", rule_id="G3_COMPILER_BYPASS")
        else:
            _log("WARNING", target_file, warn_msg, rule_id="G3_COMPILER_BYPASS")
            all_warnings.append(("G3_COMPILER_BYPASS", warn_msg))

    # ========================================================================
    # SEC_UNSAFE_PATTERN — risky constructs in new code: TLS off, shell=True, SQL string-building, innerHTML, pickle (WARN ONLY)
    # ========================================================================
    _lower_target = target_file.replace("\\", "/").lower()
    if not _lower_target.endswith((".md", ".txt", ".rst")) and "/tests/" not in _lower_target and not _lower_target.rsplit("/", 1)[-1].startswith("test_"):
        unsafe_hits = check_unsafe_code_patterns(added_text)
        if unsafe_hits:
            unsafe_msg = f"Yeni kodda riskli yapı tespit edildi: {'; '.join(unsafe_hits)}. Gerekçesiz bırakmayın veya güvenli alternatifi kullanın."
            if is_rule_shadow("SEC_UNSAFE_PATTERN", cfg):
                _log("SHADOW_TRIGGER", target_file, f"[SHADOW] {unsafe_msg}", rule_id="SEC_UNSAFE_PATTERN")
            else:
                _log("WARNING", target_file, unsafe_msg, rule_id="SEC_UNSAFE_PATTERN")
                all_warnings.append(("SEC_UNSAFE_PATTERN", unsafe_msg))

    # ========================================================================
    # GUARD 4: G4 — IMPORT MATRIX (BLOCK)
    # ========================================================================
    g4_violated, g4_reason = check_g4_import_matrix(target_file, added_text)
    if g4_violated:
        if is_rule_shadow("G4_IMPORT_MATRIX", cfg):
            _log("SHADOW_TRIGGER", target_file, f"[SHADOW] {g4_reason}", rule_id="G4_IMPORT_MATRIX")
        else:
            _log("BLOCKED", target_file, g4_reason, rule_id="G4_IMPORT_MATRIX")
            print(json.dumps({
                "decision": "deny",
                "reason": f"🛑 [G4_IMPORT_MATRIX]: '{target_file}' - {g4_reason}"
            }))
            sys.exit(0)

    # ========================================================================
    # GUARD 4B: ARCH_PMA_* — PRAGMATIC MODULAR ARCHITECTURE BOUNDARIES (BLOCK)
    # ========================================================================
    pma_hits = []
    pma_h_violated, pma_h_reason = check_pma_horizontal(target_file)
    if pma_h_violated:
        pma_hits.append(("ARCH_PMA_HORIZONTAL_DENY", pma_h_reason))
    pma_i_violated, pma_i_rule, pma_i_reason = check_pma_imports(target_file, added_text)
    if pma_i_violated:
        pma_hits.append((pma_i_rule, pma_i_reason))
    for pma_rule, pma_reason in pma_hits:
        if is_rule_shadow(pma_rule, cfg):
            _log("SHADOW_TRIGGER", target_file, f"[SHADOW] {pma_reason}", rule_id=pma_rule)
        else:
            _log("BLOCKED", target_file, pma_reason, rule_id=pma_rule)
            print(json.dumps({
                "decision": "deny",
                "reason": f"🛑 [{pma_rule}]: '{target_file}' - {pma_reason}"
            }))
            sys.exit(0)

    # ========================================================================
    # GUARD 5: OE_SPIKE — OVER-ENGINEERING (WARN ONLY)
    # ========================================================================
    oe_triggered, oe_msg = check_oe_spike(added_text, complexity_thresholds)
    if oe_triggered:
        if is_rule_shadow("OE_SPIKE", cfg):
            _log("SHADOW_TRIGGER", target_file, f"[SHADOW] {oe_msg}", rule_id="OE_SPIKE")
        else:
            _log("WARNING", target_file, oe_msg, rule_id="OE_SPIKE")
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
        if is_rule_shadow("ARCH_FILE_GROWTH", cfg):
            _log("SHADOW_TRIGGER", target_file, f"[SHADOW] {arch_msg}", rule_id="ARCH_FILE_GROWTH")
        else:
            _log("WARNING", target_file, arch_msg, rule_id="ARCH_FILE_GROWTH")
            all_warnings.append(("ARCH_FILE_GROWTH", arch_msg))

    # ========================================================================
    # GUARD 7: EXISTING SRP (Single Responsibility Principle & Web SRP)
    # ========================================================================
    if not is_test_file:
        if file_lower.endswith((".html", ".htm")):
            from .web_srp_analyzer import analyze_html_srp
            is_violation, rule_id, reason_msg, web_warnings = analyze_html_srp(projected_content, file_path=target_file)
            for wid, wmsg in web_warnings:
                if is_rule_shadow(wid, cfg):
                    _log("SHADOW_TRIGGER", target_file, f"[SHADOW] {wmsg}", rule_id=wid)
                else:
                    _log("WARNING", target_file, wmsg, rule_id=wid)
                    all_warnings.append((wid, wmsg))
            if is_violation:
                if is_rule_shadow(rule_id, cfg):
                    _log("SHADOW_TRIGGER", target_file, f"[SHADOW] {reason_msg}", rule_id=rule_id)
                else:
                    _log("BLOCKED", target_file, reason_msg, rule_id=rule_id)
                    print(json.dumps({
                        "decision": "deny",
                        "reason": f"🛑 [{rule_id}]: '{target_file}' - {reason_msg}"
                    }))
                    sys.exit(0)

        elif is_python:
            is_violation, reason = analyze_python_srp(projected_content, file_path=target_file)
            if is_violation:
                if is_rule_shadow("SRP_BOUNDARY", cfg):
                    _log("SHADOW_TRIGGER", target_file, f"[SHADOW] {reason}", rule_id="SRP_BOUNDARY")
                else:
                    _log("BLOCKED", target_file, reason, rule_id="SRP_BOUNDARY")
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
                    _log("SHADOW_TRIGGER", target_file, f"[SHADOW] {reason_msg}", rule_id="SRP_BOUNDARY")
                else:
                    _log("BLOCKED", target_file, reason_msg, rule_id="SRP_BOUNDARY")
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
        _log("WARNING", target_file, warn_msg, rule_id=rule_id)
        all_warnings.append((rule_id, warn_msg))

    # Stage doc obligation if production/engine code is changed and doc governance is enabled
    pending_doc_record = None
    if should_enforce_doc_obligations(target_file, cfg=cfg) and is_doc_governed_target(target_file, cfg, p_root):
        pending_doc_record = target_file

    # ========================================================================
    # GUARD 9: STATIC LINTER & COMPILER DIAGNOSTIC FEEDBACK (WARN ONLY)
    # ========================================================================
    diag_warnings = read_recent_diagnostics(target_file)
    for d_rule, d_msg in diag_warnings:
        _log("WARNING", target_file, d_msg, rule_id=d_rule)
        all_warnings.append((d_rule, d_msg))

    # ========================================================================
    # PASS / APPROVED
    # Two-phase commit: All guards passed. Record resolution intents!
    # Physical reconciliation commits resolutions once written to disk.
    # ========================================================================
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
            record_pending_doc_obligation(pending_doc_record, project_root=p_root, conversation_id=c_id)

        # Review obligation removed (AI review disabled).
    except StateLockTimeout as lock_err:
        _log("BLOCKED", target_file, f"State lock timeout: {lock_err}", rule_id="STATE_LOCK_TIMEOUT")
        print(json.dumps({
            "decision": "deny",
            "reason": f"🛑 [STATE_LOCK_TIMEOUT]: Durum dosyası kilit zaman aşımı ({lock_err}). Kayıp güncelleme riskini önlemek için işlem güvenli kilit alınana kadar reddedildi."
        }))
        sys.exit(0)


    elapsed_ms = (time.perf_counter() - start_time) * 1000
    _log("APPROVED", target_file, f"All Guards Passed ({elapsed_ms:.1f}ms)", rule_id="PASS")
    res_payload = {"decision": "allow"}
    if all_warnings:
        res_payload["reason"] = " ⚠ ".join(
            f"[{rule_id}] {msg}" for rule_id, msg in all_warnings
        )
    print(json.dumps(res_payload))
    trigger_background_validation(target_file)
    sys.exit(0)


_CRASH_CONTEXT: dict = {}


def _log_cli_error(tb_text: str) -> None:
    """Persist a crash traceback to the global and project-local error logs (best effort)."""
    from datetime import datetime
    event = next((a for a in sys.argv[1:] if a.startswith("--")), "stop" if _CRASH_CONTEXT.get("stop") else "pre-tool" if _CRASH_CONTEXT else "unknown")
    who = f" tool={_CRASH_CONTEXT.get('tool', '')!r} conversation={_CRASH_CONTEXT.get('conversation_id', '')!r}" if _CRASH_CONTEXT else ""
    entry = f"[{datetime.now().isoformat()}] hook_event={event}{who} argv={sys.argv!r}\n{tb_text}\n"
    for path in (
        os.path.expanduser("~/.gemini/config/plugins/gravityguard/logs/gravityguard_errors.log"),
        os.path.join(".gravityguard", "runtime", "gravityguard_errors.log"),
    ):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(entry)
        except Exception:
            pass


def _audit_guard_unavailable(exc: BaseException) -> None:
    """Record the fail-closed denial in the permanent audit stream so engine outages are not blind spots in telemetry.

    Only the exception type/message and the tool name are stored (no payload, arguments or file contents).
    """
    try:
        log_event(
            "stop" if _CRASH_CONTEXT.get("stop") else (_CRASH_CONTEXT.get("tool") or "unknown"),
            "BLOCKED",
            "engine",
            f"[GUARD_UNAVAILABLE]: {type(exc).__name__}: {str(exc)[:200]}",
            rule_id="GUARD_UNAVAILABLE",
            conversation_id=_CRASH_CONTEXT.get("conversation_id") or None,
        )
    except Exception as audit_err:  # telemetry must never turn an outage into a second failure
        sys.stderr.write(f"[GravityGuard] could not audit GUARD_UNAVAILABLE: {type(audit_err).__name__}\n")


def _recover_from_crash() -> Optional[dict]:
    """Keep the guard useful after an engine defect without failing open.

    1. Re-validate the same payload with the last committed engine (full protection, so a half-edited working tree
       cannot wedge the agent). 2. If that is unavailable too, allow only writes to engine source files so the
       defect can be repaired (`engine_integrity.repair_reason`). Anything else stays denied by the caller.
    """
    raw = _CRASH_CONTEXT.get("raw") or ""
    if not raw.strip():
        return None
    answer = run_lkg(raw, sys.argv)
    if answer is not None:
        return {**answer, "_recovery": "GUARD_FALLBACK_LKG"}
    reason = repair_reason(raw)
    return {"decision": "allow", "reason": reason, "_recovery": "GUARD_REPAIR_MODE"} if reason else None


def _audit_recovery(recovery: str, exc: BaseException) -> None:
    try:
        log_event(
            "stop" if _CRASH_CONTEXT.get("stop") else (_CRASH_CONTEXT.get("tool") or "unknown"),
            "WARNING",
            "engine",
            f"[{recovery}]: engine defect {type(exc).__name__}: {str(exc)[:160]}",
            rule_id=recovery,
            conversation_id=_CRASH_CONTEXT.get("conversation_id") or None,
        )
    except Exception as audit_err:  # telemetry must never turn a recovery into a failure
        sys.stderr.write(f"[GravityGuard] could not audit {recovery}: {type(audit_err).__name__}\n")


def run_cli() -> None:
    try:
        validate_gravityguard()
    except Exception as crash:
        import traceback
        _log_cli_error(traceback.format_exc())
        recovered = _recover_from_crash()
        if recovered is not None:
            recovery = recovered.pop("_recovery")
            _audit_recovery(recovery, crash)
            print(json.dumps(recovered))
            return
        _audit_guard_unavailable(crash)
        # Native hosts must receive an explicit result even when persistence or
        # another subsystem fails. Do not echo payloads or exception contents.
        print("[GravityGuard] validation failed; operation was not validated", file=sys.stderr)
        print(json.dumps({"decision": "continue" if "--stop" in sys.argv else "deny",
                          "reason": "[GUARD_UNAVAILABLE]: Validation could not complete"}))
