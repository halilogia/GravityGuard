import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gravityguard_engine.hook_output import drop_repeated_warnings, finalize


class DropRepeatedWarningsTests(unittest.TestCase):
    def setUp(self):
        self.log_dir = tempfile.mkdtemp()

    def drop(self, warnings, conv="conv-1", target="src/a.py"):
        return drop_repeated_warnings(warnings, conv, target, self.log_dir)

    def test_same_warning_is_said_once_per_conversation_and_file(self):
        growth = [("ARCH_FILE_GROWTH", "Modülerlik Uyarısı: 'a.py' 1005 LOC")]
        self.assertEqual(self.drop(growth), growth)
        # Only the line count moved: nothing new for the agent.
        self.assertEqual(self.drop([("ARCH_FILE_GROWTH", "Modülerlik Uyarısı: 'a.py' 1012 LOC")]), [])

    def test_new_finding_other_file_or_other_conversation_is_said(self):
        first = [("SEC_UNSAFE_PATTERN", "innerHTML kullanımı")]
        self.drop(first)
        other = [("SEC_UNSAFE_PATTERN", "eval kullanımı")]
        self.assertEqual(self.drop(other), other)
        self.assertEqual(self.drop(first, target="src/b.py"), first)
        self.assertEqual(self.drop(first, conv="conv-2"), first)

    def test_only_the_repeat_is_removed_from_a_mixed_list(self):
        self.drop([("T2_NO_OBSERVABLE_ASSERTION", "assert yok")])
        mixed = [("T2_NO_OBSERVABLE_ASSERTION", "assert yok"), ("DESIGN_ICON_RULE", "emoji")]
        self.assertEqual(self.drop(mixed), [("DESIGN_ICON_RULE", "emoji")])

    def test_unreadable_state_starts_fresh(self):
        with open(os.path.join(self.log_dir, "warned_once.json"), "w", encoding="utf-8") as f:
            f.write("{torn")
        warn = [("ARCH_FILE_GROWTH", "buyume")]
        self.assertEqual(self.drop(warn), warn)


class FinalizeTests(unittest.TestCase):
    def test_rejection_gets_lesson_and_stop_output_gets_no_briefing(self):
        deny = json.dumps({"decision": "deny", "reason": "[G1_SILENT_EXCEPTION]: x"}) + "\n"
        out = json.loads(finalize(deny, True, "conv-x"))
        self.assertIn("Doğru yol:", out["reason"])


if __name__ == "__main__":
    unittest.main()
