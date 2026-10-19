#!/usr/bin/env python3
"""
Unit tests for GravityGuard Architecture Rules (G3, G4, OE Spike, Cumulative Growth, SRP).
"""
import os
import io
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine.architecture_rules import (
    analyze_python_srp,
    check_arch_file_growth,
    check_design_icon_rule,
    check_g3_compiler_bypass,
    check_oe_spike,
    check_pma_horizontal,
    check_pma_imports,
    is_cohesive_module_by_filename,
    is_pma_exempt,
    is_py_cohesive_monolith,
    is_ts_cohesive_monolith,
)


class TestDesignIconRule(unittest.TestCase):
    def test_detects_icons_in_all_supported_source_files(self):
        icons = ['🔍', '📋', '⚡', '⏳', '✔', '✅', '🗑', '🚀', '💡']
        for extension in ('.ts', '.tsx', '.js', '.jsx', '.html', '.vue', '.svelte', '.css', '.py'):
            with self.subTest(extension=extension):
                self.assertEqual(check_design_icon_rule('src/button' + extension, ' '.join(icons)), icons)

    def test_excludes_documentation_data_and_tests(self):
        for path in ('README.md', 'config.json', 'docs/demo.ts', 'documentation/demo.py',
                     'doc/demo.html', 'test_button.py', 'button.test.ts', 'button.spec.ts',
                     'spec.js', 'tests/button.ts', r'C:\app\tests\button.py', '__tests__/button.ts'):
            with self.subTest(path=path):
                self.assertEqual(check_design_icon_rule(path, '✅'), [])

    def test_empty_plain_text_and_duplicate_icons(self):
        self.assertEqual(check_design_icon_rule('src/button.ts', ''), [])
        self.assertEqual(check_design_icon_rule('src/button.ts', 'const label = "Kaydet";'), [])
        self.assertEqual(check_design_icon_rule('src/button.ts', '✅ ✅ 🗑️'), ['✅', '🗑️'])

    def test_dispatcher_allows_write_and_emits_warning(self):
        from gravityguard_engine import dispatcher

        with tempfile.TemporaryDirectory() as directory:
            for extension in ('.ts', '.css'):
                target = str(Path(directory) / ('button' + extension))
                payload = {'toolCall': {'name': 'write_to_file', 'args': {'TargetFile': target}}}
                output = io.StringIO()
                with self.subTest(extension=extension), ExitStack() as stack:
                    stack.enter_context(patch('sys.stdin', io.StringIO(json.dumps(payload))))
                    stack.enter_context(patch('sys.stdout', output))
                    stack.enter_context(patch('sys.argv', ['gravityguard']))
                    stack.enter_context(patch.object(dispatcher, 'resolve_project_root', return_value=Path(directory)))
                    stack.enter_context(patch.object(dispatcher, 'load_gravityguard_config', return_value={}))
                    stack.enter_context(patch.object(dispatcher, 'get_projected_and_old_content', return_value=('', 'const label = "✅";')))
                    for name in ('reconcile_obligations_on_disk', 'record_review_obligation',
                                 'record_pending_doc_obligation', 'trigger_background_validation'):
                        stack.enter_context(patch.object(dispatcher, name))
                    stack.enter_context(patch.object(dispatcher, 'evaluate_test_evidence', return_value=([], {})))
                    stack.enter_context(patch.object(dispatcher, 'read_recent_diagnostics', return_value=[]))
                    log = stack.enter_context(patch.object(dispatcher, 'log_event'))
                    with self.assertRaises(SystemExit) as result:
                        dispatcher.validate_gravityguard()
                    self.assertEqual(result.exception.code, 0)
                    response = json.loads(output.getvalue())
                    self.assertEqual(response['decision'], 'allow')
                    message = 'Tasarım kuralına uymuyor hemen düzelt: kodda standart emoji/ikon kullanımı tespit edildi (✅).'
                    self.assertIn('[DESIGN_ICON_RULE] ' + message, response['reason'])
                    log.assert_any_call('write_to_file', 'WARNING', target, message,
                                        rule_id='DESIGN_ICON_RULE', conversation_id='default')


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


