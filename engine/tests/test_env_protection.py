import json
import os
import sys
import unittest
from pathlib import Path

# Add engine directory to sys.path
ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from gravityguard_engine.security_rules import is_protected_env_file
from gravityguard_engine.dispatcher import validate_gravityguard
import io
from unittest.mock import patch

class TestEnvProtection(unittest.TestCase):
    def test_is_protected_env_file(self):
        # Protected files
        self.assertTrue(is_protected_env_file(".env"))
        self.assertTrue(is_protected_env_file(".env.local"))
        self.assertTrue(is_protected_env_file(".env.production"))
        self.assertTrue(is_protected_env_file("C:/my_project/.env"))
        self.assertTrue(is_protected_env_file("/home/user/app/.env.staging"))

        # Exempt template and test files
        self.assertFalse(is_protected_env_file(".env.example"))
        self.assertFalse(is_protected_env_file(".env.sample"))
        self.assertFalse(is_protected_env_file(".env.template"))
        self.assertFalse(is_protected_env_file(".env.test"))
        self.assertFalse(is_protected_env_file("example.env"))
        self.assertFalse(is_protected_env_file("config.py"))
        self.assertFalse(is_protected_env_file("environment.ts"))
        self.assertFalse(is_protected_env_file(""))

    def test_dispatcher_blocks_env_write(self):
        payload = {
            "conversationId": "test-env-conv",
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": ".env",
                    "CodeContent": "API_KEY=12345"
                }
            }
        }
        with patch("sys.stdin", io.StringIO(json.dumps(payload))), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_stdout, \
             self.assertRaises(SystemExit) as cm:
            validate_gravityguard()

        self.assertEqual(cm.exception.code, 0)
        output = json.loads(mock_stdout.getvalue())
        self.assertEqual(output.get("decision"), "deny")
        self.assertIn("G0_ENV_PROTECTION", output.get("reason", ""))

    def test_dispatcher_allows_env_example_write(self):
        payload = {
            "conversationId": "test-env-conv",
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": ".env.example",
                    "CodeContent": "API_KEY=your_key_here"
                }
            }
        }
        with patch("sys.stdin", io.StringIO(json.dumps(payload))), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_stdout, \
             self.assertRaises(SystemExit) as cm:
            validate_gravityguard()

        self.assertEqual(cm.exception.code, 0)
        output = json.loads(mock_stdout.getvalue())
        self.assertEqual(output.get("decision"), "allow")

    def test_dispatcher_blocks_env_read(self):
        payload = {
            "conversationId": "test-env-conv",
            "toolCall": {
                "name": "view_file",
                "args": {
                    "AbsolutePath": "C:/my_project/.env"
                }
            }
        }
        with patch("sys.stdin", io.StringIO(json.dumps(payload))), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_stdout, \
             self.assertRaises(SystemExit) as cm:
            validate_gravityguard()

        self.assertEqual(cm.exception.code, 0)
        output = json.loads(mock_stdout.getvalue())
        self.assertEqual(output.get("decision"), "deny")
        self.assertIn("G0_ENV_PROTECTION", output.get("reason", ""))
        self.assertIn("OKUNAMAZ", output.get("reason", ""))

    def test_dispatcher_allows_normal_view_file(self):
        payload = {
            "conversationId": "test-env-conv",
            "toolCall": {
                "name": "view_file",
                "args": {
                    "AbsolutePath": "C:/my_project/src/calculator.py"
                }
            }
        }
        with patch("sys.stdin", io.StringIO(json.dumps(payload))), \
             patch("sys.stdout", new_callable=io.StringIO) as mock_stdout, \
             self.assertRaises(SystemExit) as cm:
            validate_gravityguard()

        self.assertEqual(cm.exception.code, 0)
        output = json.loads(mock_stdout.getvalue())
        self.assertEqual(output.get("decision"), "allow")

if __name__ == "__main__":
    unittest.main()
