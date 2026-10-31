"""Regression cases for the security review's reproduced bypasses."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

_ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from gravityguard_engine.dispatcher import validate_gravityguard, is_rule_shadow
from gravityguard_engine.diffing import get_projected_and_old_content, ProjectionError
from gravityguard_engine.publication_guard import scan_git_secrets


class SecurityHardeningTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / ".gravityguard.json").write_text("{}", encoding="utf-8")
        self.env = patch.dict(os.environ, {"GRAVITYGUARD_LOG_DIR": str(self.root / "logs"),
            "GRAVITYGUARD_DISABLE_ASYNC": "1", "GRAVITYGUARD_TEST_VIRTUAL_FILES": "",
            "GRAVITYGUARD_USER_CONFIG": str(self.root / "missing")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def call(self, name, args):
        payload = {"workspacePaths": [str(self.root)], "toolCall": {"name": name, "args": args}}
        out = io.StringIO()
        with patch("sys.stdin", io.StringIO(json.dumps(payload))), patch("sys.stdout", out), patch("sys.argv", ["guard"]):
            with self.assertRaises(SystemExit):
                validate_gravityguard()
        return json.loads(out.getvalue())

    def assert_rule(self, answer, rule):
        self.assertEqual(answer["decision"], "deny")
        self.assertIn(rule, answer["reason"])

    def test_binary_suffix_does_not_hide_secret_or_env_read(self):
        self.assert_rule(self.call("future", {"path": str(self.root / "asset.png"), "content": "ghp_" + "A" * 36}), "G0_SECRET_LEAK")
        self.assert_rule(self.call("Read", {"path": str(self.root / ".env.png")}), "G0_ENV_PROTECTION")

    def test_mandatory_policy_floor_and_control_plane(self):
        cfg = {"rules": {"G0_ENV_PROTECTION": "shadow", "G0_SECRET_LEAK": {"mode": "shadow"}}}
        (self.root / ".gravityguard.json").write_text(json.dumps(cfg))
        self.assertFalse(is_rule_shadow("G0_SECRET_LEAK", cfg))
        self.assert_rule(self.call("read_file", {"path": str(self.root / ".env")}), "G0_ENV_PROTECTION")
        self.assert_rule(self.call("future", {"path": str(self.root / ".gravityguard.json"), "content": json.dumps(cfg)}), "POLICY_INTEGRITY")
        self.assert_rule(self.call("future", {"path": str(self.root / ".agents" / "hooks.json"), "content": "{}"}), "POLICY_INTEGRITY")

    def test_projection_rejects_mismatch_ambiguity_missing_and_read_error(self):
        file = self.root / "model.py"
        file.write_text("same\nsame\n", encoding="utf-8")
        for search in ("absent", "same", ""):
            self.assert_rule(self.call("future", {"path": str(file), "old_string": search, "new_string": "replacement"}), "PROJECTION_UNSUPPORTED")
        self.assert_rule(self.call("future", {"path": str(file), "edits": [{"old_string": "absent", "new_string": "ghp_" + "A" * 36}]}), "PROJECTION_UNSUPPORTED")
        self.assert_rule(self.call("Edit", {"path": str(self.root / "absent.py"), "old_string": "a", "new_string": "b"}), "PROJECTION_UNSUPPORTED")
        file.write_bytes(b"\xff")
        with self.assertRaises(ProjectionError):
            get_projected_and_old_content(str(file), "future", {"path": str(file), "content": "replacement"})

    def test_line_bound_projection_and_sequential_edits(self):
        file = self.root / "model.py"
        file.write_text("same\nsame\n", encoding="utf-8")
        before, after = get_projected_and_old_content(str(file), "future", {"path": str(file),
            "edits": [{"old_string": "same", "new_string": "first", "StartLine": 1, "EndLine": 1},
                      {"old_string": "same", "new_string": "second"}]})
        self.assertEqual(after, "first\nsecond\n")
        self.assertEqual(before, "same\nsame\n")

    def test_shell_checks_apply_to_renamed_command_tools(self):
        self.assert_rule(self.call("new_shell", {"CommandLine": "cat .env"}), "G0_ENV_PROTECTION")
        self.assert_rule(self.call("new_shell", {"cmd": "echo ghp_" + "A" * 36}), "G0_SECRET_LEAK")
        self.assertEqual(self.call("new_shell", {"command": "git status"})["decision"], "allow")

    def test_git_gate_scans_staged_and_untracked_text_with_binary_suffix(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        file = self.root / "asset.png"
        file.write_text("ghp_" + "A" * 36, encoding="utf-8")
        self.assertTrue(scan_git_secrets(self.root))
        self.assertFalse(scan_git_secrets(self.root, staged_only=True))
        subprocess.run(["git", "add", "asset.png"], cwd=self.root, check=True, capture_output=True)
        self.assertTrue(scan_git_secrets(self.root, staged_only=True))

    def test_git_gate_catches_null_prefixed_secret_bypass(self):
        """ChatGPT Red-Team RG-001: NUL byte prefix must not bypass untracked secret scan."""
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        file = self.root / "sneaky.dat"
        file.write_bytes(b"\x00\x00ghp_" + b"A" * 36)
        findings = scan_git_secrets(self.root)
        self.assertTrue(any("G0_SECRET_LEAK" in f for f in findings))
