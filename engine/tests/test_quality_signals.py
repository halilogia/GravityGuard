import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gravityguard_engine.quality_signals import (
    find_evasion_markers,
)


class EvasionMarkerTests(unittest.TestCase):
    def test_detects_suppression_markers(self):
        text = "x = f()  # type: ignore\n// eslint-disable-next-line\ncatch (e) { void e; }\n"
        self.assertEqual(find_evasion_markers(text), ["type-ignore", "eslint-disable", "discarded-error"])

    def test_real_fix_has_no_markers(self):
        self.assertEqual(find_evasion_markers("except ValueError as e:\n    logger.error(e)\n    raise\n"), [])

    def test_empty(self):
        self.assertEqual(find_evasion_markers(""), [])

    def test_single_implementation_signal_is_gone(self):
        import gravityguard_engine.quality_signals as qs
        self.assertFalse(hasattr(qs, "check_single_implementation"))
        self.assertFalse(hasattr(qs, "oe_single_impl_mode"))


if __name__ == "__main__":
    unittest.main()
