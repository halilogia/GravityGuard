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


# ---------------------------------------------------------------------------
# Zero-context review: risk classifier, snapshot hash, payload, registry, anti-loop
# ---------------------------------------------------------------------------
import subprocess

from gravityguard_engine.review_governance import (
    build_feedback_prompt,
    build_review_payload,
    classify_change_risk,
    compute_snapshot_hash,
    detect_writer_agent,
    evaluate_zero_context_gate,
    get_session_record,
    get_snapshot_record,
    ingest_result_file,
    normalize_agent,
    normalize_findings,
    parse_unified_diff,
    payload_paths,
    record_review_result,
    register_writer_session,
    render_review_payload_markdown,
)
from gravityguard_engine.review_policy import (
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    classify_file_risk,
    get_review_governance_config,
    is_comment_line,
    is_review_governance_enabled,
    is_test_path,
    risk_meets_threshold,
)

ZC_CFG = {"reviewGovernance": {"enabled": True}}
PY_BASE = "def alpha(x):\n    return x + 1\n\n\ndef beta(y):\n    return y * 2\n"


def _git(root, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=str(root), check=True, capture_output=True)


class _GitRepoCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="gg_zc_test_")
        self.root = Path(self.temp_dir)
        _git(self.root, "init", "-q")
        self.write("README.md", "# demo\n")
        self.write("src/app.py", PY_BASE)
        self.write("tests/test_app.py", "def test_a():\n    assert True\n")
        self.write("package-lock.json", "{}\n")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "base")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def write(self, rel, text):
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")

    def risk(self, **kw):
        return classify_change_risk(self.root, **kw)


class TestRiskPolicyPure(unittest.TestCase):
    def test_helpers(self):
        self.assertTrue(is_comment_line("   # note"))
        self.assertTrue(is_comment_line("// note"))
        self.assertTrue(is_comment_line(""))
        self.assertFalse(is_comment_line("x = 1  # trailing"))
        self.assertTrue(is_test_path("tests/a.py"))
        self.assertTrue(is_test_path("src/test_x.py"))
        self.assertTrue(is_test_path("src/x.spec.ts"))
        self.assertFalse(is_test_path("src/x.py"))
        self.assertTrue(risk_meets_threshold(RISK_HIGH, RISK_MEDIUM))
        self.assertFalse(risk_meets_threshold(RISK_LOW, RISK_MEDIUM))
        self.assertTrue(risk_meets_threshold(RISK_LOW, "bogus") is False)

    def test_file_classes(self):
        code = ["x = 1"] * 5
        self.assertEqual(classify_file_risk("package-lock.json", code, [])[0], RISK_LOW)
        self.assertEqual(classify_file_risk("docs/auth.md", code, [])[0], RISK_LOW)
        self.assertEqual(classify_file_risk("src/a.py", ["# c", ""], ["# d"])[0], RISK_LOW)
        self.assertEqual(classify_file_risk("src/a.py", code, [])[0], RISK_LOW)
        self.assertEqual(classify_file_risk("engine/core.py", code, [])[0], RISK_HIGH)
        self.assertEqual(classify_file_risk("src/auth_service.py", code, [])[0], RISK_HIGH)
        self.assertEqual(classify_file_risk("src/api/routes.py", code, [])[0], RISK_HIGH)
        self.assertEqual(classify_file_risk("types/index.d.ts", code, [])[0], RISK_HIGH)
        self.assertEqual(classify_file_risk("tests/test_a.py", [], code, deleted=True)[0], RISK_HIGH)
        self.assertEqual(classify_file_risk("src/a.py", ["x = 1"] * 150, [])[0], RISK_MEDIUM)
        self.assertEqual(classify_file_risk("src/a.py", ["x = 1"] * 151, [])[0], RISK_HIGH)
        self.assertEqual(classify_file_risk("src/a.py", ["x = 1"] * 30, [])[0], RISK_LOW)
        self.assertEqual(classify_file_risk("src/a.py", ["x = 1"] * 31, [])[0], RISK_MEDIUM)
        self.assertEqual(classify_file_risk("src/a.py", ["x = 1"] * 20, ["y = 2"] * 11)[0], RISK_MEDIUM)
        for new_fn in ("def f(x):", "async def f():", "function f() {", "export function f() {", "const f = (a) => a", "class K:", "fn main() {", "func main() {"):
            self.assertEqual(classify_file_risk("src/a.x", [new_fn], [])[0], RISK_MEDIUM, new_fn)
        self.assertEqual(classify_file_risk("requirements.txt", ["flask"], [])[0], RISK_MEDIUM)
        # a large JSON (non-code) change is capped at MEDIUM
        self.assertEqual(classify_file_risk("data/x.json", ['"a": 1'] * 200, [])[0], RISK_MEDIUM)
        # tests are not HIGH by path alone, even under engine/
        self.assertEqual(classify_file_risk("engine/tests/test_x.py", code, [])[0], RISK_LOW)

    def test_config_defaults_and_opt_in(self):
        self.assertFalse(is_review_governance_enabled(None))
        self.assertFalse(is_review_governance_enabled({"reviewGovernance": "yes"}))
        self.assertFalse(is_review_governance_enabled({"reviewGovernance": {}}))
        self.assertTrue(is_review_governance_enabled(ZC_CFG))
        d = get_review_governance_config(None)
        self.assertEqual((d["maxFixTurns"], d["minRisk"], d["highLines"], d["mediumLines"], d["stagedOnly"]), (2, RISK_HIGH, 150, 30, False))
        c = get_review_governance_config({"reviewGovernance": {"enabled": True, "maxFixTurns": 0, "minRisk": RISK_MEDIUM,
                                                               "highLines": 10, "mediumLines": True, "stagedOnly": 1}})
        self.assertEqual((c["maxFixTurns"], c["minRisk"], c["highLines"], c["mediumLines"], c["stagedOnly"]), (0, RISK_MEDIUM, 10, 30, True))
        bad = get_review_governance_config({"reviewGovernance": {"maxFixTurns": -1, "minRisk": "x", "highLines": 0}})
        self.assertEqual((bad["maxFixTurns"], bad["minRisk"], bad["highLines"]), (2, RISK_HIGH, 150))


