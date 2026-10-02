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

    def test_rule_specific_causal_isolation(self):
        target = "src/app.py"
        # 1. First block is G1
        id1 = log_event("write", "BLOCKED", target, "violation G1", rule_id="G1_SILENT_EXCEPTION", conversation_id="conv-rule-iso")
        
        # 2. Second block on the same file is G2 (different rule)
        id2 = log_event("write", "BLOCKED", target, "violation G2", rule_id="G2_TEST_INTEGRITY", conversation_id="conv-rule-iso")

        live_path = os.path.join(self.test_dir, "srp_guardian_live.json")
        with open(live_path, "r", encoding="utf-8") as f:
            live = json.load(f)

        events = live["events"]
        # id2 is the latest event (index 0)
        self.assertEqual(events[0]["eventId"], id2)
        # Crucial check: G2 must NOT be marked as a repeated violation of G1!
        self.assertEqual(events[0]["outcome"], "BLOCKED")
        self.assertIsNone(events[0]["parentViolationId"])
        self.assertEqual(events[0]["recoveryAttempts"], 1)

    def test_resolved_rule_id_and_rule_stats(self):
        target = "src/payment.py"
        conv = "conv-stats"
        # 1. Trigger G1 block
        b_id = log_event("write", "BLOCKED", target, "empty except block", rule_id="G1_SILENT_EXCEPTION", conversation_id=conv)

        # 2. Agent provides clean code -> APPROVED with rule_id="PASS"
        a_id = log_event("write", "APPROVED", target, "proper exception logged", rule_id="PASS", conversation_id=conv)

        live_path = os.path.join(self.test_dir, "srp_guardian_live.json")
        with open(live_path, "r", encoding="utf-8") as f:
            live = json.load(f)

        rec_ev = live["events"][0]
        self.assertEqual(rec_ev["eventId"], a_id)
        self.assertEqual(rec_ev["outcome"], "RECOVERED")
        self.assertEqual(rec_ev["resolvedRuleId"], "G1_SILENT_EXCEPTION")
        self.assertEqual(rec_ev["parentViolationId"], b_id)

        eff = live["effectiveness"]
        self.assertEqual(eff["totalBlocked"], 1)
        self.assertEqual(eff["totalRecovered"], 1)
        self.assertEqual(eff["recoveryRate"], 100.0)
        self.assertIn("G1_SILENT_EXCEPTION", eff["ruleStats"])
        g1_stat = eff["ruleStats"]["G1_SILENT_EXCEPTION"]
        self.assertEqual(g1_stat["blocked"], 1)
        self.assertEqual(g1_stat["recovered"], 1)
        self.assertEqual(g1_stat["recoveryRate"], 100.0)

    def test_explicit_conversation_id_isolation(self):
        target = "src/shared.py"
        # Session A gets blocked on src/shared.py
        id_a = log_event("write", "BLOCKED", target, "violation A", rule_id="G1_SILENT_EXCEPTION", conversation_id="sess-A")

        # Session B makes an approved edit on the same src/shared.py
        id_b = log_event("write", "APPROVED", target, "clean edit B", rule_id="PASS", conversation_id="sess-B")

        live_path = os.path.join(self.test_dir, "srp_guardian_live.json")
        with open(live_path, "r", encoding="utf-8") as f:
            live = json.load(f)

        ev_b = live["events"][0]
        self.assertEqual(ev_b["eventId"], id_b)
        # Session B edit should NOT be marked as RECOVERED because Session A's violation belongs to sess-A!
        self.assertNotEqual(ev_b.get("outcome"), "RECOVERED")
        self.assertIsNone(ev_b.get("parentViolationId"))

        # Now Session A makes an approved edit on src/shared.py
        id_a_rec = log_event("write", "APPROVED", target, "fixed A", rule_id="PASS", conversation_id="sess-A")
        with open(live_path, "r", encoding="utf-8") as f:
            live = json.load(f)

        ev_a = live["events"][0]
        self.assertEqual(ev_a["eventId"], id_a_rec)
        self.assertEqual(ev_a["outcome"], "RECOVERED")
        self.assertEqual(ev_a["parentViolationId"], id_a)

    def test_multi_rule_recovery_all_resolved(self):
        target = "src/multi_rule.py"
        conv = "conv-multi-rec"

        # 1. First block is G1
        id_g1 = log_event("write", "BLOCKED", target, "violation G1", rule_id="G1_SILENT_EXCEPTION", conversation_id=conv)
        # 2. Second block on same file is G2
        id_g2 = log_event("write", "BLOCKED", target, "violation G2", rule_id="G2_TEST_INTEGRITY", conversation_id=conv)

        # 3. Approved clean edit fixes both
        id_app = log_event("write", "APPROVED", target, "fixed both G1 and G2", rule_id="PASS", conversation_id=conv)

        live_path = os.path.join(self.test_dir, "srp_guardian_live.json")
        with open(live_path, "r", encoding="utf-8") as f:
            live = json.load(f)

        # Verify active violations are completely cleared
        self.assertEqual(len(live.get("activeViolations", {})), 0)

        # Verify effectiveness stats accurately credit both rules
        eff = live["effectiveness"]
        self.assertEqual(eff["totalBlocked"], 2)
        self.assertEqual(eff["totalRecovered"], 2)
        self.assertEqual(eff["recoveryRate"], 100.0)

        rule_stats = eff["ruleStats"]
        self.assertIn("G1_SILENT_EXCEPTION", rule_stats)
        self.assertIn("G2_TEST_INTEGRITY", rule_stats)
        self.assertEqual(rule_stats["G1_SILENT_EXCEPTION"]["recovered"], 1)
        self.assertEqual(rule_stats["G2_TEST_INTEGRITY"]["recovered"], 1)

        # Verify permanent log contains RECOVERED entries for both rules
        perm_path = os.path.join(self.test_dir, "gravityguard_permanent_audit.jsonl")
        perm_events = []
        with open(perm_path, "r", encoding="utf-8") as pf:
            for line in pf:
                perm_events.append(json.loads(line))

        recovered_rules = [e.get("resolvedRuleId") for e in perm_events if e.get("outcome") == "RECOVERED"]
        self.assertIn("G1_SILENT_EXCEPTION", recovered_rules)
        self.assertIn("G2_TEST_INTEGRITY", recovered_rules)

    def test_audit_lock_timeout_fails_closed(self):
        from unittest.mock import patch
        from gravityguard_engine.state_lock import StateLock
        target = "src/timeout.py"

        # Mock StateLock.acquire to return False (simulating lock contention timeout)
        with patch.object(StateLock, "acquire", return_value=False):
            eid = log_event("write", "BLOCKED", target, "lock timeout test", rule_id="G1_SILENT_EXCEPTION")
            self.assertTrue(eid.startswith("evt_"))

        # Live file should either not exist or not have recorded this event without a lock
        live_path = os.path.join(self.test_dir, "srp_guardian_live.json")
        if os.path.exists(live_path):
            with open(live_path, "r", encoding="utf-8") as f:
                live = json.load(f)
            event_ids = [e["eventId"] for e in live.get("events", [])]
            self.assertNotIn(eid, event_ids)

    def test_rebuild_live_state_from_permanent_audit_on_corruption(self):
        target = "src/crash_recovery.py"
        conv = "conv-rebuild"

        # 1. Generate some audit history
        log_event("write", "BLOCKED", target, "violation G1", rule_id="G1_SILENT_EXCEPTION", conversation_id=conv)
        log_event("write", "APPROVED", target, "fixed G1", rule_id="PASS", conversation_id=conv)

        live_path = os.path.join(self.test_dir, "srp_guardian_live.json")
        self.assertTrue(os.path.exists(live_path))

        # 2. Simulate catastrophic corruption: write garbage to live JSON
        with open(live_path, "w", encoding="utf-8") as f:
            f.write("{ corrupt json truncated...")

        # 3. Next event should detect corruption and auto-rebuild from permanent audit
        new_target = "src/next_file.py"
        log_event("write", "APPROVED", new_target, "clean write", rule_id="PASS", conversation_id=conv)

        # 4. Verify live state was reconstructed with historical counts intact
        with open(live_path, "r", encoding="utf-8") as f:
            live = json.load(f)

        eff = live["effectiveness"]
        # History preserved: 1 block, 1 recovery from prior file
        self.assertEqual(eff["totalBlocked"], 1)
        self.assertEqual(eff["totalRecovered"], 1)
        self.assertEqual(eff["recoveryRate"], 100.0)
        self.assertIn("G1_SILENT_EXCEPTION", eff["ruleStats"])
        self.assertEqual(eff["ruleStats"]["G1_SILENT_EXCEPTION"]["recovered"], 1)

    def test_live_state_atomic_replace_no_temp_leftover(self):
        target = "src/atomic_test.py"
        log_event("write", "APPROVED", target, "atomic write test", rule_id="PASS")

        live_path = os.path.join(self.test_dir, "srp_guardian_live.json")
        tmp_path = os.path.join(self.test_dir, "srp_guardian_live.tmp")

        self.assertTrue(os.path.exists(live_path))
        self.assertFalse(os.path.exists(tmp_path))

    def test_telemetry_invariant_warning_on_anomaly(self):
        import io
        from unittest.mock import patch
        target = "src/anomaly.py"

        # Create a corrupted live state where recovered > blocked to simulate anomaly
        live_path = os.path.join(self.test_dir, "srp_guardian_live.json")
        bad_data = {
            "activeGuard": "GravityGuard",
            "status": "ONLINE",
            "events": [],
            "activeViolations": {},
            "effectiveness": {
                "totalBlocked": 1,
                "totalRecovered": 2,  # anomaly: recovered > blocked
                "recoveryRate": 100.0,
                "ruleStats": {
                    "G1_SILENT_EXCEPTION": {"blocked": 1, "recovered": 2, "recoveryRate": 100.0, "attempts": [1]}
                }
            }
        }
        with open(live_path, "w", encoding="utf-8") as f:
            json.dump(bad_data, f)

        # Log event and capture stderr
        stderr_buf = io.StringIO()
        with patch("sys.stderr", stderr_buf):
            log_event("write", "APPROVED", target, "clean edit", rule_id="PASS")

        stderr_output = stderr_buf.getvalue()
        self.assertIn("[GravityGuard Invariant Violation]", stderr_output)


if __name__ == "__main__":
    unittest.main()
