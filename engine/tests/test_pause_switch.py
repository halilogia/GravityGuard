import json
import os
import tempfile
import unittest
from pathlib import Path

from gravityguard_engine import pause_switch as ps
from gravityguard_engine.hook_output import finalize
from gravityguard_engine.policy_integrity import MANDATORY_RULES, is_runtime_control_file
from gravityguard_engine.shell_rules import check_shell_command


class PauseSwitchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.flag = os.path.join(self.tmp.name, ".gravityguard", "pause.json")
        os.environ["GRAVITYGUARD_PAUSE_FILE"] = self.flag
        self.addCleanup(os.environ.pop, "GRAVITYGUARD_PAUSE_FILE", None)
        self.addCleanup(self.tmp.cleanup)

    def test_pause_expires_and_caps_length(self):
        state = ps.pause(10_000, now=1000.0)
        self.assertEqual(state["minutes"], ps.MAX_MINUTES)
        self.assertIsNotNone(ps.status(now=1001.0))
        self.assertIsNone(ps.status(now=1000.0 + ps.MAX_MINUTES * 60 + 1))

    def test_resume_removes_flag(self):
        ps.pause(5)
        self.assertTrue(ps.resume())
        self.assertIsNone(ps.status())
        self.assertFalse(ps.resume())

    def test_relax_keeps_mandatory_rules_denied(self):
        deny = json.dumps({"decision": "deny", "reason": "[ARCH_RATCHET_GROWTH_DENY]: too big"})
        relaxed = json.loads(ps.relax_output(deny, MANDATORY_RULES))
        self.assertEqual(relaxed["decision"], "allow")
        self.assertIn("ARCH_RATCHET_GROWTH_DENY", relaxed["reason"])
        secret = json.dumps({"decision": "deny", "reason": "[G0_SECRET_LEAK]: key"})
        self.assertEqual(ps.relax_output(secret, MANDATORY_RULES), secret)
        stop = json.dumps({"decision": "continue", "reason": "[FINAL_SECURITY_SCAN]: leak"})
        self.assertEqual(ps.relax_output(stop, MANDATORY_RULES), stop)

    def test_finalize_relaxes_only_while_paused(self):
        deny = json.dumps({"decision": "deny", "reason": "[G7_TS_FIRST]: x"})
        self.assertEqual(json.loads(finalize(deny, False, "c"))["decision"], "deny")
        ps.pause(5)
        self.assertEqual(json.loads(finalize(deny, False, "c"))["decision"], "allow")

    def test_agent_cannot_flip_the_switch(self):
        self.assertTrue(is_runtime_control_file(str(Path.home() / ".gravityguard" / "pause.json")))
        for command in ("python gravityguard_cli.py pause off", "echo {} > ~/.gravityguard/pause.json"):
            self.assertIn("POLICY_INTEGRITY", check_shell_command({"command": command}))


class QuarantineLiftTest(unittest.TestCase):
    def test_approved_write_lifts_the_denial(self):
        from gravityguard_engine.session_quarantine import denied_targets, record_denied_target, session_logger

        with tempfile.TemporaryDirectory() as log_dir:
            os.environ["GRAVITYGUARD_LOG_DIR"] = log_dir
            self.addCleanup(os.environ.pop, "GRAVITYGUARD_LOG_DIR", None)
            target = os.path.join(log_dir, "a.py")
            record_denied_target("c1", target, log_dir)
            self.assertTrue(denied_targets("c1", log_dir))
            log = session_logger(lambda *a, **k: None, "Edit", "c1")
            log("APPROVED", target, "ok", rule_id="PASS")
            self.assertEqual(denied_targets("c1", log_dir), [])


if __name__ == "__main__":
    unittest.main()
