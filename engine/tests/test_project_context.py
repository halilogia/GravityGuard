#!/usr/bin/env python3
"""
Unit tests for GravityGuard Project Context & Multi-Root Resolution (Defect C).
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine.project_context import (

    DEFAULT_COMPLEXITY_THRESHOLDS,
    extract_project_info,
    is_doc_governed_target,
    load_gravityguard_config,
    resolve_complexity_thresholds,
    resolve_project_root,
    should_enforce_doc_obligations,
)


class TestProjectContextAndMultiRoot(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="gg_multiroot_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_multi_root_workspace_resolution_matches_target_ancestor(self):
        """
        Defect C fix: In a multi-root workspace [rootA, rootB], when target_file belongs to rootB,
        resolve_project_root must return rootB, not rootA!
        """
        root_a = os.path.join(self.temp_dir, "workspace_a")
        root_b = os.path.join(self.temp_dir, "workspace_b")
        os.makedirs(os.path.join(root_a, "src"), exist_ok=True)
        os.makedirs(os.path.join(root_b, "src"), exist_ok=True)

        target_file_b = os.path.join(root_b, "src", "service.ts")
        payload = {
            "workspacePaths": [root_a, root_b],
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": target_file_b}
            }
        }

        # Clear any override during direct function test
        orig_override = os.environ.pop("GRAVITYGUARD_LOG_DIR", None)
        try:
            resolved = resolve_project_root(payload, target_file=target_file_b)
            self.assertEqual(resolved, Path(os.path.abspath(root_b)))

            # If target belongs to root_a, resolves to root_a
            target_file_a = os.path.join(root_a, "src", "client.ts")
            resolved_a = resolve_project_root(payload, target_file=target_file_a)
            self.assertEqual(resolved_a, Path(os.path.abspath(root_a)))
        finally:
            if orig_override is not None:
                os.environ["GRAVITYGUARD_LOG_DIR"] = orig_override

    def test_multi_root_fallback_to_first_workspace_when_no_target_match(self):
        root_a = os.path.join(self.temp_dir, "workspace_a")
        root_b = os.path.join(self.temp_dir, "workspace_b")
        os.makedirs(root_a, exist_ok=True)
        os.makedirs(root_b, exist_ok=True)

        payload = {"workspacePaths": [root_a, root_b]}
        orig_override = os.environ.pop("GRAVITYGUARD_LOG_DIR", None)
        try:
            resolved = resolve_project_root(payload, target_file="")
            self.assertEqual(resolved, Path(os.path.abspath(root_a)))
        finally:
            if orig_override is not None:
                os.environ["GRAVITYGUARD_LOG_DIR"] = orig_override

    def test_resolve_complexity_thresholds_clamps_below_floors(self):
        cfg = {"complexity": {"monolithLoc": 5, "singleWriteLoc": 1}}
        resolved = resolve_complexity_thresholds(cfg)
        # 5 is below floor (100), 1 is below floor (10); must retain defaults
        self.assertEqual(resolved["monolithLoc"], DEFAULT_COMPLEXITY_THRESHOLDS["monolithLoc"])
        self.assertEqual(resolved["singleWriteLoc"], DEFAULT_COMPLEXITY_THRESHOLDS["singleWriteLoc"])

    def test_doc_governed_target_excludes_tests_and_non_code(self):
        self.assertFalse(is_doc_governed_target("tests/test_core.py"))
        self.assertFalse(is_doc_governed_target("src/components/button.test.tsx"))
        self.assertFalse(is_doc_governed_target("docs/architecture.md"))
        self.assertTrue(is_doc_governed_target("engine/validator.py"))
        self.assertTrue(is_doc_governed_target("src/services/billing.ts"))


if __name__ == "__main__":
    unittest.main()
