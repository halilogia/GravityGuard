"""Tier 4 deep security audit: findings, SARIF, git binding, scan CLI, fix verification."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gravityguard_engine.diffing import binding_is_stale, git_binding
from gravityguard_engine.security_audit import (
    Finding, dedupe, invalidate_stale_report, list_files, load_report, make_finding_id,
    record_baseline, report_findings, run_scan, scan_text, to_sarif, verify_patched,
)

ENGINE = Path(__file__).resolve().parents[1]
VULN = (
    "import os, pickle, subprocess, sys\n"
    "def handler(request):\n"
    "    name = request.args.get('f')\n"
    "    os.system('ls ' + name)\n"
    "    data = pickle.loads(sys.stdin.buffer.read())\n"
    "    eval(name)\n"
    "    return open('/srv/' + name).read()\n"
)


def git(root, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=str(root), check=True, capture_output=True)


def make_repo(root: Path, files: dict) -> None:
    git(root, "init", "-q")
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")


class FindingModelTests(unittest.TestCase):
    def test_validation_and_roundtrip(self):
        f = Finding("GG-1", "GGS004", "HIGH", 0.7, "m", "a.py", 3, attack_path=[{"file": "a.py", "line": 3, "description": "d"}],
                    evidence_payload="eval(x)", reproduction_test="t.py", unexamined_scope=["x"])
        self.assertEqual(Finding.from_dict(f.to_dict()), f)
        self.assertEqual(f.verification_status, "UNVERIFIED")
        with self.assertRaises(ValueError):
            Finding("i", "r", "SEVERE", 0.5, "m", "a", 1)
        with self.assertRaises(ValueError):
            Finding("i", "r", "LOW", 1.5, "m", "a", 1)
        with self.assertRaises(ValueError):
            Finding("i", "r", "LOW", 0.5, "m", "a", 1, verification_status="DONE")

    def test_dedupe_keeps_highest_confidence_per_rule_file_line(self):
        a = Finding("1", "GGS004", "HIGH", 0.4, "m", "a.py", 3)
        b = Finding("2", "GGS004", "HIGH", 0.9, "m", "a.py", 3)
        c = Finding("3", "GGS004", "HIGH", 0.9, "m", "a.py", 4)
        out = dedupe([a, b, c])
        self.assertEqual([(f.line, f.confidence) for f in out], [(3, 0.9), (4, 0.9)])
        self.assertEqual(make_finding_id("R", "f", 1), make_finding_id("R", "f", 1))


class RuleTests(unittest.TestCase):
    def test_python_taint_rules(self):
        rules = {f.rule_id: f for f in scan_text("v.py", VULN)}
        self.assertEqual({"GGS002", "GGS003", "GGS004", "GGS005"}, set(rules))
        self.assertEqual(rules["GGS002"].severity, "CRITICAL")
        self.assertEqual(rules["GGS002"].line, 4)
        self.assertEqual([s["line"] for s in rules["GGS002"].attack_path], [3, 4])
        self.assertIn("os.system", rules["GGS002"].evidence_payload)

    def test_constants_and_safe_forms_are_clean(self):
        safe = "import os, subprocess, yaml\nos.system('ls')\nsubprocess.run(['ls'], shell=False)\nyaml.load(x, Loader=yaml.SafeLoader)\neval('1')\n"
        self.assertEqual(scan_text("s.py", safe), [])

    def test_shell_true_and_yaml(self):
        text = "import subprocess, yaml\ndef f(cmd):\n    subprocess.run(cmd, shell=True)\n    yaml.load(cmd)\n"
        self.assertEqual({f.rule_id for f in scan_text("a.py", text)}, {"GGS002", "GGS003"})

    def test_hardcoded_secret_redacted_and_placeholder_ignored(self):
        key = "AKIA" + "ABCDEFGHIJKLMNOP"
        found = scan_text("c.py", f'KEY = "{key}"\npassword = "changeme-example"\n')
        self.assertEqual([(f.rule_id, f.line) for f in found], [("GGS001", 1)])
        found = scan_text("c.js", 'const password = "hunter2hunter2";\n')
        self.assertEqual(found[0].rule_id, "GGS001")
        self.assertNotIn("hunter2hunter2", found[0].evidence_payload)

    def test_js_rules(self):
        text = "const cp = require('child_process');\ncp.exec('ls ' + dir);\nconst f = new Function(code);\nfs.readFile(req.query.p, cb);\n"
        self.assertEqual({f.rule_id for f in scan_text("a.js", text)}, {"GGS002", "GGS004", "GGS005"})


class SarifTests(unittest.TestCase):
    def test_sarif_structure_and_dedup(self):
        findings = scan_text("v.py", VULN)
        sarif = to_sarif(findings + findings, {"commit": "c", "tree": "t"})
        self.assertEqual(sarif["version"], "2.1.0")
        self.assertIn("sarif-schema-2.1.0", sarif["$schema"])
        run = sarif["runs"][0]
        self.assertEqual(len(run["results"]), len(findings))
        ids = [r["id"] for r in run["tool"]["driver"]["rules"]]
        self.assertEqual(ids, sorted(set(ids)))
        for res in run["results"]:
            self.assertEqual(run["tool"]["driver"]["rules"][res["ruleIndex"]]["id"], res["ruleId"])
            self.assertIn(res["level"], ("error", "warning", "note"))
            self.assertGreaterEqual(res["locations"][0]["physicalLocation"]["region"]["startLine"], 1)
            self.assertTrue(res["codeFlows"][0]["threadFlows"][0]["locations"])
            self.assertIn("gravityguardFindingId/v1", res["partialFingerprints"])
        self.assertEqual(run["versionControlProvenance"][0]["revisionId"], "c")
        json.dumps(sarif)

    def test_sarif_roundtrips_through_load_report(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "r.sarif"
            findings = scan_text("v.py", VULN)
            path.write_text(json.dumps(to_sarif(findings, {"tree": "t"})), encoding="utf-8")
            loaded = report_findings(load_report(path))
            self.assertEqual({f.finding_id for f in loaded}, {f.finding_id for f in findings})


class ScanCliTests(unittest.TestCase):
    def test_diff_vs_all_and_formats(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            make_repo(root, {"old.py": VULN, "ok.py": "x = 1\n"})
            (root / "ok.py").write_text("import os\ndef f(a):\n    os.system(a)\n", encoding="utf-8")
            self.assertEqual(list_files(root, "diff"), ["ok.py"])
            self.assertEqual(list_files(root, "all"), ["ok.py", "old.py"])

            code, out = run_scan(root, "diff")
            self.assertEqual(code, 1)
            self.assertTrue(out.endswith("security-scan.sarif"))
            sarif = json.loads(Path(out).read_text(encoding="utf-8"))
            self.assertEqual({r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] for r in sarif["runs"][0]["results"]}, {"ok.py"})

            code, out = run_scan(root, "all", "json", "rep/all.json")
            data = json.loads(Path(out).read_text(encoding="utf-8"))
            self.assertEqual({f["file"] for f in data["findings"]}, {"ok.py", "old.py"})
            self.assertEqual(data["binding"]["tree"], git_binding(root)["tree"])
            self.assertIn("ok.py", data["binding"]["file_hashes"])

            code, out = run_scan(root, "all", "text", "rep/all.txt")
            self.assertIn("GGS002", Path(out).read_text(encoding="utf-8"))

    def test_clean_repo_exits_zero_and_subcommand_entrypoint(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            make_repo(root, {"ok.py": "x = 1\n"})
            proc = subprocess.run([sys.executable, str(ENGINE / "governance_control.py"), "scan", "--all", "--root", str(root)],
                                  cwd=str(ENGINE), capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = root / ".gravityguard" / "reports" / "security-scan.sarif"
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["runs"][0]["results"], [])
            self.assertEqual(list_files(root, "all"), ["ok.py"])  # reports dir is never rescanned


class GitBindingTests(unittest.TestCase):
    def test_tree_hash_and_file_change_invalidate_findings(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            make_repo(root, {"a.py": "import os\ndef f(a):\n    os.system(a)\n"})
            _, out = run_scan(root, "all", "json", "r.json")
            report = load_report(Path(out))
            self.assertFalse(binding_is_stale(report["binding"], root))
            self.assertFalse(invalidate_stale_report(report, root)["findings"][0]["stale"])

            # uncommitted edit: HEAD tree unchanged, file hash changed
            (root / "a.py").write_text("import os\ndef f(a):\n    os.system('ls')\n", encoding="utf-8")
            self.assertTrue(binding_is_stale(report["binding"], root))

            # restore file content, then move the tree with a new commit
            (root / "a.py").write_text("import os\ndef f(a):\n    os.system(a)\n", encoding="utf-8")
            self.assertFalse(binding_is_stale(report["binding"], root))
            (root / "b.txt").write_text("x", encoding="utf-8")
            git(root, "add", "-A")
            git(root, "commit", "-q", "-m", "second")
            self.assertTrue(binding_is_stale(report["binding"], root))

            f = report["findings"][0]
            f["verification_status"] = "CONFIRMED_EXPLOITABLE"
            stale = invalidate_stale_report(report, root)["findings"][0]
            self.assertTrue(stale["stale"])
            self.assertEqual(stale["verification_status"], "UNVERIFIED")

class FixVerificationTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        make_repo(self.root, {
            "app.py": "def safe(x):\n    return x\n",
            "tests/test_repro.py": "import unittest\nfrom app import safe\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertEqual(safe('a'), 'A')\n",
        })
        self.finding = Finding("GG-1", "GGS004", "HIGH", 0.8, "m", "app.py", 1, reproduction_test="tests/test_repro.py")

    def tearDown(self):
        self._dir.cleanup()

    def runner(self, root, test):
        proc = subprocess.run([sys.executable, "-m", "unittest", "-q", "tests.test_repro"], cwd=str(root), capture_output=True)
        return proc.returncode

    def test_fail_before_pass_after(self):
        record_baseline(self.finding, self.root, self.runner)
        self.assertEqual(self.finding.verification_status, "CONFIRMED_EXPLOITABLE")
        with self.assertRaisesRegex(ValueError, "unchanged"):
            verify_patched(self.finding, self.root, self.runner)
        (self.root / "app.py").write_text("def safe(x):\n    return x.upper()\n", encoding="utf-8")
        verify_patched(self.finding, self.root, self.runner)
        self.assertEqual(self.finding.verification_status, "PATCHED_VERIFIED")

    def test_rejections(self):
        with self.assertRaisesRegex(ValueError, "baseline"):
            verify_patched(self.finding, self.root, self.runner)
        # patched claim with a patch that does not fix the test
        record_baseline(self.finding, self.root, self.runner)
        (self.root / "app.py").write_text("def safe(x):\n    return x + ''\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "still fails"):
            verify_patched(self.finding, self.root, self.runner)
        self.assertEqual(self.finding.verification_status, "CONFIRMED_EXPLOITABLE")

    def test_baseline_rejects_passing_test_and_bad_paths(self):
        (self.root / "app.py").write_text("def safe(x):\n    return x.upper()\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "does not reproduce"):
            record_baseline(self.finding, self.root, self.runner)
        for bad in (None, "../outside.py", "missing.py"):
            f = Finding("GG-2", "R", "LOW", 0.5, "m", "app.py", 1, reproduction_test=bad)
            with self.assertRaises(ValueError):
                record_baseline(f, self.root, self.runner)

    def test_default_runner_runs_real_test(self):
        record_baseline(self.finding, self.root)
        (self.root / "app.py").write_text("def safe(x):\n    return x.upper()\n", encoding="utf-8")
        verify_patched(self.finding, self.root)
        self.assertEqual(self.finding.verification_status, "PATCHED_VERIFIED")


if __name__ == "__main__":
    unittest.main()
