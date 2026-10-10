#!/usr/bin/env python3
"""
Unit tests for review obligations: fingerprint, provenance, staleness, receipt
verification, and the final diff guard.

These cover the invariant the feature exists for:

    A review receipt proves a review was performed against a specific candidate
    state. It does not prove the review was correct or complete.

Only process facts are asserted: was an invocation observed, does the receipt
match the candidate, is the candidate still what was reviewed.
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
    clear_governance_state,
    governance_transaction,
    load_governance_state,
)
from gravityguard_engine.review_governance import (
    RECEIPT_SUBDIR,
    evaluate_review_obligations,
    fingerprint_from_hashes,
    get_unresolved_review_obligations,
    hash_text,
    record_review_obligation,
    register_review_invocation,
)

REVIEW_CFG = {"review": {"enabled": True}}


def _write_receipt(root: Path, review_id: str, source_fingerprint: str, nonce: str, model: str = "m1"):
    """Writes a well-formed receipt as the Swarm runtime would."""
    reviews_dir = root.joinpath(*RECEIPT_SUBDIR)
    reviews_dir.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schemaVersion": 1,
        "reviewId": review_id,
        "nonce": nonce,
        "role": "code-reviewer",
        "model": model,
        "sourceFingerprint": source_fingerprint,
        "resultHash": "deadbeef",
        "changedFiles": [],
        "findingsParsed": True,
        "parseError": None,
        "findings": [],
        "rawResult": "{}",
    }
    (reviews_dir / f"{review_id}.json").write_text(json.dumps(receipt), encoding="utf-8")


class TestReviewGovernance(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="gg_review_test_")
        self.orig_log_dir = os.environ.get("GRAVITYGUARD_LOG_DIR")
        os.environ["GRAVITYGUARD_LOG_DIR"] = self.temp_dir
        self.root = Path(self.temp_dir)
        self.cid = "sess-review"

    def tearDown(self):
        if self.orig_log_dir is not None:
            os.environ["GRAVITYGUARD_LOG_DIR"] = self.orig_log_dir
        else:
            os.environ.pop("GRAVITYGUARD_LOG_DIR", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_obligation(self, rel: str = "src/app.py", content: str = "print('hi')\n"):
        """Creates the file on disk and records the obligation; returns (file, entry)."""
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        entry = record_review_obligation(str(target), content, self.root, self.cid, REVIEW_CFG)
        self.assertIsNotNone(entry)
        return target, entry

    # --- trigger integration ------------------------------------------------

    def test_disabled_review_records_no_obligation(self):
        target = self.root / "src" / "app.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        entry = record_review_obligation(str(target), "x", self.root, self.cid, {"review": {"enabled": False}})
        self.assertIsNone(entry)

    def test_non_code_records_no_obligation(self):
        entry = record_review_obligation(str(self.root / "README.md"), "x", self.root, self.cid, REVIEW_CFG)
        self.assertIsNone(entry)

    # --- fingerprint --------------------------------------------------------

    def test_fingerprint_is_order_independent(self):
        a = fingerprint_from_hashes({"a.py": "1", "b.py": "2"})
        b = fingerprint_from_hashes({"b.py": "2", "a.py": "1"})
        self.assertEqual(a, b)

    def test_fingerprint_changes_with_content(self):
        self.assertNotEqual(fingerprint_from_hashes({"a.py": "1"}), fingerprint_from_hashes({"a.py": "2"}))

    def test_records_single_obligation_for_the_session(self):
        _, entry = self._make_obligation()
        _, entry2 = self._make_obligation("src/other.py", "print('other')\n")
        # Same session reuses one review; the candidate accumulates files.
        self.assertEqual(entry["review_id"], entry2["review_id"])
        self.assertIn("src/app.py", entry2["changed_files"])
        self.assertIn("src/other.py", entry2["changed_files"])

    # --- provenance ---------------------------------------------------------

    def test_missing_invocation_keeps_obligation_open(self):
        _, entry = self._make_obligation()
        _write_receipt(self.root, entry["review_id"], entry["source_fingerprint"], entry["nonce"])
        report = evaluate_review_obligations(self.root, self.cid)
        self.assertIn(entry["review_id"], report["unresolved"])
        self.assertIn("reviewer-invocation-not-observed", report["unresolved"][entry["review_id"]]["problems"])

    def test_full_chain_resolves(self):
        _, entry = self._make_obligation()
        register_review_invocation(entry["review_id"], entry["nonce"], entry["source_fingerprint"], self.root, self.cid)
        _write_receipt(self.root, entry["review_id"], entry["source_fingerprint"], entry["nonce"])
        report = evaluate_review_obligations(self.root, self.cid)
        self.assertIn(entry["review_id"], report["resolved"])
        self.assertEqual(get_unresolved_review_obligations(self.root, self.cid), {})

    def test_forged_receipt_without_invocation_is_rejected(self):
        # The Lead "writes its own receipt" without ever calling Swarm.
        _, entry = self._make_obligation()
        _write_receipt(self.root, entry["review_id"], entry["source_fingerprint"], entry["nonce"])
        report = evaluate_review_obligations(self.root, self.cid)
        self.assertNotIn(entry["review_id"], report["resolved"])

    # --- integrity ----------------------------------------------------------

    def test_fingerprint_mismatch_keeps_open(self):
        _, entry = self._make_obligation()
        register_review_invocation(entry["review_id"], entry["nonce"], entry["source_fingerprint"], self.root, self.cid)
        _write_receipt(self.root, entry["review_id"], "different-fingerprint", entry["nonce"])
        report = evaluate_review_obligations(self.root, self.cid)
        self.assertIn("fingerprint-mismatch", report["unresolved"][entry["review_id"]]["problems"])

    def test_nonce_mismatch_keeps_open(self):
        _, entry = self._make_obligation()
        register_review_invocation(entry["review_id"], entry["nonce"], entry["source_fingerprint"], self.root, self.cid)
        _write_receipt(self.root, entry["review_id"], entry["source_fingerprint"], "wrong-nonce")
        report = evaluate_review_obligations(self.root, self.cid)
        self.assertIn("nonce-mismatch", report["unresolved"][entry["review_id"]]["problems"])

    def test_missing_receipt_keeps_open(self):
        _, entry = self._make_obligation()
        register_review_invocation(entry["review_id"], entry["nonce"], entry["source_fingerprint"], self.root, self.cid)
        report = evaluate_review_obligations(self.root, self.cid)
        self.assertIn("receipt-missing", report["unresolved"][entry["review_id"]]["problems"])

    def test_stale_candidate_keeps_obligation_open(self):
        target, entry = self._make_obligation(content="print('v1')\n")
        register_review_invocation(entry["review_id"], entry["nonce"], entry["source_fingerprint"], self.root, self.cid)
        _write_receipt(self.root, entry["review_id"], entry["source_fingerprint"], entry["nonce"])
        # Candidate changes after the review was made.
        target.write_text("print('v2')\n", encoding="utf-8")
        report = evaluate_review_obligations(self.root, self.cid)
        self.assertIn("stale-candidate", report["unresolved"][entry["review_id"]]["problems"])

    def test_receipt_id_mismatch_is_unreadable(self):
        _, entry = self._make_obligation()
        register_review_invocation(entry["review_id"], entry["nonce"], entry["source_fingerprint"], self.root, self.cid)
        reviews_dir = self.root.joinpath(*RECEIPT_SUBDIR)
        reviews_dir.mkdir(parents=True, exist_ok=True)
        bad = {"reviewId": "someone-else", "resultHash": "x", "findingsParsed": True}
        (reviews_dir / f"{entry['review_id']}.json").write_text(json.dumps(bad), encoding="utf-8")
        report = evaluate_review_obligations(self.root, self.cid)
        problems = report["unresolved"][entry["review_id"]]["problems"]
        self.assertTrue(any("id-mismatch" in p for p in problems))

    # --- hashing consistency ------------------------------------------------

    def test_crlf_and_lf_hash_the_same(self):
        self.assertEqual(hash_text("a\r\nb"), hash_text("a\nb"))

    def test_receipt_survives_crlf_write(self):
        """A CRLF write is not seen as a stale candidate."""
        target, entry = self._make_obligation(content="a\nb\n")
        register_review_invocation(entry["review_id"], entry["nonce"], entry["source_fingerprint"], self.root, self.cid)
        _write_receipt(self.root, entry["review_id"], entry["source_fingerprint"], entry["nonce"])
        # Rewrite the same logical content with CRLF (a Windows editor would).
        target.write_bytes(b"a\r\nb\r\n")
        report = evaluate_review_obligations(self.root, self.cid)
        self.assertIn(entry["review_id"], report["resolved"])

    # --- session isolation --------------------------------------------------

    def test_other_sessions_obligation_does_not_appear(self):
        _, entry = self._make_obligation()
        with governance_transaction(self.root) as state:
            state["sessions"]["other-session"] = {
                "review_obligations": {"pending": {"rev-other": {"review_id": "rev-other", "changed_files": {}}}}
            }
        visible = get_unresolved_review_obligations(self.root, self.cid)
        self.assertIn(entry["review_id"], visible)
        self.assertNotIn("rev-other", visible)


if __name__ == "__main__":
    unittest.main()
