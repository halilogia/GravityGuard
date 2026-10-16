#!/usr/bin/env python3
"""
Unit tests for GravityGuard Test Evidence Airbag (T1, T2, T3).
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine.test_evidence import (
    check_t1_missing_test,
    check_t2_observable_assertion,
    check_t3_symbol_to_test_link,
    is_exempt_from_test_evidence,
    evaluate_test_evidence,
    resolve_candidate_test_file,
    resolve_subsystem_test_files,
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


class TestSubsystemMappingAndMtimeExemption(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "src" / "webview").mkdir(parents=True)
        (self.root / "src" / "other").mkdir(parents=True)
        (self.root / "tests").mkdir()
        self.prod = (self.root / "src" / "webview" / "layout.ts").as_posix()
        (self.root / "src" / "webview" / "layout.ts").write_text("export function renderLayout() {}\n")
        (self.root / "src" / "other" / "plain.ts").write_text("export function plain() {}\n")

    def _write_test(self, name: str, content: str = "renderLayout();\n") -> str:
        path = self.root / "tests" / name
        path.write_text(content, encoding="utf-8")
        return path.as_posix()

    def test_webview_file_accepts_subsystem_integration_test(self):
        tasks_test = self._write_test("tasks.test.mjs")
        files = resolve_subsystem_test_files(self.prod)
        self.assertIn(tasks_test, files)
        warned, msg, cand = check_t1_missing_test(self.prod, "export function renderLayout() {}")
        self.assertFalse(warned)
        self.assertEqual(cand, tasks_test)

    def test_unmapped_production_file_still_warns(self):
        self._write_test("tasks.test.mjs")
        plain = (self.root / "src" / "other" / "plain.ts").as_posix()
        self.assertEqual(resolve_subsystem_test_files(plain), [])
        warned, msg, cand = check_t1_missing_test(plain, "export function plain() {}")
        self.assertTrue(warned)
        self.assertIn("T1_MISSING_RELATED_TEST", msg)
        self.assertIsNone(cand)

    def test_config_subsystem_mappings_extend_defaults(self):
        custom = self._write_test("custom_ui.test.mjs")
        plain = (self.root / "src" / "other" / "plain.ts").as_posix()
        cfg = {"testEvidence": {"subsystemMappings": {"src/other/**": ["tests/custom_*.test.mjs"]}}}
        self.assertEqual(resolve_subsystem_test_files(plain, cfg), [custom])
        warned, _, cand = check_t1_missing_test(plain, "export function plain() {}", cfg)
        self.assertFalse(warned)
        self.assertEqual(cand, custom)

    def test_config_mapping_overrides_default_glob_key(self):
        self._write_test("tasks.test.mjs")
        custom = self._write_test("only_this.test.mjs")
        cfg = {"testEvidence": {"subsystemMappings": {"src/webview/**": "tests/only_this.test.mjs"}}}
        self.assertEqual(resolve_subsystem_test_files(self.prod, cfg), [custom])

    def test_stale_test_mtime_does_not_warn(self):
        test_path = self._write_test("layout.test.mjs")
        stale = time.time() - 86400
        os.utime(test_path, (stale, stale))
        for cfg in (None, {"testEvidence": {"sessionWindowSeconds": 1}}):
            warned, msg, cand = check_t1_missing_test(self.prod, "export function renderLayout() {}", cfg)
            self.assertFalse(warned, msg)
            self.assertIsNotNone(cand)

    def test_evaluate_stale_subsystem_test_yields_no_t1_and_t3_uses_union(self):
        self._write_test("tasks.test.mjs", "// unrelated\n")
        self._write_test("knowledge.test.mjs", "renderLayout();\n")
        added = "export function renderLayout() {}\n"
        warnings, actions = evaluate_test_evidence(
            self.prod, False, added.splitlines(), added,
            projected_content=added, added_line_numbers={1},
            is_python=False, is_ts=True,
        )
        self.assertEqual(warnings, [])
        self.assertIsNone(actions["record_test"])


if __name__ == "__main__":
    unittest.main()
