#!/usr/bin/env python3
"""
GravityGuard Engine — Stop / PostInvocation Lifecycle Hook Handler.
Executes final secret scans, architecture sync, obligation reconciliation,
T0 dynamic test/LCOV gates, EBDG UI screenshot gate, and task archiving.
Zero external dependencies.
"""
import json
import re
import sys
from pathlib import Path
from typing import Optional

from .delivery_gate import evaluate_ebdg_ui_gate
from .doc_automation import doc_obligation_auto
from .governance import (
    get_session_stop_retries,
    get_unresolved_doc_obligations,
    get_unresolved_test_evidence,
    increment_session_stop_retries,
    reconcile_obligations_on_disk,
    reset_session_stop_retries,
)
from .policy_integrity import MANDATORY_RULES
from .project_context import load_gravityguard_config, resolve_project_root
from .publication_guard import scan_git_secrets
from .removal_observer import observe_removals
from .state_lock import StateLockTimeout
from .stop_gate import critical_blockers, other_stop_roots, ratchet_findings
from .test_evidence import evaluate_t0_gate, final_test_evidence_warnings

_SAFE_CONVERSATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


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


def _perform_task_archiving(project_root: Path, conversation_id: str) -> None:
    from . import dispatcher as _disp
    try:
        from .task_archiver import archive_completed_tasks
        candidates = [project_root / "tasks.md", project_root / "task.md"]
        if conversation_id and conversation_id != "default" and _SAFE_CONVERSATION_ID.fullmatch(conversation_id):
            candidates.append(Path.home() / ".gemini" / "antigravity" / "brain" / conversation_id / "tasks.md")
        for t_path in candidates:
            if t_path.is_file():
                res = archive_completed_tasks(t_path)
                if res.get("performed") and int(res.get("archived_count", 0)) > 0:
                    _disp.log_event(
                        "stop", "APPROVED", str(t_path),
                        f"Archived {res['archived_count']} completed tasks into taskslog.md",
                        rule_id="TASK_ARCHIVE_AUTO",
                        conversation_id=conversation_id
                    )
    except Exception as arch_err:
        _disp.log_event(
            "stop", "WARNING", "tasks.md",
            f"Non-fatal error during automatic task archiving: {arch_err}",
            rule_id="TASK_ARCHIVE_ERROR",
            conversation_id=conversation_id
        )


def _perform_architecture_sync(project_root: Path, conversation_id: str) -> None:
    """Refresh the managed architecture block when source files change. Never breaks the session."""
    from . import dispatcher as _disp
    try:
        from .doc_automation import sync_architecture
        res = sync_architecture(project_root)
        if res and res["status"] != "unchanged":
            _disp.log_event(
                "stop", "APPROVED", res["path"], f"ARCHITECTURE.md auto-sync ({res['status']})",
                rule_id="ARCHITECTURE_SYNC_AUTO", conversation_id=conversation_id
            )
    except Exception as sync_err:
        _disp.log_event(
            "stop", "WARNING", "ARCHITECTURE.md", f"Non-fatal error during architecture sync: {sync_err}",
            rule_id="ARCHITECTURE_SYNC_ERROR", conversation_id=conversation_id
        )


def _auto_resolve_changelog(project_root: Path, conversation_id: str, unresolved_docs: dict) -> list:
    """Inject fallback CHANGELOG/KNOWLEDGE entries and close only completed obligations."""
    from . import dispatcher as _disp
    try:
        from .doc_automation import inject_changelog_entry, inject_knowledge_entry, summarize_changes
        resolved = []
        for doc in ("CHANGELOG.md", "KNOWLEDGE.md", "docs/KNOWLEDGE.md"):
            mine = []
            for p, info in unresolved_docs.items():
                candidate = Path(p)
                try:
                    (candidate if candidate.is_absolute() else project_root / candidate).resolve().relative_to(project_root.resolve())
                except ValueError:
                    continue
                if doc in info.get("required_docs", ["CHANGELOG.md"]):
                    mine.append(p)
            if not mine:
                continue
            path = project_root / doc
            inject = inject_changelog_entry if doc == "CHANGELOG.md" else inject_knowledge_entry
            if not inject(path, summarize_changes(project_root, sorted(mine))):
                continue
            resolved.extend(_disp.resolve_pending_doc_obligations(str(path), project_root, conversation_id))
            _disp.log_event(
                "stop", "APPROVED", str(path), f"Documentation entry auto-injected for {len(mine)} file(s)",
                rule_id="CHANGELOG_AUTO_INJECT" if doc == "CHANGELOG.md" else "KNOWLEDGE_AUTO_INJECT",
                conversation_id=conversation_id
            )
        return list(dict.fromkeys(resolved))
    except Exception as inj_err:
        _disp.log_event(
            "stop", "WARNING", "CHANGELOG.md", f"Non-fatal error during changelog auto-injection: {inj_err}",
            rule_id="CHANGELOG_AUTO_INJECT_ERROR", conversation_id=conversation_id
        )
        return []


