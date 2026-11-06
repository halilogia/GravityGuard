"""Tests for Stop Hook Ratchet Gate integration in GravityGuard."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from gravityguard_engine.debt_ratchet import (
    evaluate_file_ratchet,
    save_debt_ratchet,
    load_debt_ratchet
)


class TestStopRatchetGate(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="gg_stop_ratchet_")
        self.project_root = self.test_dir

        # Initialize git repo in test dir so git status works
        subprocess.run(["git", "init"], cwd=self.project_root, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.project_root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.project_root, check=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_stop_hook_detects_ratchet_regression(self):
        # Create a monolithic file with 600 lines
        file_path = os.path.join(self.project_root, "monolith.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join([f"x = {i}" for i in range(600)]))

        # Commit initial baseline
        subprocess.run(["git", "add", "."], cwd=self.project_root, check=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=self.project_root, capture_output=True, check=True)

        # Baseline established at 600
        evaluate_file_ratchet(self.project_root, file_path, threshold=500)

        # Now agent modifies file, adding 30 lines (630 lines)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join([f"x = {i}" for i in range(630)]))

        from gravityguard_engine.debt_ratchet import get_session_changed_files, evaluate_changed_files_ratchet
        changed = get_session_changed_files(self.project_root)
        self.assertIn(os.path.normpath(file_path), [os.path.normpath(p) for p in changed])

        regressions = evaluate_changed_files_ratchet(self.project_root, changed, threshold=500)
        self.assertEqual(len(regressions), 1)
        rel_f, base_l, delta_l, reg_msg = regressions[0]
        self.assertEqual(rel_f, "monolith.py")
        self.assertEqual(base_l, 600)
        self.assertEqual(delta_l, 30)
        self.assertIn("Ratchet Regresyonu", reg_msg)


if __name__ == "__main__":
    unittest.main()
