import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
"""Maintenance preserves audit causality, sequence and recoverability."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gravityguard_engine.audit import log_event, _get_journal_last_seq
from gravityguard_engine.audit_maintenance import maintain_audit, _atomic_json
from tools.telemetry_dashboard import LogStreamReader


class AuditMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.logs = self.root / "logs"
        self.archives = self.root / "private"
        env = patch.dict(os.environ, {"GRAVITYGUARD_LOG_DIR": str(self.logs)})
        env.start()
        self.addCleanup(env.stop)

    def test_clear_preserves_counters_pending_causality_and_monotonic_sequence(self):
        log_event("write", "BLOCKED", "src/a.py", "silent exception", rule_id="G1_SILENT_EXCEPTION")
        log_event("read", "BLOCKED", ".env", "protected", rule_id="G0_ENV_PROTECTION")
        result = maintain_audit(self.logs, self.archives)
        live = json.loads((self.logs / "srp_guardian_live.json").read_text())
        self.assertEqual(live["events"], [])
        self.assertEqual(live["effectiveness"]["totalBlocked"], 2)
        self.assertEqual(len(live["activeViolations"]), 2)
        (self.logs / "srp_guardian_live.json").unlink()
        log_event("edit", "APPROVED", "src/a.py", "fixed", rule_id="PASS")
        live = json.loads((self.logs / "srp_guardian_live.json").read_text())
        self.assertGreater(live["lastAuditSeq"], result["highWaterSeq"])
        self.assertEqual(live["events"][0]["outcome"], "RECOVERED")
        self.assertEqual(live["effectiveness"]["totalRecovered"], 1)
        self.assertEqual(live["effectiveness"]["codeFixRate"], 100)
        self.assertEqual(live["effectiveness"]["recoveryRate"], 50)
        records = list(LogStreamReader([self.logs / "gravityguard_permanent_audit.jsonl"]).stream_events())
        self.assertTrue(records)
        self.assertFalse(any(e.get("recordType") == "audit_checkpoint" for e in records))

    def test_crash_after_checkpoint_recovers_without_resurfacing_old_events(self):
        previous = log_event("read", "APPROVED", "README.md", "read", rule_id="READ_ALLOW")
        def crash(path, value, jsonl=False):
            if path.name == "srp_guardian_live.json":
                raise OSError("simulated interruption")
            return _atomic_json(path, value, jsonl)
        with patch("gravityguard_engine.audit_maintenance._atomic_json", side_effect=crash):
            with self.assertRaises(OSError):
                maintain_audit(self.logs, self.archives)
        log_event("write", "APPROVED", "src/a.py", "safe", rule_id="PASS")
        live = json.loads((self.logs / "srp_guardian_live.json").read_text())
        self.assertFalse(any(e.get("eventId") == previous for e in live["events"]))
        self.assertEqual(live["lastAuditSeq"], 2)

    def test_large_checkpoint_retains_high_water_for_the_next_writer(self):
        for index in range(3):
            log_event("read", "APPROVED", f"src/{index}.py", "read", rule_id="READ_ALLOW")
        log_event("write", "BLOCKED", "src/" + "a" * 9000, "blocked", rule_id="G1_SILENT_EXCEPTION")
        result = maintain_audit(self.logs, self.archives)
        journal = self.logs / "gravityguard_permanent_audit.jsonl"
        self.assertGreater(journal.stat().st_size, 8192)
        self.assertEqual(_get_journal_last_seq(str(journal)), result["highWaterSeq"])
        log_event("read", "APPROVED", "README.md", "read", rule_id="READ_ALLOW")
        live = json.loads((self.logs / "srp_guardian_live.json").read_text())
        self.assertEqual(live["lastAuditSeq"], result["highWaterSeq"] + 1)
        self.assertEqual(live["effectiveness"]["totalBlocked"], 1)

    def test_corrupt_journal_is_not_truncated(self):
        self.logs.mkdir()
        file = self.logs / "gravityguard_permanent_audit.jsonl"
        file.write_text('{"unfinished":', encoding="utf-8")
        before = file.read_bytes()
        with self.assertRaises(ValueError):
            maintain_audit(self.logs, self.archives)
        self.assertEqual(file.read_bytes(), before)
