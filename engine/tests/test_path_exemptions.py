#!/usr/bin/env python3
"""Vendor/cache exemption must not cover hand-written tools under ~/.gemini/config."""
import os
import sys
import unittest

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine.path_exemptions import is_vendor_or_cache_path


class PathExemptionTests(unittest.TestCase):
    def test_user_tools_under_gemini_config_are_governed(self):
        for p in (
            "c:/users/halil emre/.gemini/config/tools/scratchless/scratchless.py",
            "c:/users/halil emre/.gemini/config/skills/x/run.py",
        ):
            self.assertFalse(is_vendor_or_cache_path(p), p)

    def test_state_and_vendor_paths_stay_exempt(self):
        for p in (
            "c:/users/x/.gemini/antigravity/brain/abc/tasks.md",
            "c:/users/x/.gemini/logs/audit.py",
            "c:/users/x/.gemini/config/plugins/gravityguard/engine/a.py",
            "c:/users/x/proj/node_modules/a/index.js",
            "c:/users/x/.gemini/antigravity/scratch/proj/src/node_modules/a.js",
        ):
            self.assertTrue(is_vendor_or_cache_path(p), p)

    def test_scratch_project_source_is_governed(self):
        self.assertFalse(is_vendor_or_cache_path("c:/users/x/.gemini/antigravity/scratch/proj/src/app.py"))


if __name__ == "__main__":
    unittest.main()