class TestDiffParsing(unittest.TestCase):
    def test_parse_counts_numbers_and_deleted(self):
        diff = (
            "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
            "@@ -1,3 +1,4 @@ def alpha():\n ctx\n-old\n+new1\n+new2\n tail\n"
            "@@ -20,2 +21,2 @@\n-x\n+y\n"
            "diff --git a/gone.py b/gone.py\ndeleted file mode 100644\n--- a/gone.py\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-bye\n"
        )
        a, gone = parse_unified_diff(diff)
        self.assertEqual((a["added"], a["removed"]), (3, 2))
        self.assertEqual(a["added_numbers"], [2, 3, 21])
        self.assertEqual(a["hunks"][0]["context"], "def alpha():")
        self.assertEqual((a["hunks"][1]["start"], a["hunks"][1]["length"]), (21, 2))
        self.assertTrue(gone["deleted"])
        self.assertEqual(gone["path"], "gone.py")
        self.assertEqual(parse_unified_diff(""), [])
        self.assertEqual(parse_unified_diff("junk line\n"), [])

    def test_removed_line_starting_with_dashes_is_not_a_header(self):
        diff = "diff --git a/a.sql b/a.sql\n--- a/a.sql\n+++ b/a.sql\n@@ -1,2 +1,1 @@\n--- comment\n+x\n"
        rec = parse_unified_diff(diff)[0]
        self.assertEqual((rec["added"], rec["removed"]), (1, 1))


