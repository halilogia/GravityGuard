"""ARCH_RATCHET_GROWTH_DENY: delta rule, non-git baseline seeding, runtime store, touched-file Stop candidates."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gravityguard_engine.debt_ratchet import (
    evaluate_changed_files_ratchet,
    get_ratchet_store_path,
    load_debt_ratchet,
    save_debt_ratchet,
)
from gravityguard_engine.ratchet_gate import check_ratchet_growth
from gravityguard_engine.stop_gate import (
    note_touched_file,
    ratchet_findings,
    session_touched_files,
)

_ENGINE_DIR = str(Path(__file__).resolve().parent.parent)
VALIDATOR = os.path.join(_ENGINE_DIR, "gravity-validator.py")


def _src(count: int) -> str:
    return "".join(f"x{i} = {i}\n" for i in range(count))


class RatchetGrowthRuleTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="gg_growth_")  # deliberately not a git repository

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def check(self, name, old, new, threshold=500):
        return check_ratchet_growth(self.root, os.path.join(self.root, name), old, new, threshold)

    def test_net_growth_of_a_file_over_the_threshold_is_denied(self):
        msg = self.check("mono.py", _src(600), _src(630))
        self.assertIn("600 satırdan 630 satıra (+30)", msg)
        self.assertIn("TEK bir düzenleme", msg)

    def test_small_net_growth_passes_below_the_hard_cap_but_not_above_it(self):
        self.assertEqual(self.check("mono.py", _src(600), _src(620)), "")   # +20: a small fix
        self.assertNotEqual(self.check("mono.py", _src(600), _src(621)), "")
        self.assertEqual(self.check("big.py", _src(780), _src(800)), "")    # lands exactly on the cap
        self.assertNotEqual(self.check("big.py", _src(790), _src(805)), "")  # over the cap: even +15 is denied

    def test_shrinking_and_net_zero_edits_pass_so_refactors_are_never_blocked(self):
        self.assertEqual(self.check("mono.py", _src(600), _src(560)), "")
        self.assertEqual(self.check("mono.py", _src(600), _src(600)), "")

    def test_small_files_may_grow_until_they_cross_the_threshold(self):
        self.assertEqual(self.check("small.py", _src(100), _src(500)), "")
        self.assertNotEqual(self.check("small.py", _src(495), _src(520)), "")

    def test_new_files_tests_and_data_are_not_this_rules_business(self):
        self.assertEqual(self.check("fresh.py", "", _src(700)), "")  # G5_NEW_FILE_BLOAT_DENY governs creation
        self.assertEqual(self.check("tests/test_big.py", _src(600), _src(700)), "")
        self.assertEqual(self.check("data.json", _src(600), _src(700)), "")

    def test_file_outside_the_resolved_root_is_still_judged(self):
        other = tempfile.mkdtemp(prefix="gg_elsewhere_")
        try:
            msg = check_ratchet_growth(self.root, os.path.join(other, "mono.py"), _src(600), _src(650), 500)
            self.assertIn("+50", msg)
        finally:
            shutil.rmtree(other, ignore_errors=True)

    def test_first_touch_seeds_the_baseline_from_disk_size_outside_git(self):
        self.check("mono.py", _src(600), _src(560))
        store = get_ratchet_store_path(self.root)
        self.assertTrue(store.endswith(os.path.join(".gravityguard", "runtime", "debt_baselines.json")))
        self.assertEqual(load_debt_ratchet(self.root)["files"]["mono.py"]["baseline_loc"], 600)
        self.check("small.py", _src(100), _src(120))
        self.assertNotIn("small.py", load_debt_ratchet(self.root)["files"])

    def test_legacy_store_is_still_read_and_the_next_save_moves_it(self):
        legacy = os.path.join(self.root, ".gravityguard", "debt_ratchet.json")
        os.makedirs(os.path.dirname(legacy))
        with open(legacy, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "files": {"old.py": {"baseline_loc": 700}}}, fh)
        data = load_debt_ratchet(self.root)
        self.assertEqual(data["files"]["old.py"]["baseline_loc"], 700)
        save_debt_ratchet(self.root, data)
        self.assertTrue(os.path.isfile(get_ratchet_store_path(self.root)))


class TouchedFilesStopTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="gg_touched_"))
        env = mock.patch.dict(os.environ)  # other test modules park GRAVITYGUARD_LOG_DIR in the process environment
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("GRAVITYGUARD_LOG_DIR", None)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def git(self, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=self.root, check=True, capture_output=True)

    def test_touched_files_are_stored_per_session_deduped_and_source_only(self):
        big = self.root / "big.py"
        big.write_text(_src(10), encoding="utf-8")
        for _ in range(2):
            note_touched_file(self.root, "c1", str(big))
        note_touched_file(self.root, "c1", str(self.root / "notes.md"))
        note_touched_file(self.root, "c1", str(self.root.parent / "outside.py"))
        self.assertEqual(session_touched_files(self.root, "c1"), [str(big)])
        self.assertEqual(session_touched_files(self.root, "other"), [])
        state = json.loads((self.root / ".gravityguard" / "runtime" / "governance.json").read_text(encoding="utf-8"))
        self.assertEqual(state["sessions"]["c1"]["touched_files"], ["big.py"])

    def test_stop_check_finds_growth_outside_git(self):
        big = self.root / "big.py"
        big.write_text(_src(600), encoding="utf-8")
        check_ratchet_growth(str(self.root), str(big), _src(600), _src(600), 500)  # the hook's first touch
        note_touched_file(self.root, "c1", str(big))
        big.write_text(_src(650), encoding="utf-8")  # growth that bypassed the hook, e.g. a shell redirect
        found = ratchet_findings(self.root, None, "c1", False)
        self.assertEqual([rel for rel, _ in found], ["big.py"])

    def test_stop_check_ignores_logs_and_non_source_files(self):
        (self.root / "screenshots").mkdir()
        log = self.root / "screenshots" / "run.log"
        log.write_text(_src(700), encoding="utf-8")
        self.git("init", "-q")
        log.write_text(_src(900), encoding="utf-8")
        note_touched_file(self.root, "c1", str(log))
        self.assertEqual(evaluate_changed_files_ratchet(str(self.root), [str(log), str(self.root / "a.html")], 500), [])
        self.assertEqual(ratchet_findings(self.root, None, "c1", False), [])

    def test_stop_check_still_sees_the_file_after_git_commit(self):
        self.git("init", "-q")
        big = self.root / "big.py"
        big.write_text(_src(600), encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "i")
        check_ratchet_growth(str(self.root), str(big), _src(600), _src(600), 500)
        note_touched_file(self.root, "c1", str(big))
        big.write_text(_src(650), encoding="utf-8")
        self.git("commit", "-q", "-am", "grow")  # clean working tree: git status reports nothing
        self.assertEqual([rel for rel, _ in ratchet_findings(self.root, None, "c1", False)], ["big.py"])
        self.assertEqual(ratchet_findings(self.root, None, "unrelated", False), [])


class RatchetGrowthEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gg_growth_e2e_")
        self.proj = Path(self.tmp) / "proj"
        self.proj.mkdir()
        (self.proj / ".gravityguard.json").write_text("{}", encoding="utf-8")
        (self.proj / "mono.py").write_text(_src(600), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, content):
        env = {**os.environ, "GRAVITYGUARD_LOG_DIR": os.path.join(self.tmp, "logs"), "GRAVITYGUARD_DISABLE_ASYNC": "1",
               "GRAVITYGUARD_USER_CONFIG": os.path.join(self.tmp, "none.json")}
        payload = {"toolCall": {"name": "write_to_file", "args": {"TargetFile": str(self.proj / name), "CodeContent": content}},
                   "workspacePaths": [str(self.proj)], "conversationId": "c2"}
        proc = subprocess.run([sys.executable, VALIDATOR], input=json.dumps(payload), capture_output=True, text=True,
                              encoding="utf-8", cwd=str(self.proj), env=env, timeout=90)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_growth_is_blocked_shrink_is_allowed_and_the_baseline_is_kept(self):
        denied = self.write("mono.py", _src(630))
        self.assertEqual(denied["decision"], "deny")
        self.assertIn("ARCH_RATCHET_GROWTH_DENY", denied["reason"])
        self.assertEqual(self.write("mono.py", _src(550))["decision"], "allow")
        baselines = self.proj / ".gravityguard" / "runtime" / "debt_baselines.json"
        self.assertEqual(json.loads(baselines.read_text(encoding="utf-8"))["files"]["mono.py"]["baseline_loc"], 600)

    def test_allowed_write_records_the_touched_file_in_governance_json(self):
        self.assertEqual(self.write("mono.py", _src(550))["decision"], "allow")
        state = json.loads((Path(self.tmp) / "logs" / "governance.json").read_text(encoding="utf-8"))  # GRAVITYGUARD_LOG_DIR relocates it
        self.assertIn("mono.py", state["sessions"]["c2"]["touched_files"])

    def test_shadow_mode_observes_without_blocking(self):
        (self.proj / ".gravityguard.json").write_text(json.dumps({"rules": {"ARCH_RATCHET_GROWTH_DENY": "shadow"}}), encoding="utf-8")
        self.assertEqual(self.write("mono.py", _src(630))["decision"], "allow")


if __name__ == "__main__":
    unittest.main()
