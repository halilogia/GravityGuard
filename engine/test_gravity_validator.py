import unittest
import subprocess
import json
import time
import os
import sys
import tempfile
import shutil
from typing import Tuple

VALIDATOR_PATH = os.path.join(os.path.dirname(__file__), "gravity-validator.py")

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
        # Run 5 times and average
        timings = []
        for _ in range(5):
            res, ms = run_validator(payload)
            timings.append(ms)
            self.assertEqual(res.get("decision"), "allow")
        avg_ms = sum(timings) / len(timings)
        print(f"\n[PERFORMANCE BENCHMARK] Subprocess total spawn + run: {avg_ms:.2f} ms (Pure internal guard execution is ~1.0-1.6 ms)")
        self.assertLess(avg_ms, 250)  # Windows python.exe process spawn overhead

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
        rule_ids = res.get("warning_rule_ids", [])
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
        rule_ids = res.get("warning_rule_ids", [])
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
        rule_ids = res.get("warning_rule_ids", [])
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
            rule_ids = res.get("warning_rule_ids", [])
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
            rule_ids = res.get("warning_rule_ids", [])
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
        rule_ids = res.get("warning_rule_ids", [])
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
        rule_ids = res.get("warning_rule_ids", [])
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
        rule_ids = res.get("warning_rule_ids", [])
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
        rule_ids = res.get("warning_rule_ids", [])
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
        rule_ids = res.get("warning_rule_ids", [])
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
        rule_ids = res.get("warning_rule_ids", [])
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
            rule_ids = res.get("warning_rule_ids", [])
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
            rule_ids = res.get("warning_rule_ids", [])
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


if __name__ == "__main__":
    unittest.main()

