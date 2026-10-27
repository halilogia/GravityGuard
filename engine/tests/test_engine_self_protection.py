#!/usr/bin/env python3
"""The guard must not break itself, and a broken guard must neither wedge the agent nor fail open."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine import dispatcher, engine_integrity

ENGINE_FILE = str(Path(_ENGINE_DIR) / "gravityguard_engine" / "security_rules.py")
USES_UNDEFINED = "import re\n\n\ndef f(x):\n    for pattern, label in _MISSING_PATTERNS:\n        x = re.sub(pattern, label, x)\n    return x\n"


class PreWriteIntegrity(unittest.TestCase):
    def test_undefined_global_in_function_is_detected(self):
        self.assertEqual(engine_integrity.undefined_globals(USES_UNDEFINED), ["_MISSING_PATTERNS"])
        self.assertEqual(engine_integrity.undefined_globals("_MISSING_PATTERNS = []\n" + USES_UNDEFINED), [])

    def test_valid_constructs_are_not_flagged(self):
        source = (
            "import os\nfrom typing import List\n\nCACHE = {}\n\n"
            "def a(items: List[int]):\n    total = 0\n    for i in items:\n        total += i\n    return [x for x in items if x], total\n\n"
            "def b():\n    global CACHE\n    CACHE = {'k': os.sep}\n    return lambda y: y + len(CACHE)\n\n"
            "class C:\n    def m(self):\n        return __class__, __name__, print\n"
        )
        self.assertEqual(engine_integrity.undefined_globals(source), [])

    def test_wildcard_import_disables_the_check(self):
        self.assertEqual(engine_integrity.undefined_globals("from os.path import *\n\ndef f():\n    return join('a', 'b')\n"), [])

    def test_real_engine_files_are_clean(self):
        root = Path(_ENGINE_DIR)
        files = list((root / "gravityguard_engine").glob("*.py")) + [root / "gravity-validator.py"] + list((root.parent / "plugin").rglob("*.py"))
        self.assertGreater(len(files), 20)
        for file in files:
            with self.subTest(file=file.name):
                self.assertEqual(engine_integrity.engine_source_defect(str(file), file.read_text(encoding="utf-8")), "")

    def test_defect_is_reported_only_for_engine_files(self):
        self.assertIn("_MISSING_PATTERNS", engine_integrity.engine_source_defect(ENGINE_FILE, USES_UNDEFINED))
        self.assertIn("SyntaxError", engine_integrity.engine_source_defect(ENGINE_FILE, "def broken(:\n"))
        self.assertEqual(engine_integrity.engine_source_defect(str(Path(tempfile.gettempdir()) / "x.py"), USES_UNDEFINED), "")
        self.assertEqual(engine_integrity.engine_source_defect(ENGINE_FILE.replace(".py", ".md"), USES_UNDEFINED), "")

    def test_dispatcher_denies_a_write_that_would_break_the_engine(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"GRAVITYGUARD_LOG_DIR": tmp, "GRAVITYGUARD_LKG_ACTIVE": "1"}):
            current = Path(ENGINE_FILE).read_text(encoding="utf-8")
            payload = {"toolCall": {"name": "write_to_file", "args": {"TargetFile": ENGINE_FILE, "CodeContent": current + "\n\ndef broken():\n    return _NOT_DEFINED_ANYWHERE\n"}},
                       "conversationId": "c-int", "workspacePaths": [str(Path(_ENGINE_DIR).parent)]}
            out = io.StringIO()
            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), redirect_stdout(out), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    dispatcher.run_cli()
            answer = json.loads(out.getvalue().strip().splitlines()[-1])
            self.assertEqual(answer["decision"], "deny")
            self.assertIn("ENGINE_SELF_INTEGRITY", answer["reason"])
            self.assertIn("_NOT_DEFINED_ANYWHERE", answer["reason"])


class CrashRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gg_recover_")
        self.cwd = os.getcwd()
        os.chdir(self.tmp)
        self.env = mock.patch.dict(os.environ, {"GRAVITYGUARD_LOG_DIR": os.path.join(self.tmp, "audit"), "USERPROFILE": self.tmp, "HOME": self.tmp})
        self.env.start()
        os.environ.pop("GRAVITYGUARD_LKG_ACTIVE", None)
        dispatcher._CRASH_CONTEXT.clear()

    def tearDown(self):
        self.env.stop()
        os.chdir(self.cwd)
        dispatcher._CRASH_CONTEXT.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def crash(self, payload, lkg=None):
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
                mock.patch.object(dispatcher, "check_shell_command", side_effect=NameError("name '_X' is not defined")), \
                mock.patch.object(dispatcher, "run_lkg", return_value=lkg), \
                redirect_stdout(out), redirect_stderr(io.StringIO()):
            dispatcher.run_cli()
        return json.loads(out.getvalue().strip().splitlines()[-1])

    def audit(self):
        path = Path(self.tmp, "audit", "gravityguard_permanent_audit.jsonl")
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_committed_engine_answer_is_used_and_audited_as_a_warning(self):
        answer = self.crash({"toolCall": {"name": "run_command", "args": {"command": "echo hi"}}, "conversationId": "c1"}, lkg={"decision": "allow"})
        self.assertEqual(answer, {"decision": "allow"})
        events = [e for e in self.audit() if e["ruleId"] == "GUARD_FALLBACK_LKG"]
        self.assertEqual([e["status"] for e in events], ["WARNING"])

    def test_committed_engine_can_still_deny(self):
        answer = self.crash({"toolCall": {"name": "run_command", "args": {"command": "x"}}, "conversationId": "c1"}, lkg={"decision": "deny", "reason": "[G0_SECRET_LEAK]: x"})
        self.assertEqual(answer["decision"], "deny")

    def test_repair_of_engine_source_is_allowed_when_no_fallback_exists(self):
        payload = {"toolCall": {"name": "replace_file_content", "args": {"TargetFile": ENGINE_FILE, "ReplacementContent": "x"}}, "conversationId": "c2"}
        answer = self.crash(payload)
        self.assertEqual(answer["decision"], "allow")
        self.assertIn("GUARD_REPAIR_MODE", answer["reason"])
        self.assertTrue(any(e["ruleId"] == "GUARD_REPAIR_MODE" for e in self.audit()))

    def test_everything_else_stays_denied_without_a_fallback(self):
        cases = (
            {"toolCall": {"name": "run_command", "args": {"command": "echo hi"}}, "conversationId": "c3"},
            {"toolCall": {"name": "replace_file_content", "args": {"TargetFile": str(Path(self.tmp) / "app.py"), "ReplacementContent": "x"}}, "conversationId": "c3"},
        )
        for payload in cases:
            with self.subTest(tool=payload["toolCall"]["name"]):
                self.assertEqual(self.crash(payload)["decision"], "deny")

    def test_repair_requires_every_target_to_be_engine_source(self):
        payload = {"toolCall": {"name": "write_to_file", "args": {"TargetFile": ENGINE_FILE, "OtherPath": str(Path(self.tmp) / "outside.py")}}}
        self.assertEqual(engine_integrity.repair_reason(json.dumps(payload)), "")
        payload["toolCall"]["args"].pop("OtherPath")
        self.assertIn("GUARD_REPAIR_MODE", engine_integrity.repair_reason(json.dumps(payload)))
        self.assertEqual(engine_integrity.repair_reason("not json"), "")


class LastKnownGoodEndToEnd(unittest.TestCase):
    """Real git repo, real subprocess: a broken working tree is validated by the committed engine."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gg_lkg_")
        self.repo = Path(self.tmp) / "repo"
        engine_src = Path(_ENGINE_DIR)
        shutil.copytree(engine_src / "gravityguard_engine", self.repo / "engine" / "gravityguard_engine", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(engine_src / "gravity-validator.py", self.repo / "engine" / "gravity-validator.py")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "good engine")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args):
        subprocess.run(["git", *args], cwd=str(self.repo), check=True, capture_output=True)

    def run_validator(self, payload):
        env = dict(os.environ, USERPROFILE=self.tmp, HOME=self.tmp, GRAVITYGUARD_LOG_DIR=os.path.join(self.tmp, "audit"))
        env.pop("GRAVITYGUARD_LKG_ACTIVE", None)
        proc = subprocess.run([sys.executable, str(self.repo / "engine" / "gravity-validator.py")], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8", cwd=str(self.repo), env=env, timeout=120)
        return json.loads(proc.stdout.strip().splitlines()[-1]), proc

    def break_working_tree(self):
        target = self.repo / "engine" / "gravityguard_engine" / "shell_rules.py"
        text = target.read_text(encoding="utf-8")
        target.write_text(text.replace("    command = command_text(args)\n", "    command = command_text(args)\n    _UNDEFINED_SO_THE_ENGINE_CRASHES\n", 1), encoding="utf-8")

    def test_broken_working_tree_is_still_protected_by_the_committed_engine(self):
        benign = {"toolCall": {"name": "run_command", "args": {"command": "echo hello"}}, "conversationId": "lkg-1", "cwd": str(self.repo)}
        self.assertEqual(self.run_validator(benign)[0]["decision"], "allow")
        self.break_working_tree()
        answer, proc = self.run_validator(benign)
        self.assertEqual(answer["decision"], "allow", (answer, proc.stderr[-400:]))
        self.assertNotIn("GUARD_UNAVAILABLE", json.dumps(answer))
        # the working tree really is broken: without the fallback the same call is refused
        env = dict(os.environ, USERPROFILE=self.tmp, HOME=self.tmp, GRAVITYGUARD_LOG_DIR=os.path.join(self.tmp, "audit"), GRAVITYGUARD_LKG_ACTIVE="1")
        broken = subprocess.run([sys.executable, str(self.repo / "engine" / "gravity-validator.py")], input=json.dumps(benign),
                                capture_output=True, text=True, encoding="utf-8", cwd=str(self.repo), env=env, timeout=120)
        self.assertIn("GUARD_UNAVAILABLE", broken.stdout)
        # protection stays on through the fallback: a secret write is still denied
        secret = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
        write = {"toolCall": {"name": "write_to_file", "args": {"TargetFile": str(self.repo / "leak.py"), "CodeContent": f"TOKEN = '{secret}'\n"}},
                 "conversationId": "lkg-1", "cwd": str(self.repo), "workspacePaths": [str(self.repo)]}
        self.assertEqual(self.run_validator(write)[0]["decision"], "deny")

    def test_import_time_failure_also_recovers(self):
        target = self.repo / "engine" / "gravityguard_engine" / "security_rules.py"
        target.write_text(target.read_text(encoding="utf-8") + "\n\ndef broken(:\n", encoding="utf-8")  # SyntaxError at import
        benign = {"toolCall": {"name": "run_command", "args": {"command": "echo hello"}}, "conversationId": "lkg-2", "cwd": str(self.repo)}
        answer, proc = self.run_validator(benign)
        self.assertEqual(answer["decision"], "allow", (answer, proc.stderr[-400:]))


if __name__ == "__main__":
    unittest.main()
