#!/usr/bin/env python3
"""
Unit tests for the T0 gate: LCOV coverage parsing / evaluation and dynamic test execution.
"""
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

from gravityguard_engine.test_evidence import (  # noqa: E402
    _count_tests,
    detect_test_runner,
    evaluate_lcov_coverage,
    evaluate_t0_gate,
    get_min_coverage_percent,
    is_dynamic_execution_enabled,
    parse_lcov,
    run_dynamic_tests,
)

SAMPLE_LCOV = """TN:
SF:src/billing.ts
DA:1,1
DA:2,1
DA:3,0
DA:4,0
LF:4
LH:2
BRF:4
BRH:1
end_of_record
SF:src/full.ts
DA:1,3
DA:2,1
LF:2
LH:2
BRF:2
BRH:2
end_of_record
"""


def _py_cmd(code: str):
    return [sys.executable, "-c", code]


class TestParseLcov(unittest.TestCase):
    def test_parses_sf_da_lf_lh_brf_brh(self):
        files = parse_lcov(SAMPLE_LCOV)["files"]
        self.assertEqual(set(files), {"src/billing.ts", "src/full.ts"})
        b = files["src/billing.ts"]
        self.assertEqual((b["lf"], b["lh"], b["brf"], b["brh"]), (4, 2, 4, 1))
        self.assertEqual(b["lines"], {1: 1, 2: 1, 3: 0, 4: 0})

    def test_falls_back_to_da_and_brda_when_summaries_missing(self):
        text = "SF:a.py\nDA:1,2\nDA:2,0\nDA:3,5\nBRDA:1,0,0,1\nBRDA:1,0,1,-\nBRDA:2,0,0,0\nend_of_record\n"
        rec = parse_lcov(text)["files"]["a.py"]
        self.assertEqual((rec["lf"], rec["lh"]), (3, 2))
        self.assertEqual((rec["brf"], rec["brh"]), (3, 1))

    def test_garbage_and_empty_input(self):
        self.assertEqual(parse_lcov("")["files"], {})
        self.assertEqual(parse_lcov("DA:1,1\nrandom\nLF:x\n")["files"], {})
        rec = parse_lcov("SF:x\nDA:oops\nDA:2,1\nLF:bad\nend_of_record")["files"]["x"]
        self.assertEqual((rec["lf"], rec["lh"]), (1, 1))