class TestClassifyChangeRisk(_GitRepoCase):
    def test_clean_tree_is_low_with_empty_hash(self):
        r = self.risk()
        self.assertEqual((r["risk"], r["snapshot_hash"], r["lines_changed"], r["files"]), (RISK_LOW, "", 0, []))
        self.assertEqual(compute_snapshot_hash(self.root), "")

    def test_docs_lockfile_and_comment_only_are_low(self):
        self.write("README.md", "# demo\nmore docs about auth\n")
        self.write("package-lock.json", '{"a": 1}\n')
        self.write("src/app.py", "# header comment\n" + PY_BASE)
        r = self.risk()
        self.assertEqual(r["risk"], RISK_LOW)
        self.assertEqual(r["reasons"], [])
        self.assertEqual(len(r["files"]), 3)
        self.assertTrue(r["snapshot_hash"])

    def test_engine_change_is_high(self):
        self.write("engine/core.py", "x = 1\n")
        r = self.risk()
        self.assertEqual(r["risk"], RISK_HIGH)
        self.assertIn("engine/core.py", r["reasons"][0])

    def test_untracked_file_is_included(self):
        self.write("src/new_mod.py", "def brand_new():\n    return 1\n")
        r = self.risk()
        self.assertEqual(r["risk"], RISK_MEDIUM)
        self.assertEqual([f["path"] for f in r["files"]], ["src/new_mod.py"])

    def test_deleted_test_is_high(self):
        (self.root / "tests" / "test_app.py").unlink()
        self.assertEqual(self.risk()["risk"], RISK_HIGH)

    def test_line_thresholds(self):
        self.write("src/app.py", PY_BASE + "".join(f"v{i} = {i}\n" for i in range(31)))
        self.assertEqual(self.risk()["risk"], RISK_MEDIUM)
        self.write("src/app.py", PY_BASE + "".join(f"v{i} = {i}\n" for i in range(151)))
        self.assertEqual(self.risk()["risk"], RISK_HIGH)
        # config override moves the HIGH boundary
        cfg = {"reviewGovernance": {"enabled": True, "highLines": 500}}
        self.assertEqual(classify_change_risk(self.root, cfg=cfg)["risk"], RISK_MEDIUM)

    def test_new_function_is_medium(self):
        self.write("src/app.py", PY_BASE + "\n\ndef gamma():\n    return 3\n")
        self.assertEqual(self.risk()["risk"], RISK_MEDIUM)

    def test_staged_only_ignores_unstaged_edits(self):
        self.write("engine/core.py", "x = 1\n")
        self.assertEqual(self.risk(staged_only=True)["risk"], RISK_LOW)
        _git(self.root, "add", "engine/core.py")
        self.assertEqual(self.risk(staged_only=True)["risk"], RISK_HIGH)

    def test_gravityguard_state_dir_is_not_part_of_the_diff(self):
        self.write(".gravityguard/review-registry.json", "{}")
        self.assertEqual(self.risk()["files"], [])

    def test_non_repository_is_empty_low(self):
        with tempfile.TemporaryDirectory() as plain:
            r = classify_change_risk(plain)
            self.assertEqual((r["risk"], r["snapshot_hash"]), (RISK_LOW, ""))

    def test_repository_without_commits(self):
        with tempfile.TemporaryDirectory() as fresh:
            _git(fresh, "init", "-q")
            Path(fresh, "a.py").write_text("x = 1\n", encoding="utf-8")
            _git(fresh, "add", "a.py")
            self.assertEqual([f["path"] for f in classify_change_risk(fresh)["files"]], ["a.py"])


class TestSnapshotHash(_GitRepoCase):
    def test_stable_for_same_diff_and_changes_with_content(self):
        self.write("src/app.py", PY_BASE + "z = 1\n")
        h1 = compute_snapshot_hash(self.root)
        self.assertEqual(len(h1), 64)
        self.assertEqual(h1, compute_snapshot_hash(self.root))
        self.write("src/app.py", PY_BASE + "z = 2\n")
        self.assertNotEqual(h1, compute_snapshot_hash(self.root))

    def test_independent_of_staging_state_and_matches_classifier(self):
        self.write("src/app.py", PY_BASE + "z = 1\n")
        self.write("src/other.py", "q = 1\n")
        h_unstaged = compute_snapshot_hash(self.root)
        self.assertEqual(h_unstaged, self.risk()["snapshot_hash"])
        _git(self.root, "add", "-A")
        self.assertEqual(h_unstaged, compute_snapshot_hash(self.root))

    def test_base_tree_is_bound(self):
        self.write("src/app.py", PY_BASE + "z = 1\n")
        before = compute_snapshot_hash(self.root)
        self.write("other.txt", "unrelated\n")
        _git(self.root, "add", "other.txt")
        _git(self.root, "commit", "-q", "-m", "move base")
        self.assertNotEqual(before, compute_snapshot_hash(self.root))

    def test_staged_hash_differs_from_working_tree_when_unstaged_edits_exist(self):
        self.write("src/app.py", PY_BASE + "z = 1\n")
        _git(self.root, "add", "src/app.py")
        staged = compute_snapshot_hash(self.root, staged_only=True)
        self.write("src/app.py", PY_BASE + "z = 1\nw = 2\n")
        self.assertEqual(staged, compute_snapshot_hash(self.root, staged_only=True))
        self.assertNotEqual(staged, compute_snapshot_hash(self.root))


