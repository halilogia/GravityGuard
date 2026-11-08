import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gravityguard_engine.briefing import brief_first_call, build_briefing
from gravityguard_engine.rule_tips import TIPS, enrich_hook_output, lesson_text


class EnrichTests(unittest.TestCase):
    def test_deny_gets_lesson_and_loses_stop_sign(self):
        out = enrich_hook_output(json.dumps({"decision": "deny", "reason": "\U0001F6D1 [G1_SILENT_EXCEPTION]: 'a.py' - empty except"}) + "\n")
        payload = json.loads(out)
        self.assertTrue(payload["reason"].startswith("[G1_SILENT_EXCEPTION]"))
        self.assertIn("Doğru yol:", payload["reason"])
        self.assertIn("raise", payload["reason"])
        self.assertTrue(out.endswith("\n"))

    def test_allow_and_unknown_rules_are_untouched(self):
        allow = json.dumps({"decision": "allow"})
        self.assertEqual(enrich_hook_output(allow), allow)
        unknown = json.dumps({"decision": "deny", "reason": "[NOT_A_RULE_WE_KNOW]: x"})
        self.assertNotIn("Doğru yol", json.loads(enrich_hook_output(unknown))["reason"])

    def test_non_json_output_passes_through(self):
        self.assertEqual(enrich_hook_output('{"deny" broken'), '{"deny" broken')
        self.assertEqual(enrich_hook_output(""), "")

    def test_lesson_is_not_added_twice(self):
        once = enrich_hook_output(json.dumps({"decision": "deny", "reason": "[G0_SECRET_LEAK]: x"}))
        twice = enrich_hook_output(once)
        self.assertEqual(json.loads(twice)["reason"].count("Doğru yol:"), 1)

    def test_tips_have_no_parenthetical_text(self):
        for rule, (tip, _example) in TIPS.items():
            self.assertNotRegex(tip, r"\([^)]*\)", rule)
        self.assertEqual(lesson_text("NOPE"), "")


class BriefingTests(unittest.TestCase):
    def _journal(self, records):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
            f.write("{torn\n")
        self.addCleanup(os.remove, path)
        return path

    def test_top_rules_for_this_agent_only(self):
        now = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
        ts = (now - timedelta(hours=2)).isoformat()
        old = (now - timedelta(days=30)).isoformat()
        rec = lambda agent, status, rule, t=ts, outcome=None: {"agent": agent, "status": status, "ruleId": rule, "timestamp": t, "outcome": outcome or status}
        path = self._journal(
            [rec("OpenCode", "WARNING", "ARCH_FILE_GROWTH")] * 3
            + [rec("OpenCode", "BLOCKED", "G7_TS_FIRST")] * 2
            + [rec("OpenCode", "WARNING", "G7_TS_MANDATORY_FEEDBACK")] * 9
            + [rec("OpenCode", "BLOCKED", "G1_SILENT_EXCEPTION", outcome="REPEATED_VIOLATION")] * 5
            + [rec("OpenCode", "BLOCKED", "SHELL_SECURITY", t=old)] * 9
            + [rec("Claude Code", "BLOCKED", "G0_SECRET_LEAK")] * 7
            + [rec("OpenCode", "APPROVED", "PASS", outcome="CLEAN")] * 5
        )
        text = build_briefing("OpenCode", journal=path, now=now)
        lines = text.splitlines()
        self.assertIn("son 24 saatte", lines[0])
        self.assertIn("ARCH_FILE_GROWTH, 3 kez", lines[1])
        # G7_TS_FIRST tripped only twice: below the threshold of 3, so it is not worth a line.
        for absent in ("G7_TS_FIRST", "G7_TS_MANDATORY_FEEDBACK", "G1_SILENT_EXCEPTION", "SHELL_SECURITY", "G0_SECRET_LEAK"):
            self.assertNotIn(absent, text)
        self.assertIn("%42, 5/12", text)  # repeats are write attempts too, as in audit_stats
        self.assertNotRegex(text, r"\([^)]*\)")

    def test_nothing_to_say(self):
        self.assertEqual(build_briefing("Codex", journal=self._journal([])), "")

    def test_z_suffix_timestamps_count(self):
        # JS toISOString writes "...Z"; Python 3.10 fromisoformat rejected it and the briefing went silent in CI.
        now = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
        ts = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        path = self._journal([{"agent": "Codex", "status": "BLOCKED", "ruleId": "G1_SILENT_EXCEPTION", "timestamp": ts}] * 3)
        self.assertIn("G1_SILENT_EXCEPTION, 3 kez", build_briefing("Codex", journal=path, now=now))

    def test_below_threshold_or_older_than_24h_says_nothing(self):
        now = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
        recent = (now - timedelta(hours=1)).isoformat()
        stale = (now - timedelta(hours=30)).isoformat()
        rec = lambda t: {"agent": "Codex", "status": "BLOCKED", "ruleId": "G1_SILENT_EXCEPTION", "timestamp": t}
        self.assertEqual(build_briefing("Codex", journal=self._journal([rec(recent)] * 2), now=now), "")
        self.assertEqual(build_briefing("Codex", journal=self._journal([rec(stale)] * 5), now=now), "")


