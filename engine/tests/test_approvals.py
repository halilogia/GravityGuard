import json
import os
import tempfile
import unittest
from pathlib import Path

from gravityguard_engine import approvals as apr
from gravityguard_engine.hook_output import finalize
from gravityguard_engine.policy_integrity import is_runtime_control_file
from gravityguard_engine.shell_rules import check_shell_command

RULE = "ARCH_RATCHET_GROWTH_DENY"
DENY = json.dumps({"decision": "deny", "reason": f"[{RULE}]: too big"})
ACTION = {"tool": "Edit", "target": "a.py",
          "args": {"TargetFile": "a.py", "old_string": "x = 1", "new_string": "x = 2"}}


def decide(action=ACTION) -> dict:
    return json.loads(finalize(DENY, False, "c1", action))


class ApprovalTicketTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["GRAVITYGUARD_APPROVAL_DIR"] = os.path.join(self.tmp.name, "approvals")
        os.environ["GRAVITYGUARD_PAUSE_FILE"] = os.path.join(self.tmp.name, "pause.json")
        self.addCleanup(os.environ.pop, "GRAVITYGUARD_APPROVAL_DIR", None)
        self.addCleanup(os.environ.pop, "GRAVITYGUARD_PAUSE_FILE", None)
        self.addCleanup(self.tmp.cleanup)

    def test_key_is_content_sensitive(self):
        other = {**ACTION, "args": {**ACTION["args"], "new_string": "x = 3"}}
        self.assertEqual(apr.action_key(RULE, ACTION), apr.action_key(RULE, ACTION))
        self.assertNotEqual(apr.action_key(RULE, ACTION), apr.action_key(RULE, other))
        self.assertNotEqual(apr.action_key(RULE, ACTION), apr.action_key("G7_TS_FIRST", ACTION))

    def test_denial_offers_a_ticket(self):
        out = decide()
        self.assertEqual(out["decision"], "deny")
        key = apr.action_key(RULE, ACTION)
        self.assertIn(f"id {key}", out["reason"])
        self.assertIn("Bir kez izin ver", out["reason"])
        self.assertEqual([t["id"] for t in apr.list_pending()], [key])

    def test_approval_lifts_exactly_one_call(self):
        decide()
        key = apr.action_key(RULE, ACTION)
        apr.approve(key, actor="test")
        approved = decide()
        self.assertEqual(approved["decision"], "allow")
        self.assertIn("GG_APPROVED", approved["reason"])
        self.assertIn(RULE, approved["reason"])  # the rule that would have blocked it stays visible
        self.assertEqual(decide()["decision"], "deny")  # a one-shot ticket is spent

    def test_approval_does_not_cover_a_different_change(self):
        decide()
        apr.approve(apr.action_key(RULE, ACTION), actor="test")
        other = {**ACTION, "args": {**ACTION["args"], "new_string": "x = 999"}}
        self.assertEqual(decide(other)["decision"], "deny")

    def test_approval_expires(self):
        ticket = apr.record_block(RULE, "x", ACTION, ttl_minutes=1)
        receipt = apr.approve(ticket["id"], actor="test", minutes=1)
        self.assertIsNotNone(apr.approved(ticket["id"], now=receipt["expires_at"] - 1))
        self.assertIsNone(apr.approved(ticket["id"], now=receipt["expires_at"] + 1))
        expired = {**receipt, "expires_at": 1.0}  # the ticket's own clock, as the guard reads it
        apr._write(apr.receipt_path(ticket["id"]), expired)
        self.assertEqual(decide()["decision"], "deny")

    def test_denial_keeps_the_block(self):
        decide()
        key = apr.action_key(RULE, ACTION)
        apr.reject(key, "no", actor="test")
        self.assertEqual(decide()["decision"], "deny")
        self.assertEqual(apr.list_pending(), [])

    def test_revoke_withdraws_a_live_approval(self):
        decide()
        key = apr.action_key(RULE, ACTION)
        apr.approve(key, actor="test")
        apr.revoke(key, actor="test")
        self.assertEqual(decide()["decision"], "deny")

    def test_allow_and_stop_outputs_are_untouched(self):
        allow = json.dumps({"decision": "allow"})
        self.assertEqual(finalize(allow, False, "c1", ACTION), allow)
        stop = json.dumps({"decision": "continue", "reason": "[FINAL_SECURITY_SCAN]: leak"})
        self.assertEqual(finalize(stop, True, "c1", ACTION), stop)

    def test_engine_failure_is_not_approvable(self):
        broken = json.dumps({"decision": "deny", "reason": "[GUARD_UNAVAILABLE]: x"})
        self.assertEqual(finalize(broken, False, "c1", ACTION), broken)

    def test_agent_cannot_approve_itself(self):
        for command in ("python gravityguard_cli.py approvals allow 0123456789abcdef",
                        "gravityguard approvals allow abc123",
                        "python engine/approval_control.py",
                        "echo {} > ~/.gravityguard/approvals/receipts/abc.json"):
            self.assertIn("POLICY_INTEGRITY", check_shell_command({"command": command}), command)

    def test_receipt_store_is_not_agent_writable(self):
        receipt = Path.home() / ".gravityguard" / "approvals" / "receipts" / "k.json"
        self.assertTrue(is_runtime_control_file(str(receipt)))


if __name__ == "__main__":
    unittest.main()