def handle_stop_hook(payload: dict) -> None:
    """Executes the Stop / PostInvocation lifecycle hook and exits."""
    from . import dispatcher as _disp
    term_reason = payload.get("terminationReason", "")
    if term_reason in ("user_cancel", "cancelled", "user_abort"):
        print(json.dumps({"decision": "allow"}))
        sys.exit(0)

    conversation_id = payload.get("conversationId", "default")
    try:
        project_root = _disp.resolve_project_root(payload)
        cfg = _disp.load_gravityguard_config("", project_root)

        security_findings = []
        for scan_root in [project_root, *other_stop_roots(payload, project_root)]:
            security_findings.extend(scan_git_secrets(scan_root))
        if security_findings:
            reason = " | ".join(security_findings)
            _disp.log_event("stop", "BLOCKED", "workspace", reason, rule_id="FINAL_SECURITY_SCAN", conversation_id=conversation_id)
            print(json.dumps({"decision": "continue", "reason": reason}))
            sys.exit(0)

        _perform_architecture_sync(project_root, conversation_id)

        session_retries = get_session_stop_retries(project_root, conversation_id)
        if session_retries >= 5:
            critical = critical_blockers(project_root, cfg)
            if critical:
                reason = (
                    f"Devre kesici: {session_retries} deneme aşıldı ancak kritik mimari/test regresyonu mevcut; "
                    "manuel müdahale veya refactoring zorunlu. | " + " | ".join(f"[{rule}] {msg}" for rule, msg in critical)
                )
                _disp.log_event("stop", "BLOCKED", "workspace", reason, rule_id="STOP_CIRCUIT_BREAKER_BLOCKED", conversation_id=conversation_id)
                print(json.dumps({"decision": "continue", "reason": reason}))
                sys.exit(0)
            _disp.log_event(
                "stop", "WARNING", "workspace",
                f"Circuit breaker triggered (retries={session_retries}): allowing stop despite obligations",
                rule_id="STOP_CIRCUIT_BREAKER",
                conversation_id=conversation_id
            )
            reset_session_stop_retries(project_root, conversation_id)
            _perform_task_archiving(project_root, conversation_id)
            print(json.dumps({"decision": "allow", "reason": f"Devre kesici: {session_retries} deneme sonrası Stop serbest bırakıldı; açık yükümlülükler için insana bildir."}))
            sys.exit(0)

        _disp.reconcile_obligations_on_disk(project_root, conversation_id, cfg)

        unresolved_tests = dict(get_unresolved_test_evidence(project_root, conversation_id))
        unresolved_docs = dict(get_unresolved_doc_obligations(project_root, conversation_id))
        for other_root in other_stop_roots(payload, project_root):
            other_cfg = _disp.load_gravityguard_config("", other_root)
            _disp.reconcile_obligations_on_disk(other_root, conversation_id, other_cfg)
            unresolved_tests.update(get_unresolved_test_evidence(other_root, conversation_id))
            unresolved_docs.update(get_unresolved_doc_obligations(other_root, conversation_id))

        warn_reasons = []
        try:
            removals = observe_removals(project_root)
        except OSError as removal_err:
            removals = {"deleted": [], "suspicious_tests": []}
            _disp.log_event("stop", "WARNING", "workspace", f"Removal observer state error: {removal_err}", rule_id="REMOVAL_OBSERVER_ERROR", conversation_id=conversation_id)
        if removals["deleted"]:
            names = removals["deleted"]
            shown = ", ".join(names[:8]) + (f" (+{len(names) - 8} more)" if len(names) > 8 else "")
            _disp.log_event("stop", "APPROVED", "workspace", f"{len(names)} file(s) deleted outside the hook path: {shown}", rule_id="DELETE_OBSERVED", conversation_id=conversation_id)
        if removals["suspicious_tests"]:
            tests = removals["suspicious_tests"]
            shown = ", ".join(tests[:5]) + (f" (+{len(tests) - 5} more)" if len(tests) > 5 else "")
            removal_warn = (
                f"Test Silme Uyarısı: Test dosyası silindi ama test ettiği kod hâlâ duruyor: {shown}. "
                "Özellik gerçekten kaldırılıyorsa kodunu da sil; değilse testi geri getir. Emin değilsen kullanıcıya sor."
            )
            _disp.log_event("stop", "WARNING", "workspace", removal_warn, rule_id="TEST_DELETED_SUBJECT_REMAINS", conversation_id=conversation_id)
            warn_reasons.append(f"[TEST_DELETED_SUBJECT_REMAINS] {removal_warn}")
        for t_rule, t_msg in final_test_evidence_warnings(unresolved_tests):
            _disp.log_event("stop", "WARNING", "workspace", t_msg, rule_id=t_rule, conversation_id=conversation_id)
            warn_reasons += [f"[{t_rule}] {t_msg}"] if session_retries < 1 else []

        t0_findings = evaluate_t0_gate(str(project_root), cfg)
        for t0_rule, t0_msg in t0_findings:
            _disp.log_event("stop", "WARNING", "workspace", t0_msg, rule_id=t0_rule, conversation_id=conversation_id)
            warn_reasons.append(f"[{t0_rule}] {t0_msg}")

        ui_allowed, ui_warn, _ = evaluate_ebdg_ui_gate(
            project_root=project_root,
            conversation_id=conversation_id,
            session_retries=session_retries,
            cfg=cfg
        )
        if not ui_allowed and ui_warn:
            _disp.log_event("stop", "WARNING", "workspace", ui_warn, rule_id="EBDG_UI_SCREENSHOT_PENDING", conversation_id=conversation_id)
            warn_reasons.append(f"[EBDG_UI_SCREENSHOT_PENDING] {ui_warn}")

        if unresolved_docs and (session_retries >= 4 or doc_obligation_auto(cfg)):
            for closed in _auto_resolve_changelog(project_root, conversation_id, unresolved_docs):
                unresolved_docs.pop(closed, None)

        if unresolved_docs:
            changed = ", ".join(f"'{_project_relative(p, project_root)}'" for p in unresolved_docs)
            needed = sorted({d for info in unresolved_docs.values() for d in info.get("required_docs", ["CHANGELOG.md"])})
            if needed == ["CHANGELOG.md"]:
                todo = (
                    "CHANGELOG.md [Unreleased] bölümüne bu değişikliği anlatan bir girdi ekle. "
                    "(`## [Unreleased]` başlığı birden fazla geçebilir: edit_file Target'ı olarak yalnız başlığı değil, "
                    "ilk başlık satırını ve ardındaki benzersiz satırı birlikte ver; önce dosyanın ilk 15 satırını oku. "
                    "Son denemede yapılmamışsa GravityGuard tek satırlık özeti otomatik ekler.)"
                )
            else:
                todo = f"Şu dokümanları güncelle: {', '.join(needed)}."
            policy_ref = " (docs/KNOWLEDGE.md §6)" if (project_root / "docs" / "KNOWLEDGE.md").is_file() else ""
            retries_left = max(0, 5 - (session_retries + 1))
            doc_warn = (
                f"Dokümantasyon Yükümlülüğü{policy_ref}: Kod değişti ({changed}) ama doküman güncellenmedi. {todo} "
                f"(Kalan deneme: {retries_left}; sonra devre kesici durdurmaya izin verir.)"
            )
            _disp.log_event("stop", "WARNING", "workspace", doc_warn, rule_id="DOC_OBLIGATION_UNRESOLVED", conversation_id=conversation_id)
            warn_reasons.append(f"[DOC_OBLIGATION_UNRESOLVED] {doc_warn}")

        ratchet_regressions = ratchet_findings(
            project_root, cfg, conversation_id, is_rule_shadow("ARCH_RATCHET_REGRESSION", cfg), list(unresolved_docs)
        )
        warn_reasons += [f"[ARCH_RATCHET_REGRESSION] {msg}" for _rel, msg in ratchet_regressions]

        if warn_reasons:
            increment_session_stop_retries(project_root, conversation_id)
            _mark = lambda ok: chr(0x2713) if ok else chr(0x2717)
            status_summary = (
                f"Aşama Durumu: [Kod: {_mark(True)}] "
                f"[Test: {_mark(not (unresolved_tests or t0_findings))}] "
                f"[Görsel: {_mark(ui_allowed)}] "
                f"[Doküman: {_mark(not unresolved_docs)}] "
                f"[Mimari Ratchet: {_mark(not ratchet_regressions)}]"
            )
            full_reason = f"{status_summary} | " + " | ".join(warn_reasons)
            print(json.dumps({"decision": "continue", "reason": full_reason}))
        else:
            reset_session_stop_retries(project_root, conversation_id)
            _perform_task_archiving(project_root, conversation_id)
            print(json.dumps({"decision": "allow"}))
        sys.exit(0)
    except StateLockTimeout as lock_err:
        _disp.log_event("stop", "WARNING", "workspace", f"State lock timeout during Stop hook: {lock_err}", rule_id="STATE_LOCK_TIMEOUT", conversation_id=conversation_id)
        print(json.dumps({
            "decision": "continue",
            "reason": f"Durum kilidi zaman aşımı (StateLockTimeout): Oturum durumu güvenli şekilde doğrulanamadığı için henüz sonlandırılamaz ({lock_err})."
        }))
        sys.exit(0)