class TestEvaluateLcovCoverage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lcov = os.path.join(self.tmp.name, "lcov.info")
        Path(self.lcov).write_text(SAMPLE_LCOV, encoding="utf-8")

    def test_below_threshold_is_flagged_with_line_and_branch_numbers(self):
        violated, msg, details = evaluate_lcov_coverage(self.lcov, ["src/billing.ts"], 80.0)
        self.assertTrue(violated)
        self.assertIn("T0_COVERAGE_BELOW_THRESHOLD", msg)
        self.assertEqual(details["files"]["src/billing.ts"]["line_pct"], 50.0)
        self.assertEqual(details["files"]["src/billing.ts"]["branch_pct"], 25.0)
        self.assertEqual(details["below"], ["src/billing.ts"])

    def test_full_coverage_passes(self):
        violated, msg, details = evaluate_lcov_coverage(self.lcov, ["src/full.ts"], 80.0)
        self.assertFalse(violated)
        self.assertEqual(msg, "")
        self.assertEqual(details["files"]["src/full.ts"]["line_pct"], 100.0)
        self.assertEqual(details["files"]["src/full.ts"]["branch_pct"], 100.0)

    def test_threshold_boundary_is_inclusive_and_configurable(self):
        self.assertFalse(evaluate_lcov_coverage(self.lcov, ["src/billing.ts"], 50.0)[0])
        self.assertTrue(evaluate_lcov_coverage(self.lcov, ["src/billing.ts"], 50.1)[0])
        self.assertFalse(evaluate_lcov_coverage(self.lcov, ["src/billing.ts"], 0)[0])

    def test_branch_coverage_is_reported_but_does_not_trip_the_gate(self):
        text = "SF:b.ts\nLF:10\nLH:10\nBRF:10\nBRH:1\nend_of_record\n"
        Path(self.lcov).write_text(text, encoding="utf-8")
        violated, _, details = evaluate_lcov_coverage(self.lcov, ["b.ts"], 80.0)
        self.assertFalse(violated)
        self.assertEqual(details["files"]["b.ts"]["branch_pct"], 10.0)

    def test_mixed_files_only_failing_ones_are_reported(self):
        violated, msg, details = evaluate_lcov_coverage(self.lcov, ["src/full.ts", "src/billing.ts"], 80.0)
        self.assertTrue(violated)
        self.assertIn("billing.ts", msg)
        self.assertNotIn("full.ts", msg)

    def test_absolute_and_windows_paths_match_relative_sf(self):
        root = self.tmp.name
        target = os.path.join(root, "src", "billing.ts")
        self.assertTrue(evaluate_lcov_coverage(self.lcov, [target], 80.0, repo_root=root)[0])
        self.assertTrue(evaluate_lcov_coverage(self.lcov, ["src\\Billing.ts"], 80.0)[0])
        self.assertTrue(evaluate_lcov_coverage(self.lcov, ["./src/billing.ts"], 80.0)[0])

    def test_absolute_sf_matches_relative_target(self):
        Path(self.lcov).write_text("SF:C:\\proj\\src\\billing.ts\nLF:2\nLH:0\nend_of_record\n", encoding="utf-8")
        self.assertTrue(evaluate_lcov_coverage(self.lcov, ["src/billing.ts"], 80.0)[0])

    def test_suffix_match_does_not_confuse_similar_names(self):
        violated, _, details = evaluate_lcov_coverage(self.lcov, ["src/other_billing.ts"], 80.0)
        self.assertFalse(violated)
        self.assertEqual(details["unmeasured"], ["src/other_billing.ts"])

    def test_unmeasured_and_missing_report_are_not_violations(self):
        violated, _, details = evaluate_lcov_coverage(self.lcov, ["src/unknown.ts"], 80.0)
        self.assertFalse(violated)
        self.assertEqual(details["unmeasured"], ["src/unknown.ts"])
        violated, msg, details = evaluate_lcov_coverage(os.path.join(self.tmp.name, "nope.info"), ["a.ts"])
        self.assertFalse(violated)
        self.assertEqual(details["status"], "no_lcov")

    def test_file_with_no_instrumented_lines_is_not_a_violation(self):
        Path(self.lcov).write_text("SF:empty.ts\nLF:0\nLH:0\nend_of_record\n", encoding="utf-8")
        violated, _, details = evaluate_lcov_coverage(self.lcov, ["empty.ts"], 80.0)
        self.assertFalse(violated)
        self.assertIsNone(details["files"]["empty.ts"]["line_pct"])

    def test_threshold_config(self):
        self.assertEqual(get_min_coverage_percent(None), 80.0)
        self.assertEqual(get_min_coverage_percent({}), 80.0)
        self.assertEqual(get_min_coverage_percent({"testEvidence": {"minCoveragePercent": 65}}), 65.0)
        for bad in ("90", True, -1, 101, None):
            self.assertEqual(get_min_coverage_percent({"testEvidence": {"minCoveragePercent": bad}}), 80.0)


class TestDetectTestRunner(unittest.TestCase):
    def _root(self, files):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name, content in files.items():
            Path(tmp.name, name).write_text(content, encoding="utf-8")
        return tmp.name

    def test_detection_matrix(self):
        cases = [
            ({"package.json": json.dumps({"scripts": {"test": "node --test"}})}, ["npm", "test"]),
            ({"package.json": json.dumps({"scripts": {"test": 'echo "Error: no test specified" && exit 1'}})}, None),
            ({"package.json": json.dumps({"devDependencies": {"vitest": "^1"}})}, ["npx", "vitest", "run"]),
            ({"package.json": "{broken"}, None),
            ({"pytest.ini": "[pytest]"}, [sys.executable, "-m", "pytest", "-q"]),
            ({"conftest.py": ""}, [sys.executable, "-m", "pytest", "-q"]),
            ({"setup.py": ""}, [sys.executable, "-m", "pytest", "-q"]),
            ({"Cargo.toml": "[package]"}, ["cargo", "test"]),
            ({}, None),
            ({"package.json": json.dumps({"scripts": {"test": "jest"}}), "pytest.ini": ""}, ["npm", "test"]),
            ({"pytest.ini": "", "Cargo.toml": ""}, [sys.executable, "-m", "pytest", "-q"]),
        ]
        for files, expected in cases:
            self.assertEqual(detect_test_runner(self._root(files)), expected, files)


