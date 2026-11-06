import json
import sys
import tempfile
import unittest
from pathlib import Path

from gravityguard_engine import verification_gate as vg


class VerificationGateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_run_stage_records_pass_from_exit_code(self):
        entry = vg.run_stage(self.root, "compile", [sys.executable, "-c", "print('0 errors')"])
        self.assertEqual(entry["status"], "pass")
        self.assertEqual(entry["detail"], "0 errors")
        self.assertEqual(vg.load_report(self.root)["compile"]["exitCode"], 0)

    def test_run_stage_records_fail_with_stderr_tail(self):
        code = "import sys; print('2 failed', file=sys.stderr); sys.exit(3)"
        entry = vg.run_stage(self.root, "tests", [sys.executable, "-c", code])
        self.assertEqual(entry["status"], "fail")
        self.assertEqual(entry["detail"], "2 failed")
        self.assertEqual(entry["exitCode"], 3)

    def test_run_stage_rejects_unknown_stage_and_empty_command(self):
        with self.assertRaises(ValueError):
            vg.run_stage(self.root, "preview", [sys.executable, "-c", "pass"])
        with self.assertRaises(ValueError):
            vg.run_stage(self.root, "compile", [])

    def test_stages_are_kept_side_by_side(self):
        vg.run_stage(self.root, "compile", [sys.executable, "-c", "pass"])
        vg.run_stage(self.root, "tests", [sys.executable, "-c", "raise SystemExit(1)"])
        report = json.loads(vg.report_path(self.root).read_text(encoding="utf-8"))
        self.assertEqual(report["compile"]["status"], "pass")
        self.assertEqual(report["tests"]["status"], "fail")

    def test_preview_needs_screenshot_and_zero_console_errors(self):
        self.assertEqual(vg.record_preview(self.root, "missing.png", 0)["status"], "fail")
        shot = self.root / "preview.png"
        shot.write_bytes(b"\x89PNG data")
        self.assertEqual(vg.record_preview(self.root, "preview.png", 2)["detail"], "console.error: 2")
        entry = vg.record_preview(self.root, str(shot), 0)
        self.assertEqual(entry["status"], "pass")
        self.assertEqual(entry["consoleErrors"], 0)

    def test_corrupt_report_reads_as_empty(self):
        path = vg.report_path(self.root)
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(vg.load_report(self.root), {})
        self.assertEqual(vg.stage_summary({})[0].split(), ["compile", "pending"])


if __name__ == "__main__":
    unittest.main()