class TestReviewPayload(_GitRepoCase):
    def test_python_function_boundaries_are_ast_exact(self):
        self.write("src/app.py", PY_BASE.replace("return y * 2", "return y * 3"))
        p = build_review_payload(self.root)
        fn = p["files"][0]["functions"]
        self.assertEqual([(f["name"], f["start"], f["end"]) for f in fn], [("beta", 5, 6)])
        self.assertIn("return y * 3", fn[0]["source"])
        self.assertNotIn("alpha", fn[0]["source"])

    def test_nested_function_keeps_innermost_only(self):
        self.write("src/app.py", "def outer():\n    def inner():\n        return 1\n    return inner\n")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "nest")
        self.write("src/app.py", "def outer():\n    def inner():\n        return 2\n    return inner\n")
        names = [f["name"] for f in build_review_payload(self.root)["files"][0]["functions"]]
        self.assertEqual(names, ["inner"])

    def test_zero_context_payload_shape(self):
        self.write("src/app.py", PY_BASE + "z = 1\n")
        p = build_review_payload(self.root)
        self.assertEqual(set(p), {"schema", "snapshot_hash", "risk", "reasons", "files", "diff", "instructions"})
        self.assertIn("+z = 1", p["diff"])
        self.assertEqual(p["snapshot_hash"], compute_snapshot_hash(self.root))
        md = render_review_payload_markdown(p)
        self.assertIn("```diff", md)
        self.assertIn(p["snapshot_hash"], md)
        json.dumps(p)  # serializable

    def test_payload_never_contains_writer_identity(self):
        register_writer_session(self.root, "secret-session-77", "codex")
        self.write("src/app.py", PY_BASE + "z = 1\n")
        blob = json.dumps(build_review_payload(self.root)) + render_review_payload_markdown(build_review_payload(self.root))
        self.assertNotIn("secret-session-77", blob)
        self.assertNotIn("codex", blob.lower())

    def test_non_python_uses_hunk_context_and_deleted_file_has_no_functions(self):
        self.write("src/mod.js", "function one() {\n  return 1;\n}\n" + "\n" * 8 + "function two() {\n  return 2;\n}\n")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "js")
        self.write("src/mod.js", "function one() {\n  return 1;\n}\n" + "\n" * 8 + "function two() {\n  return 3;\n}\n")
        (self.root / "tests" / "test_app.py").unlink()
        files = {f["path"]: f for f in build_review_payload(self.root)["files"]}
        self.assertEqual(files["tests/test_app.py"]["functions"], [])
        self.assertTrue(files["tests/test_app.py"]["deleted"])

    def test_syntax_error_python_falls_back_to_hunks(self):
        self.write("src/app.py", PY_BASE + "def broken(:\n")
        self.assertIsInstance(build_review_payload(self.root)["files"][0]["functions"], list)

    def test_write_payload_files(self):
        from gravityguard_engine.review_governance import write_review_payload
        self.write("src/app.py", PY_BASE + "z = 1\n")
        p = build_review_payload(self.root)
        paths = write_review_payload(self.root, p)
        self.assertEqual(json.loads(paths["payload_json"].read_text(encoding="utf-8"))["snapshot_hash"], p["snapshot_hash"])
        self.assertIn("Zero-Context Review", paths["payload_md"].read_text(encoding="utf-8"))
        self.assertEqual(paths, payload_paths(self.root, p["snapshot_hash"]))


