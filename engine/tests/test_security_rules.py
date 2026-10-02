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

    def test_escape_hatch_injection_blocked(self):
        # Escape hatch pattern constructed to test validator
        marker = "# " + "srp: allow-monolith"
        added = f"{marker}\nclass GodModule: pass\n"
        blocked, reason = check_escape_hatch_tampering(added, "")
        self.assertTrue(blocked)
        self.assertIn("Güvenlik/Mimari susturma hilesi", reason)


if __name__ == "__main__":
    unittest.main()
