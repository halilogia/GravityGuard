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
    get_session_stop_retries,
    get_unresolved_doc_obligations,
    get_unresolved_test_evidence,
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


if __name__ == "__main__":
    unittest.main()
