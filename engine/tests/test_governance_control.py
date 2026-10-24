"""UI and hook writers must use one transaction lock, preserving other sessions."""
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from governance_control import waive_advisory
from gravityguard_engine.governance import governance_transaction, load_governance_state


class GovernanceControlTests(unittest.TestCase):
    def test_waiver_updates_aggregate_and_sessions_but_preserves_review(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"GRAVITYGUARD_LOG_DIR": directory}):
            root = Path(directory)
            target = str(root / "a.py")
            debt = {"test_obligations": {"pending": {target: {}}}, "review_obligations": {"pending": {"review": {}}}}
            with governance_transaction(root) as state:
                state.update(json.loads(json.dumps(debt)))
                state["sessions"] = {"a": json.loads(json.dumps(debt))}
            waive_advisory(root, target)
            state = load_governance_state(root)
            self.assertFalse(state["test_obligations"]["pending"])
            self.assertFalse(state["sessions"]["a"]["test_obligations"]["pending"])
            self.assertIn("review", state["review_obligations"]["pending"])

    def test_concurrent_ui_waiver_and_hook_writer_do_not_lose_new_debt(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"GRAVITYGUARD_LOG_DIR": directory}):
            root = Path(directory)
            waived = str(root / "a.py")
            keep = str(root / "b.py")
            with governance_transaction(root) as state:
                state["test_obligations"] = {"pending": {waived: {}}}
            script = "import sys; from pathlib import Path; from governance_control import waive_advisory; waive_advisory(Path(sys.argv[1]), sys.argv[2])"
            proc = subprocess.Popen([sys.executable, "-c", script, directory, waived], cwd=str(Path(__file__).resolve().parents[1]), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            with governance_transaction(root) as state:
                state["test_obligations"]["pending"][keep] = {"reason": "new debt"}
            _, errors = proc.communicate(timeout=15)
            self.assertEqual(proc.returncode, 0, errors)
            state = load_governance_state(root)
            self.assertIn(keep, state["test_obligations"]["pending"])
            self.assertNotIn(waived, state["test_obligations"]["pending"])
