#!/usr/bin/env python3
"""
Unit tests for GravityGuard Security Rules (G0, G1, G2, Escape Hatches).
"""
import os
import sys
import unittest

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine.security_rules import (
    check_escape_hatch_tampering,
    check_g0_secret_leak,
    check_g1_silent_exception,
    check_g2_test_integrity,
    is_placeholder,
    redact_token,
)


class TestSecurityRulesDomain(unittest.TestCase):
    def test_g0_blocks_live_tokens(self):
        token = "ghp_" + "A" * 36
        blocked, reason, _ = check_g0_secret_leak(f"const token = '{token}';")
        self.assertTrue(blocked)
        self.assertIn("GitHub Personal Access", reason)

    def test_g0_allows_placeholders(self):
        token = "ghp_your_token_here_placeholder"
        blocked, _, _ = check_g0_secret_leak(f"const token = '{token}';")
        self.assertFalse(blocked)

    def test_g0_blocks_legacy_openai_key(self):
        token = "sk-" + "Zx9Qw7Er5Ty3" * 4
        blocked, reason, _ = check_g0_secret_leak(f'KEY = "{token}"')
        self.assertTrue(blocked)
        self.assertIn("OpenAI", reason)

    def test_g0_blocks_openai_t3blbkfj_key(self):
        token = "sk-" + "A" * 20 + "T3BlbkFJ" + "b" * 20
        blocked, _, _ = check_g0_secret_leak(f'KEY = "{token}"')
        self.assertTrue(blocked)

    def test_g0_blocks_modern_openai_project_key(self):
        token = "sk-proj-" + "abcd1234" * 6
        blocked, _, _ = check_g0_secret_leak(f'KEY = "{token}"')
        self.assertTrue(blocked)

    def test_g0_legacy_key_rule_ignores_words_that_merely_contain_sk_dash(self):
        for text in (
            "demo task-report-cleanup-deepseekv4flash done",
            "risk-assessment-for-the-quarterly-review-of-all-services",
            "see the sk-learn-compatible-estimator-wrapper-package-name docs",
            "disk-usage-monitoring-and-alerting-configuration-file",
        ):
            blocked, _, _ = check_g0_secret_leak(text)
            self.assertFalse(blocked, text)

    def test_g0_legacy_key_rule_allows_placeholders(self):
        for token in ("sk-" + "x" * 48, "sk-your_api_key_here_" + "0" * 27, "sk-" + "example" * 7):
            blocked, _, _ = check_g0_secret_leak(f'KEY = "{token}"')
            self.assertFalse(blocked, token)

    def test_g1_blocks_empty_except_in_python(self):
        code = "try:\n    do_it()\nexcept:\n    pass\n"
        blocked, reason = check_g1_silent_exception(
            added_lines=code.splitlines(),
            added_text=code,
            added_line_numbers={1, 2, 3, 4},
            projected_content=code,
            is_python=True,
            is_ts=False,
        )
        self.assertTrue(blocked)
        self.assertIn("except: pass", reason)

    def test_g1_allows_meaningful_recovery(self):
        code = "try:\n    do_it()\nexcept Exception as e:\n    logger.error(e)\n    return []\n"
        blocked, _ = check_g1_silent_exception(
            added_lines=code.splitlines(),
            added_text=code,
            added_line_numbers={1, 2, 3, 4, 5},
            projected_content=code,
            is_python=True,
            is_ts=False,
        )
        self.assertFalse(blocked)

    def test_g2_blocks_skip_tricks(self):
        # Disabler pattern constructed to test validator without triggering self-block
        disabler = "@" + "pytest.mark.skip"
        added = f"{disabler}\ndef test_feature(): pass\n"
        blocked, reason, _ = check_g2_test_integrity(added, "", added, is_test_file=True)
        self.assertTrue(blocked)
        self.assertIn(disabler, reason)

    def test_g0_blocks_hyphenated_sk_secret_but_not_placeholders_or_slugs(self):
        blocked, _, _ = check_g0_secret_leak("API_KEY = 'sk-FAKE-do-not-use-0000'")
        self.assertTrue(blocked)
        blocked, _, _ = check_g0_secret_leak("API_KEY = 'sk-Ab3dE-fG7hI-jK9lM-nO1pQ-rS5tU'")
        self.assertTrue(blocked)
        for harmless in ("KEY = 'sk-xxxx'", "KEY = 'sk-your-key-here'", "KEY=sk-example-0000-AAAA-bbbb-1111",
                         "see sk-learn-pipeline-config-docs", "task-report-cleanup-Deepseek4"):
            blocked, _, _ = check_g0_secret_leak(harmless)
            self.assertFalse(blocked, harmless)

    def test_g2_warns_on_always_true_assertions(self):
        for tautology in ("def test_a():\n    assert True\n", "def test_a():\n    assert 1 == 1\n",
                          "def test_a():\n    assert 'a' == 'a', 'msg'\n",
                          "def test_a(self):\n        self.assertTrue(True)\n",
                          "def test_a(self):\n        self.assertEqual(1, 1)\n",
                          "it('x', () => { expect(true).toBe(true); });\n"):
            blocked, _, warn = check_g2_test_integrity(tautology, "", tautology, is_test_file=True)
            self.assertFalse(blocked)
            self.assertIn("her zaman geçen", warn or "", tautology)
        real = "def test_a():\n    assert compute(2) == 4\n"
        self.assertIsNone(check_g2_test_integrity(real, "", real, is_test_file=True)[2])

    def test_g2_warns_on_commented_out_assert(self):
        added = "def test_a():\n    # assert compute(2) == 4\n    pass\n"
        _, _, warn = check_g2_test_integrity(added, "", added, is_test_file=True)
        self.assertIn("yorum satırına", warn or "")
        prose = "def test_a():\n    # assert that the cache is warm first\n    assert compute(2) == 4\n"
        self.assertIsNone(check_g2_test_integrity(prose, "", prose, is_test_file=True)[2])

    def test_g2_rename_is_not_a_deletion_but_removal_is(self):
        old = "def test_old_name():\n    assert compute(1) == 2\n\ndef test_other():\n    assert compute(2) == 4\n"
        renamed = old.replace("test_old_name", "test_new_name")
        blocked, _, _ = check_g2_test_integrity("def test_new_name():\n", old, renamed, is_test_file=True)
        self.assertFalse(blocked)
        removed = "def test_other():\n    assert compute(2) == 4\n"
        blocked, reason, _ = check_g2_test_integrity("", old, removed, is_test_file=True)
        self.assertTrue(blocked)
        self.assertIn("yeniden adlandırıyorsan", reason)

    def test_escape_hatch_injection_blocked(self):
        # Escape hatch pattern constructed to test validator
        marker = "# " + "srp: allow-monolith"
        added = f"{marker}\nclass GodModule: pass\n"
        blocked, reason = check_escape_hatch_tampering(added, "")
        self.assertTrue(blocked)
        self.assertIn("Güvenlik/Mimari susturma hilesi", reason)


if __name__ == "__main__":
    unittest.main()
