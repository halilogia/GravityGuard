#!/usr/bin/env python3
"""
Unit tests for GravityGuard Test Evidence Airbag (T1, T2, T3).
"""
import os
import sys
import unittest

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine.test_evidence import (
    check_t1_missing_test,
    check_t2_observable_assertion,
    check_t3_symbol_to_test_link,
    is_exempt_from_test_evidence,
    resolve_candidate_test_file,
)


class TestTestEvidenceDomain(unittest.TestCase):
    def test_exempt_patterns(self):
        self.assertTrue(is_exempt_from_test_evidence("src/types.ts"))
        self.assertTrue(is_exempt_from_test_evidence("src/constants.py"))
        self.assertTrue(is_exempt_from_test_evidence("src/models.d.ts"))
        self.assertFalse(is_exempt_from_test_evidence("src/billing.py"))

    def test_resolve_candidate_test_file_normalizes_hyphen_and_underscore(self):
        cand, expected = resolve_candidate_test_file("engine/gravity-validator.py")
        self.assertTrue(cand is not None and cand.endswith("test_gravity_validator.py"))


    def test_t2_detects_unasserted_test(self):
        code = "def test_something():\n    x = 1\n    y = 2\n"
        warned, msg = check_t2_observable_assertion(
            added_lines=code.splitlines(),
            added_text=code,
            is_python=True,
            is_ts=False,
            projected_content=code,
            added_line_numbers={1, 2, 3},
        )
        self.assertTrue(warned)
        self.assertIn("T2_NO_OBSERVABLE_ASSERTION", msg)

    def test_t2_allows_assert(self):
        code = "def test_something():\n    assert 1 == 1\n"
        warned, _ = check_t2_observable_assertion(
            added_lines=code.splitlines(),
            added_text=code,
            is_python=True,
            is_ts=False,
            projected_content=code,
            added_line_numbers={1, 2},
        )
        self.assertFalse(warned)


if __name__ == "__main__":
    unittest.main()
