"""Unit tests for GravityGuard Debt Ratchet Module."""

import os
import shutil
import subprocess
import tempfile
import unittest

from gravityguard_engine.debt_ratchet import (
    DEFAULT_RATCHET_THRESHOLD,
    is_test_or_exempt_file,
    count_clean_lines,
    load_debt_ratchet,
    save_debt_ratchet,
    evaluate_file_ratchet,
    evaluate_changed_files_ratchet,
    get_project_debt_summary,
    get_session_changed_files,
    get_ratchet_store_path,
    scan_project,
)


class TestDebtRatchet(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="gg_ratchet_test_")
        self.project_root = self.test_dir

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_exemptions(self):
        self.assertTrue(is_test_or_exempt_file("tests/test_foo.py"))
        self.assertTrue(is_test_or_exempt_file("src/foo.test.ts"))
        self.assertTrue(is_test_or_exempt_file("src/foo.spec.js"))
        self.assertTrue(is_test_or_exempt_file("README.md"))
        self.assertTrue(is_test_or_exempt_file("config.json"))
        self.assertFalse(is_test_or_exempt_file("src/engine.py"))
        self.assertFalse(is_test_or_exempt_file("src/parser.ts"))

    def test_count_clean_lines(self):
        content = "line 1\n\n  \nline 2\nline 3\n"
        self.assertEqual(count_clean_lines(content), 3)

    def test_file_under_threshold_no_debt(self):
        file_path = os.path.join(self.project_root, "small.py")
        content = "\n".join([f"x = {i}" for i in range(100)])
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        is_reg, base, delta, msg = evaluate_file_ratchet(
            project_root=self.project_root,
            file_path=file_path,
            threshold=500
        )
        self.assertFalse(is_reg)
        self.assertEqual(delta, 0)
        self.assertEqual(msg, "")

    def test_first_discovery_over_threshold_locks_baseline(self):
        file_path = os.path.join(self.project_root, "monolith.py")
        content = "\n".join([f"x = {i}" for i in range(600)])
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        # First evaluation: baseline is established at 600 (no regression yet)
        is_reg, base, delta, msg = evaluate_file_ratchet(
            project_root=self.project_root,
            file_path=file_path,
            threshold=500
        )
        self.assertFalse(is_reg)
        self.assertEqual(base, 600)
        self.assertEqual(delta, 0)

        # Verify saved in ratchet store
        data = load_debt_ratchet(self.project_root)
        self.assertIn("monolith.py", data["files"])
        self.assertEqual(data["files"]["monolith.py"]["baseline_loc"], 600)

    def test_regression_triggers_block(self):
        file_path = os.path.join(self.project_root, "monolith.py")
        content = "\n".join([f"x = {i}" for i in range(600)])
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Lock baseline at 600
        evaluate_file_ratchet(self.project_root, file_path, threshold=500)

        # Expand to 625 lines (+25 regression)
        expanded_content = "\n".join([f"x = {i}" for i in range(625)])
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(expanded_content)

        is_reg, base, delta, msg = evaluate_file_ratchet(
            self.project_root, file_path, threshold=500
        )
        self.assertTrue(is_reg)
        self.assertEqual(base, 600)
        self.assertEqual(delta, 25)
        self.assertIn("Ratchet Regresyonu", msg)
        self.assertIn("+25 satır yeni borç", msg)

    def test_improvement_permanently_lowers_baseline(self):
        file_path = os.path.join(self.project_root, "monolith.py")
        content = "\n".join([f"x = {i}" for i in range(600)])
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Lock baseline at 600
        evaluate_file_ratchet(self.project_root, file_path, threshold=500)

        # Refactor to 550 lines (-50 reduction)
        refactored = "\n".join([f"x = {i}" for i in range(550)])
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(refactored)

        is_reg, base, delta, msg = evaluate_file_ratchet(
            self.project_root, file_path, threshold=500
        )
        self.assertFalse(is_reg)
        self.assertEqual(base, 550)
        self.assertEqual(delta, -50)
        self.assertIn("Ratchet İyileşmesi", msg)

        # Verify new baseline is now locked at 550
        data = load_debt_ratchet(self.project_root)
        self.assertEqual(data["files"]["monolith.py"]["baseline_loc"], 550)

        # Now, if someone tries to grow it back to 560, it MUST be a regression against 550!
        grown = "\n".join([f"x = {i}" for i in range(560)])
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(grown)

        is_reg2, base2, delta2, msg2 = evaluate_file_ratchet(
            self.project_root, file_path, threshold=500
        )
        self.assertTrue(is_reg2)
        self.assertEqual(base2, 550)
        self.assertEqual(delta2, 10)

    def test_dropping_below_threshold_resolves_debt(self):
        file_path = os.path.join(self.project_root, "monolith.py")
        content = "\n".join([f"x = {i}" for i in range(600)])
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        evaluate_file_ratchet(self.project_root, file_path, threshold=500)

        # Fully modularize to 300 lines (below 500)
        modularized = "\n".join([f"x = {i}" for i in range(300)])
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(modularized)

        is_reg, base, delta, msg = evaluate_file_ratchet(
            self.project_root, file_path, threshold=500
        )
        self.assertFalse(is_reg)

        # File is no longer in debt store
        data = load_debt_ratchet(self.project_root)
        self.assertNotIn("monolith.py", data["files"])

    def test_evaluate_changed_files_ratchet(self):
        f1 = os.path.join(self.project_root, "clean.py")
        with open(f1, "w", encoding="utf-8") as f:
            f.write("\n".join([f"x = {i}" for i in range(100)]))

        f2 = os.path.join(self.project_root, "bad_regression.py")
        with open(f2, "w", encoding="utf-8") as f:
            f.write("\n".join([f"x = {i}" for i in range(700)]))
        # Lock baseline at 700
        evaluate_file_ratchet(self.project_root, f2, threshold=500)
        # Regress to 750
        with open(f2, "w", encoding="utf-8") as f:
            f.write("\n".join([f"x = {i}" for i in range(750)]))

        regressions = evaluate_changed_files_ratchet(
            project_root=self.project_root,
            changed_files=[f1, f2],
            threshold=500
        )
        self.assertEqual(len(regressions), 1)
        rel, base, delta, msg = regressions[0]
        self.assertEqual(rel, "bad_regression.py")
        self.assertEqual(base, 700)
        self.assertEqual(delta, 50)

    def _write(self, rel, lines):
        path = os.path.join(self.project_root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(f"x = {i}" for i in range(lines)))
        return path

    def _git(self, *args):
        subprocess.run(["git", *args], cwd=self.project_root, capture_output=True, check=True)

    def _init_repo(self):
        self._git("init")
        self._git("config", "user.name", "T")
        self._git("config", "user.email", "t@example.com")

    def test_exemption_ignores_parent_dirs_and_excluded_dirs(self):
        self.assertFalse(is_test_or_exempt_file("src/engine.py"))
        self.assertTrue(is_test_or_exempt_file("node_modules/pkg/index.js"))
        self.assertTrue(is_test_or_exempt_file("../outside.py"))
        # project living under a folder named tests must not be exempt
        path = self._write("tests_root/app.py", 600)
        self.assertEqual(evaluate_file_ratchet(self.project_root, path)[1], 600)

    def test_corrupt_store_is_moved_aside_not_silently_reset(self):
        store = get_ratchet_store_path(self.project_root)
        os.makedirs(os.path.dirname(store))
        with open(store, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(load_debt_ratchet(self.project_root)["files"], {})
        self.assertTrue(os.path.isfile(store + ".corrupt"))

    def test_garbage_baseline_does_not_crash(self):
        path = self._write("m.py", 600)
        save_debt_ratchet(self.project_root, {"files": {"m.py": {"baseline_loc": "abc"}}})
        is_reg, base, _, _ = evaluate_file_ratchet(self.project_root, path, threshold=500)
        self.assertEqual(base, 500)
        self.assertTrue(is_reg)

    def test_no_record_mode_never_writes_store(self):
        path = self._write("m.py", 600)
        evaluate_file_ratchet(self.project_root, path, auto_record_baseline=False)
        self.assertFalse(os.path.exists(get_ratchet_store_path(self.project_root)))

    def test_first_seen_baseline_comes_from_git_head(self):
        self._init_repo()
        path = self._write("old.py", 600)
        self._git("add", ".")
        self._git("commit", "-m", "i")
        self._write("old.py", 650)
        is_reg, base, delta, _ = evaluate_file_ratchet(self.project_root, path)
        self.assertTrue(is_reg)
        self.assertEqual((base, delta), (600, 50))

    def test_new_file_over_threshold_is_regression(self):
        self._init_repo()
        self._write("seed.py", 10)
        self._git("add", ".")
        self._git("commit", "-m", "i")
        path = self._write("brand_new.py", 620)
        is_reg, base, delta, _ = evaluate_file_ratchet(self.project_root, path)
        self.assertTrue(is_reg)
        self.assertEqual((base, delta), (500, 120))

    def test_changed_files_handles_untracked_dirs_spaces_and_deletes(self):
        self._init_repo()
        self._write("gone.py", 5)
        self._git("add", ".")
        self._git("commit", "-m", "i")
        os.remove(os.path.join(self.project_root, "gone.py"))
        new_dir = self._write("new dir/süper mod.py", 5)
        changed = [os.path.normpath(p) for p in get_session_changed_files(self.project_root)]
        self.assertIn(os.path.normpath(new_dir), changed)
        self.assertFalse(any(p.endswith("gone.py") for p in changed))

    def test_summary_skips_deleted_files_and_scan_registers(self):
        self._write("big.py", 700)
        self.assertEqual(scan_project(self.project_root), 1)
        self.assertEqual(get_project_debt_summary(self.project_root)["total_files_with_debt"], 1)
        os.remove(os.path.join(self.project_root, "big.py"))
        self.assertEqual(get_project_debt_summary(self.project_root)["total_files_with_debt"], 0)


if __name__ == "__main__":
    unittest.main()
