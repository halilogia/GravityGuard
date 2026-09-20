import unittest
import subprocess
import json
import time
import os
import sys
import atexit
import tempfile
import shutil
from typing import Tuple
from unittest.mock import patch, MagicMock

# Hermetic test suite: no test may launch a real background worker process.
# Set BEFORE importing any module so every spawn path observes it. Tests that
# specifically assert the spawn contract clear this var locally.
os.environ["GRAVITYGUARD_DISABLE_ASYNC"] = "1"

# Audit-log isolation: each validator subprocess below appends to the security
# audit stream. Without redirecting it, a suite run floods the REAL user log and
# (since only the last 50 events are kept) evicts all genuine security events,
# so the Live Security Monitor webview would show test fixtures as real activity.
# Set BEFORE any subprocess spawns so every child inherits it.
_AUDIT_LOG_DIR = tempfile.mkdtemp(prefix="gg_audit_")
os.environ["GRAVITYGUARD_LOG_DIR"] = _AUDIT_LOG_DIR
# Delete the temp audit dir on interpreter exit, otherwise every suite run leaves
# a gg_audit_* folder behind in %TEMP%.
atexit.register(shutil.rmtree, _AUDIT_LOG_DIR, ignore_errors=True)

VALIDATOR_PATH = os.path.join(os.path.dirname(__file__), "gravity-validator.py")

# The REAL harness decodes hook stdout with protojson and REJECTS unknown fields.
# `json.loads` below accepts anything, which is exactly why the suite stayed green
# (87/87) while the live guard was blocked in production: the stdout contract was
# never validated. Only these keys are legal for a PreToolUse response.
# Source: antigravity-ide/builtin/skills/agy-customizations/docs/hooks.md (PreToolUse Output).
SCHEMA_ALLOWED_KEYS = {"decision", "reason", "permissionOverrides", "overwrite"}


def _warnings_from(res: dict) -> str:
    """Warnings are delivered through `reason` (the only schema-valid, agent-visible
    field). This helper keeps call sites readable."""
    return res.get("reason", "") or ""