class TestSessionRegistry(_GitRepoCase):
    def test_normalize_agent(self):
        self.assertEqual(normalize_agent("Claude Code"), "claude-code")
        self.assertEqual(normalize_agent("claude_code"), "claude-code")
        self.assertEqual(normalize_agent("CLAUDE"), "claude-code")
        self.assertEqual(normalize_agent("agy"), "antigravity")
        self.assertEqual(normalize_agent("Codex"), "codex")
        self.assertEqual(normalize_agent("opencode"), "opencode")
        self.assertEqual(normalize_agent("vim"), "unknown")
        self.assertEqual(normalize_agent(None), "unknown")

    def test_detect_writer_agent_priority(self):
        saved = os.environ.get("GRAVITYGUARD_AGENT")
        try:
            os.environ["GRAVITYGUARD_AGENT"] = "opencode"
            self.assertEqual(detect_writer_agent({"agent": "codex"}), "codex")
            self.assertEqual(detect_writer_agent({"agentName": "Antigravity"}), "antigravity")
            self.assertEqual(detect_writer_agent({"agent": 5}), "opencode")
            self.assertEqual(detect_writer_agent(None), "opencode")
            os.environ.pop("GRAVITYGUARD_AGENT")
            self.assertEqual(detect_writer_agent({}), "unknown")
        finally:
            if saved is not None:
                os.environ["GRAVITYGUARD_AGENT"] = saved
            else:
                os.environ.pop("GRAVITYGUARD_AGENT", None)

    def test_register_correlates_session_agent_and_snapshot(self):
        rec = register_writer_session(self.root, "conv-1", "claude-code", "h" * 64)
        self.assertEqual((rec["agent"], rec["fix_turns"], rec["snapshots"]), ("claude-code", 0, ["h" * 64]))
        self.assertEqual(get_session_record(self.root, "conv-1")["agent"], "claude-code")
        snap = get_snapshot_record(self.root, "h" * 64)
        self.assertEqual((snap["session_id"], snap["status"]), ("conv-1", "pending"))
        self.assertIsNone(get_session_record(self.root, "nope"))
        self.assertIsNone(get_snapshot_record(self.root, "nope"))

    def test_unknown_agent_never_overwrites_known_but_fills_unknown(self):
        register_writer_session(self.root, "c", None)
        self.assertEqual(get_session_record(self.root, "c")["agent"], "unknown")
        register_writer_session(self.root, "c", "codex")
        register_writer_session(self.root, "c", "garbage")
        self.assertEqual(get_session_record(self.root, "c")["agent"], "codex")

    def test_snapshot_not_duplicated_and_corrupt_registry_recovers(self):
        register_writer_session(self.root, "c", "codex", "a" * 64)
        register_writer_session(self.root, "c", "codex", "a" * 64)
        self.assertEqual(get_session_record(self.root, "c")["snapshots"], ["a" * 64])
        (self.root / ".gravityguard" / "review-registry.json").write_text("[1, 2", encoding="utf-8")
        self.assertIsNone(get_session_record(self.root, "c"))
        register_writer_session(self.root, "c2", "opencode")
        self.assertEqual(get_session_record(self.root, "c2")["agent"], "opencode")
        (self.root / ".gravityguard" / "review-registry.json").write_text("[]", encoding="utf-8")
        self.assertIsNone(get_session_record(self.root, "c2"))


class TestFindingsAndFeedback(unittest.TestCase):
    def test_normalize_findings(self):
        raw = [
            {"file": " a.py ", "line": 12, "type": "SECURITY", "suggestion": " fix it "},
            {"file": "b.py", "line": "x", "type": "weird"},
            {"file": "", "line": 1},
            {"line": 3},
            "not a dict",
            {"file": "c.py", "line": True, "type": "logic", "suggestion": "s"},
        ]
        out = normalize_findings(raw)
        self.assertEqual(out[0], {"file": "a.py", "line": 12, "type": "security", "suggestion": "fix it"})
        self.assertEqual(out[1], {"file": "b.py", "line": 0, "type": "other", "suggestion": ""})
        self.assertEqual(out[2]["line"], 0)
        self.assertEqual(len(out), 3)
        self.assertEqual(normalize_findings({"findings": [{"file": "z", "type": "docs"}]})[0]["type"], "docs")
        self.assertEqual(normalize_findings(None), [])
        self.assertEqual(normalize_findings("x"), [])

    def test_feedback_prompt_addresses_writer_with_structured_findings(self):
        findings = normalize_findings([{"file": "a.py", "line": 7, "type": "logic", "suggestion": "off-by-one"},
                                       {"file": "b.py", "type": "docs"}])
        prompt = build_feedback_prompt("codex", findings, "f" * 64, 1, 2)
        self.assertIn("codex", prompt)
        self.assertIn("1/2", prompt)
        self.assertIn("ffffffffffff", prompt)
        self.assertIn("1. [logic] a.py:7 — off-by-one", prompt)
        self.assertIn("2. [docs] b.py — açıklama yok", prompt)