class TestPmaBoundaryDetector(unittest.TestCase):
    SHOP = "C:\\work\\shop\\src"

    def _imp(self, rel_path, text):
        return check_pma_imports(f"{self.SHOP}\\{rel_path}", text)

    # --- A) ARCH_PMA_HORIZONTAL_DENY ---
    def test_horizontal_layers_are_blocked(self):
        for layer in ("controllers", "services", "repositories", "managers"):
            violated, msg = check_pma_horizontal(f"/work/shop/src/{layer}/user.ts")
            self.assertTrue(violated, layer)
            self.assertIn("Hop hemşerim!", msg)
            self.assertIn("src/features/<ozellik>/", msg)
            self.assertIn("ARCH_PMA_HORIZONTAL_DENY", msg)

    def test_horizontal_blocks_windows_paths_and_index_files(self):
        self.assertTrue(check_pma_horizontal("C:\\work\\shop\\src\\Services\\index.ts")[0])
        self.assertTrue(check_pma_horizontal("/work/shop/src/services/index.ts")[0])
        self.assertTrue(check_pma_horizontal("/work/shop/src/controllers/main.ts")[0])

    def test_horizontal_allows_vertical_slices_and_other_trees(self):
        self.assertFalse(check_pma_horizontal("/work/shop/src/features/auth/login.ts")[0])
        self.assertFalse(check_pma_horizontal("/work/shop/src/core/engine.ts")[0])
        self.assertFalse(check_pma_horizontal("/work/shop/src/shared/button.ts")[0])
        self.assertFalse(check_pma_horizontal("/work/shop/lib/services/legacy.ts")[0])
        self.assertFalse(check_pma_horizontal("/work/shop/src/features/auth/services.ts")[0])

    def test_horizontal_exempts_tests_and_gravityguard_repo(self):
        self.assertFalse(check_pma_horizontal("/work/shop/src/services/user.test.ts")[0])
        self.assertFalse(check_pma_horizontal("/work/shop/src/services/user.spec.ts")[0])
        self.assertFalse(check_pma_horizontal("/work/shop/src/services/test_user.py")[0])
        self.assertFalse(check_pma_horizontal("/work/shop/tests/src/services/x.py")[0])
        self.assertFalse(check_pma_horizontal("/work/shop/src/services/user.test.mjs")[0])
        self.assertFalse(check_pma_horizontal("C:\\Users\\Halil Emre\\GitHub\\GravityGuard\\src\\services\\x.ts")[0])
        self.assertFalse(check_pma_horizontal("/work/shop/node_modules/pkg/src/services/x.js")[0])

    # --- B) ARCH_PMA_DEEP_IMPORT ---
    def test_deep_import_alias_is_blocked(self):
        violated, rule, msg = self._imp("features\\cart\\cart.ts", "import { s } from '@/features/auth/internal/secret';\n")
        self.assertTrue(violated)
        self.assertEqual(rule, "ARCH_PMA_DEEP_IMPORT")
        self.assertIn("features/auth", msg)

    def test_deep_import_relative_is_blocked(self):
        text = "import { Sub } from '../auth/components/Sub';\n"
        violated, rule, _ = self._imp("features/cart/ui/CartView.tsx", text.replace("../auth", "../../auth"))
        self.assertTrue(violated)
        self.assertEqual(rule, "ARCH_PMA_DEEP_IMPORT")
        violated, rule, _ = self._imp("features/cart/cart.ts", text)
        self.assertTrue(violated)

    def test_deep_import_python_and_require_and_dynamic(self):
        self.assertEqual(self._imp("features/cart/a.py", "from features.auth.internal.secret import x\n")[1], "ARCH_PMA_DEEP_IMPORT")
        self.assertEqual(self._imp("features/cart/a.py", "from src.features.auth.internal import x\n")[1], "ARCH_PMA_DEEP_IMPORT")
        self.assertEqual(self._imp("features/cart/a.py", "from ..auth.internal import x\n")[1], "ARCH_PMA_DEEP_IMPORT")
        self.assertEqual(self._imp("features/cart/a.js", "const s = require('@/features/auth/internal/secret');\n")[1], "ARCH_PMA_DEEP_IMPORT")
        self.assertEqual(self._imp("features/cart/a.ts", "const m = await import('features/auth/internal/secret');\n")[1], "ARCH_PMA_DEEP_IMPORT")
        self.assertEqual(self._imp("features/cart/a.ts", "export * from '@/features/auth/internal/secret';\n")[1], "ARCH_PMA_DEEP_IMPORT")

    def test_public_api_and_own_slice_are_allowed(self):
        for text in (
            "import { login } from '@/features/auth';\n",
            "import { login } from '@/features/auth/index';\n",
            "import { login } from '../auth';\n",
            "import { login } from '../auth/index.ts';\n",
            "import { own } from './internal/own';\n",
            "import { own } from '@/features/cart/internal/own';\n",
            "import React from 'react';\n",
            "import x from 'some-lib/features/auth/internal';\n",
        ):
            self.assertFalse(self._imp("features/cart/cart.ts", text)[0], text)
        self.assertFalse(self._imp("features/cart/a.py", "from features.auth import login\n")[0])

    # --- C) ARCH_PMA_CORE_PURITY ---
    def test_core_purity(self):
        for text in (
            "import { x } from '@/features/auth';\n",
            "import { x } from '../features/auth/index';\n",
            "import { x } from '@/pipelines/logging';\n",
            "import { Button } from '@/shared/ui/Button';\n",
            "from features.auth import login\n",
        ):
            violated, rule, _ = self._imp("core/engine.ts", text)
            self.assertTrue(violated, text)
            self.assertEqual(rule, "ARCH_PMA_CORE_PURITY")
        self.assertFalse(self._imp("core/engine.ts", "import { u } from '@/shared/utils/format';\n")[0])
        self.assertFalse(self._imp("core/engine.ts", "import { h } from './helpers';\nimport fs from 'fs';\n")[0])

    # --- D) ARCH_PMA_SHARED_PURITY ---
    def test_shared_purity(self):
        violated, rule, _ = self._imp("shared/ui/Button.tsx", "import { u } from '@/features/auth';\n")
        self.assertTrue(violated)
        self.assertEqual(rule, "ARCH_PMA_SHARED_PURITY")
        self.assertTrue(self._imp("shared/util.ts", "import { u } from '../features/auth/index';\n")[0])
        self.assertFalse(self._imp("shared/ui/Button.tsx", "import { c } from '@/core/engine';\n")[0])
        self.assertFalse(self._imp("shared/ui/Button.tsx", "import { c } from './Icon';\n")[0])

    # --- exemptions ---
    def test_composition_roots_are_exempt(self):
        text = "import { a } from '@/features/auth/internal/secret';\n"
        for rel in ("core/index.ts", "shared/index.ts", "features/cart/index.ts", "core/main.ts", "shared/App.tsx"):
            self.assertFalse(self._imp(rel, text)[0], rel)

    def test_tests_and_gravityguard_repo_are_exempt_from_imports(self):
        text = "import { a } from '@/features/auth/internal/secret';\n"
        self.assertFalse(self._imp("features/cart/cart.test.ts", text)[0])
        self.assertFalse(self._imp("features/cart/cart.spec.ts", text)[0])
        self.assertFalse(self._imp("features/cart/test_cart.py", text)[0])
        self.assertFalse(check_pma_imports("/work/shop/tests/src/features/cart/a.ts", text)[0])
        self.assertFalse(check_pma_imports("C:\\Users\\Halil Emre\\GitHub\\GravityGuard\\src\\core\\a.ts", "import x from '@/features/a/b';\n")[0])

    def test_files_outside_pma_layers_and_empty_text_are_ignored(self):
        text = "import { a } from '@/features/auth/internal/secret';\n"
        self.assertFalse(check_pma_imports("/work/shop/src/pipelines/log.ts", text)[0])
        self.assertFalse(check_pma_imports("/work/shop/src/other/a.ts", text)[0])
        self.assertFalse(check_pma_imports("/work/shop/src/core/a.ts", "   \n")[0])
        self.assertFalse(check_pma_horizontal("")[0])
        self.assertTrue(is_pma_exempt(""))

    def test_dispatcher_wires_pma_guard(self):
        src = open(os.path.join(_ENGINE_DIR, "gravityguard_engine", "dispatcher.py"), encoding="utf-8").read()
        self.assertIn("check_pma_horizontal(target_file)", src)
        self.assertIn("check_pma_imports(target_file, added_text)", src)
        self.assertIn("ARCH_PMA_HORIZONTAL_DENY", src)


if __name__ == "__main__":
    unittest.main()