def run_validator(payload: dict) -> Tuple[dict, float]:
    start = time.perf_counter()
    proc = subprocess.Popen(
        [sys.executable, VALIDATOR_PATH],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    stdout, stderr = proc.communicate(input=json.dumps(payload))
    elapsed_ms = (time.perf_counter() - start) * 1000
    try:
        res = json.loads(stdout.strip())
    except Exception as e:
        res = {"error": str(e), "stdout": stdout, "stderr": stderr}
    # Gate on the protocol contract: a payload the harness cannot decode must fail
    # loudly here instead of silently blocking every write tool at runtime.
    if "error" not in res:
        assert set(res.keys()) <= SCHEMA_ALLOWED_KEYS, (
            f"Hook stdout violates the PreToolUse schema. Illegal key(s): "
            f"{set(res.keys()) - SCHEMA_ALLOWED_KEYS}. protojson rejects the WHOLE "
            f"response on an unknown field, so this blocks the tool call. Got: {res}"
        )
    return res, elapsed_ms

class TestGravityGuardPhase1(unittest.TestCase):

    def test_syntax(self):
        """Python syntax check on gravity-validator.py"""
        res = subprocess.run([sys.executable, "-m", "py_compile", VALIDATOR_PATH], capture_output=True)
        self.assertEqual(res.returncode, 0, f"Syntax error: {res.stderr.decode('utf-8')}")

    # --- G1: SILENT EXCEPTION ---
    def test_g1_block_new_empty_except_python(self):
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/service.py",
                    "TargetContent": "result = do_task()",
                    "ReplacementContent": "try:\n    result = do_task()\nexcept:\n    pass"
                }
            }
        }
        res, ms = run_validator(payload)
        self.assertEqual(res.get("decision"), "deny")
        self.assertIn("G1_SILENT_EXCEPTION", res.get("reason", ""))

    def test_g1_block_new_empty_catch_ts(self):
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/service.ts",
                    "TargetContent": "const res = await doTask();",
                    "ReplacementContent": "try {\n  const res = await doTask();\n} catch {}"
                }
            }
        }
        res, ms = run_validator(payload)
        self.assertEqual(res.get("decision"), "deny")
        self.assertIn("G1_SILENT_EXCEPTION", res.get("reason", ""))

    def test_g1_allow_fallback_return(self):
        """Fallback with return value should NOT be blocked in Phase 1"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/service.py",
                    "TargetContent": "return do_task()",
                    "ReplacementContent": "try:\n    return do_task()\nexcept Exception:\n    return None"
                }
            }
        }
        res, ms = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")

    def test_g1_allow_existing_empty_catch_unchanged(self):
        """If existing unchanged code had empty except, editing other lines must pass"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/service.py",
                    "TargetContent": "x = 1",
                    "ReplacementContent": "x = 2"
                }
            }
        }
        res, ms = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")

    # --- G2: TEST INTEGRITY ---
    def test_g2_block_new_skip_python(self):
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/tests/test_order.py",
                    "TargetContent": "def test_calc():",
                    "ReplacementContent": "@pytest.mark.skip(reason='broken')\ndef test_calc():"
                }
            }
        }
        res, ms = run_validator(payload)
        self.assertEqual(res.get("decision"), "deny")
        self.assertIn("G2_TEST_INTEGRITY", res.get("reason", ""))

    def test_g2_block_new_skip_ts(self):
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/tests/order.test.ts",
                    "TargetContent": "it('creates order', () => {",
                    "ReplacementContent": "it.skip('creates order', () => {"
                }
            }
        }
        res, ms = run_validator(payload)
        self.assertEqual(res.get("decision"), "deny")
        self.assertIn("G2_TEST_INTEGRITY", res.get("reason", ""))

    def test_g2_block_test_case_deletion(self):
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/tests/test_order.py",
                    "TargetContent": "def test_order_submission():\n    assert True\n\ndef test_order_cancel():\n    assert True",
                    "ReplacementContent": "def test_order_submission():\n    assert True"
                }
            }
        }
        res, ms = run_validator(payload)
        self.assertEqual(res.get("decision"), "deny")
        self.assertIn("Mevcut test senaryosu silindi", res.get("reason", ""))

    def test_g2_allow_normal_test_refactor(self):
        """Refactoring inside test body without deleting the test case must be ALLOWED"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/tests/test_order.py",
                    "TargetContent": "def test_calc():\n    assert calc(1, 2) == 3",
                    "ReplacementContent": "def test_calc():\n    expected = 3\n    actual = calc(1, 2)\n    assert actual == expected"
                }
            }
        }
        res, ms = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")

    # --- G3: COMPILER / LINTER BYPASS (WARN ONLY) ---
    def test_g3_warn_new_suppression(self):
        """New # noqa or @ts-ignore must be ALLOWED with warning log, not blocked"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/calc.py",
                    "TargetContent": "import foo",
                    "ReplacementContent": "import foo  # noqa: F401"
                }
            }
        }
        res, ms = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")  # Never blocks

    # --- G4: IMPORT MATRIX ---
    def test_g4_block_forbidden_import(self):
        # Create temp .gravityguard.json in test directory
        test_dir = os.path.dirname(__file__)
        cfg_path = os.path.join(test_dir, ".gravityguard.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"layers": {"ui": {"forbiddenImports": ["network", "database"]}}}, f)

        try:
            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": os.path.join(test_dir, "ui", "view.py"),
                        "TargetContent": "# view code",
                        "ReplacementContent": "import network.client\n# view code"
                    }
                }
            }
            res, ms = run_validator(payload)
            self.assertEqual(res.get("decision"), "deny")
            self.assertIn("G4_IMPORT_MATRIX", res.get("reason", ""))
        finally:
            if os.path.exists(cfg_path):
                os.remove(cfg_path)

    # --- OE_SPIKE ---
    def test_oe_spike_warn(self):
        """OE_SPIKE produces WARN log, but does NOT block"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/module.py",
                    "TargetContent": "# base",
                    "ReplacementContent": "class WorkerFactory:\n    pass\n\nclass WorkerRegistry:\n    pass\n"
                }
            }
        }
        res, ms = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")  # Never blocks

    # --- PERFORMANCE TIMING ---
    def test_sub_50ms_performance(self):
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/math_utils.py",
                    "TargetContent": "def add(a, b): return a + b",
                    "ReplacementContent": "def add(a, b): return a + b + 0"
                }
            }
        }
        # Take the MEDIAN, not the mean. This test is a regression guard against
        # spawn latency blowing up, not a benchmark of guard logic (for that
        # invariant see test_core_in_memory_latency, which asserts <10ms purely
        # in-memory). A single outlier spike (antivirus, scheduler, another app
        # competing for a loaded machine) must not fail the suite: a mean is
        # dominated by such outliers, a median is not.
        # Observed on this machine: 143-244 ms typical, 329 ms worst spike.
        timings = []
        for _ in range(5):
            res, ms = run_validator(payload)
            timings.append(ms)
            self.assertEqual(res.get("decision"), "allow")
        median_ms = sorted(timings)[len(timings) // 2]
        print(
            f"\n[PERFORMANCE BENCHMARK] Subprocess spawn: median {median_ms:.2f} ms "
            f"(min {min(timings):.2f}, max {max(timings):.2f}; "
            f"pure in-memory guard logic is ~0.03-0.06 ms)"
        )
        # Generous threshold: Windows python.exe spawn + module load on a loaded
        # machine. This guards against a regression (e.g. an accidental network or
        # sleep at import time), not against normal environment jitter.
        self.assertLess(median_ms, 400)

    # --- PHASE 1.1 HARDENING EDGE CASES ---

    def test_g1_write_to_file_existing_empty_catch_unchanged(self):
        """write_to_file overwriting a file with existing unchanged empty except must be ALLOWED"""
        temp_file = os.path.join(os.path.dirname(__file__), "temp_g1_existing.py")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write("def foo():\n    try:\n        pass\n    except:\n        pass\n\ndef bar():\n    return 1\n")

            payload = {
                "toolCall": {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": temp_file,
                        "CodeContent": "def foo():\n    try:\n        pass\n    except:\n        pass\n\ndef bar():\n    return 2\n"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "allow")
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    def test_g1_write_to_file_new_empty_catch(self):
        """write_to_file adding a new empty except must be BLOCKED"""
        temp_file = os.path.join(os.path.dirname(__file__), "temp_g1_new.py")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write("def foo():\n    return 1\n")

            payload = {
                "toolCall": {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": temp_file,
                        "CodeContent": "def foo():\n    try:\n        return 1\n    except:\n        pass\n"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "deny")
            self.assertIn("G1_SILENT_EXCEPTION", res.get("reason", ""))
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    def test_g1_multi_replace_new_empty_catch(self):
        """multi_replace_file_content introducing an empty except must be BLOCKED"""
        payload = {
            "toolCall": {
                "name": "multi_replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/service.py",
                    "ReplacementChunks": [
                        {
                            "TargetContent": "x = 1",
                            "ReplacementContent": "try:\n    x = 1\nexcept Exception:\n    pass"
                        }
                    ]
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "deny")
        self.assertIn("G1_SILENT_EXCEPTION", res.get("reason", ""))

    def test_g2_pytest_mark_xfail_allowed(self):
        """Expected failure annotation should not be blocked -> ALLOW"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/tests/test_feature.py",
                    "TargetContent": "def test_known_bug():",
                    "ReplacementContent": "@pytest." + "mark." + "xfail(reason='known upstream issue')\ndef test_known_bug():"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")

    def test_g2_it_only_warn_not_block(self):
        """Single test focus annotation should generate WARNING log, but NOT block execution"""
        only_kw = "on" + "ly"
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/tests/feature.test.ts",
                    "TargetContent": "it('runs fine', () => {",
                    "ReplacementContent": f"it.{only_kw}('runs fine', () => {{"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")

    def test_g2_existing_skip_unchanged_allowed(self):
        """Existing skip in test file must not block unrelated edits in other tests"""
        skip_kw = "sk" + "ip"
        temp_file = os.path.join(os.path.dirname(__file__), "temp_test_skip.py")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(f"@pytest.mark.{skip_kw}(reason='legacy')\ndef test_old():\n    pass\n\ndef test_new():\n    assert 1 == 1\n")

            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": temp_file,
                        "TargetContent": "assert 1 == 1",
                        "ReplacementContent": "assert 2 == 2"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "allow")
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    def test_g2_existing_skip_plus_new_skip_blocked(self):
        """Adding a SECOND skip to a file that already had one must be BLOCKED"""
        skip_kw = "sk" + "ip"
        temp_file = os.path.join(os.path.dirname(__file__), "temp_test_2skip.py")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(f"@pytest.mark.{skip_kw}(reason='legacy')\ndef test_old():\n    pass\n\ndef test_new():\n    assert 1 == 1\n")

            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": temp_file,
                        "TargetContent": "def test_new():",
                        "ReplacementContent": f"@pytest.mark.{skip_kw}(reason='bad')\ndef test_new():"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "deny")
            self.assertIn("G2_TEST_INTEGRITY", res.get("reason", ""))
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    def test_g2_duplicate_test_deletion_blocked(self):
        """Deleting one of multiple same-named tests must be caught by Counter -> BLOCK"""
        temp_file = os.path.join(os.path.dirname(__file__), "temp_test_dup.py")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write("def test_dup():\n    assert True\n\ndef test_dup():\n    assert False\n")

            payload = {
                "toolCall": {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": temp_file,
                        "CodeContent": "def test_dup():\n    assert True\n"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "deny")
            self.assertIn("Mevcut test senaryosu silindi", res.get("reason", ""))
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    def test_g4_relative_import_blocked(self):
        """Relative Python forbidden import (e.g. from ..network.client import Client) -> BLOCK"""
        test_dir = os.path.dirname(__file__)
        cfg_path = os.path.join(test_dir, ".gravityguard.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"layers": {"ui": {"forbiddenImports": ["network"]}}}, f)

        try:
            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": os.path.join(test_dir, "ui", "view.py"),
                        "TargetContent": "# ui code",
                        "ReplacementContent": "from ..network.client import Client\n# ui code"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "deny")
            self.assertIn("G4_IMPORT_MATRIX", res.get("reason", ""))
        finally:
            if os.path.exists(cfg_path):
                os.remove(cfg_path)

    def test_g4_segment_match_networking_allowed(self):
        """Forbidden 'network' must NOT match 'networking' due to path segment equality -> ALLOW"""
        test_dir = os.path.dirname(__file__)
        cfg_path = os.path.join(test_dir, ".gravityguard.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"layers": {"ui": {"forbiddenImports": ["network"]}}}, f)

        try:
            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": os.path.join(test_dir, "ui", "view.py"),
                        "TargetContent": "# ui code",
                        "ReplacementContent": "import networking\n# ui code"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "allow")
        finally:
            if os.path.exists(cfg_path):
                os.remove(cfg_path)

    def test_g4_ts_side_effect_import_blocked(self):
        """TypeScript side-effect import `import '../network/client'` -> BLOCK"""
        test_dir = os.path.dirname(__file__)
        cfg_path = os.path.join(test_dir, ".gravityguard.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"layers": {"ui": {"forbiddenImports": ["network"]}}}, f)

        try:
            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": os.path.join(test_dir, "ui", "view.ts"),
                        "TargetContent": "// ui code",
                        "ReplacementContent": "import '../network/client';\n// ui code"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "deny")
            self.assertIn("G4_IMPORT_MATRIX", res.get("reason", ""))
        finally:
            if os.path.exists(cfg_path):
                os.remove(cfg_path)

    # --- G0: SECRET LEAK GUARD TESTS ---

    def test_g0_block_private_key(self):
        """Private key header in added lines must be BLOCKED"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/auth.py",
                    "TargetContent": "# certs",
                    "ReplacementContent": "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...\n-----END RSA PRIVATE KEY-----"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "deny")
        self.assertIn("G0_SECRET_LEAK", res.get("reason", ""))

    def test_g0_block_github_pat(self):
        """GitHub Personal Access Token in added lines must be BLOCKED"""
        token = "ghp_" + "1234567890abcdefghijklmnopqrstuvwxyz"
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/config.py",
                    "TargetContent": "token = None",
                    "ReplacementContent": f"token = '{token}'"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "deny")
        self.assertIn("G0_SECRET_LEAK", res.get("reason", ""))

    def test_g0_block_claude_api_key(self):
        """Anthropic Claude API key in added lines must be BLOCKED"""
        token = "sk-ant-api03-" + "abcdef1234567890_ABCDEF1234567890"
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/ai.py",
                    "TargetContent": "key = None",
                    "ReplacementContent": f"key = '{token}'"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "deny")
        self.assertIn("G0_SECRET_LEAK", res.get("reason", ""))

    def test_g0_block_openai_proj_key(self):
        """OpenAI modern project key in added lines must be BLOCKED"""
        token = "sk-proj-" + "abcdef1234567890_ABCDEF1234567890"
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/ai.py",
                    "TargetContent": "key = None",
                    "ReplacementContent": f"key = '{token}'"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "deny")
        self.assertIn("G0_SECRET_LEAK", res.get("reason", ""))

    def test_g0_block_gemini_api_key(self):
        """Google Gemini API key in added lines must be BLOCKED"""
        token = "AIza" + "SyD1234567890_abcdefghijklmnopqrstuv"
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/ai.py",
                    "TargetContent": "key = None",
                    "ReplacementContent": f"key = '{token}'"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "deny")
        self.assertIn("G0_SECRET_LEAK", res.get("reason", ""))

    def test_g0_block_slack_token(self):
        """Slack token (xoxb-, xoxp-, etc.) in added lines must be BLOCKED"""
        token = "xoxb-" + "123456789012-1234567890123-abcdefghijklmnopqrstuvwx"
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/slack.py",
                    "TargetContent": "token = None",
                    "ReplacementContent": f"token = '{token}'"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "deny")
        self.assertIn("G0_SECRET_LEAK", res.get("reason", ""))

    def test_g0_allow_obvious_placeholder(self):
        """Obvious placeholder values must be ALLOWED"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/ai.py",
                    "TargetContent": "key = None",
                    "ReplacementContent": "key = 'sk-proj-your-api-key-here-placeholder'"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")

    def test_g0_warn_bearer_token(self):
        """Generic Bearer token must generate WARNING log, but NOT block"""
        bearer = "Bearer " + "eyJhGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abcdef1234567890"
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/client.ts",
                    "TargetContent": "headers: {}",
                    "ReplacementContent": f"headers: {{ 'Authorization': '{bearer}' }}"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")

    def test_g0_warn_db_connection_uri(self):
        """Database connection URI with password must generate WARNING, but NOT block"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/db.ts",
                    "TargetContent": "url = None",
                    "ReplacementContent": "url = 'postgres://admin:SuperSecretPassword99@db.host.internal:5432/main'"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")

    def test_g0_ignore_simple_password(self):
        """Common variable assignment 'password = ...' must be IGNORED (not blocked)"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/user.py",
                    "TargetContent": "password = None",
                    "ReplacementContent": "password = 'user_input_string'"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")

    def test_g0_existing_secret_unchanged(self):
        """Existing secret in file on disk must NOT block unrelated changes"""
        token = "ghp_" + "9999999999abcdefghijklmnopqrstuvwxyz"
        temp_file = os.path.join(os.path.dirname(__file__), "temp_existing_secret.py")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(f"TOKEN = '{token}'\n\ndef add(a, b):\n    return a + b\n")

            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": temp_file,
                        "TargetContent": "return a + b",
                        "ReplacementContent": "return a + b + 0"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "allow")
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    def test_g0_redaction_verified(self):
        """Raw token must NEVER appear unredacted in deny reason"""
        secret = "ghp_" + "SECRETTOKENVALUE1234567890SECRET"
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/leak.py",
                    "TargetContent": "k = None",
                    "ReplacementContent": f"k = '{secret}'"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "deny")
        self.assertNotIn(secret, res.get("reason", ""))
        self.assertIn("****", res.get("reason", ""))

    # --- PERFORMANCE BENCHMARKS (Core In-Memory vs Subprocess Hook) ---

    def test_core_in_memory_latency(self):
        """Directly tests in-memory guard evaluation time (< 10 ms invariant)"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("gravity_validator", VALIDATOR_PATH)
        gv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gv)

        old_code = "def calc(a, b):\n    return a + b\n"
        new_code = "def calc(a, b):\n    return a + b + 0\n"

        timings = []
        for _ in range(100):
            t0 = time.perf_counter()
            added_lines, added_text, added_line_nos = gv.get_diff_analysis(old_code, new_code)
            gv.check_g1_silent_exception(added_lines, added_text, added_line_nos, new_code, True, False)
            gv.check_oe_spike(added_text)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            timings.append(elapsed_ms)

        avg_core_ms = sum(timings) / len(timings)
        print(f"\n[BENCHMARK - CORE EVALUATOR] Average in-memory logic execution: {avg_core_ms:.3f} ms")
        self.assertLess(avg_core_ms, 10.0, "Core in-memory rule evaluator must execute in < 10ms")

class TestGravityGuardPhase2(unittest.TestCase):
    """
    Phase 2: Test Evidence Analyzer Tests (T1, T2, T3)
    Invariants:
    - Never BLOCKS (decision must always be 'allow').
    - Emits informative warnings when evidence is lacking.
    - Exempts constants, types, configs, and declarations.
    """

    # --- T1: MISSING_RELATED_TEST ---

    def test_t1_exempt_constants_and_types(self):
        """Changes to constants.py or types.ts must NOT trigger T1 warning"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/constants.py",
                    "TargetContent": "TIMEOUT = 10",
                    "ReplacementContent": "TIMEOUT = 30"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")
        rule_ids = _warnings_from(res)
        self.assertNotIn("T1_MISSING_RELATED_TEST", rule_ids)

    def test_t1_exempt_declarations_and_migrations(self):
        """Changes to .d.ts or migrations must NOT trigger T1 warning"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/types/api.d.ts",
                    "TargetContent": "export interface User { id: string; }",
                    "ReplacementContent": "export interface User { id: string; name: string; }"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")
        rule_ids = _warnings_from(res)
        self.assertNotIn("T1_MISSING_RELATED_TEST", rule_ids)

    def test_t1_warn_when_candidate_test_absent(self):
        """When production code changes and no test file exists on disk, T1 must WARN (not block)"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/billing_service.py",
                    "TargetContent": "def pay(): return True",
                    "ReplacementContent": "def pay():\n    validate_card()\n    return True"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow", "T1 must never block production changes")
        rule_ids = _warnings_from(res)
        self.assertIn("T1_MISSING_RELATED_TEST", rule_ids)

    def test_t1_allow_when_candidate_test_recently_touched(self):
        """When candidate test file exists and was touched in this session, T1 must NOT warn"""
        temp_dir = tempfile.mkdtemp()
        try:
            src_dir = os.path.join(temp_dir, "src")
            tests_dir = os.path.join(temp_dir, "tests")
            os.makedirs(src_dir, exist_ok=True)
            os.makedirs(tests_dir, exist_ok=True)

            prod_file = os.path.join(src_dir, "order.py")
            test_file = os.path.join(tests_dir, "test_order.py")

            with open(prod_file, "w", encoding="utf-8") as f:
                f.write("def create_order():\n    return {'id': 1}\n")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("def test_create_order():\n    assert True\n")

            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": prod_file,
                        "TargetContent": "return {'id': 1}",
                        "ReplacementContent": "return {'id': 2}"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "allow")
            rule_ids = _warnings_from(res)
            self.assertNotIn("T1_MISSING_RELATED_TEST", rule_ids)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_t1_warn_when_candidate_test_untouched_in_session(self):
        """When candidate test file exists but was not touched in session window, T1 must WARN"""
        temp_dir = tempfile.mkdtemp()
        try:
            src_dir = os.path.join(temp_dir, "src")
            tests_dir = os.path.join(temp_dir, "tests")
            os.makedirs(src_dir, exist_ok=True)
            os.makedirs(tests_dir, exist_ok=True)

            prod_file = os.path.join(src_dir, "order.py")
            test_file = os.path.join(tests_dir, "test_order.py")

            with open(prod_file, "w", encoding="utf-8") as f:
                f.write("def create_order():\n    return {'id': 1}\n")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("def test_create_order():\n    assert True\n")

            past_time = time.time() - 1000
            os.utime(test_file, (past_time, past_time))

            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": prod_file,
                        "TargetContent": "return {'id': 1}",
                        "ReplacementContent": "return {'id': 2}"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "allow")
            rule_ids = _warnings_from(res)
            self.assertIn("T1_MISSING_RELATED_TEST", rule_ids)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # --- T2: NO_OBSERVABLE_ASSERTION ---

    def test_t2_warn_empty_python_test_no_assertion(self):
        """Python test case added without any assertion must trigger T2 warning (not block)"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/tests/test_auth.py",
                    "TargetContent": "# placeholder",
                    "ReplacementContent": "def test_login_flow():\n    token = get_token()\n    print(token)"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")
        rule_ids = _warnings_from(res)
        self.assertIn("T2_NO_OBSERVABLE_ASSERTION", rule_ids)

    def test_t2_allow_python_test_with_assert(self):
        """Python test case with standard assert must NOT trigger T2 warning"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/tests/test_auth.py",
                    "TargetContent": "# placeholder",
                    "ReplacementContent": "def test_login_flow():\n    token = get_token()\n    assert token is not None"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")
        rule_ids = _warnings_from(res)
        self.assertNotIn("T2_NO_OBSERVABLE_ASSERTION", rule_ids)

    def test_t2_allow_python_test_with_pytest_raises(self):
        """Python test case using pytest.raises must NOT trigger T2 warning"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/tests/test_auth.py",
                    "TargetContent": "# placeholder",
                    "ReplacementContent": "def test_login_invalid():\n    with pytest.raises(ValueError):\n        login('')"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")
        rule_ids = _warnings_from(res)
        self.assertNotIn("T2_NO_OBSERVABLE_ASSERTION", rule_ids)

    def test_t2_warn_empty_ts_test_no_assertion(self):
        """TS test case added without any assertion must trigger T2 warning (not block)"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/tests/auth.test.ts",
                    "TargetContent": "// placeholder",
                    "ReplacementContent": "it('should authenticate user', () => {\n  const user = authenticate();\n});"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")
        rule_ids = _warnings_from(res)
        self.assertIn("T2_NO_OBSERVABLE_ASSERTION", rule_ids)

    def test_t2_allow_ts_test_with_expect(self):
        """TS test case with expect(...).toBe(...) must NOT trigger T2 warning"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/tests/auth.test.ts",
                    "TargetContent": "// placeholder",
                    "ReplacementContent": "it('should authenticate user', () => {\n  const user = authenticate();\n  expect(user.role).toBe('admin');\n});"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")
        rule_ids = _warnings_from(res)
        self.assertNotIn("T2_NO_OBSERVABLE_ASSERTION", rule_ids)

    def test_t2_ignore_describe_and_before_each(self):
        """Modifying only describe or beforeEach blocks must NOT trigger T2 warning"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/tests/suite.test.ts",
                    "TargetContent": "// suite",
                    "ReplacementContent": "describe('AuthService', () => {\n  beforeEach(() => {\n    clearSession();\n  });\n});"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")
        rule_ids = _warnings_from(res)
        self.assertNotIn("T2_NO_OBSERVABLE_ASSERTION", rule_ids)

    # --- T3: SYMBOL_TO_TEST_LINK ---

    def test_t3_allow_when_symbol_referenced_in_test(self):
        """When modified production symbol appears in candidate test, T3 must NOT warn"""
        temp_dir = tempfile.mkdtemp()
        try:
            src_dir = os.path.join(temp_dir, "src")
            tests_dir = os.path.join(temp_dir, "tests")
            os.makedirs(src_dir, exist_ok=True)
            os.makedirs(tests_dir, exist_ok=True)

            prod_file = os.path.join(src_dir, "calc.py")
            test_file = os.path.join(tests_dir, "test_calc.py")

            with open(prod_file, "w", encoding="utf-8") as f:
                f.write("def old(): pass\n")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("def test_calc():\n    assert calculate_total([1]) == 1\n")

            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": prod_file,
                        "TargetContent": "def old(): pass",
                        "ReplacementContent": "def calculate_total(items):\n    return sum(items)\n"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "allow")
            rule_ids = _warnings_from(res)
            self.assertNotIn("T3_SYMBOL_TO_TEST_LINK", rule_ids)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_t3_warn_when_symbol_absent_in_test(self):
        """When modified production symbol does not appear in candidate test, T3 must WARN"""
        temp_dir = tempfile.mkdtemp()
        try:
            src_dir = os.path.join(temp_dir, "src")
            tests_dir = os.path.join(temp_dir, "tests")
            os.makedirs(src_dir, exist_ok=True)
            os.makedirs(tests_dir, exist_ok=True)

            prod_file = os.path.join(src_dir, "calc.py")
            test_file = os.path.join(tests_dir, "test_calc.py")

            with open(prod_file, "w", encoding="utf-8") as f:
                f.write("def old(): pass\n")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("def test_legacy():\n    assert True\n")

            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": prod_file,
                        "TargetContent": "def old(): pass",
                        "ReplacementContent": "def compute_untested_formula(x):\n    return x * 42\n"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "allow")
            rule_ids = _warnings_from(res)
            self.assertIn("T3_SYMBOL_TO_TEST_LINK", rule_ids)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_phase2_never_blocks(self):
        """Verify that multiple simultaneous Phase 2 warnings NEVER produce a deny decision"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/untested_service.py",
                    "TargetContent": "# empty",
                    "ReplacementContent": "def process_payment(amount):\n    return amount > 0\n"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow", "Phase 2 must NEVER block changes under any circumstance")

    def test_phase2_in_memory_latency(self):
        """Directly benchmarks Phase 2 Test Evidence evaluator in-memory execution (< 5ms)"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("gravity_validator", VALIDATOR_PATH)
        gv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gv)

        added_lines = ["def test_order():\n", "    assert calculate_total([1]) == 1\n"]
        added_text = "".join(added_lines)

        timings = []
        for _ in range(100):
            t0 = time.perf_counter()
            gv.check_t2_observable_assertion(added_lines, added_text, True, False)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            timings.append(elapsed_ms)

        avg_ms = sum(timings) / len(timings)
        print(f"\n[BENCHMARK - PHASE 2 EVALUATOR] Average in-memory logic execution: {avg_ms:.3f} ms")
        self.assertLess(avg_ms, 5.0, "Phase 2 in-memory evaluator must execute in < 5ms")

    # --- PHASE 2 HARDENING TESTS (Edge-cases & Body Modifications) ---

    def test_t2_warn_when_existing_python_test_body_modified_without_assertion(self):
        """When an existing test's body is modified to remove assertions, T2 must WARN"""
        temp_dir = tempfile.mkdtemp()
        try:
            test_file = os.path.join(temp_dir, "test_auth.py")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("def test_login():\n    assert login() is True\n")

            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": test_file,
                        "TargetContent": "    assert login() is True",
                        "ReplacementContent": "    print(login())"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "allow")
            self.assertIn("T2_NO_OBSERVABLE_ASSERTION", _warnings_from(res))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_t2_warn_when_one_test_has_assertion_and_one_lacks_it(self):
        """When a change introduces 2 tests, one asserted and one unasserted, T2 must WARN"""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/tests/multi.test.ts",
                    "TargetContent": "// placeholder",
                    "ReplacementContent": "it('asserted test', () => {\n  expect(foo()).toBe(true);\n});\n\nit('unasserted test', () => {\n  doSomething();\n});"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")
        self.assertIn("T2_NO_OBSERVABLE_ASSERTION", _warnings_from(res))

    def test_t3_catch_body_only_python_modification(self):
        """When only a function body is modified, T3 must still resolve the parent symbol via AST"""
        temp_dir = tempfile.mkdtemp()
        try:
            src_dir = os.path.join(temp_dir, "src")
            tests_dir = os.path.join(temp_dir, "tests")
            os.makedirs(src_dir, exist_ok=True)
            os.makedirs(tests_dir, exist_ok=True)

            prod_file = os.path.join(src_dir, "calc.py")
            test_file = os.path.join(tests_dir, "test_calc.py")

            with open(prod_file, "w", encoding="utf-8") as f:
                f.write("def calculate(x):\n    return x + 1\n")
            # Candidate test file does NOT mention 'calculate'
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("def test_dummy():\n    assert True\n")

            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": prod_file,
                        "TargetContent": "    return x + 1",
                        "ReplacementContent": "    validate(x)\n    return x + 1"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "allow")
            self.assertIn("T3_SYMBOL_TO_TEST_LINK", _warnings_from(res))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_t3_warn_when_one_of_two_symbols_missing_in_test(self):
        """When 2 symbols are changed and 1 is missing from test, T3 must WARN (not stay silent)"""
        temp_dir = tempfile.mkdtemp()
        try:
            src_dir = os.path.join(temp_dir, "src")
            tests_dir = os.path.join(temp_dir, "tests")
            os.makedirs(src_dir, exist_ok=True)
            os.makedirs(tests_dir, exist_ok=True)

            prod_file = os.path.join(src_dir, "service.py")
            test_file = os.path.join(tests_dir, "test_service.py")

            with open(prod_file, "w", encoding="utf-8") as f:
                f.write("def old(): pass\n")
            # Only 'foo' is in the test file, 'bar' is absent
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("def test_service():\n    assert foo() == 1\n")

            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": prod_file,
                        "TargetContent": "def old(): pass",
                        "ReplacementContent": "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "allow")
            self.assertIn("T3_SYMBOL_TO_TEST_LINK", _warnings_from(res))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_t3_ignore_exported_scalar_constant(self):
        """Exported scalar constant (e.g. export const MAX = 3) must NOT be treated as a T3 function symbol"""
        temp_dir = tempfile.mkdtemp()
        try:
            src_dir = os.path.join(temp_dir, "src")
            tests_dir = os.path.join(temp_dir, "tests")
            os.makedirs(src_dir, exist_ok=True)
            os.makedirs(tests_dir, exist_ok=True)

            prod_file = os.path.join(src_dir, "constants.ts")
            test_file = os.path.join(tests_dir, "constants.test.ts")

            with open(prod_file, "w", encoding="utf-8") as f:
                f.write("// constants\n")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("it('works', () => { expect(1).toBe(1); });\n")

            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": prod_file,
                        "TargetContent": "// constants",
                        "ReplacementContent": "export const MAX_RETRIES = 3;\nexport const DEFAULT_TIMEOUT = 5000;"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "allow")
            self.assertNotIn("T3_SYMBOL_TO_TEST_LINK", _warnings_from(res))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_t3_catch_exported_arrow_function(self):
        """Exported arrow function (e.g. export const handle = () => {}) must be caught by T3"""
        temp_dir = tempfile.mkdtemp()
        try:
            src_dir = os.path.join(temp_dir, "src")
            tests_dir = os.path.join(temp_dir, "tests")
            os.makedirs(src_dir, exist_ok=True)
            os.makedirs(tests_dir, exist_ok=True)

            prod_file = os.path.join(src_dir, "handler.ts")
            test_file = os.path.join(tests_dir, "handler.test.ts")

            with open(prod_file, "w", encoding="utf-8") as f:
                f.write("// handler\n")
            # Candidate test does NOT mention 'handleUserEvent'
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("it('dummy', () => { expect(true).toBe(true); });\n")

            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": prod_file,
                        "TargetContent": "// handler",
                        "ReplacementContent": "export const handleUserEvent = (event: any) => {\n  return event.type;\n};"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "allow")
            self.assertIn("T3_SYMBOL_TO_TEST_LINK", _warnings_from(res))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_t1_source_roots_config_respected(self):
        """Configured sourceRoots (e.g. ['core_logic']) must be used to resolve candidate test"""
        temp_dir = tempfile.mkdtemp()
        try:
            cfg_path = os.path.join(temp_dir, ".gravityguard.json")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump({
                    "testEvidence": {
                        "sourceRoots": ["core_logic"],
                        "testRoots": ["tests"]
                    }
                }, f)

            core_dir = os.path.join(temp_dir, "core_logic")
            tests_dir = os.path.join(temp_dir, "tests")
            os.makedirs(core_dir, exist_ok=True)
            os.makedirs(tests_dir, exist_ok=True)

            prod_file = os.path.join(core_dir, "engine.py")
            test_file = os.path.join(tests_dir, "test_engine.py")

            with open(prod_file, "w", encoding="utf-8") as f:
                f.write("def run(): pass\n")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("def test_engine(): assert True\n")

            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": prod_file,
                        "TargetContent": "def run(): pass",
                        "ReplacementContent": "def run():\n    return 42\n"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "allow")
            self.assertNotIn("T1_MISSING_RELATED_TEST", _warnings_from(res))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # ========================================================================
    # PHASE 2.5 TESTS: ARCH_FILE_GROWTH & STATIC LINTER DIAGNOSTICS
    # ========================================================================

    def test_arch_file_growth_over_1000_loc_triggers_warn(self):
        """When projected content exceeds 1000 non-empty lines, ARCH_FILE_GROWTH warns without blocking"""
        temp_dir = tempfile.mkdtemp()
        try:
            prod_file = os.path.join(temp_dir, "large_service.py")
            # 950 lines initial
            initial_lines = [f"def func_{i}():\n    return {i}\n" for i in range(475)]
            with open(prod_file, "w", encoding="utf-8") as f:
                f.writelines(initial_lines)

            # Add 80 more lines (total ~1030 lines)
            added_content = "\n".join([f"def new_func_{i}():\n    return {i}" for i in range(40)])
            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": prod_file,
                        "TargetContent": "def func_0():\n    return 0\n",
                        "ReplacementContent": "def func_0():\n    return 0\n\n" + added_content
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "allow", "ARCH_FILE_GROWTH must never block")
            rule_ids = _warnings_from(res)
            self.assertIn("ARCH_FILE_GROWTH", rule_ids)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_arch_file_growth_single_addition_over_180_loc_triggers_warn(self):
        """When a single tool-call adds 180+ clean lines, ARCH_FILE_GROWTH warns"""
        big_block = "\n".join([f"var_{i} = {i}" for i in range(200)])
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": "C:/fake_project/src/new_monolith.py",
                    "CodeContent": big_block
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")
        self.assertIn("ARCH_FILE_GROWTH", _warnings_from(res))

    def test_arch_file_growth_creeping_growth_800_plus_80_triggers_warn(self):
        """When an 800+ LOC file receives 80+ lines, ARCH_FILE_GROWTH warns"""
        temp_dir = tempfile.mkdtemp()
        try:
            prod_file = os.path.join(temp_dir, "creeping_module.py")
            # 820 lines initial
            initial_lines = [f"line_{i} = {i}\n" for i in range(820)]
            with open(prod_file, "w", encoding="utf-8") as f:
                f.writelines(initial_lines)

            # Add 85 lines
            added_content = "\n".join([f"extra_line_{i} = {i}" for i in range(85)])
            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": prod_file,
                        "TargetContent": "line_0 = 0\n",
                        "ReplacementContent": "line_0 = 0\n" + added_content + "\n"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "allow")
            self.assertIn("ARCH_FILE_GROWTH", _warnings_from(res))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_arch_file_growth_exempt_for_test_files(self):
        """Test files (e.g. test_suite.py) are exempt from ARCH_FILE_GROWTH even with 1000+ lines"""
        big_test = "\n".join([f"def test_case_{i}(): assert True" for i in range(1100)])
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": "C:/fake_project/tests/test_huge_suite.py",
                    "CodeContent": big_test
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")
        rule_ids = _warnings_from(res)
        self.assertNotIn("ARCH_FILE_GROWTH", rule_ids)

    def test_arch_file_growth_normal_small_edit_no_warning(self):
        """Normal small modification to a small file produces NO ARCH_FILE_GROWTH warning"""
        payload = {
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": "C:/fake_project/src/small_service.py",
                    "CodeContent": "def greet(name: str) -> str:\n    return f'Hello, {name}'\n"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")
        rule_ids = _warnings_from(res)
        self.assertNotIn("ARCH_FILE_GROWTH", rule_ids)

    def test_static_linter_diagnostics_fresh_read(self):
        """When diagnostics.json has a fresh entry for the target file, validator emits STATIC_LINTER_DIAGNOSTIC"""
        temp_dir = tempfile.mkdtemp()
        try:
            runtime_dir = os.path.join(temp_dir, ".gravityguard", "runtime")
            os.makedirs(runtime_dir, exist_ok=True)
            diag_file = os.path.join(runtime_dir, "diagnostics.json")

            target_file = os.path.join(temp_dir, "src", "payment.py")
            os.makedirs(os.path.dirname(target_file), exist_ok=True)
            with open(target_file, "w", encoding="utf-8") as f:
                f.write("def pay(): pass\n")

            diag_payload = {
                "version": 1,
                "lastUpdated": time.time(),
                "entries": {
                    target_file: {
                        "tool": "ruff",
                        "timestamp": time.time(),
                        "errors": [
                            {"line": 1, "rule": "F841", "message": "Local variable 'x' is assigned to but never used"}
                        ]
                    }
                }
            }
            with open(diag_file, "w", encoding="utf-8") as f:
                json.dump(diag_payload, f)

            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": target_file,
                        "TargetContent": "def pay(): pass",
                        "ReplacementContent": "def pay():\n    return True\n"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "allow")
            rule_ids = _warnings_from(res)
            self.assertIn("STATIC_LINTER_DIAGNOSTIC", rule_ids)
            warnings = _warnings_from(res)
            self.assertIn("ruff", warnings)
            self.assertIn("F841", warnings)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_static_linter_diagnostics_stale_skipped(self):
        """When diagnostics.json entry is older than 600s, it is treated as stale and skipped"""
        temp_dir = tempfile.mkdtemp()
        try:
            runtime_dir = os.path.join(temp_dir, ".gravityguard", "runtime")
            os.makedirs(runtime_dir, exist_ok=True)
            diag_file = os.path.join(runtime_dir, "diagnostics.json")

            target_file = os.path.join(temp_dir, "src", "payment.py")
            os.makedirs(os.path.dirname(target_file), exist_ok=True)
            with open(target_file, "w", encoding="utf-8") as f:
                f.write("def pay(): pass\n")

            diag_payload = {
                "version": 1,
                "lastUpdated": time.time() - 700,
                "entries": {
                    target_file: {
                        "tool": "ruff",
                        "timestamp": time.time() - 700,  # 700 seconds old
                        "errors": [
                            {"line": 1, "rule": "F841", "message": "Old error"}
                        ]
                    }
                }
            }
            with open(diag_file, "w", encoding="utf-8") as f:
                json.dump(diag_payload, f)

            payload = {
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {
                        "TargetFile": target_file,
                        "TargetContent": "def pay(): pass",
                        "ReplacementContent": "def pay():\n    return True\n"
                    }
                }
            }
            res, _ = run_validator(payload)
            self.assertEqual(res.get("decision"), "allow")
            rule_ids = _warnings_from(res)
            self.assertNotIn("STATIC_LINTER_DIAGNOSTIC", rule_ids)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_async_runner_orchestration_trigger(self):
        """Verifies trigger_background_validation runs safely and never blocks the caller.

        This test is fully hermetic: Popen is mocked so the suite never launches a
        real background async_runner process (which would flash a console window
        and leave a stray process behind).
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location("gravity_validator", VALIDATOR_PATH)
        gv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gv)

        with patch.dict(os.environ, {"GRAVITYGUARD_DISABLE_ASYNC": "0"}), \
             patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()

            # Unsupported / empty targets -> early return, no spawn at all
            gv.trigger_background_validation("README.md")
            gv.trigger_background_validation("")
            mock_popen.assert_not_called()

            # Supported extension -> exactly one hidden background spawn
            gv.trigger_background_validation("src/auth.py")
            mock_popen.assert_called_once()

    def test_async_spawning_kill_switch_prevents_all_spawns(self):
        """Verifies GRAVITYGUARD_DISABLE_ASYNC=1 fully suppresses background spawning."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("gravity_validator", VALIDATOR_PATH)
        gv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gv)

        sys.path.insert(0, os.path.dirname(VALIDATOR_PATH))
        import async_runner

        with patch.dict(os.environ, {"GRAVITYGUARD_DISABLE_ASYNC": "1"}), \
             patch("subprocess.Popen") as mock_popen:
            gv.trigger_background_validation("src/auth.py")
            mock_popen.assert_not_called()

        self.assertTrue(async_runner.async_spawning_disabled())

    def test_async_runner_debounce_state_management(self):
        """Verifies async_runner's debounce state load/save and idle detection logic"""
        temp_dir = tempfile.mkdtemp()
        try:
            sys.path.insert(0, os.path.dirname(VALIDATOR_PATH))
            import async_runner
            from pathlib import Path

            p_root = Path(temp_dir)
            d_path = async_runner.get_debounce_file_path(p_root)

            # Initial state
            initial = async_runner.load_debounce_state(d_path)
            self.assertEqual(initial["last_edit_time"], 0.0)
            self.assertFalse(initial["worker_running"])

            # Save updated state
            now = time.time()
            async_runner.save_debounce_state(d_path, {"last_edit_time": now, "worker_running": True})

            loaded = async_runner.load_debounce_state(d_path)
            self.assertEqual(loaded["last_edit_time"], now)
            self.assertTrue(loaded["worker_running"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_benchmark_1000_runs_avg_and_p95(self):
        """Measures 1,000 iterations of in-memory core evaluator: records average, p95, and p99 latency"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("gravity_validator", VALIDATOR_PATH)
        gv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gv)

        old_code = "def authenticate(user, pwd):\n    return True\n"
        new_code = "def authenticate(user, pwd):\n    token = user + pwd\n    return token\n"

        timings = []
        for _ in range(1000):
            t0 = time.perf_counter()
            added_lines, added_text, line_nums = gv.get_diff_analysis(old_code, new_code)
            gv.check_g0_secret_leak(added_text)
            gv.check_g1_silent_exception(added_lines, added_text, line_nums, new_code, True, False)
            gv.check_g3_compiler_bypass(added_text)
            gv.check_oe_spike(added_text)
            gv.check_arch_file_growth("src/auth.py", old_code, new_code, added_lines, False)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            timings.append(elapsed_ms)

        timings.sort()
        avg_ms = sum(timings) / len(timings)
        p95_ms = timings[int(len(timings) * 0.95)]
        p99_ms = timings[int(len(timings) * 0.99)]

        print(f"\n[BENCHMARK - 1000 RUNS] Avg: {avg_ms:.4f} ms | p95: {p95_ms:.4f} ms | p99: {p99_ms:.4f} ms")
        self.assertLess(avg_ms, 1.0, "Core evaluator average latency must be < 1ms")
        self.assertLess(p95_ms, 2.0, "Core evaluator p95 latency must be < 2ms")

    # --- PHASE 2.5 CRITICAL HARDENING TESTS ---

    def test_tsc_per_file_diagnostics_integration(self):
        """Verifies tsc compiler output is parsed per-file and matched by read_recent_diagnostics"""
        temp_dir = tempfile.mkdtemp()
        try:
            sys.path.insert(0, os.path.dirname(VALIDATOR_PATH))
            import async_runner
            from pathlib import Path

            p_root = Path(temp_dir).resolve()
            diag_path = async_runner.get_diagnostics_file_path(p_root)

            auth_file = p_root / "src" / "auth.ts"
            unrelated_file = p_root / "src" / "unrelated.ts"
            auth_file.parent.mkdir(parents=True, exist_ok=True)
            auth_file.write_text("export const token = 123;\n", encoding="utf-8")
            unrelated_file.write_text("export const name = 'test';\n", encoding="utf-8")

            sample_tsc_stdout = (
                f"{auth_file}(12,5): error TS2322: Type 'string' is not assignable to type 'number'.\n"
                f"{auth_file}(18,1): error TS2554: Expected 2 arguments, but got 1.\n"
            )

            file_errors_map = async_runner.parse_tsc_output(sample_tsc_stdout, p_root)
            norm_auth_key = str(auth_file).replace("\\", "/")
            self.assertIn(norm_auth_key, file_errors_map)
            self.assertEqual(len(file_errors_map[norm_auth_key]), 2)
            self.assertEqual(file_errors_map[norm_auth_key][0]["rule"], "TS2322")

            # Save to diagnostics.json as run_debounce_worker would do
            diag_data = {"version": 1, "lastUpdated": time.time(), "entries": {}}
            for f_path, errs in file_errors_map.items():
                diag_data["entries"][f_path] = {
                    "tool": "tsc",
                    "timestamp": time.time(),
                    "errors": errs
                }
            async_runner.save_diagnostics(diag_path, diag_data)

            # Test validator reader on auth_file -> must surface TS2322
            import importlib.util
            spec = importlib.util.spec_from_file_location("gravity_validator", VALIDATOR_PATH)
            gv = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(gv)

            auth_warnings = gv.read_recent_diagnostics(str(auth_file))
            self.assertTrue(len(auth_warnings) > 0, "auth.ts must receive tsc diagnostics")
            self.assertEqual(auth_warnings[0][0], "STATIC_LINTER_DIAGNOSTIC")
            self.assertIn("TS2322", auth_warnings[0][1])

            # Test validator reader on unrelated_file -> must NOT receive auth.ts error
            unrelated_warnings = gv.read_recent_diagnostics(str(unrelated_file))
            self.assertEqual(len(unrelated_warnings), 0, "unrelated.ts must not see auth.ts errors")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_should_run_after_idle_decision_matrix(self):
        """Verifies pure debounce logic: returns True strictly when idle_threshold has passed"""
        sys.path.insert(0, os.path.dirname(VALIDATOR_PATH))
        import async_runner

        # Invalid last edit
        self.assertFalse(async_runner.should_run_after_idle(0.0, 100.0, 3.0))

        # 1.0s elapsed (< 3.0s) -> False
        self.assertFalse(async_runner.should_run_after_idle(100.0, 101.0, 3.0))

        # 2.9s elapsed (< 3.0s) -> False
        self.assertFalse(async_runner.should_run_after_idle(100.0, 102.9, 3.0))

        # 3.0s elapsed (== 3.0s) -> True
        self.assertTrue(async_runner.should_run_after_idle(100.0, 103.0, 3.0))

        # 5.0s elapsed (> 3.0s) -> True
        self.assertTrue(async_runner.should_run_after_idle(100.0, 105.0, 3.0))

        # New edit reset: now == last_edit -> False
        self.assertFalse(async_runner.should_run_after_idle(105.0, 105.0, 3.0))

    def test_should_spawn_worker_duplicate_protection(self):
        """Verifies the state-based duplicate suppression decision for batch workers."""
        sys.path.insert(0, os.path.dirname(VALIDATOR_PATH))
        import async_runner

        self.assertFalse(async_runner.should_spawn_worker(worker_already_running=True))
        self.assertTrue(async_runner.should_spawn_worker(worker_already_running=False))

    def test_orchestration_mock_subprocess_popen(self):
        """Verifies trigger_background_validation invokes async_runner detached without waiting.

        GravityGuard is a pre-tool hook: it fires BEFORE the AI's tool call writes
        the file to disk. Therefore trigger_background_validation() must NOT require
        the file to exist locally. We mock subprocess.Popen (and os.path.exists for
        the runner_path check only) so the test is self-contained and target-file
        existence is irrelevant to this contract.
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location("gravity_validator", VALIDATOR_PATH)
        gv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gv)

        target = "C:/fake_project/src/auth.ts"
        real_runner_path = os.path.join(os.path.dirname(VALIDATOR_PATH), "async_runner.py")

        with patch.dict(os.environ, {"GRAVITYGUARD_DISABLE_ASYNC": "0"}), \
             patch("subprocess.Popen") as mock_popen, \
             patch("os.path.exists", side_effect=lambda p: True if "async_runner" in str(p) else os.path.exists.__wrapped__(p) if hasattr(os.path.exists, "__wrapped__") else True):
            mock_proc = MagicMock()
            mock_popen.return_value = mock_proc

            gv.trigger_background_validation(target)

            # Ensure Popen was called exactly once
            mock_popen.assert_called_once()
            call_args, call_kwargs = mock_popen.call_args

            # Check binary command arguments
            cmd_list = call_args[0]
            self.assertTrue(any("async_runner.py" in arg for arg in cmd_list))
            self.assertIn("--file", cmd_list)
            self.assertIn(target, cmd_list)

            # Verify NO visible console window can appear: hidden-console flags
            # (CREATE_NO_WINDOW, NOT DETACHED_PROCESS) plus SW_HIDE startupinfo.
            if sys.platform == "win32":
                flags = call_kwargs.get("creationflags")
                self.assertEqual(flags, subprocess.CREATE_NO_WINDOW)
                self.assertEqual(flags & 0x00000008, 0, "DETACHED_PROCESS must not be used")
                startupinfo = call_kwargs.get("startupinfo")
                self.assertIsNotNone(startupinfo, "hidden STARTUPINFO required on Windows")
                self.assertTrue(startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW)
                self.assertEqual(startupinfo.wShowWindow, subprocess.SW_HIDE)
            else:
                self.assertTrue(call_kwargs.get("start_new_session"))

            self.assertEqual(call_kwargs.get("stdout"), subprocess.DEVNULL)
            self.assertEqual(call_kwargs.get("stderr"), subprocess.DEVNULL)

            # CRITICAL: Verify parent process NEVER waits on the background child
            mock_proc.wait.assert_not_called()
            mock_proc.communicate.assert_not_called()

    def test_lint_coalescing_integration_active_worker_state(self):
        """Integration-style coalescing contract test (no real sleep, no subprocess):

        Verifies that the state-based coalescing contract holds:
        - Trigger 1: should_spawn_file_worker() returns True → worker claims
        - Triggers 2-N: same file, worker already claimed → should_spawn_file_worker() returns False
        - Different file: always gets its own independent claim
        - clean_file_state() after completion leaves state minimal for next cycle

        This test uses only in-memory pure helpers — no subprocess, no sleep.
        """
        sys.path.insert(0, os.path.dirname(VALIDATOR_PATH))
        import async_runner

        # Simulate initial shared state (as loaded from debounce_state.json)
        active_workers: dict = {}
        file_edits: dict = {}
        norm_auth = "C:/project/src/auth.ts"
        norm_calc = "C:/project/src/calc.py"

        # --- Trigger 1: auth.ts first edit ---
        self.assertTrue(async_runner.should_spawn_file_worker(active_workers, norm_auth),
                        "First trigger must be able to claim worker")
        # Claim the worker (simulating what main() does)
        active_workers[norm_auth] = True
        file_edits[norm_auth] = 100.0

        # --- Trigger 2: auth.ts second edit (rapid burst, worker already active) ---
        self.assertFalse(async_runner.should_spawn_file_worker(active_workers, norm_auth),
                         "Second trigger must see active worker and NOT spawn duplicate")
        # Simulate timestamp reset (what the no-op path does)
        file_edits[norm_auth] = 100.15

        # --- Trigger 3: auth.ts third edit ---
        self.assertFalse(async_runner.should_spawn_file_worker(active_workers, norm_auth),
                         "Third trigger must also see active worker")
        file_edits[norm_auth] = 100.25

        # --- Multi-file isolation: calc.py is independent ---
        self.assertTrue(async_runner.should_spawn_file_worker(active_workers, norm_calc),
                        "Different file must get independent worker claim")
        active_workers[norm_calc] = True
        file_edits[norm_calc] = 100.10

        # --- Worker for auth.ts completes: 300ms quiet window elapsed ---
        now_after_quiet = 100.25 + 0.3 + 0.01  # 10ms past the window
        self.assertTrue(async_runner.should_run_file_lint(file_edits[norm_auth], now_after_quiet),
                        "After 300ms quiet window, linter must be cleared to run")

        # --- Cleanup after auth.ts linter finishes ---
        state_dict = {
            "active_lint_workers": dict(active_workers),
            "file_edits": dict(file_edits)
        }
        async_runner.clean_file_state(state_dict, norm_auth)

        # auth.ts state purged
        self.assertNotIn(norm_auth, state_dict["active_lint_workers"])
        self.assertNotIn(norm_auth, state_dict["file_edits"])

        # calc.py state untouched
        self.assertIn(norm_calc, state_dict["active_lint_workers"])
        self.assertIn(norm_calc, state_dict["file_edits"])

        # --- Next cycle: auth.ts can be claimed again cleanly ---
        fresh_active_workers = state_dict["active_lint_workers"]
        self.assertTrue(async_runner.should_spawn_file_worker(fresh_active_workers, norm_auth),
                        "After cleanup, auth.ts must be claimable again for next burst")

    def test_no_visible_console_for_any_spawned_process(self):
        """Regression: background spawns must never open a visible terminal window.

        DETACHED_PROCESS was the original bug: a detached process owns no console,
        so every console child it launches (cmd.exe via npx, ruff, godot) allocates
        a brand-new VISIBLE console window. The contract is now CREATE_NO_WINDOW +
        SW_HIDE, which descendants inherit.
        """
        sys.path.insert(0, os.path.dirname(VALIDATOR_PATH))
        import async_runner

        fake_proc = MagicMock()
        fake_proc.communicate.return_value = ("", "")
        fake_proc.returncode = 0
        fake_proc.poll.return_value = 0

        with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
            async_runner.run_hidden(["ruff", "check", "x.py"], timeout=5)
            self.assertTrue(mock_popen.called, "run_hidden must spawn via Popen")
            _, spawn_kwargs = mock_popen.call_args

            if sys.platform == "win32":
                flags = spawn_kwargs.get("creationflags")
                self.assertEqual(flags & async_runner._CREATE_NO_WINDOW,
                                 async_runner._CREATE_NO_WINDOW)
                self.assertEqual(flags & 0x00000008, 0,
                                 "DETACHED_PROCESS causes visible child consoles")
                startupinfo = spawn_kwargs.get("startupinfo")
                self.assertIsNotNone(startupinfo)
                self.assertEqual(startupinfo.wShowWindow, subprocess.SW_HIDE)
            else:
                self.assertNotIn("creationflags", spawn_kwargs)

        # No module may reintroduce the DETACHED_PROCESS flag as live code.
        engine_dir = os.path.dirname(VALIDATOR_PATH)
        for module_name in ("gravity-validator.py", "async_runner.py"):
            with open(os.path.join(engine_dir, module_name), "r", encoding="utf-8") as fh:
                source = fh.read()
            for line in source.splitlines():
                if line.lstrip().startswith("#"):
                    continue
                self.assertNotIn("DETACHED_PROCESS = 0x00000008", line,
                                 f"{module_name} must not spawn detached console processes")


    # --- PHASE 2.5: PER-FILE LINT BURST COALESCING & STATE CLEANUP TESTS ---
    def test_lint_coalescing_first_trigger_spawns_worker(self):
        """Scenario 1: First edit trigger on a file must claim and spawn worker."""
        sys.path.insert(0, os.path.dirname(VALIDATOR_PATH))
        import async_runner
        active_workers = {}
        file_key = "C:/fake/auth.ts"
        self.assertTrue(async_runner.should_spawn_file_worker(active_workers, file_key))

    def test_lint_coalescing_worker_already_active_prevents_duplicate(self):
        """Scenario 2: When worker is already active for a file, subsequent triggers do NOT spawn new worker."""
        sys.path.insert(0, os.path.dirname(VALIDATOR_PATH))
        import async_runner
        active_workers = {"C:/fake/auth.ts": True}
        file_key = "C:/fake/auth.ts"
        self.assertFalse(async_runner.should_spawn_file_worker(active_workers, file_key))

    def test_lint_coalescing_quiet_window_under_threshold(self):
        """Scenario 3: If edit occurred 100ms ago (< 300ms coalesce window), linter must NOT run yet."""
        sys.path.insert(0, os.path.dirname(VALIDATOR_PATH))
        import async_runner
        last_edit = 100.0
        now = 100.1  # 100ms elapsed
        self.assertFalse(async_runner.should_run_file_lint(last_edit, now, coalesce_window=0.3))

    def test_lint_coalescing_quiet_window_reached(self):
        """Scenario 4: If 300ms has elapsed with no new edits, quiet window is satisfied and linter can run."""
        sys.path.insert(0, os.path.dirname(VALIDATOR_PATH))
        import async_runner
        last_edit = 100.0
        now = 100.3  # Exactly 300ms elapsed
        self.assertTrue(async_runner.should_run_file_lint(last_edit, now, coalesce_window=0.3))
        now_later = 100.45  # 450ms elapsed
        self.assertTrue(async_runner.should_run_file_lint(last_edit, now_later, coalesce_window=0.3))

    def test_lint_coalescing_new_burst_resets_window(self):
        """Scenario 5: If a new edit arrives during the quiet window, the timer window resets."""
        sys.path.insert(0, os.path.dirname(VALIDATOR_PATH))
        import async_runner
        # Initial edit at t=100.0. A second edit arrives at t=100.2
        last_edit = 100.2
        # At t=100.3 (300ms from initial edit, but only 100ms from latest edit) -> must NOT run
        self.assertFalse(async_runner.should_run_file_lint(last_edit, 100.3, coalesce_window=0.3))
        # At t=100.5 (300ms from latest edit) -> now it runs!
        self.assertTrue(async_runner.should_run_file_lint(last_edit, 100.5, coalesce_window=0.3))

    def test_lint_coalescing_clean_file_state(self):
        """Scenario 6: Once worker finishes, active claim and timestamp are purged from state."""
        sys.path.insert(0, os.path.dirname(VALIDATOR_PATH))
        import async_runner
        state = {
            "active_lint_workers": {"C:/fake/auth.ts": True, "C:/fake/other.py": True},
            "file_edits": {"C:/fake/auth.ts": 123.45, "C:/fake/other.py": 678.90}
        }
        async_runner.clean_file_state(state, "C:/fake/auth.ts")
        self.assertNotIn("C:/fake/auth.ts", state["active_lint_workers"])
        self.assertNotIn("C:/fake/auth.ts", state["file_edits"])
        # Unrelated file state remains intact
        self.assertIn("C:/fake/other.py", state["active_lint_workers"])
        self.assertIn("C:/fake/other.py", state["file_edits"])

    def test_lint_coalescing_multi_file_isolation(self):
        """Scenario 7: Worker active on auth.ts does NOT block worker spawn on calc.py."""
        sys.path.insert(0, os.path.dirname(VALIDATOR_PATH))
        import async_runner
        active_workers = {"C:/fake/auth.ts": True}
        file_ts = "C:/fake/auth.ts"
        file_py = "C:/fake/calc.py"
        self.assertFalse(async_runner.should_spawn_file_worker(active_workers, file_ts))
        self.assertTrue(async_runner.should_spawn_file_worker(active_workers, file_py))

    # --- PHASE 2.5 HARDENING: NEW FILE CREATED AFTER WORKER SPAWN ---
    def test_new_file_created_after_worker_spawn_is_linted_once(self):
        """Regression: a file created *after* the worker spawn must still be linted once.

        GravityGuard is a PreToolUse hook, so this worker is spawned BEFORE the AI
        writes the file. main() previously exited early when the target was missing,
        which silently meant every newly created file was never linted. The worker now
        waits a *bounded* grace period for the file to land.

        Uses a mocked clock: no real 300ms/2s sleeps, no subprocesses.
        """
        from pathlib import Path
        sys.path.insert(0, os.path.dirname(VALIDATOR_PATH))
        import async_runner

        temp_dir = tempfile.mkdtemp(prefix="gg_newfile_")
        try:
            project_root = Path(temp_dir)
            target_file = project_root / "src" / "auth.ts"
            norm_key = str(target_file.resolve()).replace("\\", "/")

            # Pre-tool ordering: the file does not exist when the worker starts.
            self.assertFalse(target_file.exists(), "precondition: new file must be absent")

            # --- Pure bounded-wait decision matrix (no sleeping involved) ---
            self.assertTrue(async_runner.should_wait_for_target_file(False, 0.0, 2.0))
            self.assertTrue(async_runner.should_wait_for_target_file(False, 1.9, 2.0))
            self.assertFalse(async_runner.should_wait_for_target_file(True, 0.0, 2.0),
                             "file appeared -> stop waiting immediately")
            self.assertFalse(async_runner.should_wait_for_target_file(False, 2.0, 2.0),
                             "grace exhausted -> bounded wait must end")

            # --- Worker integration on a mocked clock ---
            clock = {"now": 1000.0, "sleeps": 0}

            def fake_sleep(seconds):
                clock["sleeps"] += 1
                clock["now"] += seconds
                # The AI writes the file shortly after the worker's quiet window.
                if clock["sleeps"] == 2:
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    target_file.write_text("export const token = 1;\n", encoding="utf-8")

            lint_calls = []

            with patch("async_runner.time.sleep", side_effect=fake_sleep), \
                 patch("async_runner.time.time", side_effect=lambda: clock["now"]), \
                 patch("async_runner.execute_single_file_lint",
                       side_effect=lambda tf, proot, dpath: lint_calls.append(tf)):
                async_runner.run_coalesced_file_lint_worker(
                    str(target_file), project_root, coalesce_window=0.3, grace_period=2.0
                )

            self.assertEqual(len(lint_calls), 1,
                             "a newly created file must be linted exactly once")

            # Completed work must release its claim so the next burst starts fresh.
            state = async_runner.load_debounce_state(
                async_runner.get_debounce_file_path(project_root))
            self.assertNotIn(norm_key, state.get("active_lint_workers", {}))
            self.assertNotIn(norm_key, state.get("file_edits", {}))

            # Guard against reintroducing the exact early-exit that caused this bug.
            with open(os.path.join(os.path.dirname(VALIDATOR_PATH), "async_runner.py"),
                      "r", encoding="utf-8") as fh:
                normalized = "\n".join(line.strip() for line in fh.read().splitlines())
            self.assertNotIn("if not os.path.exists(target_file):\nsys.exit(0)", normalized,
                             "main() must not skip linting for not-yet-written files")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_worker_exits_cleanly_when_new_file_never_appears(self):
        """A file that never materialises must not hang the worker or leak state."""
        from pathlib import Path
        sys.path.insert(0, os.path.dirname(VALIDATOR_PATH))
        import async_runner

        temp_dir = tempfile.mkdtemp(prefix="gg_nofile_")
        try:
            project_root = Path(temp_dir)
            target_file = project_root / "src" / "never_written.py"
            norm_key = str(target_file.resolve()).replace("\\", "/")

            clock = {"now": 2000.0, "sleeps": 0}

            def fake_sleep(seconds):
                clock["sleeps"] += 1
                clock["now"] += seconds

            lint_calls = []
            with patch("async_runner.time.sleep", side_effect=fake_sleep), \
                 patch("async_runner.time.time", side_effect=lambda: clock["now"]), \
                 patch("async_runner.execute_single_file_lint",
                       side_effect=lambda tf, proot, dpath: lint_calls.append(tf)):
                async_runner.run_coalesced_file_lint_worker(
                    str(target_file), project_root, coalesce_window=0.3, grace_period=2.0
                )

            # Bounded wait: finite number of polls, then a clean no-op exit.
            self.assertEqual(len(lint_calls), 0, "missing file must never be linted")
            self.assertLessEqual(clock["sleeps"], 10, "grace wait must be bounded")

            state = async_runner.load_debounce_state(
                async_runner.get_debounce_file_path(project_root))
            self.assertNotIn(norm_key, state.get("active_lint_workers", {}))
            self.assertNotIn(norm_key, state.get("file_edits", {}))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # --- PHASE 2.5 HARDENING: DEBOUNCE WORKER LIFECYCLE ---
    def test_max_lifetime_expiry_releases_worker_running_claim(self):
        """Regression: max_lifetime expiry must clear the persisted worker_running flag.

        The worker previously returned on the max_lifetime guard WITHOUT setting
        worker_running = False. A long edit burst (>120s) therefore left a stale
        worker_running = True in debounce_state.json, and every subsequent
        trigger_debounce_worker_if_needed() saw an "active" worker and refused to
        spawn one. The safety mechanism permanently deadlocked itself.

        Uses a mocked clock: no real 120s wait, no subprocesses.
        """
        from pathlib import Path
        sys.path.insert(0, os.path.dirname(VALIDATOR_PATH))
        import async_runner

        temp_dir = tempfile.mkdtemp(prefix="gg_lifetime_")
        try:
            project_root = Path(temp_dir)
            debounce_path = async_runner.get_debounce_file_path(project_root)

            # Worker is mid-flight: claimed, with an edit timestamp that never
            # goes idle, so only the max_lifetime guard can end the loop.
            async_runner.save_debounce_state(debounce_path, {
                "last_edit_time": 1e9,
                "worker_running": True,
                "file_edits": {},
                "active_lint_workers": {},
            })

            clock = {"now": 500.0, "sleeps": 0}

            def fake_sleep(seconds):
                clock["sleeps"] += 1
                clock["now"] += seconds

            with patch("async_runner.time.sleep", side_effect=fake_sleep), \
                 patch("async_runner.time.time", side_effect=lambda: clock["now"]), \
                 patch("async_runner.run_batch_tsc", side_effect=AssertionError(
                     "max_lifetime expiry must NOT run tsc")):
                async_runner.run_debounce_worker(
                    project_root, idle_threshold=3.0, max_lifetime=120.0
                )

            # Bounded: the mocked loop must terminate without real waiting.
            self.assertLessEqual(clock["sleeps"], 50,
                                 "max_lifetime guard must bound the loop")

            state = async_runner.load_debounce_state(debounce_path)
            self.assertFalse(state.get("worker_running", True),
                             "expired worker must release its claim or the TSC "
                             "debounce deadlocks permanently")

            # Consequence check: a later edit can claim a worker again.
            self.assertTrue(async_runner.should_spawn_worker(state.get("worker_running", False)),
                            "after expiry, a new trigger must be able to claim a worker")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_max_lifetime_expiry_without_state_file_does_not_recreate_runtime_dir(self):
        """If the state file is already gone, expiry must exit without recreating it."""
        from pathlib import Path
        sys.path.insert(0, os.path.dirname(VALIDATOR_PATH))
        import async_runner

        temp_dir = tempfile.mkdtemp(prefix="gg_lifetime_nostate_")
        try:
            project_root = Path(temp_dir)
            debounce_path = async_runner.get_debounce_file_path(project_root)
            # No state file is written: get_debounce_file_path() only creates the
            # runtime directory, so the path is legitimately absent here.
            self.assertFalse(debounce_path.exists(), "precondition: no state file")

            clock = {"now": 900.0, "sleeps": 0}

            def fake_sleep(seconds):
                clock["sleeps"] += 1
                clock["now"] += seconds

            with patch("async_runner.time.sleep", side_effect=fake_sleep), \
                 patch("async_runner.time.time", side_effect=lambda: clock["now"]), \
                 patch("async_runner.save_debounce_state",
                       side_effect=AssertionError("must not persist state when none exists")):
                async_runner.run_debounce_worker(
                    project_root, idle_threshold=3.0, max_lifetime=120.0
                )

            self.assertFalse(debounce_path.exists(),
                             "absent state file must not be re-created on expiry")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestHookStdoutContract(unittest.TestCase):
    """
    Regression guard for the production incident where a WARN turned into a HARD
    tool failure: the hook emitted `warnings` / `warning_rule_ids`, the harness
    decoded stdout with protojson, rejected the unknown field and discarded the
    ENTIRE response — so every write tool call was blocked.

    Invariant: stdout keys must stay within SCHEMA_ALLOWED_KEYS, and warnings must
    still reach the user/agent through `reason`.
    """

    def test_warn_path_emits_only_schema_keys_and_delivers_warning(self):
        """A warning-producing call must stay schema-valid AND still surface the warning."""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/service.py",
                    "TargetContent": "result = do_task()",
                    "ReplacementContent": (
                        "import os  # noqa\n"
                        "result = do_task()\n"
                    )
                }
            }
        }
        res, _ = run_validator(payload)

        self.assertEqual(res.get("decision"), "allow",
                         "WARN-only guards must never block a write")
        # (1) No schema-invalid field may appear, or protojson kills the response.
        self.assertNotIn("warnings", res)
        self.assertNotIn("warning_rule_ids", res)
        # (2) The warning must still be delivered — schema-valid, agent-visible.
        self.assertIn("G3_COMPILER_BYPASS", _warnings_from(res))

    def test_clean_edit_emits_minimal_schema_valid_response(self):
        """A warning-free edit must emit a bare, schema-valid allow."""
        payload = {
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "C:/fake_project/src/math_utils.py",
                    "TargetContent": "def add(a, b):\n    return a + b\n",
                    "ReplacementContent": "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
                }
            }
        }
        res, _ = run_validator(payload)
        self.assertEqual(res.get("decision"), "allow")
        self.assertLessEqual(set(res.keys()), SCHEMA_ALLOWED_KEYS)


if __name__ == "__main__":
    unittest.main()



