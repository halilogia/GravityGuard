#!/usr/bin/env python3
"""
Unit tests for the review trigger policy (opt-in, path/suffix based).
"""
import os
import sys
import unittest
from pathlib import Path

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine.review_policy import (
    is_review_enabled,
    is_review_exempt_file,
    should_require_review,
)


class TestReviewPolicy(unittest.TestCase):
    def test_review_disabled_by_default(self):
        self.assertFalse(is_review_enabled({}))
        self.assertFalse(is_review_enabled(None))
        self.assertFalse(should_require_review("src/app.py", {}, None))

    def test_review_enabled_but_requires_code_suffix(self):
        cfg = {"review": {"enabled": True}}
        self.assertTrue(is_review_enabled(cfg))
        self.assertTrue(should_require_review("src/app.py", cfg, None))
        self.assertTrue(should_require_review("addons/foo.gd", cfg, None))
        # Non-code is never review-triggering.
        self.assertFalse(should_require_review("README.md", cfg, None))
        self.assertFalse(should_require_review("package.json", cfg, None))

    def test_test_files_never_trigger_review(self):
        cfg = {"review": {"enabled": True}}
        self.assertFalse(should_require_review("tests/test_app.py", cfg, None))
        self.assertFalse(should_require_review("src/app_test.py", cfg, None))
        self.assertFalse(should_require_review("src/app.test.ts", cfg, None))
        self.assertFalse(should_require_review("project/test/app.spec.ts", cfg, None))

    def test_default_exemptions_can_be_overridden(self):
        cfg = {"review": {"enabled": True}}
        # A custom exempt pattern suppresses review even for source.
        custom = {"review": {"enabled": True, "exemptPatterns": ["src/generated/**"]}}
        self.assertTrue(should_require_review("src/generated/api.py", cfg, None))
        self.assertFalse(should_require_review("src/generated/api.py", custom, None))

    def test_relative_matching_against_project_root(self):
        cfg = {"review": {"enabled": True}}
        root = Path("/proj")
        self.assertFalse(should_require_review("/proj/tests/test_x.py", cfg, root))
        self.assertTrue(should_require_review("/proj/src/x.py", cfg, root))

    def test_exempt_helper_inverts_for_code(self):
        cfg = {"review": {"enabled": True}}
        self.assertTrue(is_review_exempt_file("README.md", cfg, None))
        self.assertFalse(is_review_exempt_file("src/x.py", cfg, None))


if __name__ == "__main__":
    unittest.main()
