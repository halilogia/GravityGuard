#!/usr/bin/env python3
"""
Unit tests for the Evidence-Based Delivery Gate (EBDG) Phase 0 UI screenshot verification.
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine.delivery_gate import (
    is_ui_file,
    find_recent_screenshots,
    evaluate_ebdg_ui_gate,
    write_delivery_receipt
)


class TestDeliveryGate(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_is_ui_file_detection(self):
        # UI extensions
        self.assertTrue(is_ui_file("styles/main.css"))
        self.assertTrue(is_ui_file("index.html"))
        self.assertTrue(is_ui_file("src/App.vue"))
        self.assertTrue(is_ui_file("components/Modal.svelte"))
        self.assertTrue(is_ui_file("scenes/level1.tscn"))

        # JSX/TSX in UI directory
        self.assertTrue(is_ui_file("src/components/Button.tsx"))
        self.assertTrue(is_ui_file("app/ui/Navbar.jsx"))
        self.assertTrue(is_ui_file("src/views/Dashboard.tsx"))

        # Non-UI files
        self.assertFalse(is_ui_file("src/server.py"))
        self.assertFalse(is_ui_file("lib/math.ts"))
        self.assertFalse(is_ui_file("README.md"))
        self.assertFalse(is_ui_file("package.json"))

    def test_no_ui_files_passes_gate(self):
        allowed, warn, path = evaluate_ebdg_ui_gate(
            project_root=self.project_root,
            conversation_id="conv-1",
            session_retries=0,
            custom_modified_files=["engine/rules.py", "README.md"]
        )
        self.assertTrue(allowed)
        self.assertIsNone(warn)
        self.assertIsNone(path)

    def test_ui_file_without_screenshot_warns(self):
        allowed, warn, path = evaluate_ebdg_ui_gate(
            project_root=self.project_root,
            conversation_id="conv-1",
            session_retries=0,
            custom_modified_files=["index.html", "css/styles.css"]
        )
        self.assertFalse(allowed)
        self.assertIsNotNone(warn)
        self.assertIn("EBDG_UI_SCREENSHOT_PENDING", warn)
        self.assertIsNone(path)

        # Verify receipt was written with PENDING_EVIDENCE
        receipt_path = self.project_root / ".gravityguard" / "runtime" / "delivery_receipt.json"
        self.assertTrue(receipt_path.is_file())
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["deliveryStatus"], "PENDING_EVIDENCE")

    def test_ui_file_with_fresh_screenshot_passes(self):
        evidence_dir = self.project_root / ".gravityguard" / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        screenshot = evidence_dir / "verified_layout.png"
        screenshot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 2000)

        allowed, warn, path = evaluate_ebdg_ui_gate(
            project_root=self.project_root,
            conversation_id="conv-1",
            session_retries=0,
            custom_modified_files=["src/components/Header.tsx"]
        )
        self.assertTrue(allowed)
        self.assertIsNone(warn)
        self.assertEqual(path, screenshot)

        # Verify receipt was written with VERIFIED
        receipt_path = self.project_root / ".gravityguard" / "runtime" / "delivery_receipt.json"
        self.assertTrue(receipt_path.is_file())
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["deliveryStatus"], "VERIFIED")
        self.assertEqual(receipt["evidence"]["screenshot"], str(screenshot))

    def test_circuit_breaker_prevents_deadlock(self):
        # When retries reach maxRetries (default 2), it allows completion without deadlock
        allowed, warn, path = evaluate_ebdg_ui_gate(
            project_root=self.project_root,
            conversation_id="conv-1",
            session_retries=2,
            custom_modified_files=["style.css"]
        )
        self.assertTrue(allowed)
        self.assertIsNone(warn)
        self.assertIsNone(path)

        receipt_path = self.project_root / ".gravityguard" / "runtime" / "delivery_receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["deliveryStatus"], "UNVERIFIED_CIRCUIT_BREAKER")

    def test_disabled_by_config(self):
        cfg = {"deliveryGate": {"enabled": False}}
        allowed, warn, path = evaluate_ebdg_ui_gate(
            project_root=self.project_root,
            conversation_id="conv-1",
            session_retries=0,
            cfg=cfg,
            custom_modified_files=["style.css"]
        )
        self.assertTrue(allowed)
        self.assertIsNone(warn)


if __name__ == "__main__":
    unittest.main()
