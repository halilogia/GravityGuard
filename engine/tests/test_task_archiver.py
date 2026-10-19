import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine.task_archiver import archive_completed_tasks


class TestTaskArchiver(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gg_test_archiver_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_archive_below_threshold_does_nothing(self):
        t_file = self.tmp / "tasks.md"
        t_file.write_text("- [ ] task 1\n- [x] done 1\n- [x] done 2\n", encoding="utf-8")

        res = archive_completed_tasks(t_file, threshold=5)
        self.assertFalse(res["performed"])
        self.assertEqual(res["archived_count"], 0)
        self.assertEqual(res["retained_done_count"], 2)
        self.assertFalse((self.tmp / "taskslog.md").exists())

    def test_archive_above_threshold_retains_recent(self):
        t_file = self.tmp / "tasks.md"
        lines = [
            "# Tasks",
            "- [ ] active 1",
            "- [x] done 1",
            "- [x] done 2",
            "- [x] done 3",
            "- [x] done 4",
            "- [x] done 5",
            "- [x] done 6",
            "- [ ] active 2"
        ]
        t_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Threshold=4, keep_recent=2 -> 6 done > 4, so 6 - 2 = 4 archived
        res = archive_completed_tasks(t_file, threshold=4, keep_recent=2, date_str="2026-10-19")
        self.assertTrue(res["performed"])
        self.assertEqual(res["archived_count"], 4)
        self.assertEqual(res["retained_done_count"], 2)

        # Check tasks.md content
        content = t_file.read_text(encoding="utf-8")
        self.assertNotIn("done 1", content)
        self.assertNotIn("done 4", content)
        self.assertIn("done 5", content)
        self.assertIn("done 6", content)
        self.assertIn("active 1", content)
        self.assertIn("active 2", content)

        # Check taskslog.md content
        log_file = self.tmp / "taskslog.md"
        self.assertTrue(log_file.exists())
        log_content = log_file.read_text(encoding="utf-8")
        self.assertIn("## [2026-10-19]", log_content)
        self.assertIn("- [x] done 1", log_content)
        self.assertIn("- [x] done 4", log_content)
        self.assertNotIn("- [x] done 5", log_content)

    def test_archive_force_mode(self):
        t_file = self.tmp / "tasks.md"
        t_file.write_text("- [x] immediate done\n", encoding="utf-8")

        res = archive_completed_tasks(t_file, force=True, date_str="2026-10-19")
        self.assertTrue(res["performed"])
        self.assertEqual(res["archived_count"], 1)
        self.assertTrue((self.tmp / "taskslog.md").exists())


if __name__ == "__main__":
    unittest.main()
