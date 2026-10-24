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
        # A path that is absolute on THIS platform and Python version (os.path.isabs("/x") differs between them on
        # Windows), so the adapter must hand it over unchanged.
        target = os.path.abspath("/proj/a.py")
        payload = adapter.to_engine_pretool({
            "session_id": "s1", "cwd": "/proj", "tool_name": "Write",
            "tool_input": {"file_path": target, "content": "x = 1\n"},
        })
        self.assertEqual(payload["toolCall"]["name"], "write_to_file")
        self.assertEqual(payload["toolCall"]["args"], {"TargetFile": target, "CodeContent": "x = 1\n"})

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
                {"old_string": "a", "new_string": "b"}, {"old_string": "c", "new_string": "d", "replace_all": True}]},
        })
        chunks = payload["toolCall"]["args"]["ReplacementChunks"]
        self.assertEqual([c["TargetContent"] for c in chunks], ["a", "c"])
        self.assertEqual([c["AllowMultiple"] for c in chunks], [False, True])

    def test_tools_without_file_rules_are_ignored(self):
        for name in ("Bash", "Read", "Grep"):
            self.assertIsNone(adapter.to_engine_pretool({"session_id": "s1", "cwd": "/p", "tool_name": name, "tool_input": {}}))

    def test_notebook_edit_becomes_a_write_of_the_new_cell_source(self):
        target = os.path.abspath("/proj/a.ipynb")
        payload = adapter.to_engine_pretool({
            "session_id": "s1", "cwd": "/proj", "tool_name": "NotebookEdit",
            "tool_input": {"notebook_path": target, "new_source": "x = 1\n", "cell_id": "c1"},
        })
        self.assertEqual(payload["toolCall"]["name"], "write_to_file")
        self.assertEqual(payload["toolCall"]["args"], {"TargetFile": target, "CodeContent": "x = 1\n"})

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
    def test_stop_hook_active_does_not_short_circuit_the_engine(self):
        """Claude Code continuing because of this hook is no reason to let the agent leave: the engine decides."""
        answer = {"decision": "continue", "reason": "tests missing"}
        with mock.patch.object(adapter, "run_engine", return_value=answer) as run:
            out = adapter.handle({"session_id": "s1", "cwd": "/p", "stop_hook_active": True}, stop=True)
        self.assertEqual(out, {"decision": "block", "reason": "tests missing"})
        run.assert_called_once()

    def test_missing_engine_denies_with_a_note(self):
        event = {"session_id": "s1", "cwd": "/p", "tool_name": "Write", "tool_input": {"file_path": "/p/a.py", "content": "x"}}
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"GRAVITYGUARD_ENGINE": str(Path(tempfile.gettempdir()) / "no_such_engine.py")}):
            with redirect_stderr(err):
                self.assertEqual(adapter.handle(event, stop=False)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("engine not found", err.getvalue())


class TestEmergencyDeny(unittest.TestCase):
    """Engine dead: harmless work still passes, an unrecoverable leak does not."""

    KEY = "sk-proj-" + "abcd1234" * 6
    PEM = "-----BEGIN RSA " + "PRIVATE KEY-----\nabc"  # split so this file itself never trips the secret guard

    def run_without_engine(self, tool, tool_input, **env):
        event = {"session_id": "s1", "cwd": "/p", "tool_name": tool, "tool_input": tool_input}
        missing = str(Path(tempfile.gettempdir()) / "no_such_engine.py")
        with mock.patch.dict(os.environ, {"GRAVITYGUARD_ENGINE": missing, **env}), redirect_stderr(io.StringIO()):
            return adapter.handle(event, stop=False)

    def assertDenied(self, out):
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertNotIn(self.KEY, json.dumps(out), "the deny reason must not echo the secret")

    def test_secret_write_is_denied_without_the_engine(self):
        self.assertDenied(self.run_without_engine("Write", {"file_path": "/p/a.py", "content": f'K = "{self.KEY}"'}))

    def test_secret_in_edit_multiedit_and_notebook_is_denied_without_the_engine(self):
        self.assertDenied(self.run_without_engine("Edit", {"file_path": "/p/a.py", "old_string": "a", "new_string": self.KEY}))
        self.assertDenied(self.run_without_engine("MultiEdit", {"file_path": "/p/a.py", "edits": [
            {"old_string": "a", "new_string": "b"}, {"old_string": "c", "new_string": self.KEY}]}))
        self.assertDenied(self.run_without_engine("NotebookEdit", {"notebook_path": "/p/a.ipynb", "new_source": self.KEY}))

    def test_private_key_and_github_token_are_denied_without_the_engine(self):
        for text in (self.PEM, "t = 'ghp_" + "a1B2c3D4" * 4 + "'", "AKIA" + "ABCDEFGH12345678"):
            out = self.run_without_engine("Write", {"file_path": "/p/a.txt", "content": text})
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny", text)

    def test_unvalidated_writes_are_denied_without_the_engine(self):
        self.assertDenied(self.run_without_engine("Write", {"file_path": "/p/a.py", "content": "x = 1\n"}))
        self.assertDenied(self.run_without_engine("future", {"path": "/p/n.md", "content": "task-report-cleanup done"}))

    def test_live_env_read_is_denied_but_templates_and_other_files_are_not(self):
        for name in (".env", ".env.local", ".ENV"):
            out = self.run_without_engine("Read", {"file_path": f"/p/{name}"})
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny", name)
        for name in (".env.example", ".env.sample", "environment.md"):
            self.assertDenied(self.run_without_engine("Read", {"file_path": f"/p/{name}"}))
        self.assertIsNone(self.run_without_engine("Read", {"file_path": "/p/main.py"}))

    def test_fail_open_switch_turns_the_emergency_check_off(self):
        out = self.run_without_engine("Write", {"file_path": "/p/a.py", "content": self.KEY}, GRAVITYGUARD_ADAPTER_FAIL_OPEN="1")
        self.assertIsNone(out)

    def test_stop_without_engine_blocks(self):
        with mock.patch.object(adapter, "run_engine", return_value=None):
            self.assertEqual(adapter.handle({"session_id": "s1", "cwd": "/p"}, stop=True)["decision"], "block")


class TestEndToEnd(unittest.TestCase):
    """The adapter against the real engine, as Claude Code would run it (one process per hook call)."""

    def setUp(self):
        self.proj = tempfile.mkdtemp(prefix="gg_claude_e2e_")
        (Path(self.proj) / "tests").mkdir()
        (Path(self.proj) / ".git").write_text("gitdir: x", encoding="utf-8")
        (Path(self.proj) / "tests" / "test_base.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
        (Path(self.proj) / "util.py").write_text("def f():\n    x = 1\n    return x\n", encoding="utf-8")
        self.env = dict(os.environ, GRAVITYGUARD_LOG_DIR=str(Path(self.proj) / ".gglog"), GRAVITYGUARD_DISABLE_ASYNC="1",
                        CLAUDE_PROJECT_DIR=self.proj, PYTHONIOENCODING="utf-8",
                        GRAVITYGUARD_USER_CONFIG=os.path.join(self.proj, "nonexistent_user_config.json"))

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

    def test_secret_in_a_notebook_cell_is_denied(self):
        key = "sk-proj-" + "abcd1234" * 6
        out = self.hook("s1", "NotebookEdit", {"notebook_path": os.path.join(self.proj, "nb.ipynb"),
                                               "new_source": f'KEY = "{key}"\n', "cell_id": "c1"})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertNotIn(key, json.dumps(out))

    def test_harmless_notebook_cell_is_silent(self):
        out = self.hook("s1", "NotebookEdit", {"notebook_path": os.path.join(self.proj, "nb.ipynb"), "new_source": "print(1)\n"})
        self.assertIsNone(out)

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

    def test_user_default_config_shadows_rules_for_a_project_without_its_own(self):
        """~/.gravityguard.json (here via GRAVITYGUARD_USER_CONFIG) applies end to end when the project has no config."""
        user_cfg = Path(self.proj) / "user_default.json"
        user_cfg.write_text(json.dumps({"rules": {"G1_SILENT_EXCEPTION": "shadow", "SRP_BOUNDARY": {"mode": "shadow"}}}), encoding="utf-8")
        self.env["GRAVITYGUARD_USER_CONFIG"] = str(user_cfg)
        silent = {"file_path": os.path.join(self.proj, "util.py"), "old_string": "    x = 1\n",
                  "new_string": "    try:\n        x = int('a')\n    except Exception:\n        pass\n"}
        self.assertIsNone(self.hook("s1", "Edit", silent))
        ts = "const a = () => { if (activeTab === 'x') {} if (activeTab === 'y') {} };\n" + "<div className=\"glass-card\"/>\n" * 3
        self.assertIsNone(self.hook("s1", "Write", {"file_path": os.path.join(self.proj, "App.tsx"), "content": ts}))
        # secrets are not in the shadow list and stay denied
        key = "sk-proj-" + "abcd1234" * 6
        out = self.hook("s1", "Write", {"file_path": os.path.join(self.proj, "k.py"), "content": f'KEY = "{key}"\n'})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        # a project config wins completely: its empty rules make the silent except deny again
        (Path(self.proj) / ".gravityguard.json").write_text("{}", encoding="utf-8")
        out = self.hook("s1", "Edit", silent)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

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

    def test_open_obligation_keeps_blocking_through_stop_hook_active_until_the_engine_breaker_releases(self):
        self.hook("A", "Write", {"file_path": os.path.join(self.proj, "foo.py"), "content": "def foo():\n    return 1\n"})
        self.assertEqual(self.hook("A", stop=True)["decision"], "block")
        for attempt in range(2, 6):          # Claude Code reports stop_hook_active from the second stop on
            out = self.hook("A", stop=True, stop_hook_active=True)
            self.assertIsNotNone(out, f"stop #{attempt} must still be blocked")
            self.assertEqual(out["decision"], "block")
        self.assertIsNone(self.hook("A", stop=True, stop_hook_active=True), "the engine circuit breaker (5 retries) releases the stop")

    def test_doc_debt_stop_message_is_project_relative_and_plain(self):
        (Path(self.proj) / ".gravityguard.json").write_text(
            json.dumps({"governance": {"enforceDocObligations": True}, "testEvidence": {"exemptPatterns": ["engine/*"]}}), encoding="utf-8")
        self.hook("A", "Write", {"file_path": os.path.join(self.proj, "engine", "core.py"), "content": "def core():\n    return 1\n"})
        out = self.hook("A", stop=True)
        reason = out["reason"]
        self.assertIn("CHANGELOG.md [Unreleased] bölümüne bu değişikliği anlatan bir girdi ekle", reason)
        self.assertIn("'engine/core.py'", reason)
        self.assertNotIn(self.proj, reason, "no absolute path in the message")
        self.assertNotIn("KNOWLEDGE.md", reason, "the project has no docs/KNOWLEDGE.md")
        self.assertIn("Kalan deneme: 4", reason)

    def test_non_string_content_is_denied_not_a_traceback(self):
        out = self.hook("A", "Write", {"file_path": os.path.join(self.proj, "n.py"), "content": 12345})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("TOOL_SCHEMA_UNSUPPORTED", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_clearing_the_obligation_releases_the_stop(self):
        self.hook("A", "Write", {"file_path": os.path.join(self.proj, "foo.py"), "content": "def foo():\n    return 1\n"})
        self.assertEqual(self.hook("A", stop=True)["decision"], "block")
        test_file = os.path.join(self.proj, "tests", "test_foo.py")
        content = "def test_foo():\n    assert 1 == 1\n\ndef test_foo_again():\n    assert 2 == 2\n"
        self.hook("A", "Write", {"file_path": test_file, "content": content})
        Path(test_file).write_text(content, encoding="utf-8")        # the PreToolUse hook runs before the write itself
        self.assertIsNone(self.hook("A", stop=True, stop_hook_active=True), "evidence exists on disk, nothing is owed")


class TestAdapterRobustness(unittest.TestCase):
    def setUp(self):
        self.proj = tempfile.mkdtemp(prefix="gg_claude_rb_")
        (Path(self.proj) / ".git").mkdir()
        (Path(self.proj) / "src" / "deep").mkdir(parents=True)
        (Path(self.proj) / ".env").write_text("SECRET=1\n", encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "GRAVITYGUARD_LOG_DIR", "GRAVITYGUARD_AUDIT_DIR")}
        self.env.update(PYTHONIOENCODING="utf-8", GRAVITYGUARD_DISABLE_ASYNC="1",
                        GRAVITYGUARD_AUDIT_DIR=str(Path(self.proj) / ".ggaudit"))

    def tearDown(self):
        shutil.rmtree(self.proj, ignore_errors=True)

    def run_hook(self, event, raw=None):
        proc = subprocess.run([sys.executable, str(_ADAPTER)], input=raw if raw is not None else json.dumps(event),
                              capture_output=True, text=True, encoding="utf-8", env=self.env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return (json.loads(proc.stdout) if proc.stdout.strip() else None), proc.stderr

    def test_read_of_live_env_is_denied_and_other_reads_pass_silently(self):
        env_read = {"session_id": "r", "cwd": self.proj, "tool_name": "Read", "tool_input": {"file_path": str(Path(self.proj) / ".env")}}
        out, _ = self.run_hook(env_read)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("G0_ENV_PROTECTION", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIsNone(adapter.to_engine_pretool({"tool_name": "Read", "tool_input": {"file_path": "/p/src/a.py"}}))
        self.assertIsNotNone(adapter.to_engine_pretool({"tool_name": "Read", "tool_input": {"file_path": "/p/.env.local"}}))
        example = {"session_id": "r", "cwd": self.proj, "tool_name": "Read", "tool_input": {"file_path": str(Path(self.proj) / ".env.example")}}
        self.assertIsNone(self.run_hook(example)[0])

    def test_settings_example_matcher_includes_read(self):
        settings = json.loads((_ADAPTER.parent / "settings.example.json").read_text(encoding="utf-8"))
        self.assertEqual("*", settings["hooks"]["PreToolUse"][0]["matcher"])

    def test_deeply_nested_payload_denies_with_a_note(self):
        out, err = self.run_hook(None, raw="[" * 100000)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("nested too deeply", err)

    def test_without_claude_project_dir_the_root_is_found_by_walking_up(self):
        event = {"session_id": "w", "cwd": str(Path(self.proj) / "src" / "deep")}
        self.assertEqual(Path(adapter.workspace_paths(event)[0]).resolve(), Path(self.proj).resolve())

    def test_audit_log_goes_where_gravityguard_audit_dir_points(self):
        """Documented behaviour (plugin README): the central ~/.gemini/logs is the default so the Live Monitor sees Claude
        Code activity; GRAVITYGUARD_AUDIT_DIR keeps the stream project-local."""
        event = {"session_id": "a", "cwd": self.proj, "tool_name": "Write",
                 "tool_input": {"file_path": str(Path(self.proj) / "src" / "x.py"), "content": "x = 1\n"}}
        self.env["CLAUDE_PROJECT_DIR"] = self.proj
        logs = Path(self.proj) / ".gravityguard" / "logs"
        self.env["GRAVITYGUARD_AUDIT_DIR"] = str(logs)
        self.run_hook(event)
        self.assertTrue(logs.is_dir() and any(logs.rglob("*.jsonl")), "audit stream must land in GRAVITYGUARD_AUDIT_DIR")


class TestShellDeny(unittest.TestCase):
    def setUp(self):
        self.addCleanup(os.environ.pop, adapter.FAIL_OPEN_ENV, None)
        os.environ.pop(adapter.FAIL_OPEN_ENV, None)

    def deny(self, command, tool="Bash"):
        return adapter.handle({"tool_name": tool, "tool_input": {"command": command}, "session_id": "sh"}, stop=False)

    def test_secret_literal_in_a_command_is_denied_in_both_shells(self):
        token = "ghp_" + "a" * 30          # built at runtime so this file holds no secret literal
        for tool in ("Bash", "PowerShell"):
            out = self.deny(f'echo "TOKEN={token}" >> notes.txt', tool)
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_shell_read_of_a_live_env_is_denied(self):
        for command in ("cat .env", "type .\\.env", "Get-Content C:\\p\\.env.local", "grep KEY config/.env", "source .env"):
            out = self.deny(command)
            self.assertIsNotNone(out, command)
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_env_templates_and_unrelated_commands_pass(self):
        for command in ("cat .env.example", "cat README.md", "echo hi", "git status", "ls -a", "grep -r environment src",
                        'git commit -m "deny live .env reads" 2>&1 | tail -6', "echo .env | head -1"):
            self.assertIsNone(self.deny(command), command)

    def test_availability_override_does_not_disable_a_working_security_engine(self):
        os.environ[adapter.FAIL_OPEN_ENV] = "1"
        self.assertEqual(self.deny("cat .env")["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_settings_example_covers_shell_tools(self):
        settings = json.loads((_ADAPTER.parent / "settings.example.json").read_text(encoding="utf-8"))
        matcher = settings["hooks"]["PreToolUse"][0]["matcher"]
        self.assertEqual(matcher, "*")


if __name__ == "__main__":
    unittest.main()
