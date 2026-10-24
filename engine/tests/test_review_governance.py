#!/usr/bin/env python3
"""
Unit tests for review obligations: candidate fingerprint, staleness, and the
self-review record (`.gravityguard/self-review/<id>.json`).

These cover the invariant the feature exists for:

    A self-review record proves a review step happened against a specific
    candidate state. It does not prove the review was correct or complete.

Only process facts are asserted: is the record schema-valid, does it carry the
candidate fingerprint, is the candidate still what was reviewed.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine.governance import (
    governance_transaction,
)
from gravityguard_engine.review_governance import (
    RECEIPT_SUBDIR,
    _load_receipt,
    evaluate_review_obligations,
    fingerprint_from_hashes,
    get_unresolved_review_obligations,
    hash_text,
    record_review_obligation,
)

REVIEW_CFG = {"review": {"enabled": True, "forceAll": True}}
VALID_NOTES = "Diff okundu: mantık, test, doküman ve import kontrol edildi."


def _write_receipt(root: Path, review_id: str, source_fingerprint, **overrides):
    """Writes a self-review record as the agent would; ``overrides`` replace or (None) drop fields."""
    reviews_dir = root.joinpath(*RECEIPT_SUBDIR)
    reviews_dir.mkdir(parents=True, exist_ok=True)
    receipt = {
        "reviewId": review_id,
        "sourceFingerprint": source_fingerprint,
        "findings": [],
        "notes": VALID_NOTES,
    }
    receipt.update(overrides)
    receipt = {k: v for k, v in receipt.items() if v is not None}
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

    def _problems(self, entry):
        report = evaluate_review_obligations(self.root, self.cid)
        self.assertIn(entry["review_id"], report["unresolved"])
        return report["unresolved"][entry["review_id"]]["problems"]

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

    # --- self-review record: schema -----------------------------------------

    def test_valid_self_review_resolves(self):
        _, entry = self._make_obligation()
        _write_receipt(self.root, entry["review_id"], entry["source_fingerprint"])
        report = evaluate_review_obligations(self.root, self.cid)
        self.assertIn(entry["review_id"], report["resolved"])
        self.assertEqual(get_unresolved_review_obligations(self.root, self.cid), {})

    def test_valid_self_review_with_findings_resolves(self):
        _, entry = self._make_obligation()
        _write_receipt(self.root, entry["review_id"], entry["source_fingerprint"], findings=["minor naming nit"])
        report = evaluate_review_obligations(self.root, self.cid)
        self.assertIn(entry["review_id"], report["resolved"])

    def test_load_receipt_accepts_valid_record(self):
        _, entry = self._make_obligation()
        _write_receipt(self.root, entry["review_id"], entry["source_fingerprint"])
        data, err = _load_receipt(self.root, entry["review_id"])
        self.assertIsNone(err)
        self.assertEqual(data["sourceFingerprint"], entry["source_fingerprint"])

    def test_missing_receipt_keeps_open(self):
        _, entry = self._make_obligation()
        self.assertIn("receipt-missing", self._problems(entry))

    def test_short_notes_rejected(self):
        _, entry = self._make_obligation()
        _write_receipt(self.root, entry["review_id"], entry["source_fingerprint"], notes="ok")
        self.assertIn("receipt-notes-too-short", self._problems(entry))

    def test_whitespace_padded_notes_rejected(self):
        _, entry = self._make_obligation()
        _write_receipt(self.root, entry["review_id"], entry["source_fingerprint"], notes="ok" + " " * 40)
        self.assertIn("receipt-notes-too-short", self._problems(entry))

    def test_missing_notes_rejected(self):
        _, entry = self._make_obligation()
        _write_receipt(self.root, entry["review_id"], entry["source_fingerprint"], notes=None)
        self.assertIn("receipt-notes-too-short", self._problems(entry))

    def test_missing_findings_rejected(self):
        _, entry = self._make_obligation()
        _write_receipt(self.root, entry["review_id"], entry["source_fingerprint"], findings=None)
        self.assertIn("receipt-findings-invalid", self._problems(entry))

    def test_non_list_findings_rejected(self):
        _, entry = self._make_obligation()
        _write_receipt(self.root, entry["review_id"], entry["source_fingerprint"], findings="none")
        self.assertIn("receipt-findings-invalid", self._problems(entry))

    def test_receipt_id_mismatch_rejected(self):
        _, entry = self._make_obligation()
        _write_receipt(self.root, entry["review_id"], entry["source_fingerprint"], reviewId="someone-else")
        self.assertIn("receipt-id-mismatch", self._problems(entry))

    def test_receipt_not_an_object_rejected(self):
        _, entry = self._make_obligation()
        reviews_dir = self.root.joinpath(*RECEIPT_SUBDIR)
        reviews_dir.mkdir(parents=True, exist_ok=True)
        (reviews_dir / f"{entry['review_id']}.json").write_text("[]", encoding="utf-8")
        self.assertIn("receipt-not-an-object", self._problems(entry))

    def test_unreadable_receipt_rejected(self):
        _, entry = self._make_obligation()
        reviews_dir = self.root.joinpath(*RECEIPT_SUBDIR)
        reviews_dir.mkdir(parents=True, exist_ok=True)
        (reviews_dir / f"{entry['review_id']}.json").write_text("{not json", encoding="utf-8")
        self.assertTrue(any(p.startswith("receipt-unreadable") for p in self._problems(entry)))

    def test_invalid_review_id_rejected(self):
        for bad_id in ("../escape", "", "a" * 129, "has space"):
            _, err = _load_receipt(self.root, bad_id)
            self.assertEqual(err, "receipt-invalid-id", bad_id)

    # --- self-review record: fingerprint binding ----------------------------

    def test_missing_source_fingerprint_keeps_open(self):
        _, entry = self._make_obligation()
        _write_receipt(self.root, entry["review_id"], None)
        self.assertIn("fingerprint-mismatch", self._problems(entry))

    def test_fingerprint_mismatch_keeps_open(self):
        _, entry = self._make_obligation()
        _write_receipt(self.root, entry["review_id"], "different-fingerprint")
        self.assertIn("fingerprint-mismatch", self._problems(entry))

    # --- staleness ----------------------------------------------------------

    def test_stale_candidate_keeps_obligation_open(self):
        target, entry = self._make_obligation(content="print('v1')\n")
        _write_receipt(self.root, entry["review_id"], entry["source_fingerprint"])
        # Candidate changes after the review was made.
        target.write_text("print('v2')\n", encoding="utf-8")
        self.assertIn("stale-candidate", self._problems(entry))

    def test_deleted_candidate_is_stale(self):
        target, entry = self._make_obligation()
        _write_receipt(self.root, entry["review_id"], entry["source_fingerprint"])
        target.unlink()
        self.assertIn("stale-candidate", self._problems(entry))

    def test_rereview_after_change_resolves(self):
        target, entry = self._make_obligation(content="print('v1')\n")
        _write_receipt(self.root, entry["review_id"], entry["source_fingerprint"])
        target.write_text("print('v2')\n", encoding="utf-8")
        # The hook re-records the changed file; the fingerprint moves, so the old record no longer matches.
        entry2 = record_review_obligation(str(target), "print('v2')\n", self.root, self.cid, REVIEW_CFG)
        self.assertEqual(entry["review_id"], entry2["review_id"])
        self.assertIn("fingerprint-mismatch", self._problems(entry2))
        _write_receipt(self.root, entry2["review_id"], entry2["source_fingerprint"])
        report = evaluate_review_obligations(self.root, self.cid)
        self.assertIn(entry2["review_id"], report["resolved"])

    # --- hashing consistency ------------------------------------------------

    def test_crlf_and_lf_hash_the_same(self):
        self.assertEqual(hash_text("a\r\nb"), hash_text("a\nb"))

    def test_receipt_survives_crlf_write(self):
        """A CRLF write is not seen as a stale candidate."""
        target, entry = self._make_obligation(content="a\nb\n")
        _write_receipt(self.root, entry["review_id"], entry["source_fingerprint"])
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



    # --- risk-gated review (ChatGPT R1.1) -----------------------------------

    def test_low_risk_candidate_is_auto_exempt_at_evaluation(self):
        """In default risk-gated mode, 1 non-security file (<5 files, <120 lines) is auto-exempt."""
        risk_gated_cfg = {"review": {"enabled": True}}
        target = self.root / "src" / "small.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x = 1\n", encoding="utf-8")
        entry = record_review_obligation(str(target), "x = 1\n", self.root, self.cid, risk_gated_cfg)
        self.assertIsNotNone(entry)

        # evaluate should auto-resolve without receipt!
        report = evaluate_review_obligations(self.root, self.cid, risk_gated_cfg)
        self.assertEqual(len(report["unresolved"]), 0)
        self.assertIn(entry["review_id"], report["resolved"])

    def test_security_file_triggers_review_in_risk_gated_mode(self):
        """Files matching security/engine patterns trigger review even if small."""
        risk_gated_cfg = {"review": {"enabled": True}}
        target = self.root / "engine" / "auth.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("SECRET_KEY = 1\n", encoding="utf-8")
        entry = record_review_obligation(str(target), "SECRET_KEY = 1\n", self.root, self.cid, risk_gated_cfg)
        self.assertIsNotNone(entry)

        report = evaluate_review_obligations(self.root, self.cid, risk_gated_cfg)
        self.assertIn(entry["review_id"], report["unresolved"])
        self.assertIn("Güvenlik/yönetişim modülü değişti", report["unresolved"][entry["review_id"]]["trigger_reason"])

    def test_manifest_file_triggers_review_in_risk_gated_mode(self):
        """Modifying package manifests triggers review."""
        risk_gated_cfg = {"review": {"enabled": True}}
        target = self.root / "package.json"
        target.write_text("{}", encoding="utf-8")
        # package.json is non-code suffix so record_review_obligation skips it,
        # but if recorded or paired with code:
        code_target = self.root / "src" / "index.js"
        code_target.parent.mkdir(parents=True, exist_ok=True)
        code_target.write_text("import foo from 'foo';", encoding="utf-8")
        entry = record_review_obligation(str(code_target), "import foo from 'foo';", self.root, self.cid, risk_gated_cfg)
        # artificially associate package.json
        with governance_transaction(self.root) as state:
            state["sessions"][self.cid]["review_obligations"]["pending"][entry["review_id"]]["changed_files"]["package.json"] = "dummy"

        report = evaluate_review_obligations(self.root, self.cid, risk_gated_cfg)
        self.assertIn(entry["review_id"], report["unresolved"])
        self.assertIn("Dış bağımlılık", report["unresolved"][entry["review_id"]]["trigger_reason"])


if __name__ == "__main__":
    unittest.main()