class TestAntiLoop(_GitRepoCase):
    CFG = {"reviewGovernance": {"enabled": True, "maxFixTurns": 2}}
    FINDING = [{"file": "src/app.py", "line": 2, "type": "logic", "suggestion": "handle None"}]

    def _snap(self, session="s1", agent="claude-code", tag="a"):
        h = tag * 64
        register_writer_session(self.root, session, agent, h)
        return h

    def test_two_fix_turns_then_escalate(self):
        h1 = self._snap(tag="a")
        r1 = record_review_result(self.root, h1, self.FINDING, self.CFG)
        self.assertEqual((r1["status"], r1["fix_turns"], r1["escalate"]), ("findings", 1, False))
        self.assertIn("1/2", r1["feedback_prompt"])
        self.assertEqual(r1["writer_agent"], "claude-code")
        h2 = self._snap(tag="b")  # writer fixed -> new snapshot hash, same session
        r2 = record_review_result(self.root, h2, self.FINDING, self.CFG)
        self.assertEqual((r2["fix_turns"], r2["escalate"]), (2, True))
        self.assertIn("2/2", r2["feedback_prompt"])

    def test_same_hash_is_idempotent_and_consumes_no_turn(self):
        h = self._snap()
        first = record_review_result(self.root, h, self.FINDING, self.CFG)
        again = record_review_result(self.root, h, self.FINDING, self.CFG)
        flipped = record_review_result(self.root, h, [], self.CFG)
        self.assertFalse(first["cached"])
        self.assertTrue(again["cached"] and flipped["cached"])
        self.assertEqual(again["fix_turns"], 1)
        self.assertEqual(flipped["status"], "findings", "a decided snapshot cannot be flipped")
        self.assertEqual(get_session_record(self.root, "s1")["fix_turns"], 1)

    def test_clean_verdict_resets_counter(self):
        record_review_result(self.root, self._snap(tag="a"), self.FINDING, self.CFG)
        ok = record_review_result(self.root, self._snap(tag="b"), [], self.CFG)
        self.assertEqual((ok["status"], ok["fix_turns"], ok["feedback_prompt"], ok["escalate"]), ("passed", 0, None, False))

    def test_sessions_do_not_share_budget(self):
        record_review_result(self.root, self._snap("s1", tag="a"), self.FINDING, self.CFG)
        r = record_review_result(self.root, self._snap("s2", "codex", tag="b"), self.FINDING, self.CFG)
        self.assertEqual((r["fix_turns"], r["writer_agent"]), (1, "codex"))

    def test_max_fix_turns_zero_escalates_immediately(self):
        cfg = {"reviewGovernance": {"enabled": True, "maxFixTurns": 0}}
        r = record_review_result(self.root, self._snap(), self.FINDING, cfg)
        self.assertTrue(r["escalate"])

    def test_result_for_unregistered_snapshot(self):
        r = record_review_result(self.root, "9" * 64, self.FINDING, self.CFG)
        self.assertEqual((r["status"], r["writer_agent"], r["fix_turns"]), ("findings", "unknown", 1))
        clean = record_review_result(self.root, "8" * 64, [], self.CFG)
        self.assertEqual((clean["status"], clean["fix_turns"]), ("passed", 0))

    def test_ingest_result_file(self):
        h = self._snap()
        self.assertIsNone(ingest_result_file(self.root, h, self.CFG))
        rp = payload_paths(self.root, h)["result"]
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text("{not json", encoding="utf-8")
        self.assertIsNone(ingest_result_file(self.root, h, self.CFG))
        rp.write_text(json.dumps({"findings": self.FINDING}), encoding="utf-8")
        self.assertEqual(ingest_result_file(self.root, h, self.CFG)["status"], "findings")


