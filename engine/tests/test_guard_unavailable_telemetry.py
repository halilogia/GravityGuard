#!/usr/bin/env python3
"""An engine crash must stay visible in telemetry: error log with call identity + a GUARD_UNAVAILABLE audit event."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine import dispatcher


class GuardUnavailableTelemetry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gg_crash_")
        self.cwd = os.getcwd()
        os.chdir(self.tmp)
        self.env = mock.patch.dict(os.environ, {
            "GRAVITYGUARD_LOG_DIR": os.path.join(self.tmp, "audit"),
            "USERPROFILE": self.tmp,
            "HOME": self.tmp,
            "GRAVITYGUARD_LKG_ACTIVE": "1",  # no last-known-good fallback: this suite checks the fail-closed path itself
        })
        self.env.start()
        dispatcher._CRASH_CONTEXT.clear()

    def tearDown(self):
        self.env.stop()
        os.chdir(self.cwd)
        dispatcher._CRASH_CONTEXT.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def crash(self, payload):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
                mock.patch.object(dispatcher, "check_shell_command", side_effect=NameError("name '_X' is not defined")), \
                redirect_stdout(out), redirect_stderr(err):
            dispatcher.run_cli()
        return json.loads(out.getvalue().strip().splitlines()[-1])

    def audit_events(self):
        path = Path(self.tmp, "audit", "gravityguard_permanent_audit.jsonl")
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_crash_is_audited_and_fails_closed(self):
        decision = self.crash({"toolCall": {"name": "run_command", "args": {"command": "echo hi"}}, "conversationId": "c-test"})
        self.assertEqual(decision["decision"], "deny")
        self.assertIn("GUARD_UNAVAILABLE", decision["reason"])
        events = [e for e in self.audit_events() if e.get("ruleId") == "GUARD_UNAVAILABLE"]
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["status"], "BLOCKED")
        self.assertEqual(events[0]["action"], "run_command")
        self.assertIn("NameError", events[0]["reason"])
        self.assertIn("c-test", events[0]["conversationId"])

    def test_error_log_names_the_denied_call(self):
        self.crash({"toolCall": {"name": "run_command", "args": {"command": "echo hi"}}, "conversationId": "c-test"})
        log = Path(self.tmp, ".gravityguard", "runtime", "gravityguard_errors.log").read_text(encoding="utf-8")
        self.assertIn("hook_event=pre-tool", log)
        self.assertIn("tool='run_command'", log)
        self.assertIn("conversation='c-test'", log)
        self.assertIn("NameError", log)

    def test_payload_arguments_never_reach_the_logs(self):
        self.crash({"toolCall": {"name": "run_command", "args": {"command": "echo TOP-SECRET-ARGUMENT"}}, "conversationId": "c-test"})
        blob = Path(self.tmp, ".gravityguard", "runtime", "gravityguard_errors.log").read_text(encoding="utf-8")
        blob += Path(self.tmp, "audit", "gravityguard_permanent_audit.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("TOP-SECRET-ARGUMENT", blob)

    def test_telemetry_failure_does_not_break_the_denial(self):
        with mock.patch.object(dispatcher, "log_event", side_effect=OSError("disk full")):
            decision = self.crash({"toolCall": {"name": "run_command", "args": {"command": "x"}}, "conversationId": "c"})
        self.assertEqual(decision["decision"], "deny")


if __name__ == "__main__":
    unittest.main()
