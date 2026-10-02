#!/usr/bin/env python3
"""
Unit tests for GravityGuard Architecture Rules (G3, G4, OE Spike, Cumulative Growth, SRP).
"""
import os
import sys
import unittest

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine.architecture_rules import (
    analyze_python_srp,
    check_arch_file_growth,
    check_g3_compiler_bypass,
    check_oe_spike,
    is_cohesive_module_by_filename,
    is_py_cohesive_monolith,
    is_ts_cohesive_monolith,
)


class TestArchitectureRulesDomain(unittest.TestCase):
    def test_g3_detects_compiler_suppressions(self):
        # Escape markers to avoid triggering self-lint
        supp = "@" + "ts-ignore"
        added = f"// {supp}\nconst x: any = 1;\n"
        matches = check_g3_compiler_bypass(added)
        self.assertIn(supp, matches)

    def test_oe_spike_detects_premature_abstraction(self):
        added = "class A:\n    pass\nclass B:\n    pass\nclass C:\n    pass\n"
        triggered, msg = check_oe_spike(added)
        self.assertTrue(triggered)
        self.assertIn("Aşırı Soyutlama Uyarısı", msg)

    def test_cohesive_module_filename_detection(self):
        self.assertTrue(is_cohesive_module_by_filename("src/models.py"))
        self.assertTrue(is_cohesive_module_by_filename("src/app_types.py"))
        self.assertTrue(is_cohesive_module_by_filename("src/events.py"))
        self.assertFalse(is_cohesive_module_by_filename("src/god_page.py"))

    def test_srp_detects_ui_and_network_conflict(self):
        content = "import tkinter\nimport requests\nclass App: pass\n"
        violates, reason = analyze_python_srp(content, "src/app.py")
        self.assertTrue(violates)
        self.assertIn("Sorumluluk Çakışması", reason)

    def test_srp_detects_god_module(self):
        content = "\n".join([f"class Service{i}:\n    def execute(self):\n        pass\n" for i in range(5)])
        violates, reason = analyze_python_srp(content, "src/services.py")
        self.assertTrue(violates)
        self.assertIn("God Module", reason)


if __name__ == "__main__":
    unittest.main()