class TestZeroContextGate(_GitRepoCase):
    CFG = {"reviewGovernance": {"enabled": True, "maxFixTurns": 2}}
    FINDING = [{"file": "engine/core.py", "line": 1, "type": "logic", "suggestion": "fix"}]

    def gate(self, cfg=None, session="s1", agent="codex"):
        return evaluate_zero_context_gate(self.root, self.CFG if cfg is None else cfg, session, agent)

    def write_result(self, snapshot, findings):
        rp = payload_paths(self.root, snapshot)["result"]
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(findings), encoding="utf-8")

    def test_disabled_by_default(self):
        self.write("engine/core.py", "x = 1\n")
        self.assertEqual(evaluate_zero_context_gate(self.root, None)["action"], "disabled")
        self.assertEqual(evaluate_zero_context_gate(self.root, {"reviewGovernance": {"enabled": False}})["action"], "disabled")
        self.assertFalse(self.gate({})["block"])
        self.assertFalse((self.root / ".gravityguard" / "review-registry.json").exists())

    def test_skip_when_no_diff_or_below_threshold(self):
        self.assertEqual(self.gate()["action"], "skip")
        self.write("README.md", "# changed\n")
        self.assertEqual(self.gate()["action"], "skip")
        self.write("src/app.py", PY_BASE + "\n\ndef gamma():\n    return 3\n")  # MEDIUM < default HIGH
        self.assertEqual(self.gate()["action"], "skip")
        medium = {"reviewGovernance": {"enabled": True, "minRisk": RISK_MEDIUM}}
        self.assertEqual(self.gate(medium)["action"], "review_required")

    def test_full_lifecycle_review_fix_escalate(self):
        self.write("engine/core.py", "x = 1\n")
        g = self.gate()
        self.assertEqual((g["action"], g["block"], g["risk"]), ("review_required", True, RISK_HIGH))
        self.assertTrue(Path(g["payload_path"]).is_file())
        payload_text = Path(g["payload_path"]).read_text(encoding="utf-8")
        self.assertIn("+x = 1", payload_text)
        self.assertNotIn("codex", payload_text.lower())
        self.assertEqual(self.gate()["action"], "review_required", "still waiting for reviewer; stable")

        # reviewer writes findings -> writer gets feedback (turn 1)
        self.write_result(g["snapshot_hash"], {"findings": self.FINDING})
        g = self.gate()
        self.assertEqual((g["action"], g["block"], g["fix_turns"]), ("fix_required", True, 1))
        self.assertIn("codex", g["message"])
        self.assertIn("engine/core.py:1", g["message"])
        self.assertEqual(self.gate()["fix_turns"], 1, "polling again does not burn turns")

        # writer fixes -> new snapshot -> new review -> findings again (turn 2) -> escalate
        self.write("engine/core.py", "x = 2\n")
        g = self.gate()
        self.assertEqual(g["action"], "review_required")
        self.write_result(g["snapshot_hash"], self.FINDING)
        g = self.gate()
        self.assertEqual(g["action"], "escalate")
        self.assertFalse(g["block"])
        self.assertIn("2 tur", g["message"])

    def test_clean_review_passes_and_new_change_needs_new_review(self):
        self.write("engine/core.py", "x = 1\n")
        g = self.gate()
        self.write_result(g["snapshot_hash"], [])
        self.assertEqual(self.gate()["action"], "passed")
        self.assertEqual(self.gate()["action"], "passed", "idempotent")
        self.write("engine/core.py", "x = 99\n")
        self.assertEqual(self.gate()["action"], "review_required")

    def test_staged_only_setting(self):
        cfg = {"reviewGovernance": {"enabled": True, "stagedOnly": True}}
        self.write("engine/core.py", "x = 1\n")
        self.assertEqual(self.gate(cfg)["action"], "skip")
        _git(self.root, "add", "engine/core.py")
        self.assertEqual(self.gate(cfg)["action"], "review_required")


class TestResilience(_GitRepoCase):
    def test_git_unavailable_yields_empty_low_risk(self):
        from unittest import mock
        with mock.patch("gravityguard_engine.review_governance.subprocess.run", side_effect=OSError("no git")):
            r = classify_change_risk(self.root)
        self.assertEqual((r["risk"], r["snapshot_hash"], r["files"]), (RISK_LOW, "", []))

    def test_oversize_untracked_file_is_skipped(self):
        self.write("big.txt", "x" * 200_001)
        self.assertEqual(self.risk()["files"], [])

    def test_unreadable_untracked_file_is_skipped(self):
        from unittest import mock
        self.write("src/new.py", "x = 1\n")
        with mock.patch.object(Path, "read_text", side_effect=OSError("denied")):
            self.assertEqual(self.risk()["files"], [])

    def test_missing_file_for_ast_falls_back_to_hunks(self):
        from gravityguard_engine.review_governance import _read_new_text, changed_function_boundaries
        self.assertIsNone(_read_new_text(self.root, "nope.py", False))
        rec = {"path": "gone.py", "deleted": False, "added_numbers": [1],
               "hunks": [{"start": 1, "length": 2, "context": "def ctx():"}]}
        spans = changed_function_boundaries(self.root, rec)
        self.assertEqual([s["name"] for s in spans], ["def ctx():"])

    def test_staged_only_reads_index_content(self):
        self.write("src/app.py", PY_BASE.replace("y * 2", "y * 9"))
        _git(self.root, "add", "src/app.py")
        self.write("src/app.py", PY_BASE)  # working tree reverted, index still has the change
        names = [f["name"] for f in build_review_payload(self.root, staged_only=True)["files"][0]["functions"]]
        self.assertEqual(names, ["beta"])

    def test_huge_function_source_is_truncated(self):
        body = "".join(f"    v{i} = {i}\n" for i in range(300))
        self.write("src/app.py", "def huge():\n" + body)
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "huge")
        self.write("src/app.py", "def huge():\n" + body.replace("v5 = 5", "v5 = 6"))
        src = build_review_payload(self.root)["files"][0]["functions"][0]["source"]
        self.assertTrue(src.endswith("# ... truncated ..."))
        self.assertEqual(len(src.splitlines()), 201)