class QuietBriefingTests(unittest.TestCase):
    def test_no_trigger_injects_nothing_and_records_nothing(self):
        log_dir = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"GRAVITYGUARD_LOG_DIR": log_dir}):
            out = '{"decision": "allow", "reason": "note"}\n'
            self.assertEqual(brief_first_call(out, "conv-quiet", log_dir), out)
        journal = os.path.join(log_dir, "gravityguard_permanent_audit.jsonl")
        marks = []
        if os.path.exists(journal):
            with open(journal, encoding="utf-8") as f:
                marks = [r for r in map(json.loads, f) if r.get("ruleId") == "BRIEFING_SENT"]
        self.assertEqual(marks, [])


class FirstCallBriefingTests(unittest.TestCase):
    def setUp(self):
        self.log_dir = tempfile.mkdtemp()
        ts = datetime.now(timezone.utc).isoformat()
        with open(os.path.join(self.log_dir, "gravityguard_permanent_audit.jsonl"), "w", encoding="utf-8") as f:
            for agent in ("Antigravity IDE", "Claude Code") * 3:
                f.write(json.dumps({"agent": agent, "status": "BLOCKED", "ruleId": "G1_SILENT_EXCEPTION", "timestamp": ts}) + "\n")
        env = mock.patch.dict(os.environ, {"GRAVITYGUARD_LOG_DIR": self.log_dir})
        env.start()
        self.addCleanup(env.stop)

    def _marks(self):
        with open(os.path.join(self.log_dir, "gravityguard_permanent_audit.jsonl"), encoding="utf-8") as f:
            return [r for r in map(json.loads, f) if r.get("ruleId") == "BRIEFING_SENT"]

    def test_first_allowed_call_carries_briefing_once(self):
        first = brief_first_call('{"decision": "allow", "reason": "token note"}\n', "conv-1", self.log_dir)
        reason = json.loads(first)["reason"]
        self.assertTrue(reason.startswith("GravityGuard: son 24 saatte"))
        self.assertTrue(reason.endswith("\n\ntoken note"))
        self.assertEqual([m.get("conversationId") for m in self._marks()], ["conv-1"])
        again = '{"decision": "allow"}\n'
        self.assertEqual(brief_first_call(again, "conv-1", self.log_dir), again)

    def test_rejection_does_not_use_up_the_briefing(self):
        deny = '{"decision": "deny", "reason": "x"}\n'
        self.assertEqual(brief_first_call(deny, "conv-2", self.log_dir), deny)
        self.assertIn("G1_SILENT_EXCEPTION", brief_first_call('{"decision": "allow"}', "conv-2", self.log_dir))

    def test_agents_with_session_hook_are_skipped(self):
        out = '{"decision": "allow"}'
        self.assertEqual(brief_first_call(out, "claude:abc", self.log_dir), out)
        self.assertEqual(brief_first_call(out, "codex:abc", self.log_dir), out)


if __name__ == "__main__":
    unittest.main()
