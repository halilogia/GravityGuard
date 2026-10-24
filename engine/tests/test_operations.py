"""Adversarial contracts for provider-independent file operations."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gravityguard_engine.operations import normalize_operation, provider_tool_call, UnsupportedOperation
from gravityguard_engine.diffing import get_projected_and_old_content
from gravityguard_engine.dispatcher import validate_gravityguard


class OperationTests(unittest.TestCase):
    def test_provider_uses_cwd_and_preserves_unsupported_schemas(self):
        cwd = str(Path.cwd() / "nested")
        call = provider_tool_call("quantum_mutator", {"filePath": "a.py", "code": ""}, cwd)
        self.assertEqual(call["name"], "write_to_file")
        self.assertEqual(call["args"]["TargetFile"], str(Path(cwd) / "a.py"))
        args = {"file_path": "a.py", "edits": [{"old_string": "a", "new_string": "b"}, "junk"]}
        self.assertEqual(provider_tool_call("MultiEdit", args, cwd), {"name": "MultiEdit", "args": args})
        self.assertEqual(provider_tool_call("Bash", {"command": "ls"}, cwd)["args"]["command"], "ls")

    def test_renamed_tools_and_empty_replacements(self):
        self.assertEqual(normalize_operation("quantum_mutator", {"filePath": "a.py", "text": ""}).kind, "WRITE")
        op = normalize_operation("Read", {"path": "a.py", "old_string": "x", "new_string": ""})
        self.assertEqual(op.kind, "EDIT")
        self.assertEqual(op.args["ReplacementContent"], "")
        op = normalize_operation("future", {"filename": "a.py", "edits": [{"search": "x", "replace": ""}]})
        self.assertEqual(op.kind, "MULTI_EDIT")

    def test_unsupported_payloads_do_not_become_reads(self):
        for args in (
            {"path": "a.py"}, {"path": "a.py", "content": None},
            {"path": "a.py", "content": "", "text": "hidden"},
            {"path": "a.py", "file_path": "b.py", "content": "x"},
            {"path": "a.py", "old_string": "x"},
            {"path": "a.py", "edits": [None]},
            {"path": "a.py", "edits": [{"path": "b.py", "old_string": "a", "new_string": "b"}]},
            {"path": "a.py", "diff": "@@"}, {"uri": "file:///a.py"},
            {"path": "a.py", "old_string": "a", "new_string": "b", "content": "c"},
        ):
            with self.subTest(args=args), self.assertRaises(UnsupportedOperation):
                normalize_operation("patch_file", args)
        self.assertIsNone(normalize_operation("ask_question", {"text": "hello"}))
        self.assertEqual(normalize_operation("read_file", {"path": "a.py"}).kind, "READ")

    def test_projection_uses_semantics_and_deletions(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "a.py"
            target.write_text("alpha beta", encoding="utf-8")
            old, new = get_projected_and_old_content(str(target), "future", {
                "path": str(target), "edits": [{"old_string": "alpha ", "new_string": ""},
                                               {"old_string": "beta", "new_string": "gamma"}]})
            self.assertEqual((old, new), ("alpha beta", "gamma"))

    def test_dispatcher_blocks_renamed_overwrite_secret_and_ambiguous_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("Original", encoding="utf-8")
            cases = [
                ("future", {"path": "README.md", "text": "Truncated"}, "G4_NO_BLIND_OVERWRITE"),
                ("Read", {"path": "a.py", "content": "key = 'ghp_" + "A" * 36 + "'"}, "G0_SECRET_LEAK"),
                ("mcp_custom_code_review", {"path": "a.py", "content": "ghp_" + "A" * 36}, "G0_SECRET_LEAK"),
                ("future", {"filePath": ".env"}, "TOOL_SCHEMA_UNSUPPORTED"),
                ("read_file", {"path": ".env"}, "G0_ENV_PROTECTION"),
                ("delete_file", {"path": "README.md"}, "TOOL_SCHEMA_UNSUPPORTED"),
                ("future", {"path": "a.py", "edits": [7]}, "TOOL_SCHEMA_UNSUPPORTED"),
            ]
            for name, args, rule in cases:
                payload = {"workspacePaths": [directory], "toolCall": {"name": name, "args": args}}
                with self.subTest(rule=rule), patch.dict(os.environ, {
                    "GRAVITYGUARD_LOG_DIR": directory, "GRAVITYGUARD_USER_CONFIG": str(root / "absent.json"),
                    "GRAVITYGUARD_DISABLE_ASYNC": "1",
                }), patch("sys.stdin", io.StringIO(json.dumps(payload))), patch("sys.stdout", new_callable=io.StringIO) as out:
                    with self.assertRaises(SystemExit):
                        validate_gravityguard()
                    answer = json.loads(out.getvalue())
                    self.assertEqual(answer["decision"], "deny")
                    self.assertIn(rule, answer["reason"])

    def test_hook_manifests_listen_to_every_tool_once(self):
        root = Path(__file__).resolve().parents[2]
        manifests = [json.loads((root / name).read_text(encoding="utf-8")) for name in ("hooks.json", "plugin/hooks.json")]
        self.assertEqual(manifests[0], manifests[1])
        hooks = manifests[0]["gravityguard"]["PreToolUse"]
        self.assertEqual(len(hooks), 1)
        self.assertEqual(hooks[0]["matcher"], "*")
