#!/usr/bin/env python3
"""Shell evasion of the file-tool guard: protected control files, interpreter scripts and session quarantine."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine.session_quarantine import record_denied_target
from gravityguard_engine.shell_rules import check_shell_command

VALIDATOR = Path(_ENGINE_DIR) / "gravity-validator.py"
PROTECTED_SKILL = "~/.gemini/config/plugins/gravityguard/skills/core-docs/SKILL.md"


class _Workspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.realpath(self._tmp.name)
        self.state = os.path.join(self.root, "state")
        os.makedirs(self.state)
        old = os.environ.get("GRAVITYGUARD_LOG_DIR")
        os.environ["GRAVITYGUARD_LOG_DIR"] = self.state
        self.addCleanup(lambda: os.environ.pop("GRAVITYGUARD_LOG_DIR", None) if old is None
                        else os.environ.__setitem__("GRAVITYGUARD_LOG_DIR", old))

    def script(self, name, body):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        return path

    def check(self, command, conversation_id=None):
        return check_shell_command({"command": command}, self.root, conversation_id)


class TestProtectedControlFiles(_Workspace):
    def test_interpreter_script_writing_protected_file_is_blocked(self):
        self.script("scratch/temp.py", f"with open({PROTECTED_SKILL!r}, 'w') as f:\n    f.write('x')\n")
        self.assertTrue(self.check("python scratch/temp.py").startswith("[POLICY_INTEGRITY]"))

    def test_script_building_the_path_from_parts_is_blocked(self):
        self.script("w.py", "import pathlib\npathlib.Path('.claude').joinpath('settings.json').write_text('{}')\n")
        self.assertTrue(self.check("python w.py").startswith("[POLICY_INTEGRITY]"))

    def test_shell_script_body_is_checked(self):
        self.script("w.sh", "echo '{}' > .agents/hooks.json\n")
        self.assertTrue(self.check("bash w.sh").startswith("[POLICY_INTEGRITY]"))

    def test_powershell_and_shell_writers_are_blocked(self):
        for command in (
            "Set-Content -Path 'C:\\Users\\Halil Emre\\proj\\.agents\\hooks.json' -Value '{}'",
            "'{}' | Out-File -FilePath .gemini\\hooks.json",
            "powershell -Command \"Set-Content 'C:\\Users\\Halil Emre\\.gemini\\hooks.json' x; Write-Host done\"",
            "Add-Content .claude\\settings.json 'x'",
            "echo {} > .claude/settings.json",
            "echo {} >> .claude/settings.local.json",
            "echo {} | tee .agents/hooks.json",
            "rm .agents/hooks.json",
            "del .claude\\settings.json",
            "Remove-Item -Force .gemini\\hooks.json",
            "mv evil.json .claude/settings.local.json",
            "Move-Item evil.json .agents\\hooks.json",
            "cp evil.json .agents/hooks.json",
            "Copy-Item evil.json -Destination .claude\\settings.json",
            "sed -i s/a/b/ .agents/hooks.json",
            "rm -rf .gravityguard/runtime",
            "python edit.py .claude/settings.json",
            "python -c \"open('.claude/settings.json', 'w').write('{}')\"",
            "python - <<EOF\nimport pathlib\npathlib.Path('.agents/hooks.json').write_text('{}')\nEOF",
            "git checkout -- x && rm .agents/hooks.json",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.check(command).startswith("[POLICY_INTEGRITY]"), self.check(command))

    def test_legitimate_commands_are_not_blocked(self):
        self.script("tools/build.py", "with open('out.txt', 'w') as f:\n    f.write('built')\n")
        self.script("tools/read_cfg.py", "print(open('.claude/settings.json').read())\n")
        for command in (
            "git status",
            "git diff --stat",
            "pytest tests/",
            "python -m pytest -q engine/tests",
            "npm test",
            "node --version",
            "python tools/build.py",
            "python tools/read_cfg.py",
            "ls -la .gemini",
            "echo hi > out.txt",
            "echo hi 2>&1 | tee build.log",
            "cat .claude/settings.json",
            "cp .claude/settings.json backup.json",
            "python -c \"print(open('.claude/settings.json').read())\"",
            "git commit -m 'document hooks.json handling'",
            "rm -rf node_modules",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.check(command), "")


class TestRelativePathResolution(_Workspace):
    PLUGIN_DIR = str(Path.home() / ".gemini" / "config" / "plugins" / "gravityguard")

    def test_relative_write_inside_the_installed_plugin_is_blocked(self):
        reason = check_shell_command({"command": "echo a > notes.txt"}, self.PLUGIN_DIR)
        self.assertTrue(reason.startswith("[POLICY_INTEGRITY]"))

    def test_directory_change_stops_relative_resolution(self):
        for command in (f'cd "{self.root}" && git init -q . && echo a > a', f'Set-Location "{self.root}"; "a" | Out-File a'):
            with self.subTest(command=command):
                self.assertEqual(check_shell_command({"command": command}, self.PLUGIN_DIR), "")

    def test_absolute_protected_path_is_blocked_even_after_cd(self):
        command = f'cd "{self.root}" && echo a > "{self.PLUGIN_DIR}/hooks.json"'
        self.assertTrue(check_shell_command({"command": command}, self.root).startswith("[POLICY_INTEGRITY]"))


class TestLinearTime(_Workspace):
    def test_adversarial_commands_finish_quickly(self):
        record_denied_target("conv-1", os.path.join(self.root, "src", "app.py"))
        inputs = {
            "repeated flags": "rm " + "-r " * 66_000,
            "distinct operands": "rm " + " ".join(f"f{i}.py" for i in range(30_000)),
            "repeated scripts": "python " + "a.py " * 40_000,
            "many redirects": "echo " + " ".join(f">r{i}" for i in range(30_000)),
            "copy destinations": "cp a " + "-destination x " * 20_000,
            "unbalanced quotes": "python -c '" + "\"x " * 60_000,
        }
        for label, command in inputs.items():
            with self.subTest(label=label):
                start = time.perf_counter()
                self.check(command, "conv-1")
                self.assertLess(time.perf_counter() - start, 2.0)


class TestSessionQuarantine(_Workspace):
    def setUp(self):
        super().setUp()
        self.target = os.path.join(self.root, "src", "app.py")
        record_denied_target("conv-1", self.target)

    def test_shell_write_to_denied_target_is_evasion(self):
        for command in (
            f'echo x > "{self.target}"',
            f"rm {self.target}",
            f"python -c \"open(r'{self.target}', 'w').write('x')\"",
            "sed -i s/a/b/ src/app.py",
            "Set-Content src\\app.py 'x'",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.check(command, "conv-1").startswith("[HOOK_EVASION_DETECTED]"))

    def test_script_writing_denied_target_is_evasion(self):
        self.script("scratch/fix.py", "from pathlib import Path\nPath('src/app.py').write_text('patched')\n")
        self.assertTrue(self.check("python scratch/fix.py", "conv-1").startswith("[HOOK_EVASION_DETECTED]"))

    def test_quarantine_is_scoped_to_the_conversation_and_to_writes(self):
        self.script("scratch/fix.py", "from pathlib import Path\nPath('src/app.py').write_text('patched')\n")
        self.assertEqual(self.check("python scratch/fix.py", "conv-2"), "")
        self.assertEqual(self.check("python scratch/fix.py"), "")
        for command in ("cat src/app.py", "git diff src/app.py", "python -m pytest -q", "echo x > other.txt",
                        "python src/app.py", "rm src/other.py"):
            with self.subTest(command=command):
                self.assertEqual(self.check(command, "conv-1"), "")

    def test_evasion_wins_over_control_file_rule(self):
        hooks = os.path.join(self.root, ".agents", "hooks.json")
        record_denied_target("conv-1", hooks)
        self.assertTrue(self.check(f'echo {{}} > "{hooks}"', "conv-1").startswith("[HOOK_EVASION_DETECTED]"))
        self.assertTrue(self.check(f'echo {{}} > "{hooks}"', "conv-2").startswith("[POLICY_INTEGRITY]"))


class TestDispatcherEndToEnd(_Workspace):
    def run_hook(self, name, args):
        payload = {"conversationId": "e2e", "workspacePaths": [self.root], "cwd": self.root,
                   "toolCall": {"name": name, "args": args}}
        env = {**os.environ, "GRAVITYGUARD_LOG_DIR": self.state, "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.run([sys.executable, str(VALIDATOR)], input=json.dumps(payload), capture_output=True,
                              text=True, encoding="utf-8", env=env, cwd=self.root, timeout=60, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_denied_file_write_then_shell_write_is_evasion(self):
        hooks = os.path.join(self.root, ".agents", "hooks.json")
        write = self.run_hook("write_to_file", {"TargetFile": hooks, "CodeContent": "{}"})
        self.assertEqual(write["decision"], "deny")
        self.assertIn("POLICY_INTEGRITY", write["reason"])
        shell = self.run_hook("run_command", {"CommandLine": f'echo {{}} > "{hooks}"', "Cwd": self.root})
        self.assertEqual(shell["decision"], "deny")
        self.assertIn("HOOK_EVASION_DETECTED", shell["reason"])

    def test_interpreter_script_against_protected_file_is_denied_without_prior_write(self):
        self.script("scratch/temp.py", f"open({PROTECTED_SKILL!r}, 'w').write('x')\n")
        shell = self.run_hook("run_command", {"CommandLine": "python scratch/temp.py", "Cwd": self.root})
        self.assertEqual(shell["decision"], "deny")
        self.assertIn("POLICY_INTEGRITY", shell["reason"])

    def test_ordinary_command_is_allowed(self):
        self.assertEqual(self.run_hook("run_command", {"CommandLine": "git status", "Cwd": self.root})["decision"], "allow")


if __name__ == "__main__":
    unittest.main()
