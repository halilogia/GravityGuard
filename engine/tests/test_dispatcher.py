import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))

from gravityguard_engine import dispatcher  # noqa: E402


class StopDocAutomationTests(unittest.TestCase):
    def test_combined_knowledge_obligation_closes_in_real_state(self):
        from gravityguard_engine.governance import record_pending_doc_obligation, get_unresolved_doc_obligations
        for knowledge in ("KNOWLEDGE.md", "docs/KNOWLEDGE.md"):
            with self.subTest(knowledge=knowledge), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "CHANGELOG.md").write_text("## [Unreleased]\n", encoding="utf-8")
                doc = root / knowledge
                doc.parent.mkdir(parents=True, exist_ok=True)
                doc.write_text("# Knowledge\n", encoding="utf-8")
                target = str(root / "rules/a.py")
                record_pending_doc_obligation(target, ["CHANGELOG.md", knowledge], project_root=root, conversation_id="test")
                pending = get_unresolved_doc_obligations(root, "test")
                with mock.patch.object(dispatcher, "log_event") as log:
                    closed = dispatcher._auto_resolve_changelog(root, "test", pending)
                self.assertEqual(closed, [target.replace("\\", "/")])
                self.assertFalse(get_unresolved_doc_obligations(root, "test"))
                self.assertIn("[auto-ADR]", doc.read_text(encoding="utf-8"))
                self.assertIn("KNOWLEDGE_AUTO_INJECT", [c.kwargs.get("rule_id") for c in log.call_args_list])

    def test_auto_resolve_changelog_injects_and_closes_obligation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CHANGELOG.md").write_text("# L\n\n## [Unreleased]\n\n- a\n", encoding="utf-8")
            pending = {"engine/x.py": {"required_docs": ["CHANGELOG.md"]}}
            with mock.patch.object(dispatcher, "resolve_pending_doc_obligations", return_value=["engine/x.py"]) as res, \
                    mock.patch.object(dispatcher, "log_event"):
                closed = dispatcher._auto_resolve_changelog(root, "cid", pending)
            self.assertEqual(closed, ["engine/x.py"])
            res.assert_called_once()
            self.assertIn("[auto]", (root / "CHANGELOG.md").read_text(encoding="utf-8"))

    def test_architecture_sync_failure_is_non_fatal(self):
        with mock.patch("gravityguard_engine.doc_automation.sync_architecture", side_effect=RuntimeError("boom")), \
                mock.patch.object(dispatcher, "log_event") as log:
            dispatcher._perform_architecture_sync(Path("."), "cid")
        self.assertEqual(log.call_args.kwargs["rule_id"], "ARCHITECTURE_SYNC_ERROR")


if __name__ == "__main__":
    unittest.main()
