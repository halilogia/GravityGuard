#!/usr/bin/env python3
"""STATIC_LINTER_DIAGNOSTIC: only findings on lines this edit touched, never for scratch files."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gravityguard_engine.diagnostics import read_recent_diagnostics


class DiagnosticsFilterTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="gg_diag_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.runtime = os.path.join(self.root, ".gravityguard", "runtime")
        os.makedirs(self.runtime)
        with open(os.path.join(self.runtime, "diagnostics.json"), "w", encoding="utf-8") as f:
            json.dump({"version": 1, "lastUpdated": 0, "entries": {}}, f)

    def _write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def _publish(self, path, errors):
        stamp = time.time()
        with open(os.path.join(self.runtime, "diagnostics.json"), "w", encoding="utf-8") as f:
            json.dump({"version": 1, "lastUpdated": stamp, "entries": {
                path: {"tool": "ruff", "timestamp": stamp, "errors": errors}}}, f)

    def test_error_on_unchanged_line_is_not_reported(self):
        path = self._write("src/a.py", "import os\nx = 1\ny = 2\n")
        read_recent_diagnostics(path)  # snapshot taken before the edit
        self._write("src/a.py", "import os\nx = 1\ny = 2\nz = 3\n")
        self._publish(path, [{"line": 1, "rule": "F401", "message": "os unused"}])
        self.assertEqual(read_recent_diagnostics(path), [])

    def test_error_on_changed_line_is_reported(self):
        path = self._write("src/b.py", "import os\nx = 1\n")
        read_recent_diagnostics(path)
        self._write("src/b.py", "import os\nx = 1\nunused = 2\n")
        self._publish(path, [{"line": 1, "rule": "F401", "message": "os unused"},
                             {"line": 3, "rule": "F841", "message": "unused var"}])
        result = read_recent_diagnostics(path)
        self.assertEqual(len(result), 1)
        self.assertIn("1 hata", result[0][1])
        self.assertIn("F841", result[0][1])

    def test_first_sight_of_a_file_reports_everything(self):
        path = self._write("src/c.py", "import os\n")
        self._publish(path, [{"line": 1, "rule": "F401", "message": "os unused"}])
        self.assertEqual(len(read_recent_diagnostics(path)), 1)

    def test_scratch_paths_are_skipped(self):
        for rel in ("scratch/s.py", "tmp/s.py", "temp/s.py", ".gemini/antigravity/scratch/abc/s.py"):
            path = self._write(rel, "import os\n")
            self._publish(path, [{"line": 1, "rule": "F401", "message": "os unused"}])
            self.assertEqual(read_recent_diagnostics(path), [], rel)


if __name__ == "__main__":
    unittest.main()
