#!/usr/bin/env python3
"""
Unit tests for GravityGuard Telemetry & Audit Reliability:
1. Synthetic JSON / JWT secret redaction.
2. Two-phase fallback spool recovery and crash idempotency.
3. Streaming metrics aggregation with bounded O(1) memory.
4. Non-destructive log rotation under StateLock.
"""
from collections import Counter
from datetime import datetime, timezone
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)
_ROOT_DIR = os.path.dirname(_ENGINE_DIR)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from gravityguard_engine.audit import (
    log_event,
    redact_secrets,
    redact_record,
    _prepare_fallback_spool,
    _commit_fallback_spool,
)
from gravityguard_engine.state_lock import StateLock
from tools.telemetry_dashboard import (
    AggregatedMetrics,
    LogStreamReader,
    parse_iso_datetime,
    perform_log_rotation,
)


class TestAuditReliability(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="gg_test_reliability_")
        self.old_log_dir = os.environ.get("GRAVITYGUARD_LOG_DIR")
        os.environ["GRAVITYGUARD_LOG_DIR"] = self.test_dir
        os.environ["ANTIGRAVITY_CONVERSATION_ID"] = "test-conv-rel"

    def tearDown(self):
        if self.old_log_dir is not None:
            os.environ["GRAVITYGUARD_LOG_DIR"] = self.old_log_dir
        else:
            os.environ.pop("GRAVITYGUARD_LOG_DIR", None)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_synthetic_json_and_jwt_secret_redaction(self):
        """Verifies redaction of synthetic JSON key-values, single quotes, and JWT tokens."""
        # 1. JSON quoted string with key-value
        synth_key = "example-synthetic-credential-12345"
        json_str = f'{{"api_key": "{synth_key}"}}'
        redacted_json = redact_secrets(json_str)
        self.assertNotIn(synth_key, redacted_json)
        self.assertIn('"api_key": "***[REDACTED]***"', redacted_json)

        # 2. Single quoted string with key-value
        single_quote_str = f"'secret_key': '{synth_key}'"
        redacted_sq = redact_secrets(single_quote_str)
        self.assertNotIn(synth_key, redacted_sq)
        self.assertIn("'secret_key': '***[REDACTED]***'", redacted_sq)

        # 3. JWT token
        jwt_token = "eyJ" + "hbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0." + "doNotLeakThisSignature123"
        raw_jwt_text = f"Bearer {jwt_token} auth header"
        redacted_jwt = redact_secrets(raw_jwt_text)
        self.assertNotIn("doNotLeakThisSignature123", redacted_jwt)
        self.assertIn("[REDACTED_JWT]", redacted_jwt)

        # 4. Structural dictionary redaction
        dict_payload = {
            "api_key": synth_key,
            "secret": synth_key,
            "normal_field": "safe_value",
            "nested": {
                "password": "super_secret_password_987"
            }
        }
        scrubbed = redact_record(dict_payload)
        self.assertEqual(scrubbed["api_key"], "[REDACTED_CREDENTIAL]")
        self.assertEqual(scrubbed["secret"], "[REDACTED_CREDENTIAL]")
        self.assertEqual(scrubbed["normal_field"], "safe_value")
        self.assertEqual(scrubbed["nested"]["password"], "[REDACTED_CREDENTIAL]")

    def test_log_event_scrubs_synthetic_credentials_before_writing(self):
        """Verifies that secrets passed in reason or target are sanitized in disk logs."""
        target = "src/auth_service.py"
        synth_secret = "synthetic-secret-xyz-9999"
        payload_reason = f'Blocked token leak: {{"access_token": "{synth_secret}"}}'

        eid = log_event("write", "BLOCKED", target, payload_reason, rule_id="G0_SECRET_LEAK")
        self.assertTrue(eid.startswith("evt_"))

        # Verify disk journal
        perm_path = os.path.join(self.test_dir, "gravityguard_permanent_audit.jsonl")
        with open(perm_path, "r", encoding="utf-8") as f:
            disk_content = f.read()

        self.assertNotIn(synth_secret, disk_content)
        parsed_rec = json.loads(disk_content.strip())
        self.assertIn('"access_token": "***[REDACTED]***"', parsed_rec["reason"])

    def test_two_phase_spool_recovery_and_crash_replay(self):
        """Simulates an orphaned .processing file from a process crash and ensures clean recovery."""
        # Create an orphaned .processing file
        orphaned_file = os.path.join(self.test_dir, "gravityguard_audit_fallback.processing.9999_deadbeef")
        spooled_record = {
            "auditSeq": -1,
            "eventId": "evt_orphaned_spool_1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "write",
            "status": "BLOCKED",
            "ruleId": "G1_SILENT_EXCEPTION",
            "resolvedRuleId": None,
            "target": "src/recovered_file.py",
            "project": "TestProject",
            "projectRoot": self.test_dir,
            "fileExt": ".py",
            "conversationId": "test-conv-rel",
            "model": "test-model",
            "reason": "orphaned lock timeout recovery test",
            "outcome": "BLOCKED",
            "parentViolationId": None,
            "recoveryAttempts": 1,
            "resolutionMs": None
        }
        with open(orphaned_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(spooled_record) + "\n")

        # Next normal log_event() should discover, replay, and clean up the orphan
        next_eid = log_event("write", "APPROVED", "src/normal.py", "normal write", rule_id="PASS")
        self.assertTrue(next_eid.startswith("evt_"))

        # Orphaned file must have been committed and removed
        self.assertFalse(os.path.exists(orphaned_file))

        # Permanent journal must contain the recovered event followed by the new event
        perm_path = os.path.join(self.test_dir, "gravityguard_permanent_audit.jsonl")
        with open(perm_path, "r", encoding="utf-8") as f:
            records = [json.loads(l) for l in f if l.strip()]

        eids = [r["eventId"] for r in records]
        self.assertIn("evt_orphaned_spool_1", eids)
        self.assertIn(next_eid, eids)

        # Sequence numbers must be strictly sequential
        rec_orphaned = next(r for r in records if r["eventId"] == "evt_orphaned_spool_1")
        rec_next = next(r for r in records if r["eventId"] == "evt_next" or r["eventId"] == next_eid)
        self.assertEqual(rec_orphaned["auditSeq"], 1)
        self.assertEqual(rec_next["auditSeq"], 2)

        # Live state must reflect the spooled event's causal statistics
        live_path = os.path.join(self.test_dir, "srp_guardian_live.json")
        with open(live_path, "r", encoding="utf-8") as f:
            live = json.load(f)
        self.assertEqual(live["effectiveness"]["totalBlocked"], 1)
        self.assertEqual(live["lastAuditSeq"], 2)

    def test_streaming_metrics_aggregator_zero_list_buffering(self):
        """Verifies AggregatedMetrics streams events without keeping an .events list."""
        sample_stream = [
            {
                "eventId": "e1",
                "timestamp": "2026-10-10T10:00:00+00:00",
                "status": "BLOCKED",
                "ruleId": "G1_SILENT_EXCEPTION",
                "target": "src/core.py",
                "project": "ProjA",
                "fileExt": ".py",
                "outcome": "BLOCKED"
            },
            {
                "eventId": "e2",
                "timestamp": "2026-10-10T10:01:00+00:00",
                "status": "APPROVED",
                "ruleId": "PASS",
                "resolvedRuleId": "G1_SILENT_EXCEPTION",
                "target": "src/core.py",
                "project": "ProjA",
                "fileExt": ".py",
                "outcome": "RECOVERED",
                "recoveryAttempts": 2,
                "resolutionMs": 1500.0
            },
            {
                "eventId": "e3",
                "timestamp": "2026-10-10T10:02:00+00:00",
                "status": "WARNING",
                "ruleId": "ARCH_FILE_GROWTH",
                "target": "src/big.ts",
                "project": "ProjA",
                "fileExt": ".ts",
                "outcome": "WARNING"
            }
        ]

        def event_generator():
            for item in sample_stream:
                yield item

        metrics = AggregatedMetrics(event_generator(), label="TestPeriod")

        # Must not store all events in memory
        self.assertFalse(hasattr(metrics, "events"))
        self.assertEqual(metrics.total, 3)
        self.assertEqual(metrics.total_blocked, 1)
        self.assertEqual(metrics.total_recovered, 1)
        self.assertEqual(metrics.total_warning, 1)
        self.assertEqual(metrics.recovery_rate, 100.0)
        self.assertEqual(metrics.median_attempts, 2.0)
        self.assertEqual(metrics.avg_duration_s, 1.5)
        self.assertEqual(len(metrics.recent_interventions), 2)  # BLOCKED and WARNING

    def test_log_rotation_is_non_destructive_under_statelock(self):
        """Verifies that perform_log_rotation snapshots without wiping the active journal."""
        perm_path = os.path.join(self.test_dir, "gravityguard_permanent_audit.jsonl")
        with open(perm_path, "w", encoding="utf-8") as f:
            for i in range(10):
                f.write(json.dumps({"auditSeq": i + 1, "eventId": f"evt_{i}"}) + "\n")

        initial_size = os.path.getsize(perm_path)
        self.assertGreater(initial_size, 0)

        # Run rotation with low threshold so it triggers
        perform_log_rotation(threshold_mb=0.00001)

        # Active log must NOT have been wiped to 0 bytes
        self.assertTrue(os.path.exists(perm_path))
        self.assertEqual(os.path.getsize(perm_path), initial_size)

        # Archive directory should have the snapshot
        repo_archive_dir = os.path.join(_ROOT_DIR, "archives", "audit-logs")
        self.assertTrue(os.path.isdir(repo_archive_dir))
        archives = [f for f in os.listdir(repo_archive_dir) if f.startswith("gravityguard_permanent_audit_")]
        self.assertGreater(len(archives), 0)


if __name__ == "__main__":
    unittest.main()
