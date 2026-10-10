import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from gravityguard_engine.security_rules import is_doc_or_rule_file, check_blind_doc_overwrite
from gravityguard_engine.dispatcher import validate_gravityguard

class TestDocOverwriteGuard(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.existing_doc = Path(self.temp_dir) / "README.md"
        self.existing_doc.write_text("# My Project\nOriginal Content\n", encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_is_doc_or_rule_file(self):
        self.assertTrue(is_doc_or_rule_file("README.md"))
        self.assertTrue(is_doc_or_rule_file("docs/ARCHITECTURE.md"))
        self.assertTrue(is_doc_or_rule_file("skills/core-docs/SKILL.md"))
        self.assertTrue(is_doc_or_rule_file("AGENTS.md"))
        self.assertTrue(is_doc_or_rule_file("LICENSE"))
        self.assertFalse(is_doc_or_rule_file("src/main.py"))
        self.assertFalse(is_doc_or_rule_file("web/App.tsx"))
        self.assertFalse(is_doc_or_rule_file("package.json"))

    def test_blocks_blind_overwrite_on_existing_doc(self):
        payload = {
            "conversationId": "test-doc-conv",
            "workspacePaths": [self.temp_dir],
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(self.existing_doc),
                    "CodeContent": "# New Blind Content"
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
        self.assertIn("G4_NO_BLIND_OVERWRITE", output.get("reason", ""))
        self.assertIn("replace_file_content", output.get("reason", ""))
        self.assertIn("Claude Code: Edit", output.get("reason", ""), "the message must fit Claude Code too")

    def test_allows_creating_brand_new_doc_with_write_to_file(self):
        new_doc = Path(self.temp_dir) / "CHANGELOG.md"
        payload = {
            "conversationId": "test-doc-conv",
            "workspacePaths": [self.temp_dir],
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(new_doc),
                    "CodeContent": "# Initial Changelog\n"
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

    def test_allows_replace_file_content_on_existing_doc(self):
        payload = {
            "conversationId": "test-doc-conv",
            "workspacePaths": [self.temp_dir],
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": str(self.existing_doc),
                    "TargetContent": "Original Content",
                    "ReplacementContent": "Updated Content"
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

    def test_core_docs_skill_contract_invariants(self):
        """Contract test: guarantees that core-docs/SKILL.md retains the Autonomous Invariant Capture protocol."""
        repo_root = ENGINE_DIR.parent
        skill_file = repo_root / "plugin" / "skills" / "core-docs" / "SKILL.md"
        self.assertTrue(skill_file.is_file(), f"Missing core-docs SKILL.md at {skill_file}")
        content = skill_file.read_text(encoding="utf-8")
        self.assertIn("OTONOM İNİSİYATİF", content, "core-docs SKILL.md must retain 'OTONOM İNİSİYATİF' protocol!")
        self.assertIn("KNOWLEDGE.md", content, "core-docs SKILL.md must mandate KNOWLEDGE.md ADR/GOTCHA capture!")
        self.assertIn("TASKS.md", content, "core-docs SKILL.md must mandate TASKS.md progress marking!")

if __name__ == "__main__":
    unittest.main()
