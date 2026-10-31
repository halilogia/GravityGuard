import importlib.util
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))

from gravityguard_engine import doc_automation  # noqa: E402
from gravityguard_engine.project_context import should_enforce_doc_obligations  # noqa: E402


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_arch", ROOT / "tools" / "generate_architecture.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ChangelogInjectionTests(unittest.TestCase):
    def test_injects_under_first_unreleased_heading_only_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "CHANGELOG.md"
            path.write_text("# Log\n\n## [Unreleased]\n\n### Added\n- x\n\n## [Unreleased]\n\n- old\n", encoding="utf-8")
            self.assertTrue(doc_automation.inject_changelog_entry(path, "`engine/a.py`"))
            self.assertFalse(doc_automation.inject_changelog_entry(path, "`engine/a.py`"))
            lines = path.read_text(encoding="utf-8").splitlines()
            idx = lines.index("## [Unreleased]")
            self.assertTrue(lines[idx + 2].startswith(doc_automation.AUTO_ENTRY_PREFIX))
            self.assertEqual(sum(l.startswith(doc_automation.AUTO_ENTRY_PREFIX) for l in lines), 1)

    def test_preserves_crlf_and_refuses_without_heading(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "CHANGELOG.md"
            path.write_bytes(b"# Log\r\n\r\n## [Unreleased]\r\n\r\n- a\r\n")
            self.assertTrue(doc_automation.inject_changelog_entry(path, "`src/x.ts`"))
            self.assertNotIn(b"\n", path.read_bytes().replace(b"\r\n", b""))
            path.write_text("# Log\n", encoding="utf-8")
            self.assertFalse(doc_automation.inject_changelog_entry(path, "`src/x.ts`"))


class GenericAutomationTests(unittest.TestCase):
    def test_generic_metrics_newlines_and_idempotence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "ARCHITECTURE.md"
            doc.write_bytes(b"# Manual\r\nKeep this.\r\n")
            for rel in ("addons/a.gd", "app/a.tsx", "tests/test_a.py", "node_modules/ignore.js"):
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("one\n\ntwo\n", encoding="utf-8")
            with mock.patch.object(doc_automation, "changed_code_files", return_value=["addons/a.gd"]):
                self.assertEqual(doc_automation.sync_architecture(root)["status"], "appended")
                self.assertEqual(doc_automation.sync_architecture(root)["status"], "unchanged")
            content = doc.read_text(encoding="utf-8")
            self.assertIn("Source files: **3**; non-empty LOC: **6**", content)
            self.assertIn("Test files: **1**", content)
            self.assertIn("Keep this.", content)
            self.assertNotIn(b"\n", doc.read_bytes().replace(b"\r\n", b""))
            (root / "app/a.tsx").write_text("one\n", encoding="utf-8")
            self.assertEqual(doc_automation.sync_generic_architecture(root)["status"], "updated")
            self.assertEqual(doc.read_text(encoding="utf-8").count(doc_automation.ARCH_START), 1)

    def test_generic_block_cap_preserves_manual_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "ARCHITECTURE.md"
            manual = "Manual content\n" * 210
            doc.write_text(manual, encoding="utf-8")
            for i in range(205):
                folder = root / f"area{i}"
                folder.mkdir()
                (folder / "a.go").write_text("package main\n", encoding="utf-8")
            doc_automation.sync_generic_architecture(root)
            text = doc.read_text(encoding="utf-8")
            self.assertTrue(text.startswith(manual))
            self.assertLessEqual(len(text[text.index(doc_automation.ARCH_START):].splitlines()), 200)

    def test_changed_paths_handle_spaces_unicode_renames_and_extensions(self):
        status = " M addons/hello world.gd\0?? web/ç.tsx\0 M src/icon.png\0R  outside/a.py\0core/old.py\0"
        with mock.patch.object(doc_automation, "_git", return_value=status):
            self.assertEqual(doc_automation.changed_code_files(Path(".")),
                             ["addons/hello world.gd", "core/old.py", "web/ç.tsx"])

    def test_knowledge_paths_resolution_and_injection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in (".gravityguard.json", "hooks.json", "plugin/hooks.json", "rules/a.md", "engine/x_rules.py", "engine/doc_policy.py"):
                self.assertTrue(doc_automation.is_knowledge_governed_path(rel, root), rel)
                self.assertTrue(doc_automation.is_knowledge_governed_path(str(root / rel), root), rel)
            for rel in ("src/a.py", "other/hooks.json", "../rules/a.py"):
                self.assertFalse(doc_automation.is_knowledge_governed_path(rel, root), rel)
            self.assertIsNone(doc_automation.resolve_knowledge_doc(root))
            doc = root / "KNOWLEDGE.md"
            doc.write_bytes(b"# Knowledge\r\n")
            self.assertEqual(doc_automation.resolve_knowledge_doc(root), "KNOWLEDGE.md")
            self.assertTrue(doc_automation.inject_knowledge_entry(doc, "rules/a.py"))
            self.assertFalse(doc_automation.inject_knowledge_entry(doc, "rules/a.py"))
            self.assertNotIn(b"\n", doc.read_bytes().replace(b"\r\n", b""))
            (root / "docs").mkdir()
            (root / "docs/KNOWLEDGE.md").write_text("# K\n", encoding="utf-8")
            self.assertEqual(doc_automation.resolve_knowledge_doc(root), "docs/KNOWLEDGE.md")


class DocObligationDefaultTests(unittest.TestCase):
    def test_default_on_when_changelog_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(should_enforce_doc_obligations("a.py", cfg={}, project_root=root))
            (root / "CHANGELOG.md").write_text("# c\n", encoding="utf-8")
            self.assertTrue(should_enforce_doc_obligations("a.py", cfg={}, project_root=root))
            self.assertFalse(should_enforce_doc_obligations(
                "a.py", cfg={"governance": {"enforceDocObligations": False}}, project_root=root))


class ArchitectureSyncTests(unittest.TestCase):
    def test_marker_block_is_replaced_and_handwritten_text_preserved(self):
        gen = _load_generator()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "engine").mkdir()
            (root / "engine" / "a.py").write_text("x = 1\n", encoding="utf-8")
            doc = root / "ARCHITECTURE.md"
            doc.write_text("# Hand written\n\nkeep me\n", encoding="utf-8")
            self.assertEqual(gen.sync_architecture(root, today="2026-01-01")[0], "appended")
            self.assertEqual(gen.sync_architecture(root, today="2026-01-02")[0], "unchanged")
            (root / "engine" / "b.py").write_text("y = 2\n", encoding="utf-8")
            self.assertEqual(gen.sync_architecture(root, today="2026-01-03")[0], "updated")
            text = doc.read_text(encoding="utf-8")
            self.assertIn("keep me", text)
            self.assertEqual(text.count(gen.ARCH_START), 1)

    def test_new_file_respects_line_cap(self):
        gen = _load_generator()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "engine").mkdir()
            for i in range(400):
                (root / "engine" / f"m{i}.py").write_text("x = 1\n", encoding="utf-8")
            status, path = gen.sync_architecture(root)
            self.assertEqual(status, "created")
            self.assertLessEqual(len(path.read_text(encoding="utf-8").splitlines()), gen.ARCH_MAX_LINES)


if __name__ == "__main__":
    unittest.main()
