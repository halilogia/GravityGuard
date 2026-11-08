"""ARCH_RATCHET_GROWTH_DENY, git-independent debt baselines, session touched files and runtime sprawl redirection."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from gravityguard_engine.debt_baselines import load_baselines, record_pre_write_baseline
from gravityguard_engine.debt_ratchet import evaluate_changed_files_ratchet
from gravityguard_engine.governance import get_governance_file_path
from gravityguard_engine.project_context import DEFAULT_COMPLEXITY_THRESHOLDS, resolve_project_root
from gravityguard_engine.ratchet_growth import check_ratchet_growth, pre_write_ratchet_denies, session_touched_files
from gravityguard_engine.runtime_paths import ephemeral_dir, is_system_or_user_root, runtime_dir

_ENGINE_DIR = str(Path(__file__).resolve().parent.parent)
VALIDATOR = os.path.join(_ENGINE_DIR, "gravity-validator.py")


def _lines(count: int, prefix: str = "x") -> str:
    return "".join(f"{prefix}{i} = {i}\n" for i in range(count))


class GrowthDenyTests(unittest.TestCase):
    def test_growth_of_a_file_at_the_limit_is_denied_with_refactor_advice(self):
        msg = check_ratchet_growth("src/core.py", _lines(500), _lines(501), 500)
        self.assertIn("500 satırdan 501 satıra (+1)", msg)
        self.assertIn("yeni bir modüle", msg)

    def test_refactor_shrink_and_equal_size_are_allowed(self):
        self.assertEqual(check_ratchet_growth("src/core.py", _lines(700), _lines(650), 500), "")
        self.assertEqual(check_ratchet_growth("src/core.py", _lines(700), _lines(700), 500), "")

    def test_files_under_the_limit_tests_data_and_new_files_are_not_locked(self):
        self.assertEqual(check_ratchet_growth("src/core.py", _lines(499), _lines(900), 500), "")
        self.assertEqual(check_ratchet_growth("tests/test_core.py", _lines(700), _lines(800), 500), "")
        self.assertEqual(check_ratchet_growth("data.json", _lines(700), _lines(800), 500), "")
        self.assertEqual(check_ratchet_growth("src/new.py", "", _lines(800), 500), "")


class PreWriteTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="gg_growth_")
        self.thresholds = dict(DEFAULT_COMPLEXITY_THRESHOLDS)
        self.env = unittest.mock.patch.dict(os.environ)
        self.env.start()
        os.environ.pop("GRAVITYGUARD_LOG_DIR", None)  # other suites leak it; here the state must live in the project

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_write_records_baseline_and_session_touch_outside_git(self):
        target = os.path.join(self.root, "mod.py")
        Path(target).write_text(_lines(480), encoding="utf-8")
        denies = pre_write_ratchet_denies(self.root, target, _lines(480), _lines(520), self.thresholds, "sess")
        self.assertEqual(denies, [])
        self.assertEqual(load_baselines(self.root), {"mod.py": 480})
        self.assertEqual([os.path.basename(p) for p in session_touched_files(Path(self.root), "sess")], ["mod.py"])
        state = json.loads(get_governance_file_path(Path(self.root)).read_text(encoding="utf-8"))
        self.assertEqual(state["sessions"]["sess"]["touched_files"], ["mod.py"])

    def test_denial_names_the_rule(self):
        target = os.path.join(self.root, "big.py")
        denies = pre_write_ratchet_denies(self.root, target, _lines(600), _lines(610), self.thresholds, "sess")
        self.assertEqual([rule for rule, _ in denies], ["ARCH_RATCHET_GROWTH_DENY"])

    def test_baseline_never_rises_and_is_dropped_when_the_file_gets_small(self):
        record_pre_write_baseline(self.root, "mod.py", 600, 650, 500)
        record_pre_write_baseline(self.root, "mod.py", 650, 700, 500)
        self.assertEqual(load_baselines(self.root), {"mod.py": 600})
        record_pre_write_baseline(self.root, "mod.py", 600, 400, 500)
        self.assertEqual(load_baselines(self.root), {})


class GitFreeBaselineTests(unittest.TestCase):
    def test_ratchet_uses_pre_write_size_when_there_is_no_git_head(self):
        root = tempfile.mkdtemp(prefix="gg_nogit_")
        try:
            target = os.path.join(root, "grown.py")
            record_pre_write_baseline(root, "grown.py", 520, 560, 500)
            Path(target).write_text(_lines(560), encoding="utf-8")
            found = evaluate_changed_files_ratchet(root, [target], threshold=500)
            self.assertEqual([(rel, base, delta) for rel, base, delta, _ in found], [("grown.py", 520, 40)])
        finally:
            shutil.rmtree(root, ignore_errors=True)


class SprawlTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="gg_home_")
        for sub in ("Desktop", "Documents", "Downloads", "vault/.obsidian", "Desktop/GitHub/Public/real"):
            os.makedirs(os.path.join(self.home, sub))
        self.env = unittest.mock.patch.dict(os.environ, {"USERPROFILE": self.home, "HOME": self.home})
        self.env.start()
        os.environ.pop("GRAVITYGUARD_LOG_DIR", None)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.home, ignore_errors=True)

    def test_user_and_system_folders_are_not_project_roots(self):
        for sub in ("", "Desktop", "Documents", "Downloads", "vault/.obsidian", "Desktop/GitHub/Public"):
            self.assertTrue(is_system_or_user_root(os.path.join(self.home, sub)), sub)
        self.assertTrue(is_system_or_user_root(os.path.dirname(os.path.realpath(self.home))))
        self.assertFalse(is_system_or_user_root(os.path.join(self.home, "Desktop", "GitHub", "Public", "real")))

    def test_runtime_of_a_user_folder_goes_to_the_central_ephemeral_dir(self):
        desktop = os.path.join(self.home, "Desktop")
        self.assertEqual(runtime_dir(desktop), ephemeral_dir(desktop) / "runtime")
        self.assertEqual(Path(os.path.realpath(self.home), ".gravityguard", "ephemeral"), Path(os.path.realpath(ephemeral_dir(desktop).parent)))
        real = os.path.join(self.home, "Desktop", "GitHub", "Public", "real")
        self.assertEqual(runtime_dir(real), Path(real) / ".gravityguard" / "runtime")

    def test_governance_state_of_a_user_folder_never_creates_a_local_marker_dir(self):
        desktop = Path(self.home, "Desktop")
        path = get_governance_file_path(desktop)
        self.assertFalse((desktop / ".gravityguard").exists())
        self.assertIn("ephemeral", path.parts)

    def test_git_marker_in_a_user_folder_does_not_make_it_the_project_root(self):
        desktop = Path(self.home, "Desktop")
        (desktop / ".git").mkdir()
        sibling = desktop / "scratch.py"
        sibling.write_text("x = 1\n", encoding="utf-8")
        self.assertNotEqual(os.path.normcase(str(resolve_project_root(None, str(sibling)))), os.path.normcase(str(desktop)))
        real = Path(self.home, "Desktop", "GitHub", "Public", "real")
        (real / ".git").mkdir()
        self.assertEqual(resolve_project_root(None, str(real / "a.py")), real)


class DispatcherDenyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gg_growth_e2e_")
        self.proj = Path(self.tmp) / "proj"
        self.proj.mkdir()
        (self.proj / "big.py").write_text(_lines(600), encoding="utf-8")
        for cmd in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "i"]):
            subprocess.run(["git", *cmd], cwd=self.proj, check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, content):
        env = {**os.environ, "GRAVITYGUARD_LOG_DIR": os.path.join(self.tmp, "logs"), "GRAVITYGUARD_DISABLE_ASYNC": "1",
               "GRAVITYGUARD_USER_CONFIG": os.path.join(self.tmp, "none.json")}
        payload = {"toolCall": {"name": "write_to_file", "args": {"TargetFile": str(self.proj / name), "CodeContent": content}},
                   "workspacePaths": [str(self.proj)], "conversationId": "c9"}
        proc = subprocess.run([sys.executable, VALIDATOR], input=json.dumps(payload), capture_output=True, text=True,
                              encoding="utf-8", cwd=str(self.proj), env=env, timeout=90)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_growth_is_blocked_and_shrink_is_allowed_end_to_end(self):
        denied = self.write("big.py", _lines(610))
        self.assertEqual(denied["decision"], "deny")
        self.assertIn("ARCH_RATCHET_GROWTH_DENY", denied["reason"])
        self.assertEqual(self.write("big.py", _lines(560))["decision"], "allow")


if __name__ == "__main__":
    unittest.main()
