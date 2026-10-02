#!/usr/bin/env python3
"""
Unit tests for GravityGuard audit & causal outcome tracking subsystem.
Verifies event ID generation, causal chaining (BLOCKED -> RECOVERED),
repeated violation attempts, and shadow mode logging.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine.audit import log_event, _resolve_log_dir


class TestAuditSubsystem(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="gg_test_audit_")
        self.old_log_dir = os.environ.get("GRAVITYGUARD_LOG_DIR")
        os.environ["GRAVITYGUARD_LOG_DIR"] = self.test_dir
        os.environ["ANTIGRAVITY_CONVERSATION_ID"] = "test-conv-1"

    def tearDown(self):
        if self.old_log_dir is not None:
            os.environ["GRAVITYGUARD_LOG_DIR"] = self.old_log_dir
        else:
            os.environ.pop("GRAVITYGUARD_LOG_DIR", None)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_log_event_generates_unique_id(self):
        eid1 = log_event("write", "APPROVED", "src/mod.py", "All guards passed", rule_id="PASS")
        eid2 = log_event("write", "APPROVED", "src/mod.py", "All guards passed", rule_id="PASS")
        self.assertTrue(eid1.startswith("evt_"))
        self.assertTrue(eid2.startswith("evt_"))
        self.assertNotEqual(eid1, eid2)

    def test_causal_chaining_blocked_then_recovered(self):
        target = "src/services/auth.py"
        # 1. Agent triggers a block
        block_id = log_event("write", "BLOCKED", target, "except: pass found", rule_id="G1_SILENT_EXCEPTION")

        live_path = os.path.join(self.test_dir, "srp_guardian_live.json")
        with open(live_path, "r", encoding="utf-8") as f:
            live = json.load(f)
        last_ev = live["events"][0]
        self.assertEqual(last_ev["eventId"], block_id)
        self.assertEqual(last_ev["outcome"], "BLOCKED")
        self.assertEqual(last_ev["recoveryAttempts"], 1)
        self.assertIsNone(last_ev["parentViolationId"])

        # 2. Agent fixes the code on next attempt -> APPROVED
        pass_id = log_event("write", "APPROVED", target, "Cleaned exception handling", rule_id="PASS")

        with open(live_path, "r", encoding="utf-8") as f:
            live = json.load(f)
        recovered_ev = live["events"][0]
        self.assertEqual(recovered_ev["eventId"], pass_id)
        self.assertEqual(recovered_ev["outcome"], "RECOVERED")
        self.assertEqual(recovered_ev["parentViolationId"], block_id)
        self.assertEqual(recovered_ev["recoveryAttempts"], 1)
        self.assertIsNotNone(recovered_ev["resolutionMs"])
        self.assertEqual(live["effectiveness"]["totalRecovered"], 1)
        self.assertEqual(live["effectiveness"]["recoveryRate"], 100.0)

    def test_repeated_violation_increments_attempts(self):
        target = "src/engine/core.py"
        # 1. First block
        id1 = log_event("write", "BLOCKED", target, "violation 1", rule_id="G1_SILENT_EXCEPTION")
        # 2. Second block (agent failed to fix)
        id2 = log_event("write", "BLOCKED", target, "violation 2", rule_id="G1_SILENT_EXCEPTION")

        live_path = os.path.join(self.test_dir, "srp_guardian_live.json")
        with open(live_path, "r", encoding="utf-8") as f:
            live = json.load(f)
        repeat_ev = live["events"][0]
        self.assertEqual(repeat_ev["eventId"], id2)
        self.assertEqual(repeat_ev["outcome"], "REPEATED_VIOLATION")
        self.assertEqual(repeat_ev["parentViolationId"], id1)
        self.assertEqual(repeat_ev["recoveryAttempts"], 2)

        # 3. Third attempt succeeds
        id3 = log_event("write", "APPROVED", target, "finally fixed", rule_id="PASS")
        with open(live_path, "r", encoding="utf-8") as f:
            live = json.load(f)
        rec_ev = live["events"][0]
        self.assertEqual(rec_ev["outcome"], "RECOVERED")
        self.assertEqual(rec_ev["parentViolationId"], id1)
        self.assertEqual(rec_ev["recoveryAttempts"], 2)

    def test_shadow_mode_logging(self):
        target = "src/legacy/big_file.py"
        eid = log_event("write", "SHADOW_TRIGGER", target, "[SHADOW] Large file growth", rule_id="ARCH_FILE_GROWTH")
        live_path = os.path.join(self.test_dir, "srp_guardian_live.json")
        with open(live_path, "r", encoding="utf-8") as f:
            live = json.load(f)
        ev = live["events"][0]
        self.assertEqual(ev["eventId"], eid)
        self.assertEqual(ev["status"], "SHADOW_TRIGGER")
        self.assertEqual(ev["outcome"], "SHADOW_OBSERVED")


if __name__ == "__main__":
    unittest.main()
