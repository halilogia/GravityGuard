#!/usr/bin/env python3
"""
Unit tests for GravityGuard Project Context & Multi-Root Resolution (Defect C).
"""
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
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

    def test_log_dir_override_does_not_replace_project_root_or_config(self):
        proj = Path(self.temp_dir) / "proj"
        logs = Path(self.temp_dir) / "logs"
        (proj / "src").mkdir(parents=True)
        logs.mkdir()
        (proj / ".gravityguard.json").write_text('{"rules": {"G1_SILENT_EXCEPTION": {"mode": "shadow"}}}', encoding="utf-8")
        (logs / ".gravityguard.json").write_text('{"rules": {}}', encoding="utf-8")
        orig = os.environ.get("GRAVITYGUARD_LOG_DIR")
        os.environ["GRAVITYGUARD_LOG_DIR"] = str(logs)
        try:
            payload = {"workspacePaths": [str(proj)]}
            root = resolve_project_root(payload)
            self.assertEqual(root, Path(os.path.abspath(proj)))
            self.assertIn("rules", load_gravityguard_config("", root) or {})
            self.assertEqual(load_gravityguard_config("", root)["rules"]["G1_SILENT_EXCEPTION"]["mode"], "shadow")
            self.assertEqual(
                load_gravityguard_config(str(proj / "src" / "a.py"), root)["rules"]["G1_SILENT_EXCEPTION"]["mode"], "shadow")
        finally:
            if orig is None:
                os.environ.pop("GRAVITYGUARD_LOG_DIR", None)
            else:
                os.environ["GRAVITYGUARD_LOG_DIR"] = orig

    def test_doc_governed_target_excludes_tests_and_non_code(self):
        self.assertFalse(is_doc_governed_target("tests/test_core.py"))
        self.assertFalse(is_doc_governed_target("src/components/button.test.tsx"))
        self.assertFalse(is_doc_governed_target("docs/architecture.md"))
        self.assertTrue(is_doc_governed_target("engine/validator.py"))
        self.assertTrue(is_doc_governed_target("src/services/billing.ts"))


class TestUserDefaultConfig(unittest.TestCase):
    """~/.gravityguard.json (or GRAVITYGUARD_USER_CONFIG) is used only when the project has no .gravityguard.json."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="gg_userdef_")
        self.proj = Path(self.temp_dir) / "proj"
        (self.proj / "src").mkdir(parents=True)
        (self.proj / ".git").mkdir()
        self.target = str(self.proj / "src" / "a.py")
        self.user_cfg = Path(self.temp_dir) / "user.json"
        self._orig = os.environ.get("GRAVITYGUARD_USER_CONFIG")
        os.environ["GRAVITYGUARD_USER_CONFIG"] = str(self.user_cfg)

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("GRAVITYGUARD_USER_CONFIG", None)
        else:
            os.environ["GRAVITYGUARD_USER_CONFIG"] = self._orig
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_fallback_used_when_project_has_no_file(self):
        self.user_cfg.write_text('{"rules": {"G1_SILENT_EXCEPTION": {"mode": "shadow"}}}', encoding="utf-8")
        for cfg in (load_gravityguard_config(self.target), load_gravityguard_config("", self.proj)):
            self.assertEqual(cfg["rules"]["G1_SILENT_EXCEPTION"]["mode"], "shadow")
        self.assertEqual(resolve_project_root(None, self.target), self.proj)

    def test_project_file_wins_without_merging(self):
        self.user_cfg.write_text('{"rules": {"SRP_BOUNDARY": "shadow"}, "complexity": {"monolithLoc": 500}}', encoding="utf-8")
        (self.proj / ".gravityguard.json").write_text('{"rules": {}}', encoding="utf-8")
        self.assertEqual(load_gravityguard_config(self.target), {"rules": {}})
        self.assertEqual(load_gravityguard_config("", self.proj), {"rules": {}})

    def test_broken_project_file_does_not_fall_back(self):
        self.user_cfg.write_text('{"rules": {"SRP_BOUNDARY": "shadow"}}', encoding="utf-8")
        (self.proj / ".gravityguard.json").write_text("{nope", encoding="utf-8")
        self.assertIsNone(load_gravityguard_config(self.target))

    def test_invalid_or_missing_user_file_is_ignored(self):
        self.assertIsNone(load_gravityguard_config(self.target))          # missing
        self.user_cfg.write_text("{not json", encoding="utf-8")
        self.assertIsNone(load_gravityguard_config(self.target))          # invalid JSON
        self.user_cfg.write_text("[1, 2]", encoding="utf-8")
        self.assertIsNone(load_gravityguard_config("", self.proj))        # not an object

    def test_default_location_is_the_home_directory(self):
        os.environ.pop("GRAVITYGUARD_USER_CONFIG")
        home = Path(self.temp_dir) / "home"
        home.mkdir()
        (home / ".gravityguard.json").write_text('{"complexity": {"monolithLoc": 500}}', encoding="utf-8")
        with unittest.mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
            self.assertEqual(load_gravityguard_config(self.target)["complexity"]["monolithLoc"], 500)
            # the home file is a default, not a project marker: a project under home keeps its own root
            nested = home / "work" / "app"
            nested.mkdir(parents=True)
            self.assertEqual(resolve_project_root(None, str(nested / "x.py")), Path.cwd())
            self.assertEqual(load_gravityguard_config(str(nested / "x.py"))["complexity"]["monolithLoc"], 500)


if __name__ == "__main__":
    unittest.main()
