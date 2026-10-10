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

from gravityguard_engine.audit import log_event, _resolve_log_dir, redact_secrets, redact_record


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

    def test_audit_seq_monotonic_increment(self):
        target = "src/seq_test.py"
        conv = "conv-seq"
        id1 = log_event("write", "BLOCKED", target, "block 1", rule_id="G1_SILENT_EXCEPTION", conversation_id=conv)
        id2 = log_event("write", "BLOCKED", target, "repeat 2", rule_id="G1_SILENT_EXCEPTION", conversation_id=conv)
        id3 = log_event("write", "APPROVED", target, "clean 3", rule_id="PASS", conversation_id=conv)

        # 1. Verify permanent journal has monotonic auditSeq: 1, 2, 3
        perm_path = os.path.join(self.test_dir, "gravityguard_permanent_audit.jsonl")
        perm_events = []
        with open(perm_path, "r", encoding="utf-8") as pf:
            for line in pf:
                perm_events.append(json.loads(line))

        self.assertEqual(len(perm_events), 3)
        self.assertEqual(perm_events[0]["auditSeq"], 1)
        self.assertEqual(perm_events[1]["auditSeq"], 2)
        self.assertEqual(perm_events[2]["auditSeq"], 3)

        # 2. Verify live state has lastAuditSeq == 3 and events have auditSeq
        live_path = os.path.join(self.test_dir, "srp_guardian_live.json")
        with open(live_path, "r", encoding="utf-8") as lf:
            live = json.load(lf)

        self.assertEqual(live["lastAuditSeq"], 3)
        self.assertEqual(live["events"][0]["auditSeq"], 3)
        self.assertEqual(live["events"][1]["auditSeq"], 2)
        self.assertEqual(live["events"][2]["auditSeq"], 1)

    def test_journal_ahead_of_live_triggers_projection_replay(self):
        target = "src/crash_recovery_wal.py"
        conv = "conv-wal-divergence"

        # 1. Initial event: seq 1
        log_event("write", "APPROVED", "src/init.py", "init passed", rule_id="PASS", conversation_id=conv)
        live_path = os.path.join(self.test_dir, "srp_guardian_live.json")
        perm_path = os.path.join(self.test_dir, "gravityguard_permanent_audit.jsonl")

        with open(live_path, "r", encoding="utf-8") as lf:
            live_init = json.load(lf)
        self.assertEqual(live_init["lastAuditSeq"], 1)

        # 2. Simulate crash between journal append and live replace:
        # Append event seq 2 directly to journal without updating live state
        crash_event = {
            "auditSeq": 2,
            "eventId": "evt_crash_sim_999",
            "timestamp": "2026-10-03T01:00:00",
            "action": "write",
            "status": "BLOCKED",
            "ruleId": "G1_SILENT_EXCEPTION",
            "resolvedRuleId": None,
            "target": target,
            "project": "TestProj",
            "projectRoot": self.test_dir,
            "fileExt": ".py",
            "conversationId": conv,
            "model": "test-model",
            "reason": "Simulated unprojected block in journal",
            "outcome": "BLOCKED",
            "parentViolationId": None,
            "recoveryAttempts": 1,
            "resolutionMs": None
        }
        with open(perm_path, "a", encoding="utf-8") as pf:
            pf.write(json.dumps(crash_event) + "\n")

        # Live file still has lastAuditSeq == 1 (lagging behind journal)
        with open(live_path, "r", encoding="utf-8") as lf:
            live_before = json.load(lf)
        self.assertEqual(live_before["lastAuditSeq"], 1)

        # 3. Next tool action: approved edit for target.
        # Should detect live (seq 1) < journal (seq 2), replay event 2 into live state,
        # restore the active violation on target, and resolve it as RECOVERED!
        rec_id = log_event("write", "APPROVED", target, "clean recovery after crash", rule_id="PASS", conversation_id=conv)

        with open(live_path, "r", encoding="utf-8") as lf:
            live_after = json.load(lf)

        # Live state caught up to seq 3
        self.assertEqual(live_after["lastAuditSeq"], 3)
        # Event 3 is RECOVERED because the missing block (seq 2) was replayed into activeViolations!
        latest_event = live_after["events"][0]
        self.assertEqual(latest_event["eventId"], rec_id)
        self.assertEqual(latest_event["outcome"], "RECOVERED")
        self.assertEqual(latest_event["parentViolationId"], "evt_crash_sim_999")
        self.assertEqual(live_after["effectiveness"]["totalRecovered"], 1)

    def test_multi_rule_recovery_assigns_monotonic_seq_to_extra_events(self):
        target = "src/multi_seq.py"
        conv = "conv-multi-seq"

        # 1. Trigger two blocks with different rules
        log_event("write", "BLOCKED", target, "violation G1", rule_id="G1_SILENT_EXCEPTION", conversation_id=conv)
        log_event("write", "BLOCKED", target, "violation G2", rule_id="G2_TEST_INTEGRITY", conversation_id=conv)

        # 2. Approved edit resolves both
        log_event("write", "APPROVED", target, "resolved both", rule_id="PASS", conversation_id=conv)

        perm_path = os.path.join(self.test_dir, "gravityguard_permanent_audit.jsonl")
        perm_events = []
        with open(perm_path, "r", encoding="utf-8") as pf:
            for line in pf:
                perm_events.append(json.loads(line))

        # 4 events total: Block G1 (1), Block G2 (2), Recover G1 (3), Recover G2 (4)
        self.assertEqual(len(perm_events), 4)
        seqs = [e["auditSeq"] for e in perm_events]
        self.assertEqual(seqs, [1, 2, 3, 4])

        live_path = os.path.join(self.test_dir, "srp_guardian_live.json")
        with open(live_path, "r", encoding="utf-8") as lf:
            live = json.load(lf)
        self.assertEqual(live["lastAuditSeq"], 4)

    def test_durability_mode_fsync_handling(self):
        from unittest.mock import patch
        old_durability = os.environ.get("GRAVITYGUARD_DURABILITY")
        os.environ["GRAVITYGUARD_DURABILITY"] = "durable"
        try:
            with patch("os.fsync") as mock_fsync:
                log_event("write", "APPROVED", "src/fsync_test.py", "fsync test", rule_id="PASS")
                # os.fsync should have been called for both the permanent log and the tmp live file
                self.assertGreaterEqual(mock_fsync.call_count, 2)
        finally:
            if old_durability is not None:
                os.environ["GRAVITYGUARD_DURABILITY"] = old_durability
            else:
                os.environ.pop("GRAVITYGUARD_DURABILITY", None)

    def test_torn_journal_tail_repair_and_append(self):
        import io
        from unittest.mock import patch

        # 1. Produce 2 valid events (seq 1, seq 2)
        log_event("write", "APPROVED", "src/valid1.py", "clean 1", rule_id="PASS")
        log_event("write", "APPROVED", "src/valid2.py", "clean 2", rule_id="PASS")

        perm_path = os.path.join(self.test_dir, "gravityguard_permanent_audit.jsonl")
        # 2. Simulate torn/partial write caused by mid-write process kill or power cut
        # Append half-written JSON without newline
        with open(perm_path, "ab") as pf:
            pf.write(b'{"auditSeq": 3, "broken_half_written":')

        # 3. Next log_event should detect torn tail, truncate to last valid newline, and proceed
        stderr_buf = io.StringIO()
        with patch("sys.stderr", stderr_buf):
            id3 = log_event("write", "APPROVED", "src/repaired.py", "clean 3", rule_id="PASS")

        self.assertIn("[GravityGuard WAL Repair]", stderr_buf.getvalue())

        # 4. Verify all lines in permanent log parse as valid JSON and seq 3 is cleanly recorded
        perm_events = []
        with open(perm_path, "r", encoding="utf-8") as pf:
            for line in pf:
                line = line.strip()
                if line:
                    perm_events.append(json.loads(line))

        self.assertEqual(len(perm_events), 3)
        self.assertEqual(perm_events[0]["auditSeq"], 1)
        self.assertEqual(perm_events[1]["auditSeq"], 2)
        self.assertEqual(perm_events[2]["auditSeq"], 3)
        self.assertEqual(perm_events[2]["eventId"], id3)

        live_path = os.path.join(self.test_dir, "srp_guardian_live.json")
        with open(live_path, "r", encoding="utf-8") as lf:
            live = json.load(lf)
        self.assertEqual(live["lastAuditSeq"], 3)

    def test_projection_ahead_of_journal_triggers_reconciliation(self):
        import io
        from unittest.mock import patch

        # 1. Produce 2 valid events
        log_event("write", "BLOCKED", "src/file1.py", "block 1", rule_id="G1_SILENT_EXCEPTION")
        log_event("write", "APPROVED", "src/file1.py", "clean 1", rule_id="PASS")

        live_path = os.path.join(self.test_dir, "srp_guardian_live.json")
        with open(live_path, "r", encoding="utf-8") as lf:
            live = json.load(lf)

        # 2. Corrupt live state by artificially pushing lastAuditSeq ahead of journal
        live["lastAuditSeq"] = 99
        live["effectiveness"]["totalBlocked"] = 999
        with open(live_path, "w", encoding="utf-8") as lf:
            json.dump(live, lf)

        # 3. Next event should detect live > journal, warn, and reconcile from canonical journal
        stderr_buf = io.StringIO()
        with patch("sys.stderr", stderr_buf):
            log_event("write", "APPROVED", "src/file2.py", "clean 2", rule_id="PASS")

        self.assertIn("[GravityGuard Projection Ahead Of Journal]", stderr_buf.getvalue())

        with open(live_path, "r", encoding="utf-8") as lf:
            live_reconciled = json.load(lf)

        # Bogus totalBlocked=999 was discarded; true history (1 block from file1) + current event
        self.assertEqual(live_reconciled["effectiveness"]["totalBlocked"], 1)
        self.assertEqual(live_reconciled["lastAuditSeq"], 3)

    def test_valid_journal_tail_without_newline_is_preserved(self):
        # 1. Produce 2 valid events (seq 1, seq 2)
        log_event("write", "APPROVED", "src/v1.py", "clean 1", rule_id="PASS")
        log_event("write", "APPROVED", "src/v2.py", "clean 2", rule_id="PASS")

        perm_path = os.path.join(self.test_dir, "gravityguard_permanent_audit.jsonl")
        # 2. Strip final newline character (simulating crash right after writing JSON but before \n delimiter)
        with open(perm_path, "rb+") as f:
            data = f.read()
            self.assertTrue(data.endswith(b"\n"))
            f.seek(0)
            f.write(data[:-1])
            f.truncate()

        # Check that file currently does not end with newline
        with open(perm_path, "rb") as f:
            self.assertFalse(f.read().endswith(b"\n"))

        # 3. Next log_event should detect that the JSON is valid, restore the missing newline delimiter, and append seq 3
        log_event("write", "APPROVED", "src/v3.py", "clean 3", rule_id="PASS")

        # 4. Assert seq 1, 2, 3 are ALL preserved
        perm_events = []
        with open(perm_path, "r", encoding="utf-8") as pf:
            for line in pf:
                line = line.strip()
                if line:
                    perm_events.append(json.loads(line))

        self.assertEqual([e["auditSeq"] for e in perm_events], [1, 2, 3])

        live_path = os.path.join(self.test_dir, "srp_guardian_live.json")
        with open(live_path, "r", encoding="utf-8") as lf:
            live = json.load(lf)
        self.assertEqual(live["lastAuditSeq"], 3)

    def test_uninitialized_or_cleared_live_state_triggers_rebuild_from_journal(self):
        import io
        from unittest.mock import patch

        # 1. Produce a BLOCKED event (seq 1, creates active violation)
        target = "src/cleared_test.py"
        log_event("write", "BLOCKED", target, "silent pass block", rule_id="G1_SILENT_EXCEPTION")

        live_path = os.path.join(self.test_dir, "srp_guardian_live.json")
        with open(live_path, "r", encoding="utf-8") as lf:
            live = json.load(lf)
        expected_key = f"test-conv-1::{target}::G1_SILENT_EXCEPTION"
        self.assertIn(expected_key, live["activeViolations"])
        self.assertEqual(live["lastAuditSeq"], 1)

        # 2. Simulate legacy clearLogs() or external wipe:
        # Overwrite live JSON with empty dict lacking lastAuditSeq and activeViolations
        with open(live_path, "w", encoding="utf-8") as lf:
            json.dump({
                "activeGuard": "GravityGuard",
                "status": "ONLINE",
                "events": []
            }, lf)

        # 3. Next event should detect missing lastAuditSeq with non-empty journal,
        # warn, and trigger full rebuild from canonical permanent log
        stderr_buf = io.StringIO()
        with patch("sys.stderr", stderr_buf):
            log_event("write", "APPROVED", "src/other.py", "clean write", rule_id="PASS")

        self.assertIn("[GravityGuard Uninitialized Projection]", stderr_buf.getvalue())

        with open(live_path, "r", encoding="utf-8") as lf:
            live_rebuilt = json.load(lf)

        # Sequence must be 2, and previously active G1 violation must be cleanly restored!
        self.assertEqual(live_rebuilt["lastAuditSeq"], 2)
        self.assertIn(expected_key, live_rebuilt["activeViolations"])
        self.assertEqual(live_rebuilt["effectiveness"]["totalBlocked"], 1)

    def test_centralized_secret_redaction_formats(self):
        """Verifies redaction of all major API keys, tokens, URIs, and private keys."""
        # OpenAI key
        fake_sk = "sk-" + "123456789012345678901234567890"
        t1 = f"Key is {fake_sk} in config"
        self.assertEqual(redact_secrets(t1), "Key is sk-***[REDACTED]*** in config")

        # Anthropic key
        fake_ant = "sk-ant-" + "api03-abcdef12345678901234567890"
        t2 = f"Found {fake_ant} in header"
        self.assertEqual(redact_secrets(t2), "Found sk-ant-***[REDACTED]*** in header")

        # GitHub token
        fake_gh = "ghp_" + "123456789012345678901234567890"
        t3 = f"Auth token: {fake_gh}"
        self.assertEqual(redact_secrets(t3), "Auth token: ghp_***[REDACTED]***")

        # AWS Access Key
        fake_aws = "AKIA" + "1234567890ABCDEF"
        t4 = f"AWS key {fake_aws} detected"
        self.assertEqual(redact_secrets(t4), "AWS key AKIA***[REDACTED]*** detected")

        # Bearer token
        t5 = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz123"
        self.assertIn("Bearer ***[REDACTED]***", redact_secrets(t5))

        # URI basic auth
        t6 = "Connect to postgres://myuser:super_secret_pw@localhost:5432/mydb"
        self.assertEqual(redact_secrets(t6), "Connect to postgres://myuser:***@localhost:5432/mydb")

        # Generic key-value secret
        t7 = "api_key='secret_key_12345678'"
        self.assertIn("api_key='***[REDACTED]***", redact_secrets(t7))

        # Private key block
        t8 = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
        self.assertEqual(redact_secrets(t8), "[REDACTED_PRIVATE_KEY]")

        # Nested record redaction
        rec = {
            "reason": fake_sk,
            "metadata": [fake_gh, {"uri": "https://admin:pass123@api.com"}],
            "count": 42
        }
        scrubbed = redact_record(rec)
        self.assertEqual(scrubbed["reason"], "sk-***[REDACTED]***")
        self.assertEqual(scrubbed["metadata"][0], "ghp_***[REDACTED]***")
        self.assertEqual(scrubbed["metadata"][1]["uri"], "https://admin:***@api.com")
        self.assertEqual(scrubbed["count"], 42)

    def test_log_event_redacts_secrets_in_live_and_permanent_logs(self):
        """Ensures secrets passed in reason, target, or metadata never leak into disk files."""
        target = "src/secret_test.py"
        fake_sk = "sk-" + "123456789012345678901234567890"
        secret_reason = f"Found OpenAI key {fake_sk} in source"
        eid = log_event("write", "BLOCKED", target, secret_reason, rule_id="G0_SECRET_LEAK")

        # 1. Check live projection
        live_path = os.path.join(self.test_dir, "srp_guardian_live.json")
        with open(live_path, "r", encoding="utf-8") as lf:
            live = json.load(lf)
        live_event = live["events"][0]
        self.assertNotIn(fake_sk, live_event["reason"])
        self.assertIn("sk-***[REDACTED]***", live_event["reason"])

        # 2. Check permanent JSONL log
        perm_path = os.path.join(self.test_dir, "gravityguard_permanent_audit.jsonl")
        with open(perm_path, "r", encoding="utf-8") as pf:
            content = pf.read()
        self.assertNotIn(fake_sk, content)
        self.assertIn("sk-***[REDACTED]***", content)

    def test_lock_timeout_buffers_to_fallback_spool_and_drains_seamlessly(self):
        """Verifies zero-drop audit guarantee: events buffered during lock timeouts are fully recovered."""
        from unittest.mock import patch
        from gravityguard_engine.state_lock import StateLock
        target = "src/spool_test.py"

        # 1. Simulate lock contention timeout
        with patch.object(StateLock, "acquire", return_value=False):
            spool_eid = log_event("write", "BLOCKED", target, "spooled lock timeout event", rule_id="G1_SILENT_EXCEPTION")
            self.assertTrue(spool_eid.startswith("evt_"))

        # Spool file should contain the buffered event
        spool_path = os.path.join(self.test_dir, "gravityguard_audit_fallback.jsonl")
        self.assertTrue(os.path.exists(spool_path))
        with open(spool_path, "r", encoding="utf-8") as sf:
            spooled_lines = [json.loads(l) for l in sf if l.strip()]
        self.assertEqual(len(spooled_lines), 1)
        self.assertEqual(spooled_lines[0]["eventId"], spool_eid)

        # 2. On next regular event with lock acquired, the spool must be drained into permanent journal
        next_eid = log_event("write", "APPROVED", target, "subsequent normal write", rule_id="PASS")

        # Fallback spool should now be empty or removed
        if os.path.exists(spool_path):
            with open(spool_path, "r", encoding="utf-8") as sf:
                self.assertEqual(sf.read().strip(), "")

        # Permanent journal must contain BOTH the spooled event and the new event
        perm_path = os.path.join(self.test_dir, "gravityguard_permanent_audit.jsonl")
        with open(perm_path, "r", encoding="utf-8") as pf:
            perm_events = [json.loads(l) for l in pf if l.strip()]

        eids = [e["eventId"] for e in perm_events]
        self.assertIn(spool_eid, eids)
        self.assertIn(next_eid, eids)
        self.assertEqual(perm_events[-2]["auditSeq"], 1)
        self.assertEqual(perm_events[-1]["auditSeq"], 2)


if __name__ == "__main__":
    unittest.main()