class TestCountTests(unittest.TestCase):
    def test_runner_output_formats(self):
        cases = [
            ("....\nRan 12 tests in 0.5s\n\nOK", 12),
            ("Ran 1 test in 0.001s", 1),
            ("ℹ tests 109\nℹ pass 109", 109),
            ("# tests 7\n# pass 7", 7),
            ("Tests:       1 failed, 4 passed, 5 total", 5),
            ("test result: ok. 3 passed; 1 failed; 0 ignored\ntest result: ok. 2 passed; 0 failed", 6),
            (" Tests  2 failed | 8 passed (10)", 10),
            ("1 failed, 2 passed in 0.50s", 3),
            ("\x1b[32m5 passed\x1b[0m in 1.20s", 5),
            ("no tests ran in 0.01s", 0),
            ("Ran 0 tests in 0.000s\n\nNO TESTS RAN", 0),
            ("hello world", None),
        ]
        for text, expected in cases:
            self.assertEqual(_count_tests(text), expected, text)


class TestRunDynamicTests(unittest.TestCase):
    def test_passing_run_reports_exit_code_and_count(self):
        res = run_dynamic_tests(os.getcwd(), 20, _py_cmd("print('Ran 3 tests in 0.1s')"))
        self.assertEqual((res["status"], res["exit_code"], res["tests_executed"]), ("ok", 0, 3))

    def test_nonzero_exit_is_failed(self):
        res = run_dynamic_tests(os.getcwd(), 20, _py_cmd("import sys; print('Ran 4 tests'); sys.exit(1)"))
        self.assertEqual((res["status"], res["exit_code"], res["tests_executed"]), ("failed", 1, 4))

    def test_zero_tests_is_no_tests(self):
        res = run_dynamic_tests(os.getcwd(), 20, _py_cmd("print('Ran 0 tests in 0.0s')"))
        self.assertEqual((res["status"], res["exit_code"], res["tests_executed"]), ("no_tests", 0, 0))

    def test_unknown_output_with_zero_exit_is_ok_not_no_tests(self):
        res = run_dynamic_tests(os.getcwd(), 20, _py_cmd("print('all good')"))
        self.assertEqual((res["status"], res["tests_executed"]), ("ok", None))

    def test_timeout_kills_the_process_tree(self):
        started = time.perf_counter()
        res = run_dynamic_tests(os.getcwd(), 1, _py_cmd("import time; time.sleep(30)"))
        self.assertEqual(res["status"], "timeout")
        self.assertLess(time.perf_counter() - started, 15)

    def test_missing_executable_and_no_runner(self):
        self.assertEqual(run_dynamic_tests(os.getcwd(), 5, ["definitely-not-a-real-binary-xyz"])["status"], "error")
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(run_dynamic_tests(empty, 5)["status"], "no_runner")

    def test_runs_real_unittest_suite_in_the_project_directory(self):
        with tempfile.TemporaryDirectory() as proj:
            Path(proj, "test_sample.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n"
                "    def test_a(self): self.assertEqual(1, 1)\n    def test_b(self): self.assertEqual(2, 1 + 1)\n",
                encoding="utf-8")
            res = run_dynamic_tests(proj, 30, [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py"])
            self.assertEqual((res["status"], res["exit_code"], res["tests_executed"]), ("ok", 0, 2))
            Path(proj, "test_sample.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n    def test_a(self): self.assertEqual(1, 2)\n",
                encoding="utf-8")
            res = run_dynamic_tests(proj, 30, [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py"])
            self.assertEqual((res["status"], res["tests_executed"]), ("failed", 1))
            self.assertIn("AssertionError", res["output_tail"])


class TestT0Gate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.lcov = os.path.join(self.root, "coverage", "lcov.info")
        os.makedirs(os.path.dirname(self.lcov))

    def _cfg(self, code, **extra):
        te = {"dynamicExecution": True, "testCommand": _py_cmd(code), "timeoutSec": 20}
        te.update(extra)
        return {"testEvidence": te}

    def _write_lcov(self, text=SAMPLE_LCOV, age=0):
        Path(self.lcov).write_text(text, encoding="utf-8")
        if age:
            past = time.time() - age
            os.utime(self.lcov, (past, past))

    def test_opt_in_default_is_off(self):
        self.assertFalse(is_dynamic_execution_enabled(None))
        self.assertFalse(is_dynamic_execution_enabled({"testEvidence": {}}))
        self.assertFalse(is_dynamic_execution_enabled({"testEvidence": {"dynamicExecution": "yes"}}))
        self.assertFalse(is_dynamic_execution_enabled({"testEvidence": {"dynamicExecution": True, "enabled": False}}))
        self.assertTrue(is_dynamic_execution_enabled({"testEvidence": {"dynamicExecution": True}}))
        marker = os.path.join(self.root, "ran.txt")
        cfg = {"testEvidence": {"testCommand": _py_cmd(f"open({marker!r}, 'w').write('x')")}}
        self.assertEqual(evaluate_t0_gate(self.root, cfg), [])
        self.assertFalse(os.path.exists(marker), "tests must not execute unless dynamicExecution is true")

    def test_failing_run_yields_t0_test_run_failed(self):
        out = evaluate_t0_gate(self.root, self._cfg("import sys; print('Ran 2 tests'); print('boom'); sys.exit(3)"))
        self.assertEqual([r for r, _ in out], ["T0_TEST_RUN_FAILED"])
        self.assertIn("3", out[0][1])
        self.assertIn("boom", out[0][1])

    def test_timeout_yields_t0_test_run_failed(self):
        out = evaluate_t0_gate(self.root, self._cfg("import time; time.sleep(30)", timeoutSec=1))
        self.assertEqual([r for r, _ in out], ["T0_TEST_RUN_FAILED"])
        self.assertIn("zaman aşımı", out[0][1])

    def test_zero_tests_yields_t0_no_tests_executed(self):
        out = evaluate_t0_gate(self.root, self._cfg("print('Ran 0 tests in 0.0s')"))
        self.assertEqual([r for r, _ in out], ["T0_NO_TESTS_EXECUTED"])

    def test_green_run_without_report_is_silent(self):
        self.assertEqual(evaluate_t0_gate(self.root, self._cfg("print('Ran 5 tests')"), ["src/billing.ts"]), [])

    def test_fresh_low_coverage_is_flagged_and_threshold_comes_from_config(self):
        self._write_lcov()
        cfg = self._cfg("print('Ran 5 tests')")
        out = evaluate_t0_gate(self.root, cfg, ["src/billing.ts"])
        self.assertEqual([r for r, _ in out], ["T0_COVERAGE_BELOW_THRESHOLD"])
        cfg["testEvidence"]["minCoveragePercent"] = 40
        self.assertEqual(evaluate_t0_gate(self.root, cfg, ["src/billing.ts"]), [])

    def test_full_coverage_is_silent(self):
        self._write_lcov()
        self.assertEqual(evaluate_t0_gate(self.root, self._cfg("print('Ran 5 tests')"), ["src/full.ts"]), [])

    def test_stale_report_not_produced_by_this_run_is_ignored(self):
        self._write_lcov(age=3600)
        self.assertEqual(evaluate_t0_gate(self.root, self._cfg("print('Ran 5 tests')"), ["src/billing.ts"]), [])

    def test_custom_lcov_path_and_exempt_files(self):
        custom = os.path.join(self.root, "out.info")
        Path(custom).write_text(SAMPLE_LCOV, encoding="utf-8")
        cfg = self._cfg("print('Ran 5 tests')", lcovPath="out.info")
        self.assertEqual([r for r, _ in evaluate_t0_gate(self.root, cfg, ["src/billing.ts"])], ["T0_COVERAGE_BELOW_THRESHOLD"])
        self.assertEqual(evaluate_t0_gate(self.root, cfg, ["src/types.ts"]), [], "exempt files are not gated")

    def test_failed_tests_short_circuit_coverage(self):
        self._write_lcov()
        out = evaluate_t0_gate(self.root, self._cfg("import sys; print('Ran 1 tests'); sys.exit(1)"), ["src/billing.ts"])
        self.assertEqual([r for r, _ in out], ["T0_TEST_RUN_FAILED"])

    def test_no_detectable_runner_is_silent(self):
        self.assertEqual(evaluate_t0_gate(self.root, {"testEvidence": {"dynamicExecution": True}}), [])


class TestT0StopHookIntegration(unittest.TestCase):
    """Runs the real gravity-validator.py Stop hook against a throwaway project."""

    VALIDATOR = os.path.join(_ENGINE_DIR, "gravity-validator.py")

    def _stop(self, te_cfg):
        with tempfile.TemporaryDirectory() as proj, tempfile.TemporaryDirectory() as logs:
            Path(proj, ".gravityguard.json").write_text(json.dumps({"testEvidence": te_cfg}), encoding="utf-8")
            env = {**os.environ, "GRAVITYGUARD_LOG_DIR": logs, "GRAVITYGUARD_DISABLE_ASYNC": "1",
                   "GRAVITYGUARD_USER_CONFIG": os.path.join(logs, "none.json")}
            proc = subprocess.run(
                [sys.executable, self.VALIDATOR], input=json.dumps({"terminationReason": "model_stop", "workspacePaths": [proj]}),
                capture_output=True, text=True, cwd=proj, env=env, timeout=60)
            return json.loads(proc.stdout.strip()), proc.stderr

    def test_stop_continues_with_t0_failure(self):
        res, err = self._stop({"dynamicExecution": True, "testCommand": _py_cmd("import sys; print('Ran 2 tests'); sys.exit(1)")})
        self.assertEqual(res.get("decision"), "continue", err)
        self.assertIn("T0_TEST_RUN_FAILED", res["reason"])
        self.assertIn("[Test: ✗]", res["reason"])

    def test_stop_continues_when_no_tests_executed(self):
        res, err = self._stop({"dynamicExecution": True, "testCommand": _py_cmd("print('Ran 0 tests in 0.0s')")})
        self.assertEqual(res.get("decision"), "continue", err)
        self.assertIn("T0_NO_TESTS_EXECUTED", res["reason"])

    def test_stop_allows_green_run(self):
        res, err = self._stop({"dynamicExecution": True, "testCommand": _py_cmd("print('Ran 3 tests in 0.1s')")})
        self.assertEqual(res.get("decision"), "allow", err)

    def test_stop_never_runs_tests_when_not_opted_in(self):
        with tempfile.TemporaryDirectory() as marker_dir:
            marker = os.path.join(marker_dir, "ran.txt")
            res, err = self._stop({"testCommand": _py_cmd(f"open({marker!r}, 'w').write('x')")})
            self.assertEqual(res.get("decision"), "allow", err)
            self.assertFalse(os.path.exists(marker))


class TestValidatorFacadeExports(unittest.TestCase):
    def test_validator_re_exports_t0_api(self):
        src = Path(_ENGINE_DIR, "gravity-validator.py").read_text(encoding="utf-8")
        for name in ("parse_lcov", "evaluate_lcov_coverage", "detect_test_runner", "run_dynamic_tests", "evaluate_t0_gate"):
            self.assertIn(name, src)


if __name__ == "__main__":
    unittest.main()
