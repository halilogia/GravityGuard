#!/usr/bin/env python3
"""Drop-in rule system: every shipped rule proves itself on its own bad/good samples."""
import importlib.util
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine import plugin_rules
from gravityguard_engine.plugin_rules import Rule, apply_plugin_rules, evaluate, load_rules, regex_rule, validate
from gravityguard_engine.dispatcher import MANDATORY_RULES


def _sample_path(rule: Rule) -> str:
    return "src/sample" + (rule.sample_ext or (rule.extensions[0] if rule.extensions else ".txt"))


def _fire(rule: Rule, content: str, path=None, cfg=None):
    n = len(content.splitlines())
    return evaluate([rule], path or _sample_path(rule), content, set(range(1, n + 1)), cfg)


class ShippedRuleTests(unittest.TestCase):
    def test_rules_are_valid_and_unique(self):
        rules = load_rules()
        self.assertTrue(rules)
        ids = [r.id for r in rules]
        self.assertEqual(len(ids), len(set(ids)), "duplicate rule id")
        for r in rules:
            with self.subTest(rule=r.id):
                self.assertIsNone(validate(r))
                self.assertNotIn(r.id, MANDATORY_RULES, "mandatory rules cannot be drop-in rules")

    def test_bad_sample_fires_and_good_sample_does_not(self):
        for r in load_rules():
            with self.subTest(rule=r.id):
                self.assertTrue(_fire(r, r.bad), "bad sample must trigger")
                good_path = "src/sample" + r.good_ext if r.good_ext else None
                self.assertFalse(_fire(r, r.good, path=good_path), "good sample must not trigger")


class EngineBehaviourTests(unittest.TestCase):
    RULE = regex_rule("TEST_RULE", r"FORBIDDEN", "msg", "tip", bad="FORBIDDEN\n", good="ok\n", extensions=(".py",))

    def test_only_added_lines_count(self):
        out = evaluate([self.RULE], "a.py", "FORBIDDEN\nnew\n", {2})
        self.assertEqual(out, [])

    def test_extension_and_test_file_filters(self):
        self.assertFalse(_fire(self.RULE, "FORBIDDEN\n", path="a.js"))
        self.assertFalse(_fire(self.RULE, "FORBIDDEN\n", path="proj/tests/test_a.py"))
        keep = regex_rule("KEEP_TESTS", "X", "m", "t", bad="X", good="y", skip_tests=False)
        self.assertTrue(_fire(keep, "X\n", path="tests/test_a.py"))

    def test_config_can_turn_rule_off_or_shadow(self):
        self.assertFalse(_fire(self.RULE, "FORBIDDEN\n", cfg={"rules": {"TEST_RULE": "off"}}))
        self.assertEqual(_fire(self.RULE, "FORBIDDEN\n", cfg={"rules": {"TEST_RULE": {"mode": "shadow"}}})[0][1], "shadow")

    def test_custom_check_function_and_crashing_rule(self):
        custom = Rule("CUSTOM_RULE", "too long", "split it", lambda c: [(n, t) for n, t in c.added if len(t) > 5],
                      bad="abcdefgh\n", good="abc\n", extensions=(".py",))
        self.assertTrue(_fire(custom, custom.bad))
        broken = Rule("BROKEN_RULE", "m", "t", lambda c: 1 / 0, bad="x", good="y")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(_fire(broken, "x\n"), [])

    def test_validate_rejects_bad_definitions(self):
        self.assertIn("UPPER_SNAKE_CASE", validate(regex_rule("lower", "x", "m", "t", bad="x", good="y")))
        self.assertIn("severity", validate(regex_rule("GOOD_ID", "x", "m", "t", bad="x", good="y", severity="maybe")))
        self.assertIn("samples", validate(regex_rule("GOOD_ID", "x", "m", "t", bad="", good="y")))


class DispatchTests(unittest.TestCase):
    def _run(self, severity):
        rule = regex_rule("DISPATCH_TEST", "BAD", "found", "fix it", bad="BAD", good="ok", severity=severity)
        logs, warnings = [], []
        orig = plugin_rules.load_rules
        plugin_rules.load_rules = lambda: [rule]
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                try:
                    apply_plugin_rules("a.txt", "BAD\n", {1}, None, lambda *a, **k: logs.append((a[0], k["rule_id"])), warnings)
                    exited = False
                except SystemExit:
                    exited = True
        finally:
            plugin_rules.load_rules = orig
        return logs, warnings, exited, buf.getvalue()

    def test_warn_rule_logs_and_collects_warning(self):
        logs, warnings, exited, out = self._run("warn")
        self.assertEqual(logs, [("WARNING", "DISPATCH_TEST")])
        self.assertEqual(warnings[0][0], "DISPATCH_TEST")
        self.assertFalse(exited)

    def test_deny_rule_blocks_with_tip(self):
        logs, _w, exited, out = self._run("deny")
        self.assertTrue(exited)
        self.assertEqual(logs, [("BLOCKED", "DISPATCH_TEST")])
        verdict = json.loads(out)
        self.assertEqual(verdict["decision"], "deny")
        self.assertIn("fix it", verdict["reason"])


class ScaffoldTests(unittest.TestCase):
    def test_generated_template_is_a_valid_passing_rule(self):
        spec = importlib.util.spec_from_file_location("new_rule", Path(_ENGINE_DIR).parent / "tools" / "new_rule.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        ns = {}
        exec(mod.TEMPLATE.format(rid="SCAFFOLD_CHECK", sev="warn"), ns)
        rule = ns["RULE"]
        self.assertIsNone(validate(rule))
        self.assertTrue(_fire(rule, rule.bad))
        self.assertFalse(_fire(rule, rule.good))


if __name__ == "__main__":
    unittest.main()
