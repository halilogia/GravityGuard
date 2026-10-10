#!/usr/bin/env python3
"""
Unit tests for GravityGuard Governance Subsystem (State, Circuit Breaker & Obligations).
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine.governance import (
    clear_doc_obligations,
    clear_governance_state,
    clear_test_evidence_state,
    compute_file_digest,
    get_governance_file_path,
    get_governance_lock_path,
    get_session_stop_retries,
    get_unresolved_doc_obligations,
    get_unresolved_test_evidence,
    governance_transaction,
    increment_session_stop_retries,
    load_governance_state,
    load_test_evidence_state,
    reconcile_obligations_on_disk,
    record_pending_doc_obligation,
    record_pending_test_evidence,
    record_resolution_intent,
    reset_session_stop_retries,
    resolve_pending_doc_obligations,
    resolve_pending_test_evidence,
    save_governance_state,
)
from gravityguard_engine.state_lock import StateLock, StateLockTimeout


class TestGovernanceDomain(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="gg_gov_test_")
        self.orig_log_dir = os.environ.get("GRAVITYGUARD_LOG_DIR")
        os.environ["GRAVITYGUARD_LOG_DIR"] = self.temp_dir

    def tearDown(self):
        if self.orig_log_dir is not None:
            os.environ["GRAVITYGUARD_LOG_DIR"] = self.orig_log_dir
        else:
            os.environ.pop("GRAVITYGUARD_LOG_DIR", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_session_retries_increment_and_reset(self):
        root = Path(self.temp_dir)
        cid = "sess-123"
        self.assertEqual(get_session_stop_retries(root, cid), 0)
        self.assertEqual(increment_session_stop_retries(root, cid), 1)
        self.assertEqual(increment_session_stop_retries(root, cid), 2)
        self.assertEqual(get_session_stop_retries(root, cid), 2)
        reset_session_stop_retries(root, cid)
        self.assertEqual(get_session_stop_retries(root, cid), 0)

    def test_record_and_resolve_test_evidence(self):
        root = Path(self.temp_dir)
        cid = "sess-abc"
        record_pending_test_evidence(
            "src/billing.ts", "tests/billing.test.ts", "billing.test.ts", "missing test",
            project_root=root, conversation_id=cid
        )
        unresolved = get_unresolved_test_evidence(root, cid)
        self.assertIn("src/billing.ts", unresolved)

        resolved = resolve_pending_test_evidence("tests/billing.test.ts", root, cid)
        self.assertIn("src/billing.ts", resolved)
        self.assertEqual(len(get_unresolved_test_evidence(root, cid)), 0)

    def test_record_and_resolve_doc_obligation(self):
        root = Path(self.temp_dir)
        cid = "sess-doc"
        record_pending_doc_obligation(
            "engine/core.py", ["CHANGELOG.md"], "Engine modified",
            project_root=root, conversation_id=cid
        )
        unresolved = get_unresolved_doc_obligations(root, cid)
        self.assertIn("engine/core.py", unresolved)

        resolved = resolve_pending_doc_obligations("CHANGELOG.md", root, cid)
        self.assertIn("engine/core.py", resolved)
        self.assertEqual(len(get_unresolved_doc_obligations(root, cid)), 0)

    def test_reconcile_obligations_on_disk(self):
        root = Path(self.temp_dir)
        cid = "sess-disk"
        record_pending_doc_obligation("engine/sync.py", ["CHANGELOG.md"], project_root=root, conversation_id=cid)
        changelog_file = root / "CHANGELOG.md"

        # Not yet on disk -> unresolved
        res_tests, res_docs = reconcile_obligations_on_disk(root, cid)
        self.assertEqual(res_docs, [])

        # Physically write file on disk
        time.sleep(0.01)
        changelog_file.write_text("# Changelog", encoding="utf-8")
        res_tests, res_docs = reconcile_obligations_on_disk(root, cid)
        self.assertIn("engine/sync.py", res_docs)
        self.assertEqual(len(get_unresolved_doc_obligations(root, cid)), 0)

    def test_resolution_intent_two_phase_commit(self):
        root = Path(self.temp_dir)
        cid = "sess-intent"
        record_pending_doc_obligation("engine/api.py", ["CHANGELOG.md"], project_root=root, conversation_id=cid)
        changelog_file = root / "CHANGELOG.md"
        changelog_file.write_text("# Old Changelog", encoding="utf-8")

        # Record resolution intent (PreTool phase)
        record_resolution_intent("doc", str(changelog_file), project_root=root, conversation_id=cid)

        # Obligation MUST remain unresolved before file is modified
        self.assertIn("engine/api.py", get_unresolved_doc_obligations(root, cid))

        # Reconcile without disk modification -> still unresolved
        res_tests, res_docs = reconcile_obligations_on_disk(root, cid)
        self.assertEqual(res_docs, [])
        self.assertIn("engine/api.py", get_unresolved_doc_obligations(root, cid))

        # Now physically modify CHANGELOG.md (Antigravity tool write phase)
        time.sleep(0.02)
        changelog_file.write_text("# New Changelog\n- Added api.py\n", encoding="utf-8")

        # Reconcile with disk modification -> now committed and resolved!
        res_tests, res_docs = reconcile_obligations_on_disk(root, cid)
        self.assertIn("engine/api.py", res_docs)
        self.assertEqual(len(get_unresolved_doc_obligations(root, cid)), 0)

    def test_same_content_touch_does_not_resolve_obligation(self):
        """Saving or touching the file with identical content (changing mtime but not hash) must NOT resolve obligation."""
        root = Path(self.temp_dir)
        cid = "sess-touch"
        changelog_file = root / "CHANGELOG.md"
        changelog_file.write_text("# Static Changelog\n", encoding="utf-8")

        record_pending_doc_obligation("engine/billing.py", ["CHANGELOG.md"], project_root=root, conversation_id=cid)
        record_resolution_intent("doc", str(changelog_file), project_root=root, conversation_id=cid)

        # Editor re-saves identical content after a delay (mtime advances, content and hash identical)
        time.sleep(0.02)
        changelog_file.write_text("# Static Changelog\n", encoding="utf-8")

        # Reconcile: must NOT resolve because hash did not mutate!
        res_tests, res_docs = reconcile_obligations_on_disk(root, cid)
        self.assertEqual(res_docs, [])
        self.assertIn("engine/billing.py", get_unresolved_doc_obligations(root, cid))

        # Now physically mutate content (hash changes)
        time.sleep(0.02)
        changelog_file.write_text("# Static Changelog\n- Added billing.py\n", encoding="utf-8")
        res_tests, res_docs = reconcile_obligations_on_disk(root, cid)
        self.assertIn("engine/billing.py", res_docs)
        self.assertEqual(len(get_unresolved_doc_obligations(root, cid)), 0)

    def test_concurrent_sessions_intents_do_not_collide(self):
        """Intents for the same file in different conversations must not overwrite each other."""
        root = Path(self.temp_dir)
        changelog_file = root / "CHANGELOG.md"
        changelog_file.write_text("# Initial Changelog\n", encoding="utf-8")

        record_pending_doc_obligation("engine/mod_a.py", ["CHANGELOG.md"], project_root=root, conversation_id="sess-A")
        record_pending_doc_obligation("engine/mod_b.py", ["CHANGELOG.md"], project_root=root, conversation_id="sess-B")

        record_resolution_intent("doc", str(changelog_file), project_root=root, conversation_id="sess-A")
        record_resolution_intent("doc", str(changelog_file), project_root=root, conversation_id="sess-B")

        state = load_governance_state(root)
        intents = state.get("resolution_intents", [])
        self.assertEqual(len(intents), 2, "Both conversation intents must be preserved in state")
        conv_ids = {it.get("conversation_id") for it in intents}
        self.assertEqual(conv_ids, {"sess-A", "sess-B"})

        # Mutate CHANGELOG on disk
        time.sleep(0.02)
        changelog_file.write_text("# Initial Changelog\n- Updated by agent\n", encoding="utf-8")

        # Reconciling sess-A resolves sess-A's obligation
        res_tests_a, res_docs_a = reconcile_obligations_on_disk(root, "sess-A")
        self.assertIn("engine/mod_a.py", res_docs_a)
        self.assertEqual(len(get_unresolved_doc_obligations(root, "sess-A")), 0)

        # Session isolation: sess-B's obligation MUST remain open!
        unresolved_b = get_unresolved_doc_obligations(root, "sess-B")
        self.assertIn("engine/mod_b.py", unresolved_b, "sess-B's obligation must NOT be prematurely cross-resolved by sess-A")

        # Reconciling sess-B now resolves sess-B's obligation
        res_tests_b, res_docs_b = reconcile_obligations_on_disk(root, "sess-B")
        self.assertIn("engine/mod_b.py", res_docs_b)
        self.assertEqual(len(get_unresolved_doc_obligations(root, "sess-B")), 0)

    def test_test_evidence_fallback_hash_based(self):
        """Fallback reconciliation for tests must be deterministic based on baseline_hash presence."""
        root = Path(self.temp_dir)
        cid = "sess-fallback-test"
        cand_test = root / "tests" / "test_sample.py"
        cand_test.parent.mkdir(parents=True, exist_ok=True)

        # 1. Candidate test does NOT exist at obligation creation time
        record_pending_test_evidence(
            "engine/sample.py", str(cand_test), "test_sample.py", "missing test",
            project_root=root, conversation_id=cid
        )
        unresolved = get_unresolved_test_evidence(root, cid)
        self.assertIn("engine/sample.py", unresolved)
        self.assertIsNone(unresolved["engine/sample.py"].get("baseline_hash"))

        # Test file not created yet -> reconcile keeps it unresolved
        res_tests, _ = reconcile_obligations_on_disk(root, cid)
        self.assertEqual(res_tests, [])
        self.assertIn("engine/sample.py", get_unresolved_test_evidence(root, cid))

        # Now test file created on disk (without PreTool intent)
        cand_test.write_text("def test_ok(): pass\n", encoding="utf-8")
        res_tests, _ = reconcile_obligations_on_disk(root, cid)
        self.assertIn("engine/sample.py", res_tests)
        self.assertEqual(len(get_unresolved_test_evidence(root, cid)), 0)

    def test_governance_transaction_nested_and_abort(self):
        """Nested transactions must share state in-memory, and exceptions must abort save."""
        root = Path(self.temp_dir)
        # 1. Nested transaction
        with governance_transaction(root) as s1:
            s1.setdefault("custom", {})["outer"] = 1
            with governance_transaction(root) as s2:
                s2.setdefault("custom", {})["inner"] = 2

        loaded = load_governance_state(root)
        self.assertEqual(loaded.get("custom", {}).get("outer"), 1)
        self.assertEqual(loaded.get("custom", {}).get("inner"), 2)

        # 2. Transaction abort on exception
        try:
            with governance_transaction(root) as s3:
                s3["custom"]["corrupted"] = 999
                raise RuntimeError("Simulated crash")
        except RuntimeError:
            pass

        reloaded = load_governance_state(root)
        self.assertNotIn("corrupted", reloaded.get("custom", {}))

    def test_concurrent_processes_no_lost_update(self):
        """Two concurrent OS processes modifying state concurrently must not lose updates."""
        root = Path(self.temp_dir)
        worker_code = """
