#!/usr/bin/env python3
"""
Tests for the documentation governance policy (doc_policy.py) and for the commit-time verifier that shares it.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from gravityguard_engine.doc_policy import is_doc_governed_path, matches_any_pattern
from gravityguard_engine.project_context import is_doc_governed_target

_VERIFIER = _ENGINE_DIR.parent / "tools" / "verify_doc_governance.py"
_spec = importlib.util.spec_from_file_location("verify_doc_governance", _VERIFIER)
verifier = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verifier)

PATTERN_CFG = {"governance": {"docObligationPatterns": ["core/**", "ui/**", "addons/godot_sidebar_ai/**/*.gd"]}}


class TestDocPolicy(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="gg_docpol_"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def governed(self, rel, cfg=None):
        return is_doc_governed_path(str(self.root / rel), cfg, self.root)

    def test_default_directories_are_governed(self):
        for rel in ("engine/a.py", "src/a.ts", "plugin/a.py", "rules/a.py", "scripts/a.sh", "tools/a.py", "engine/pkg/deep/a.py"):
            self.assertTrue(self.governed(rel), rel)

    def test_scripts_and_tools_are_governed_by_both_gates(self):
        """The two gates once disagreed: `scripts` only at Stop, `tools` only at commit."""
        self.assertTrue(self.governed("scripts/x.py"))
        self.assertTrue(self.governed("tools/x.py"))

    def test_tests_caches_runtime_dirs_and_non_code_never_owe_docs(self):
        for rel in ("tests/test_a.py", "engine/tests/test_a.py", "engine/test_a.py", "engine/a_test.py", "engine/a.spec.ts",
                    "docs/a.md", "engine/notes.txt", "engine/config.json", "engine/dist/a.js", "node_modules/p/src/a.js",
                    ".gravityguard/runtime/a.py", "archives/engine/a.py", "engine/logo.png"):
            self.assertFalse(self.governed(rel, PATTERN_CFG), rel)

    def test_hook_table_is_governed_although_it_is_json(self):
        self.assertTrue(self.governed("plugin/hooks.json"))

    def test_unlisted_directory_needs_a_pattern(self):
        self.assertFalse(self.governed("core/a.py"))
        self.assertTrue(self.governed("core/a.py", PATTERN_CFG))
        self.assertTrue(self.governed("ui/a/b/c.py", PATTERN_CFG))

    def test_double_star_directory_segment_is_optional(self):
        self.assertTrue(self.governed("addons/godot_sidebar_ai/a.gd", PATTERN_CFG))
        self.assertTrue(self.governed("addons/godot_sidebar_ai/core/a.gd", PATTERN_CFG))
        self.assertFalse(self.governed("addons/godot_sidebar_ai/a.md", PATTERN_CFG))
        self.assertFalse(self.governed("addons/other/a.gd", PATTERN_CFG))

    def test_project_can_replace_the_default_directories(self):
        cfg = {"governance": {"docGovernedDirs": ["addons", "Core"]}}
        self.assertTrue(self.governed("addons/x/a.gd", cfg))
        self.assertTrue(self.governed("core/a.py", cfg))
        self.assertFalse(self.governed("tools/a.gd", cfg), "throwaway helpers do not owe a CHANGELOG entry")
        self.assertFalse(self.governed("engine/a.py", cfg))

    def test_patterns_are_added_on_top_of_a_replaced_directory_list(self):
        cfg = {"governance": {"docGovernedDirs": ["addons"], "docObligationPatterns": ["tools/keep/**"]}}
        self.assertTrue(self.governed("tools/keep/a.py", cfg))
        self.assertFalse(self.governed("tools/other/a.py", cfg))

    def test_empty_directory_list_governs_only_patterns(self):
        self.assertFalse(self.governed("engine/a.py", {"governance": {"docGovernedDirs": []}}))

    def test_malformed_directory_list_falls_back_to_the_defaults(self):
        for value in ("core", [1], [""], None, {"core": True}):
            self.assertTrue(self.governed("engine/a.py", {"governance": {"docGovernedDirs": value}}), repr(value))

    def test_malformed_pattern_config_is_ignored(self):
        for cfg in ({"governance": {"docObligationPatterns": "core/**"}}, {"governance": {"docObligationPatterns": [None, 3, ""]}},
                    {"governance": "yes"}, {}, None):
            self.assertFalse(self.governed("core/a.py", cfg))

    def test_a_checkout_under_a_directory_named_src_does_not_govern_everything(self):
        nested = self.root / "src" / "myproject"
        nested.mkdir(parents=True)
        self.assertFalse(is_doc_governed_path(str(nested / "app" / "main.py"), None, nested))
        self.assertTrue(is_doc_governed_path(str(nested / "engine" / "main.py"), None, nested))

    def test_legacy_absolute_pattern_still_matches(self):
        cfg = {"governance": {"docObligationPatterns": ["*/core/*"]}}
        self.assertTrue(is_doc_governed_path(str(self.root / "core" / "a.py"), cfg, self.root))

    def test_matches_any_pattern_skips_junk(self):
        self.assertFalse(matches_any_pattern("core/a.py", [None, "", "  ", 5]))

    def test_explicit_pattern_can_govern_markdown_and_json_files(self):
        cfg = {"governance": {"docObligationPatterns": ["plugin/skills/**/*.md", "plugin/.claude-plugin/*.json"]}}
        self.assertTrue(self.governed("plugin/skills/sub/SKILL.md", cfg))
        self.assertTrue(self.governed("plugin/.claude-plugin/plugin.json", cfg))
        self.assertFalse(self.governed("plugin/skills/other.txt", cfg))
        self.assertFalse(self.governed("docs/guide.md", cfg))

    def test_godot_uid_files_are_non_code_metadata(self):
        cfg = {"governance": {"docGovernedDirs": ["addons"]}}
        self.assertTrue(self.governed("addons/game/player.gd", cfg))
        self.assertFalse(self.governed("addons/game/player.gd.uid", cfg))
        self.assertFalse(self.governed("addons/game/readme.md", cfg))

    def test_the_runtime_wrapper_agrees_with_the_policy(self):
        for rel in ("engine/a.py", "core/a.py", "tests/test_a.py", "plugin/hooks.json", "tools/a.py"):
            path = str(self.root / rel)
            self.assertEqual(is_doc_governed_target(path, PATTERN_CFG, self.root), is_doc_governed_path(path, PATTERN_CFG, self.root), rel)

    def test_the_commit_verifier_agrees_with_the_policy(self):
        for rel in ("engine/a.py", "core/a.py", "tests/test_a.py", "plugin/hooks.json", "tools/a.py", "scripts/a.py"):
            path = str(self.root / rel)
            self.assertEqual(verifier.is_governed_code_file(path, PATTERN_CFG, self.root), is_doc_governed_path(path, PATTERN_CFG, self.root), rel)


class TestCommitVerifier(unittest.TestCase):
    """The verifier as a pre-commit hook of ANY repository: cwd is that repository, the config is its .gravityguard.json."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="gg_verify_"))
        self.env = {k: v for k, v in os.environ.items() if k != "GRAVITYGUARD_LOG_DIR"}
        self.env["PYTHONIOENCODING"] = "utf-8"
        self.git("init", "-q")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True, env=self.env)

    def stage(self, rel, text="x = 1\n"):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.git("add", rel)

    def config(self, body):
        (self.repo / ".gravityguard.json").write_text(body, encoding="utf-8")

    def verify(self):
        proc = subprocess.run([sys.executable, str(_VERIFIER)], cwd=self.repo, capture_output=True, text=True, encoding="utf-8", env=self.env)
        return proc.returncode, proc.stdout + proc.stderr

    def test_governed_code_without_changelog_is_rejected(self):
        self.config('{"governance": {"enforceDocObligations": true, "docObligationPatterns": ["core/**"]}}')
        self.stage("core/engine.py")
        code, out = self.verify()
        self.assertEqual(code, 1, out)
        self.assertIn("core/engine.py", out)

    def test_changelog_in_the_same_commit_passes(self):
        self.config('{"governance": {"enforceDocObligations": true, "docObligationPatterns": ["core/**"]}}')
        self.stage("core/engine.py")
        self.stage("CHANGELOG.md", "# Changelog\n- core\n")
        code, out = self.verify()
        self.assertEqual(code, 0, out)

    def test_directory_outside_the_policy_passes(self):
        self.config('{"governance": {"enforceDocObligations": true}}')
        self.stage("core/engine.py")
        self.assertEqual(self.verify()[0], 0)

    def test_replaced_directory_list_decides_what_owes_a_changelog(self):
        self.config('{"governance": {"enforceDocObligations": true, "docGovernedDirs": ["core"]}}')
        self.stage("tools/helper.py")
        self.assertEqual(self.verify()[0], 0, "tools/ is not governed in this project")
        self.stage("core/engine.py")
        self.assertEqual(self.verify()[0], 1)

    def test_comment_only_change_owes_nothing(self):
        self.config('{"governance": {"enforceDocObligations": true}}')
        self.stage("engine/a.py", "# just a comment\n")
        self.assertEqual(self.verify()[0], 0)

    def test_project_that_did_not_opt_in_is_not_checked(self):
        self.stage("engine/a.py")
        code, out = self.verify()
        self.assertEqual(code, 0, out)
        self.assertIn("kapalı", out)

    def test_explicitly_disabled_project_is_not_checked(self):
        self.config('{"governance": {"enforceDocObligations": false}}')
        self.stage("engine/a.py")
        self.assertEqual(self.verify()[0], 0)


if __name__ == "__main__":
    unittest.main()
