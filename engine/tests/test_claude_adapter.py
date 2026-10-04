#!/usr/bin/env python3
"""
Unit and end-to-end tests for the Claude Code adapter (plugin/claude-code/gravityguard_claude_hook.py).
"""
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

_ENGINE_DIR = Path(__file__).resolve().parent.parent
_ADAPTER = _ENGINE_DIR.parent / "plugin" / "claude-code" / "gravityguard_claude_hook.py"

_spec = importlib.util.spec_from_file_location("gravityguard_claude_hook", _ADAPTER)
adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adapter)


class TestTranslation(unittest.TestCase):
    def setUp(self):
        self.addCleanup(os.environ.pop, "CLAUDE_PROJECT_DIR", None)
        os.environ.pop("CLAUDE_PROJECT_DIR", None)

    def test_write_becomes_write_to_file(self):
        payload = adapter.to_engine_pretool({
            "session_id": "s1", "cwd": "/proj", "tool_name": "Write",
            "tool_input": {"file_path": "/proj/a.py", "content": "x = 1\n"},
        })
        self.assertEqual(payload["toolCall"]["name"], "write_to_file")
        self.assertEqual(payload["toolCall"]["args"], {"TargetFile": "/proj/a.py", "CodeContent": "x = 1\n"})

    def test_edit_becomes_replace_file_content(self):
        payload = adapter.to_engine_pretool({
            "session_id": "s1", "cwd": "/proj", "tool_name": "Edit",
            "tool_input": {"file_path": "/proj/a.py", "old_string": "a", "new_string": "b", "replace_all": True},
        })
        self.assertEqual(payload["toolCall"]["name"], "replace_file_content")
        args = payload["toolCall"]["args"]
        self.assertEqual((args["TargetContent"], args["ReplacementContent"], args["AllowMultiple"]), ("a", "b", True))

    def test_multiedit_becomes_multi_replace_file_content(self):
        payload = adapter.to_engine_pretool({
            "session_id": "s1", "cwd": "/proj", "tool_name": "MultiEdit",
            "tool_input": {"file_path": "/proj/a.py", "edits": [
                {"old_string": "a", "new_string": "b"}, {"old_string": "c", "new_string": "d", "replace_all": True}, "junk"]},
        })
        chunks = payload["toolCall"]["args"]["ReplacementChunks"]
        self.assertEqual([c["TargetContent"] for c in chunks], ["a", "c"])
        self.assertEqual([c["AllowMultiple"] for c in chunks], [False, True])

    def test_tools_without_file_rules_are_ignored(self):
        for name in ("Bash", "Read", "Grep", "NotebookEdit"):
            self.assertIsNone(adapter.to_engine_pretool({"session_id": "s1", "cwd": "/p", "tool_name": name, "tool_input": {}}))

    def test_conversation_id_is_provider_prefixed(self):
        self.assertEqual(adapter.conversation_id({"session_id": "abc"}), "claude:abc")
        self.assertEqual(adapter.conversation_id({}), "claude:default")

    def test_project_dir_wins_over_cwd_when_the_agent_has_changed_directory(self):
        event = {"session_id": "s1", "cwd": "/proj/sub", "tool_name": "Write", "tool_input": {"file_path": "/proj/a.py", "content": ""}}
        self.assertEqual(adapter.to_engine_pretool(event)["workspacePaths"], ["/proj/sub"])
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": "/proj"}):
            self.assertEqual(adapter.to_engine_pretool(event)["workspacePaths"], ["/proj"])
            self.assertEqual(adapter.to_engine_stop(event)["workspacePaths"], ["/proj"])


class TestAnswerTranslation(unittest.TestCase):
    def test_deny_is_a_claude_deny(self):
        out = adapter.from_engine_pretool({"decision": "deny", "reason": "no keys"})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecisionReason"], "no keys")

    def test_warning_is_context_only_and_never_an_allow(self):
        out = adapter.from_engine_pretool({"decision": "allow", "reason": "heads up"})
        hook_output = out["hookSpecificOutput"]
        self.assertEqual(hook_output["additionalContext"], "heads up")
        self.assertNotIn("permissionDecision", hook_output, "an allow would skip the user's own permission prompt")

    def test_clean_allow_says_nothing(self):
        self.assertIsNone(adapter.from_engine_pretool({"decision": "allow"}))
        self.assertIsNone(adapter.from_engine_pretool({"decision": "allow", "reason": ""}))

    def test_stop_continue_becomes_block(self):
        self.assertEqual(adapter.from_engine_stop({"decision": "continue", "reason": "tests missing"}),
                         {"decision": "block", "reason": "tests missing"})
        self.assertIsNone(adapter.from_engine_stop({"decision": "allow"}))


