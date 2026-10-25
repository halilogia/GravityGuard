#!/usr/bin/env python3
"""Unit tests for tools/generate_architecture.py."""
import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

_TOOL = Path(__file__).resolve().parents[2] / "tools" / "generate_architecture.py"
_spec = importlib.util.spec_from_file_location("generate_architecture", _TOOL)
ga = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ga)


def _write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class GenerateArchitectureTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        _write(self.root, "package.json", '{"version": "9.9.9"}')
        _write(self.root, "engine/gravityguard_engine/security_rules.py", "a = 1\n\n\nb = 2\n")
        _write(self.root, "engine/gravityguard_engine/security_audit.py", "x = 1\n")
        _write(self.root, "engine/gravityguard_engine/governance.py", "g = 1\ng2 = 2\n")
        _write(self.root, "engine/gravityguard_engine/__pycache__/junk.py", "z = 1\n")
        _write(self.root, "engine/tests/test_a.py", "def test_one(): pass\n    def test_two(self): pass\n")
        _write(self.root, "src/extension.ts", "export const a = 1;\n")
        _write(self.root, "src/webview/client.ts", "export const w = 1;\n")
        _write(self.root, "tests/x.test.mjs", "test('a', () => {});\nit('b', () => {});\n")
        _write(self.root, "plugin/hook.py", "h = 1\n")
        _write(self.root, "tests/fixtures/ignored.py", "i = 1\n")

    def test_scan_skips_noise_and_sorts(self):
        files = ga.scan_files(self.root)
        self.assertEqual(files, sorted(files))
        self.assertIn("src/extension.ts", files)
        self.assertFalse(any("__pycache__" in f or "fixtures" in f for f in files))

    def test_loc_counts_non_empty_only(self):
        self.assertEqual(ga.count_loc(self.root, "engine/gravityguard_engine/security_rules.py"), 2)
        self.assertEqual(ga.count_loc(self.root, "missing.py"), 0)

    def test_test_counting(self):
        self.assertEqual(ga.count_tests(self.root, "engine/tests/test_a.py"), 2)
        self.assertEqual(ga.count_tests(self.root, "tests/x.test.mjs"), 2)
        self.assertEqual(ga.count_tests(self.root, "src/extension.ts"), 0)

    def test_metrics_layers(self):
        m = ga.collect_metrics(self.root)
        by = {l["name"]: l for l in m["layers"]}
        self.assertEqual(by["Tier 1 Fast-Path Guardrail"]["files"], 1)
        self.assertEqual(by["Tier 4 Deep-Path Güvenlik Denetçisi"]["files"], 1)
        self.assertEqual(by["Yönetişim & Yaşam Döngüsü"]["loc"], 2)
        self.assertEqual(by["Extension UI & Client"]["files"], 2)
        self.assertEqual(m["test_files"], 2)
        self.assertEqual(m["test_count"], 4)
        self.assertEqual(m["total_files"], len(m["files"]))

    def test_markdown_contents(self):
        md = ga.render_markdown(self.root, today="2026-01-02")
        self.assertIn("2026-01-02", md)
        self.assertIn("9.9.9", md)
        self.assertIn("```mermaid", md)
        self.assertIn("Tier 4", md)
        self.assertIn("security_rules.py", md)
        self.assertIn("└── ", md)

    def test_check_missing_file_fails(self):
        code, msg = ga.check(self.root, "OUT.md")
        self.assertEqual(code, 1)
        self.assertIn("bulunamadı", msg)

    def test_main_generate_then_check_ok(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(ga.main(["--output", "OUT.md"], root=self.root), 0)
            self.assertEqual(ga.main(["--check", "--output", "OUT.md"], root=self.root), 0)

    def test_check_ignores_date_line(self):
        with redirect_stdout(io.StringIO()):
            ga.main(["--output", "OUT.md"], root=self.root)
        out = self.root / "OUT.md"
        lines = out.read_text(encoding="utf-8").splitlines()
        lines = [ga.DATE_PREFIX + " 1999-01-01" if l.startswith(ga.DATE_PREFIX) else l for l in lines]
        out.write_text("\n".join(lines), encoding="utf-8")
        self.assertEqual(ga.check(self.root, "OUT.md")[0], 0)

    def test_check_detects_stale(self):
        with redirect_stdout(io.StringIO()):
            ga.main(["--output", "OUT.md"], root=self.root)
        _write(self.root, "src/new_module.ts", "export const n = 1;\n")
        err = io.StringIO()
        with redirect_stderr(err):
            code = ga.main(["--check", "--output", "OUT.md"], root=self.root)
        self.assertEqual(code, 1)
        self.assertIn("new_module.ts", err.getvalue())


if __name__ == "__main__":
    unittest.main()
