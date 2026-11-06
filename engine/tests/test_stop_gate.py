"""Circuit-breaker gap, new-file hard cap, refactoring blueprint and session knowledge distillation."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gravityguard_engine.debt_ratchet import check_new_file_bloat
from gravityguard_engine.refactor_hint import build_refactor_hint
from gravityguard_engine.stop_gate import distill_session_knowledge, note_raised_rules

_ENGINE_DIR = str(Path(__file__).resolve().parent.parent)
VALIDATOR = os.path.join(_ENGINE_DIR, "gravity-validator.py")


def _lines(count: int, prefix: str = "x") -> str:
    return "".join(f"{prefix}{i} = {i}\n" for i in range(count))


def _class_file(count: int) -> str:
    return "class Big:\n" + _lines(count - 1, "    v")


class RefactorHintTests(unittest.TestCase):
    def test_python_hint_names_biggest_units_and_target_paths(self):
        src = "class BigThing:\n" + "".join(f"    a{i} = 1\n" for i in range(40)) + "def helper():\n" + _lines(20, "    y")
        hint = build_refactor_hint(src, "src/app/core.py")
        self.assertIn("'BigThing' sınıfını (41 satır) 'src/app/core_big_thing.py'", hint)
        self.assertIn("'helper' işlevini", hint)

    def test_typescript_hint_uses_declarations(self):
        src = "export class Store {\n" + "//\n" * 30 + "}\n"
        self.assertIn("'Store' sınıfını", build_refactor_hint(src, "src/store.ts"))

    def test_no_hint_for_small_unparsable_or_unknown(self):
        self.assertEqual(build_refactor_hint("def f():\n    pass\n", "a.py"), "")
        self.assertEqual(build_refactor_hint("def broken(:\n", "a.py"), "")
        self.assertEqual(build_refactor_hint("anything", "notes.md"), "")


class NewFileBloatTests(unittest.TestCase):
    def test_big_new_source_file_is_denied_with_blueprint(self):
        msg = check_new_file_bloat("/proj", "/proj/src/mono.py", "", "class Big:\n" + _lines(700, "    v"), 600)
        self.assertIn("701", msg)
        self.assertIn("Öneri", msg)

    def test_allowed_cases_return_empty(self):
        big = _lines(700)
        self.assertEqual(check_new_file_bloat("/proj", "/proj/src/ok.py", "", _lines(600), 600), "")   # exactly at the cap
        self.assertEqual(check_new_file_bloat("/proj", "/proj/src/old.py", "x = 1\n", big, 600), "")      # existing file
        self.assertEqual(check_new_file_bloat("/proj", "/proj/tests/test_big.py", "", big, 600), "")      # tests
        self.assertEqual(check_new_file_bloat("/proj", "/proj/data.json", "", big, 600), "")              # data
        self.assertEqual(check_new_file_bloat("/proj", "/proj/src/gen.py", "", "# srp: allow-monolith\n" + big, 600), "")


class StopGateEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gg_stop_gate_")
        self.proj = Path(self.tmp) / "proj"
        (self.proj / "brain").mkdir(parents=True)
        (self.proj / "brain" / "knowledge.md").write_text("# Knowledge\n\nNotes.\n", encoding="utf-8")
        (self.proj / "big.py").write_text(_class_file(600), encoding="utf-8")
        for cmd in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "i"]):
            subprocess.run(["git", *cmd], cwd=self.proj, check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stop(self):
        env = {**os.environ, "GRAVITYGUARD_LOG_DIR": os.path.join(self.tmp, "logs"), "GRAVITYGUARD_DISABLE_ASYNC": "1",
               "GRAVITYGUARD_USER_CONFIG": os.path.join(self.tmp, "none.json")}
        payload = {"terminationReason": "model_stop", "workspacePaths": [str(self.proj)], "conversationId": "c1"}
        proc = subprocess.run([sys.executable, VALIDATOR], input=json.dumps(payload), capture_output=True, text=True,
                              encoding="utf-8", cwd=str(self.proj), env=env, timeout=90)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def write(self, name, content):
        env = {**os.environ, "GRAVITYGUARD_LOG_DIR": os.path.join(self.tmp, "logs"), "GRAVITYGUARD_DISABLE_ASYNC": "1",
               "GRAVITYGUARD_USER_CONFIG": os.path.join(self.tmp, "none.json")}
        payload = {"toolCall": {"name": "write_to_file", "args": {"TargetFile": str(self.proj / name), "CodeContent": content}},
                   "workspacePaths": [str(self.proj)], "conversationId": "c2"}
        proc = subprocess.run([sys.executable, VALIDATOR], input=json.dumps(payload), capture_output=True, text=True,
                              encoding="utf-8", cwd=str(self.proj), env=env, timeout=90)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_new_monolith_is_denied_before_it_is_written_but_a_small_file_is_not(self):
        denied = self.write("fresh_monolith.py", _class_file(700))
        self.assertEqual(denied["decision"], "deny")
        self.assertIn("G5_NEW_FILE_BLOAT_DENY", denied["reason"])
        self.assertEqual(self.write("small_module.py", _class_file(50))["decision"], "allow")

    def test_breaker_never_forgives_a_ratchet_regression_and_success_is_distilled(self):
        (self.proj / "big.py").write_text(_class_file(640), encoding="utf-8")
        first = self.stop()
        self.assertEqual(first["decision"], "continue")
        self.assertIn("Öneri", first["reason"])  # blueprint rides along with the regression
        for _ in range(4):
            self.assertEqual(self.stop()["decision"], "continue")
        sixth = self.stop()  # retries exhausted: the old breaker answered "allow" here
        self.assertEqual(sixth["decision"], "continue")
        self.assertIn("manuel müdahale", sixth["reason"])

        (self.proj / "big.py").write_text(_class_file(600), encoding="utf-8")  # the agent refactors back under its ceiling
        self.assertEqual(self.stop()["decision"], "allow")
        notes = (self.proj / "brain" / "knowledge.md").read_text(encoding="utf-8")
        self.assertIn("## Otomatik Oturum Notları", notes)
        self.assertIn("ARCH_RATCHET_REGRESSION", notes)


class KnowledgeDistillationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="gg_distill_"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_writes_one_deduplicated_line_and_keeps_crlf(self):
        (self.root / "brain").mkdir()
        (self.root / "brain" / "knowledge.md").write_bytes(b"# K\r\n\r\ntext\r\n")
        note_raised_rules(self.root, "c", ["DOC_OBLIGATION_UNRESOLVED", "ARCH_RATCHET_REGRESSION"])
        line = distill_session_knowledge(self.root, "c")
        self.assertIn("ARCH_RATCHET_REGRESSION, DOC_OBLIGATION_UNRESOLVED", line)
        data = (self.root / "brain" / "knowledge.md").read_bytes()
        self.assertEqual(data.count(b"\r\n"), data.count(b"\n"))
        note_raised_rules(self.root, "c", ["DOC_OBLIGATION_UNRESOLVED", "ARCH_RATCHET_REGRESSION"])
        self.assertIsNone(distill_session_knowledge(self.root, "c"))
        self.assertEqual(data, (self.root / "brain" / "knowledge.md").read_bytes())

    def test_nothing_raised_or_no_knowledge_file_writes_nothing(self):
        self.assertIsNone(distill_session_knowledge(self.root, "c"))
        note_raised_rules(self.root, "c", ["X_RULE"])
        self.assertIsNone(distill_session_knowledge(self.root, "c"))
        self.assertFalse((self.root / "brain").exists())


if __name__ == "__main__":
    unittest.main()