class TestHandle(unittest.TestCase):
    def test_second_stop_in_a_row_is_not_asked_again(self):
        with mock.patch.object(adapter, "run_engine", side_effect=AssertionError("engine must not run")):
            self.assertIsNone(adapter.handle({"session_id": "s1", "cwd": "/p", "stop_hook_active": True}, stop=True))

    def test_missing_engine_fails_open_with_a_note(self):
        event = {"session_id": "s1", "cwd": "/p", "tool_name": "Write", "tool_input": {"file_path": "/p/a.py", "content": "x"}}
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"GRAVITYGUARD_ENGINE": str(Path(tempfile.gettempdir()) / "no_such_engine.py")}):
            with redirect_stderr(err):
                self.assertIsNone(adapter.handle(event, stop=False))
        self.assertIn("engine not found", err.getvalue())


class TestEndToEnd(unittest.TestCase):
    """The adapter against the real engine, as Claude Code would run it (one process per hook call)."""

    def setUp(self):
        self.proj = tempfile.mkdtemp(prefix="gg_claude_e2e_")
        (Path(self.proj) / "tests").mkdir()
        (Path(self.proj) / ".git").write_text("gitdir: x", encoding="utf-8")
        (Path(self.proj) / "tests" / "test_base.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
        (Path(self.proj) / "util.py").write_text("def f():\n    x = 1\n    return x\n", encoding="utf-8")
        self.env = dict(os.environ, GRAVITYGUARD_LOG_DIR=str(Path(self.proj) / ".gglog"), GRAVITYGUARD_DISABLE_ASYNC="1",
                        CLAUDE_PROJECT_DIR=self.proj, PYTHONIOENCODING="utf-8")

    def tearDown(self):
        shutil.rmtree(self.proj, ignore_errors=True)

    def hook(self, session, tool=None, tool_input=None, stop=False, stop_hook_active=False):
        event = {"session_id": session, "cwd": self.proj, "hook_event_name": "Stop" if stop else "PreToolUse"}
        if tool:
            event.update(tool_name=tool, tool_input=tool_input)
        if stop_hook_active:
            event["stop_hook_active"] = True
        proc = subprocess.run([sys.executable, str(_ADAPTER)] + (["--stop"] if stop else []), input=json.dumps(event),
                              capture_output=True, text=True, encoding="utf-8", env=self.env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout.strip()
        return json.loads(out) if out else None

    def test_secret_in_a_new_file_is_denied(self):
        key = "sk-proj-" + "abcd1234" * 6
        out = self.hook("s1", "Write", {"file_path": os.path.join(self.proj, "app.py"), "content": f'KEY = "{key}"\n'})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertNotIn(key, json.dumps(out), "the deny reason must redact the token")

    def test_legacy_openai_key_is_denied(self):
        key = "sk-" + "Zx9Qw7Er5Ty3" * 4
        out = self.hook("s1", "Write", {"file_path": os.path.join(self.proj, "old.py"), "content": f'KEY = "{key}"\n'})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_prose_with_task_report_is_not_a_secret(self):
        out = self.hook("s1", "Write", {"file_path": os.path.join(self.proj, "notes.md"),
                                        "content": "demo task-report-cleanup-deepseekv4flash done\n"})
        self.assertIsNone(out)

    def test_silent_except_in_an_edit_is_denied(self):
        out = self.hook("s1", "Edit", {"file_path": os.path.join(self.proj, "util.py"), "old_string": "    x = 1\n",
                                       "new_string": "    try:\n        x = int('a')\n    except Exception:\n        pass\n"})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_shadow_mode_lets_the_silent_except_through(self):
        """The adoption path the adapter README recommends: observe a rule before enforcing it."""
        (Path(self.proj) / ".gravityguard.json").write_text(
            json.dumps({"rules": {"G1_SILENT_EXCEPTION": {"mode": "shadow"}}}), encoding="utf-8")
        out = self.hook("s1", "Edit", {"file_path": os.path.join(self.proj, "util.py"), "old_string": "    x = 1\n",
                                       "new_string": "    try:\n        x = int('a')\n    except Exception:\n        pass\n"})
        self.assertIsNone(out)

    def test_harmless_edit_is_silent(self):
        out = self.hook("s1", "Edit", {"file_path": os.path.join(self.proj, "util.py"), "old_string": "    return x\n",
                                       "new_string": "    return x + 1\n"})
        self.assertIsNone(out)

    def test_bash_is_not_inspected(self):
        self.assertIsNone(self.hook("s1", "Bash", {"command": "echo hi"}))

    def test_one_sessions_unfinished_work_does_not_block_another_sessions_stop(self):
        out = self.hook("A", "Write", {"file_path": os.path.join(self.proj, "foo.py"), "content": "def foo():\n    return 1\n"})
        self.assertIsNone(out, "production code without a test is a Stop-time obligation, not a deny")
        blocked = self.hook("A", stop=True)
        self.assertEqual(blocked["decision"], "block")
        self.assertIsNone(self.hook("B", stop=True), "session B touched nothing and must be allowed to stop")
        self.assertIsNone(self.hook("A", stop=True, stop_hook_active=True), "no second block in a row")


if __name__ == "__main__":
    unittest.main()
