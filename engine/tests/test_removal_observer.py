#!/usr/bin/env python3
"""Removal observer: deletions made outside the hook path are seen, and legitimate feature removal stays quiet."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine.removal_observer import deleted_paths, is_test_path, observe_removals


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True)


class RemovalObserverTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="gg_removal_"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        _git(self.root, "init", "-q")
        _git(self.root, "config", "user.email", "t@example.com")
        _git(self.root, "config", "user.name", "t")
        self.files = {
            "src/media/mediaService.ts": "export const m = 1;\n",
            "src/other/keep.ts": "export const k = 1;\n",
            "tests/mediaService.test.ts": "import { m } from '../src/media/mediaService';\n",
            "tests/curatedSync.test.ts": "import { m } from '../src/media/mediaService';\n",
            "tests/keep.test.ts": "import { k } from '../src/other/keep';\n",
            "tests/orphan.test.ts": "it('x', () => {});\n",
        }
        for rel, text in self.files.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "init")

    def _rm(self, *rels: str) -> None:
        for rel in rels:
            (self.root / rel).unlink()

    def test_is_test_path(self):
        self.assertTrue(is_test_path("tests/a.ts"))
        self.assertTrue(is_test_path("src/a.test.tsx"))
        self.assertTrue(is_test_path("pkg/test_a.py"))
        self.assertFalse(is_test_path("src/media/mediaService.ts"))

    def test_clean_tree_reports_nothing(self):
        self.assertEqual(deleted_paths(self.root), [])
        self.assertEqual(observe_removals(self.root), {"deleted": [], "suspicious_tests": []})

    def test_shell_style_deletion_is_seen(self):
        self._rm("src/media/mediaService.ts")
        self.assertEqual(observe_removals(self.root)["deleted"], ["src/media/mediaService.ts"])

    def test_staged_deletion_is_seen(self):
        _git(self.root, "rm", "-q", "src/other/keep.ts")
        self.assertEqual(deleted_paths(self.root), ["src/other/keep.ts"])

    def test_feature_removal_with_its_tests_is_not_suspicious(self):
        self._rm("src/media/mediaService.ts", "tests/mediaService.test.ts", "tests/curatedSync.test.ts")
        result = observe_removals(self.root)
        self.assertEqual(len(result["deleted"]), 3)
        self.assertEqual(result["suspicious_tests"], [])

    def test_alias_and_js_extension_import_resolves_to_deleted_ts_source(self):
        path = self.root / "tests" / "aliased.test.ts"
        path.write_text("import { m } from '@/media/mediaService.js';\n", encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "alias test")
        self._rm("src/media/mediaService.ts", "tests/aliased.test.ts")
        self.assertEqual(observe_removals(self.root)["suspicious_tests"], [])

    def test_test_deleted_but_subject_remains_is_suspicious(self):
        self._rm("tests/keep.test.ts")
        self.assertEqual(observe_removals(self.root)["suspicious_tests"], ["tests/keep.test.ts"])

    def test_test_without_resolvable_subject_is_suspicious(self):
        self._rm("src/media/mediaService.ts", "tests/orphan.test.ts")
        self.assertEqual(observe_removals(self.root)["suspicious_tests"], ["tests/orphan.test.ts"])

    def test_each_deletion_is_reported_once(self):
        self._rm("tests/keep.test.ts")
        self.assertEqual(len(observe_removals(self.root)["suspicious_tests"]), 1)
        self.assertEqual(observe_removals(self.root), {"deleted": [], "suspicious_tests": []})

    def test_restored_file_is_reported_again_when_deleted_again(self):
        self._rm("tests/keep.test.ts")
        observe_removals(self.root)
        _git(self.root, "checkout", "--", "tests/keep.test.ts")
        observe_removals(self.root)
        self._rm("tests/keep.test.ts")
        self.assertEqual(observe_removals(self.root)["deleted"], ["tests/keep.test.ts"])

    def test_non_git_directory_reports_nothing(self):
        plain = Path(tempfile.mkdtemp(prefix="gg_plain_"))
        self.addCleanup(shutil.rmtree, plain, ignore_errors=True)
        self.assertEqual(observe_removals(plain), {"deleted": [], "suspicious_tests": []})


if __name__ == "__main__":
    unittest.main()
