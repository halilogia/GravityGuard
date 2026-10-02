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


if __name__ == "__main__":
    unittest.main()