class TestStopHookIntegration(unittest.TestCase):
    """Real gravity-validator.py Stop hook with reviewGovernance opted in."""

    VALIDATOR = os.path.join(_ENGINE_DIR, "gravity-validator.py")

    def _stop(self, proj, logs, session="zc-sess", agent="codex"):
        env = {**os.environ, "GRAVITYGUARD_LOG_DIR": logs, "GRAVITYGUARD_DISABLE_ASYNC": "1",
               "GRAVITYGUARD_USER_CONFIG": os.path.join(logs, "none.json")}
        payload = {"terminationReason": "model_stop", "workspacePaths": [proj], "conversationId": session, "agent": agent}
        proc = subprocess.run([sys.executable, self.VALIDATOR], input=json.dumps(payload),
                              capture_output=True, text=True, cwd=proj, env=env, timeout=90)
        return json.loads(proc.stdout.strip()), proc.stderr

    def test_stop_blocks_until_independent_review_then_allows(self):
        with tempfile.TemporaryDirectory() as proj, tempfile.TemporaryDirectory() as logs:
            _git(proj, "init", "-q")
            Path(proj, ".gravityguard.json").write_text(json.dumps({"reviewGovernance": {"enabled": True}}), encoding="utf-8")
            Path(proj, "engine").mkdir()
            Path(proj, "engine", "core.py").write_text("x = 1\n", encoding="utf-8")
            _git(proj, "add", "-A")
            _git(proj, "commit", "-q", "-m", "base")
            Path(proj, "engine", "core.py").write_text("x = 2\n", encoding="utf-8")

            res, err = self._stop(proj, logs)
            self.assertEqual(res.get("decision"), "continue", err)
            self.assertIn("review_required", res["reason"])
            payloads = list(Path(proj, ".gravityguard", "zero-context-review").glob("*.payload.md"))
            self.assertEqual(len(payloads), 1)

            result_file = str(payloads[0]).replace(".payload.md", ".result.json")
            Path(result_file).write_text(json.dumps([{"file": "engine/core.py", "line": 1, "type": "logic", "suggestion": "s"}]), encoding="utf-8")
            res, err = self._stop(proj, logs)
            self.assertEqual(res.get("decision"), "continue", err)
            self.assertIn("fix_required", res["reason"])
            self.assertIn("codex", res["reason"])

            Path(proj, "engine", "core.py").write_text("x = 3\n", encoding="utf-8")
            res, err = self._stop(proj, logs)
            self.assertIn("review_required", res["reason"])
            new_result = str(list(Path(proj, ".gravityguard", "zero-context-review").glob("*.payload.md"))[-1])
            for p in Path(proj, ".gravityguard", "zero-context-review").glob("*.payload.md"):
                if str(p) != str(payloads[0]):
                    new_result = str(p).replace(".payload.md", ".result.json")
            Path(new_result).write_text("[]", encoding="utf-8")
            res, err = self._stop(proj, logs)
            self.assertNotIn("Bağımsız İnceleme Kapısı", res.get("reason", ""), err)

    def test_stop_ignores_gate_when_not_opted_in(self):
        with tempfile.TemporaryDirectory() as proj, tempfile.TemporaryDirectory() as logs:
            _git(proj, "init", "-q")
            Path(proj, ".gravityguard.json").write_text("{}", encoding="utf-8")
            Path(proj, "engine").mkdir()
            Path(proj, "engine", "core.py").write_text("x = 1\n", encoding="utf-8")
            res, err = self._stop(proj, logs)
            self.assertNotIn("Bağımsız İnceleme Kapısı", res.get("reason", ""), err)
            self.assertFalse(Path(proj, ".gravityguard", "zero-context-review").exists())


class TestZeroContextFacadeExports(unittest.TestCase):
    def test_validator_re_exports_zero_context_api(self):
        src = Path(_ENGINE_DIR, "gravity-validator.py").read_text(encoding="utf-8")
        for name in ("classify_change_risk", "compute_snapshot_hash", "build_review_payload", "evaluate_zero_context_gate",
                     "record_review_result", "register_writer_session", "detect_writer_agent", "is_review_governance_enabled"):
            self.assertIn(name, src)


if __name__ == "__main__":
    unittest.main()