import sys, os
from pathlib import Path

_ENGINE_DIR = sys.argv[1]
sys.path.insert(0, _ENGINE_DIR)
os.environ['GRAVITYGUARD_LOG_DIR'] = sys.argv[2]

from gravityguard_engine.governance import record_pending_doc_obligation

cid = sys.argv[3]
prod_file = sys.argv[4]

record_pending_doc_obligation(prod_file, ['CHANGELOG.md'], 'Test obligation', conversation_id=cid)
"""
        script_p = root / "_concur_worker.py"
        script_p.write_text(worker_code, encoding="utf-8")
        engine_dir = str(Path(_ENGINE_DIR).resolve())

        import subprocess
        p1 = subprocess.Popen([sys.executable, str(script_p), engine_dir, str(root), "proc-A", "engine/mod_a.py"])
        p2 = subprocess.Popen([sys.executable, str(script_p), engine_dir, str(root), "proc-B", "engine/mod_b.py"])

        rc1 = p1.wait()
        rc2 = p2.wait()

        self.assertEqual(rc1, 0, f"Worker A failed with exit code {rc1}")
        self.assertEqual(rc2, 0, f"Worker B failed with exit code {rc2}")

        state = load_governance_state(root)
        self.assertIn("proc-A", state.get("sessions", {}), "Session A must be present in state")
        self.assertIn("proc-B", state.get("sessions", {}), "Session B must be present in state")
        self.assertIn("engine/mod_a.py", state.get("doc_obligations", {}).get("pending", {}))
        self.assertIn("engine/mod_b.py", state.get("doc_obligations", {}).get("pending", {}))

    def test_governance_transaction_timeout_fails_closed_never_executes_body(self):
        """When lock cannot be acquired, governance_transaction must raise StateLockTimeout and never execute body."""
        root = Path(self.temp_dir)
        lock_path = get_governance_lock_path(root)
        external_lock = StateLock(lock_path, timeout=1.0)
        self.assertTrue(external_lock.acquire(), "External lock must be acquired first")

        body_executed = False
        with self.assertRaises(StateLockTimeout):
            with governance_transaction(root, timeout=0.05) as state:
                body_executed = True
                state.setdefault("corrupted", {})["leak"] = True

        self.assertFalse(body_executed, "Transaction body must NEVER execute on lock acquisition failure")
        external_lock.release()

        # State must remain pristine
        state_after = load_governance_state(root)
        self.assertNotIn("corrupted", state_after, "State must not be modified when lock acquisition times out")


class TestSessionIsolation(unittest.TestCase):
    """One conversation's debt, retries and circuit breaker never reach another conversation of the same project."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="gg_iso_test_")
        self.orig_log_dir = os.environ.get("GRAVITYGUARD_LOG_DIR")
        os.environ["GRAVITYGUARD_LOG_DIR"] = self.temp_dir
        self.root = Path(self.temp_dir)

    def tearDown(self):
        if self.orig_log_dir is not None:
            os.environ["GRAVITYGUARD_LOG_DIR"] = self.orig_log_dir
        else:
            os.environ.pop("GRAVITYGUARD_LOG_DIR", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_other_sessions_test_debt_is_not_mine(self):
        record_pending_test_evidence("src/a.py", None, "test_a.py", "no test", project_root=self.root, conversation_id="A")
        self.assertIn("src/a.py", get_unresolved_test_evidence(self.root, "A"))
        self.assertEqual(get_unresolved_test_evidence(self.root, "B"), {})

    def test_other_sessions_doc_debt_is_not_mine(self):
        record_pending_doc_obligation("engine/a.py", ["CHANGELOG.md"], project_root=self.root, conversation_id="A")
        self.assertIn("engine/a.py", get_unresolved_doc_obligations(self.root, "A"))
        self.assertEqual(get_unresolved_doc_obligations(self.root, "B"), {})

    def test_changelog_updated_before_the_code_still_clears_the_debt(self):
        """Docs-first order: the CHANGELOG edit happens before the code write; the debt must not open afterwards."""
        changelog = self.root / "CHANGELOG.md"
        changelog.write_text("# c\n", encoding="utf-8")
        record_resolution_intent("doc", str(changelog), self.root, "A")
        changelog.write_text("# c\n- entry\n", encoding="utf-8")
        reconcile_obligations_on_disk(self.root, "A")
        record_pending_doc_obligation(str(self.root / "engine" / "a.py"), ["CHANGELOG.md"], project_root=self.root, conversation_id="A")
        self.assertEqual(get_unresolved_doc_obligations(self.root, "A"), {})
        # The early edit pays once: a second code change owes its own entry.
        record_pending_doc_obligation(str(self.root / "engine" / "b.py"), ["CHANGELOG.md"], project_root=self.root, conversation_id="A")
        self.assertEqual(len(get_unresolved_doc_obligations(self.root, "A")), 1)

    def test_session_that_only_has_retries_still_sees_no_foreign_debt(self):
        """B's session entry is created by its own Stop retries and has no obligation list; that must not fall back to A's."""
        record_pending_test_evidence("src/a.py", None, "test_a.py", "no test", project_root=self.root, conversation_id="A")
        increment_session_stop_retries(self.root, "B")
        self.assertEqual(get_unresolved_test_evidence(self.root, "B"), {})

    def test_both_sessions_owing_the_same_file_each_keep_it(self):
        for cid in ("A", "B"):
            record_pending_test_evidence("src/shared.py", None, "test_shared.py", "no test", project_root=self.root, conversation_id=cid)
        self.assertIn("src/shared.py", get_unresolved_test_evidence(self.root, "A"))
        self.assertIn("src/shared.py", get_unresolved_test_evidence(self.root, "B"))

    def test_legacy_ownerless_pending_is_still_enforced(self):
        """A state file written before sessions existed has project-wide entries nobody owns; every conversation owes them."""
        save_governance_state({
            "test_obligations": {"pending": {"src/old.py": {"reason": "legacy"}}},
            "doc_obligations": {"pending": {"engine/old.py": {"reason": "legacy"}}},
        }, self.root)
        self.assertIn("src/old.py", get_unresolved_test_evidence(self.root, "B"))
        self.assertIn("engine/old.py", get_unresolved_doc_obligations(self.root, "B"))

    def test_no_conversation_id_sees_the_project_wide_list(self):
        record_pending_test_evidence("src/a.py", None, "test_a.py", "no test", project_root=self.root, conversation_id="A")
        self.assertIn("src/a.py", get_unresolved_test_evidence(self.root))

    def test_stop_retries_do_not_leak_between_sessions(self):
        for _ in range(4):
            increment_session_stop_retries(self.root, "A")
        self.assertEqual(get_session_stop_retries(self.root, "A"), 4)
        self.assertEqual(get_session_stop_retries(self.root, "B"), 0)
        self.assertEqual(increment_session_stop_retries(self.root, "B"), 1)
        self.assertEqual(get_session_stop_retries(self.root, "A"), 4)

    def test_malformed_retry_value_counts_as_zero(self):
        save_governance_state({"sessions": {"A": {"stop_retries": "many"}}, "stop_retries": 9}, self.root)
        self.assertEqual(get_session_stop_retries(self.root, "A"), 0)


class TestProjectIsolation(unittest.TestCase):
    """Two projects keep separate state files; a conversation's debt in one never shows up in the other."""

    def setUp(self):
        self.orig_log_dir = os.environ.pop("GRAVITYGUARD_LOG_DIR", None)
        self.base = tempfile.mkdtemp(prefix="gg_proj_test_")
        self.proj_a = Path(self.base) / "a"
        self.proj_b = Path(self.base) / "b"
        self.proj_a.mkdir()
        self.proj_b.mkdir()

    def tearDown(self):
        if self.orig_log_dir is not None:
            os.environ["GRAVITYGUARD_LOG_DIR"] = self.orig_log_dir
        shutil.rmtree(self.base, ignore_errors=True)

    def test_same_conversation_id_in_two_projects(self):
        record_pending_test_evidence("src/x.py", None, "test_x.py", "no test", project_root=self.proj_a, conversation_id="S")
        self.assertIn("src/x.py", get_unresolved_test_evidence(self.proj_a, "S"))
        self.assertEqual(get_unresolved_test_evidence(self.proj_b, "S"), {})

    def test_other_stop_roots_only_returns_roots_that_already_keep_state(self):
        from gravityguard_engine.dispatcher import _other_stop_roots
        record_pending_test_evidence("src/x.py", None, "test_x.py", "no test", project_root=self.proj_b, conversation_id="S")
        payload = {"workspacePaths": [str(self.proj_a), str(self.proj_b), str(Path(self.base) / "missing")]}
        self.assertEqual([p.name for p in _other_stop_roots(payload, self.proj_a)], ["b"])
        self.assertFalse((self.proj_a / ".gravityguard").exists(), "the Stop check must not create state in the primary root")

    def test_other_stop_roots_does_not_create_state_in_an_untouched_root(self):
        from gravityguard_engine.dispatcher import _other_stop_roots
        payload = {"workspacePaths": [str(self.proj_a), str(self.proj_b)]}
        self.assertEqual(_other_stop_roots(payload, self.proj_a), [])
        self.assertFalse((self.proj_b / ".gravityguard").exists())

    def test_other_stop_roots_is_empty_with_the_log_dir_override(self):
        from gravityguard_engine.dispatcher import _other_stop_roots
        record_pending_test_evidence("src/x.py", None, "test_x.py", "no test", project_root=self.proj_b, conversation_id="S")
        os.environ["GRAVITYGUARD_LOG_DIR"] = self.base
        try:
            self.assertEqual(_other_stop_roots({"workspacePaths": [str(self.proj_a), str(self.proj_b)]}, self.proj_a), [])
        finally:
            os.environ.pop("GRAVITYGUARD_LOG_DIR", None)


if __name__ == "__main__":
    unittest.main()
