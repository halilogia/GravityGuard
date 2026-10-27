#!/usr/bin/env python3
"""Live end-to-end checks of the zero-context review gate against a real throwaway Git repository.

No mocks: real `git diff`, real payload files under `.gravityguard/zero-context-review/`, a reviewer simulated by
writing `<hash>.result.json`, and the real anti-loop registry. Scenarios:
  a) large additions and security-sensitive files are classified HIGH_RISK automatically
  b) the payload (.payload.json / .payload.md) is produced and carries no writer history or identity
  c) a finding in .result.json -> fix_required with a feedback prompt addressed to the writer (claude-code)
  d) a clean result -> passed
  e) maxFixTurns reached -> escalate (human decides)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine.review_governance import (
    build_review_payload,
    classify_change_risk,
    evaluate_zero_context_gate,
    get_session_record,
    payload_paths,
)
from gravityguard_engine.review_policy import RISK_HIGH, RISK_LOW

CFG = {"reviewGovernance": {"enabled": True, "maxFixTurns": 2}}
SESSION = "live-session-1"
WRITER = "claude-code"
FINDING = [{"file": "src/service.py", "line": 3, "type": "security", "suggestion": "Validate the input before use."}]


def _git(root, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=str(root), check=True, capture_output=True)


class LiveZeroContextReview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gg_live_zc_")
        self.root = Path(self.tmp)
        _git(self.root, "init", "-q")
        self.write("README.md", "# live review demo\n")
        self.write("src/service.py", "def handle(x):\n    return x\n")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "base")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, text):
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")

    def gate(self):
        return evaluate_zero_context_gate(self.root, CFG, session_id=SESSION, agent=WRITER)

    def submit(self, snapshot_hash, findings):
        result = payload_paths(self.root, snapshot_hash)["result"]
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_text(json.dumps(findings), encoding="utf-8")

    def risky_change(self, n):
        """A security-sensitive edit; each distinct `n` yields a distinct snapshot hash."""
        self.write("src/auth_service.py", f"def login(user):\n    return check(user)  # revision {n}\n")

    # a) --------------------------------------------------------------------------------------------------------
    def test_a_large_addition_is_high_risk(self):
        self.write("src/big_feature.py", "\n".join(f"value_{i} = {i} * 2" for i in range(320)) + "\n")
        risk = classify_change_risk(self.root)
        self.assertEqual(risk["risk"], RISK_HIGH)
        self.assertGreater(risk["lines_changed"], 300)
        self.assertTrue(risk["snapshot_hash"])

    def test_a_security_file_is_high_risk_even_when_small(self):
        self.risky_change(1)
        self.assertEqual(classify_change_risk(self.root)["risk"], RISK_HIGH)

    def test_a_docs_only_change_is_low_risk_and_skipped(self):
        self.write("README.md", "# live review demo\n\nMore words.\n")
        self.assertEqual(classify_change_risk(self.root)["risk"], RISK_LOW)
        self.assertEqual(self.gate()["action"], "skip")

    # b) --------------------------------------------------------------------------------------------------------
    def test_b_payload_files_are_written_without_writer_identity(self):
        self.risky_change(1)
        verdict = self.gate()
        self.assertEqual(verdict["action"], "review_required")
        self.assertTrue(verdict["block"])
        paths = payload_paths(self.root, verdict["snapshot_hash"])
        self.assertTrue(paths["payload_json"].is_file(), paths["payload_json"])
        self.assertTrue(paths["payload_md"].is_file(), paths["payload_md"])
        self.assertEqual(paths["payload_json"].parent, self.root / ".gravityguard" / "zero-context-review")
        payload = json.loads(paths["payload_json"].read_text(encoding="utf-8"))
        self.assertEqual(payload["snapshot_hash"], verdict["snapshot_hash"])
        self.assertEqual(payload["risk"], RISK_HIGH)
        self.assertIn("src/auth_service.py", payload["diff"])
        self.assertEqual([f["path"] for f in payload["files"]], ["src/auth_service.py"])
        blob = (json.dumps(payload) + paths["payload_md"].read_text(encoding="utf-8")).lower()
        for leak in (WRITER, SESSION, "claude", "author", "session", "t@t"):
            self.assertNotIn(leak, blob, f"payload must not reveal writer identity/history: {leak!r}")
        # same working tree -> same hash and an identical payload
        self.assertEqual(build_review_payload(self.root)["snapshot_hash"], verdict["snapshot_hash"])

    # c) --------------------------------------------------------------------------------------------------------
    def test_c_finding_requires_fix_and_addresses_the_writer(self):
        self.risky_change(1)
        sid = self.gate()["snapshot_hash"]
        self.submit(sid, FINDING)
        verdict = self.gate()
        self.assertEqual(verdict["action"], "fix_required")
        self.assertTrue(verdict["block"])
        self.assertEqual(verdict["findings"][0]["type"], "security")
        self.assertIn(WRITER, verdict["message"])
        self.assertIn("src/service.py:3", verdict["message"])
        self.assertIn("Validate the input", verdict["message"])
        self.assertEqual(get_session_record(self.root, SESSION)["fix_turns"], 1)

    # d) --------------------------------------------------------------------------------------------------------
    def test_d_clean_result_passes(self):
        self.risky_change(1)
        sid = self.gate()["snapshot_hash"]
        self.submit(sid, [])
        verdict = self.gate()
        self.assertEqual(verdict["action"], "passed")
        self.assertFalse(verdict["block"])

    def test_d_fix_then_clean_review_resets_the_counter(self):
        self.risky_change(1)
        self.submit(self.gate()["snapshot_hash"], FINDING)
        self.assertEqual(self.gate()["action"], "fix_required")
        self.risky_change(2)  # the writer fixes the code -> a new snapshot needs a fresh review
        second = self.gate()
        self.assertEqual(second["action"], "review_required")
        self.submit(second["snapshot_hash"], [])
        self.assertEqual(self.gate()["action"], "passed")
        self.assertEqual(get_session_record(self.root, SESSION)["fix_turns"], 0)

    # e) --------------------------------------------------------------------------------------------------------
    def test_e_max_fix_turns_escalates_to_a_human(self):
        for n in (1, 2):
            self.risky_change(n)
            snap = self.gate()
            self.assertEqual(snap["action"], "review_required", f"revision {n} is a new snapshot and needs a fresh review")
            self.submit(snap["snapshot_hash"], FINDING)
            verdict = self.gate()
            if n == 1:
                self.assertEqual(verdict["action"], "fix_required")
        self.assertEqual(verdict["action"], "escalate")
        self.assertFalse(verdict["block"], "escalation hands control to a human instead of blocking")
        self.assertEqual(verdict["fix_turns"], 2)
        self.assertIn("insan", verdict["message"])


if __name__ == "__main__":
    unittest.main()
