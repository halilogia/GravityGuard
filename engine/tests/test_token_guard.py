#!/usr/bin/env python3
"""Unit tests for the GravityGuard token output guard."""
import os
import sys
import tempfile
import unittest
from unittest import mock

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine.token_guard import (
    evaluate_command_guard,
    evaluate_read_guard,
    evaluate_token_guard,
)


class TokenGuardTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="gg_token_guard_")
        self.big = os.path.join(self.dir, "big.py")
        with open(self.big, "w", encoding="utf-8") as handle:
            for i in range(6000):
                handle.write(f"value_{i} = compute_value({i})  # padding line\n")
        self.small = os.path.join(self.dir, "small.py")
        with open(self.small, "w", encoding="utf-8") as handle:
            handle.write("print('hello')\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    # ------------------------------------------------------------------ code outline rule
    def _code_file(self, name, lines):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as handle:
            for i in range(lines):
                handle.write(f"def f{i}(): return {i}\n")
        return path

    def test_unbounded_read_of_long_source_points_to_token_lens(self):
        path = self._code_file("mid.ts", 900)  # far below 150 KB, still a whole-file read
        result = evaluate_read_guard("read", {"file_path": path}, cwd=self.dir)
        self.assertEqual(result.level, "deny")
        self.assertIn("read_outline", result.reason)

    def test_claude_offset_limit_window_is_allowed(self):
        path = self._code_file("mid.py", 900)
        self.assertIsNone(evaluate_read_guard("read", {"file_path": path, "offset": 200, "limit": 300}, cwd=self.dir))
        self.assertIsNotNone(evaluate_read_guard("read", {"file_path": path, "limit": 800}, cwd=self.dir))

    def test_short_source_and_long_non_code_files_are_allowed(self):
        self.assertIsNone(evaluate_read_guard("read", {"file_path": self._code_file("ok.py", 500)}, cwd=self.dir))
        notes = os.path.join(self.dir, "notes.md")
        with open(notes, "w", encoding="utf-8") as handle:
            handle.write("line\n" * 3000)
        self.assertIsNone(evaluate_read_guard("read", {"file_path": notes}, cwd=self.dir))

    def test_images_and_pdfs_are_not_line_checked(self):
        for name in ("shot.png", "doc.pdf"):
            path = os.path.join(self.dir, name)
            with open(path, "wb") as handle:
                handle.write(b"\x89PNG\r\n" + b"\n" * 300_000)
            self.assertIsNone(evaluate_read_guard("read", {"file_path": path}, cwd=self.dir))

    def test_tail_of_long_source_is_allowed(self):
        path = self._code_file("tail.gd", 900)
        self.assertIsNone(evaluate_read_guard("read", {"file_path": path, "offset": 500}, cwd=self.dir))

    # ------------------------------------------------------------------ reads
    def test_full_read_of_big_file_is_denied(self):
        result = evaluate_read_guard("read_file", {"Path": self.big}, cwd=self.dir)
        self.assertIsNotNone(result)
        self.assertEqual(result.level, "deny")
        self.assertEqual(result.rule_id, "TOOL_OUTPUT_BLOAT")

    def test_bounded_range_is_allowed(self):
        args = {"Path": self.big, "StartLine": 100, "EndLine": 500}
        self.assertIsNone(evaluate_read_guard("read_file", args, cwd=self.dir))

    def test_oversized_range_is_denied(self):
        args = {"Path": self.big, "StartLine": 1, "EndLine": 2000}
        result = evaluate_read_guard("read_file", args, cwd=self.dir)
        self.assertIsNotNone(result)
        self.assertEqual(result.level, "deny")

    def test_start_only_with_large_tail_is_denied(self):
        args = {"Path": self.big, "StartLine": 1}
        result = evaluate_read_guard("read_file", args, cwd=self.dir)
        self.assertIsNotNone(result)
        self.assertEqual(result.level, "deny")

    def test_small_file_is_allowed(self):
        self.assertIsNone(evaluate_read_guard("read_file", {"Path": self.small}, cwd=self.dir))

    def test_non_read_tool_is_ignored(self):
        self.assertIsNone(evaluate_read_guard("run_command", {"CommandLine": "dir /s"}, cwd=self.dir))

    # --------------------------------------------------------------- commands
    def test_recursive_dir_is_warned(self):
        result = evaluate_command_guard("run_command", {"CommandLine": "dir /s /b"}, cwd=self.dir)
        self.assertIsNotNone(result)
        self.assertEqual(result.level, "warn")

    def test_recursive_getchilditem_is_warned(self):
        result = evaluate_command_guard(
            "run_command", {"CommandLine": "Get-ChildItem -Path . -Recurse"}, cwd=self.dir
        )
        self.assertIsNotNone(result)

    def test_limited_recursive_listing_is_allowed(self):
        cmd = "Get-ChildItem -Path . -Recurse | Select-Object -First 20"
        self.assertIsNone(evaluate_command_guard("run_command", {"CommandLine": cmd}, cwd=self.dir))

    def test_unbounded_git_log_is_warned(self):
        self.assertIsNotNone(evaluate_command_guard("run_command", {"CommandLine": "git log"}, cwd=self.dir))

    def test_bounded_git_log_is_allowed(self):
        self.assertIsNone(evaluate_command_guard("run_command", {"CommandLine": "git log -n 10"}, cwd=self.dir))

    def test_short_count_git_log_is_allowed(self):
        self.assertIsNone(evaluate_command_guard("bash", {"command": "git log --oneline -5"}, cwd=self.dir))
        self.assertIsNone(evaluate_command_guard("bash", {"command": "git log -20 --stat"}, cwd=self.dir))
        self.assertIsNotNone(evaluate_command_guard("bash", {"command": "git log --since=2026-01-01"}, cwd=self.dir))

    def test_bare_git_diff_is_warned(self):
        self.assertIsNotNone(evaluate_command_guard("run_command", {"CommandLine": "git diff"}, cwd=self.dir))

    def test_git_diff_stat_is_allowed(self):
        self.assertIsNone(evaluate_command_guard("run_command", {"CommandLine": "git diff --stat"}, cwd=self.dir))

    def test_cat_big_file_is_warned(self):
        result = evaluate_command_guard("run_command", {"CommandLine": f"cat {self.big}"}, cwd=self.dir)
        self.assertIsNotNone(result)

    def test_cat_small_file_is_allowed(self):
        self.assertIsNone(evaluate_command_guard("run_command", {"CommandLine": f"cat {self.small}"}, cwd=self.dir))

    def test_depth_limited_or_filtered_output_is_not_warned(self):
        for cmd in (
            "Get-ChildItem -Recurse -Depth 2",
            "Get-ChildItem -Recurse | Select-Object Name",
            "Get-ChildItem -Recurse -Name | Select -First 30",
            "dir /s /b | findstr /i foo",
            "find / -name x | head -20",
            "git log | Select-Object -First 5",
            "git log | tail -n 5",
            "Get-ChildItem -Recurse | Measure-Object",
        ):
            self.assertIsNone(evaluate_command_guard("run_command", {"CommandLine": cmd}, cwd=self.dir), cmd)
        self.assertIsNotNone(evaluate_command_guard("run_command", {"CommandLine": "Get-ChildItem -Recurse"}, cwd=self.dir))

    def test_warning_is_said_once_per_conversation(self):
        log_dir = tempfile.mkdtemp(prefix="gg_token_once_")
        with mock.patch.dict(os.environ, {"GRAVITYGUARD_LOG_DIR": log_dir}):
            args = {"CommandLine": "git log"}
            first = evaluate_token_guard("run_command", args, cwd=self.dir, conversation_id="conv-a")
            again = evaluate_token_guard("run_command", args, cwd=self.dir, conversation_id="conv-a")
            other = evaluate_token_guard("run_command", args, cwd=self.dir, conversation_id="conv-b")
            no_id = evaluate_token_guard("run_command", args, cwd=self.dir)
        self.assertIsNotNone(first)
        self.assertIsNone(again)
        self.assertIsNotNone(other)
        self.assertIsNotNone(no_id)

    def test_deny_is_never_suppressed_by_the_once_rule(self):
        log_dir = tempfile.mkdtemp(prefix="gg_token_deny_")
        with mock.patch.dict(os.environ, {"GRAVITYGUARD_LOG_DIR": log_dir}):
            for _ in range(2):
                result = evaluate_token_guard("read_file", {"Path": self.big}, cwd=self.dir, conversation_id="conv-d")
                self.assertEqual(result.level, "deny")

    def test_deny_beats_warn(self):
        args = {"Path": self.big, "CommandLine": "dir /s"}
        result = evaluate_token_guard("run_command", args, cwd=self.dir)
        self.assertIsNotNone(result)
        self.assertEqual(result.level, "warn")


if __name__ == "__main__":
    unittest.main()
