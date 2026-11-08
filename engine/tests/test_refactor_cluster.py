"""Refactor hint clusters: prefix groups, helper absorption, import templates, circular-import warning, class split."""
import unittest

from gravityguard_engine.refactor_hint import build_refactor_hint

_BODY = "    x = 1\n" * 20


def _func(name: str, call: str = "pass") -> str:
    return f"def {name}(s):\n    {call}\n{_BODY}"


class PythonClusterTests(unittest.TestCase):
    def test_prefix_group_with_private_helper_gets_import_line(self):
        src = "import re\n" + _func("parse_a", "re.sub('a', 'b', s)") + _func("parse_b", "_parse_x(s)") + _func("_parse_x") + _func("main", "parse_a(1)")
        hint = build_refactor_hint(src, "src/foo.py")
        self.assertIn("'parse_a', 'parse_b', '_parse_x'", hint)
        self.assertIn("'src/foo_parse.py'", hint)
        self.assertIn("`from .foo_parse import parse_a, parse_b`", hint)
        self.assertIn("`import re`", hint)
        self.assertNotIn("Döngüsel", hint)
        self.assertNotIn("'main', ", hint)

    def test_helper_used_outside_cluster_is_not_absorbed_but_exported_when_needed(self):
        src = _func("parse_a", "_shared(s)") + _func("parse_b", "_shared(s)") + _func("_shared") + _func("main", "_shared(1)")
        hint = build_refactor_hint(src, "foo.py")
        self.assertIn("`from .foo_parse import parse_a, parse_b`", hint)
        self.assertIn("Döngüsel import uyarısı: bu işlevler dosyada kalan '_shared'", hint)

    def test_remaining_module_names_trigger_circular_warning(self):
        src = "LIMIT = 3\n" + _func("load_a", "LIMIT") + _func("load_b", "LIMIT")
        hint = build_refactor_hint(src, "pkg/mod.py")
        self.assertIn("Döngüsel import uyarısı", hint)
        self.assertIn("'LIMIT'", hint)
        self.assertIn("'mod' dosyasını geri import etmesin", hint)

    def test_public_function_with_exclusive_helpers_forms_cluster(self):
        src = _func("build_report", "_fmt(s)") + _func("_fmt", "_pad(s)") + _func("_pad") + _func("other")
        hint = build_refactor_hint(src, "r.py")
        self.assertIn("'build_report', '_fmt', '_pad'", hint)
        self.assertIn("`from .r_build_report import build_report`", hint)

    def test_small_cluster_falls_back_to_single_unit_hint(self):
        src = "def parse_a():\n    pass\ndef parse_b():\n    pass\n" + _func("big_one")
        hint = build_refactor_hint(src, "a.py")
        self.assertNotIn("birlikte", hint)
        self.assertIn("'big_one' işlevini", hint)

    def test_giant_class_gets_mixin_split_with_template(self):
        methods = "".join(f"    def {n}(self):\n        return os.getcwd()\n" + "        y = 1\n" * 18 for n in ("load_a", "load_b", "load_c"))
        src = "import os\nclass Store:\n" + methods + "    def save(self):\n        pass\n"
        hint = build_refactor_hint(src, "src/store.py")
        self.assertIn("'Store' sınıfı", hint)
        self.assertIn("'StoreLoadMixin'", hint)
        self.assertIn("class Store(StoreLoadMixin):", hint)
        self.assertIn("`from .store_store_load import StoreLoadMixin`", hint)
        self.assertIn("`import os`", hint)
        self.assertNotIn("'Store' sınıfını", hint)

    def test_giant_class_without_prefix_groups_suggests_helper_functions(self):
        methods = "".join(f"    def {n}(self):\n" + "        y = 1\n" * 16 for n in ("alpha", "beta", "gamma", "delta"))
        hint = build_refactor_hint("class Big:\n" + methods, "big.py")
        self.assertIn("modül işlevlerine taşıyın", hint)
        self.assertIn("from .big_big_helpers import", hint)


class BlockLanguageClusterTests(unittest.TestCase):
    def test_typescript_prefix_cluster_has_import_template_and_deps(self):
        def fn(n):
            return f"export function {n}() {{\n" + "  fs.x(LIMIT);\n" * 16 + "}\n"

        src = "import { fs } from 'fs';\nconst LIMIT = 3;\n" + fn("parseA") + fn("parseB") + fn("render")
        hint = build_refactor_hint(src, "src/p.ts")
        self.assertIn("'parseA', 'parseB'", hint)
        self.assertIn("`import { parseA, parseB } from './p_parse';`", hint)
        self.assertIn("`import { fs } from 'fs';`", hint)
        self.assertIn("'LIMIT'", hint)

    def test_go_cluster_has_no_import_template(self):
        def fn(n):
            return f"func {n}() {{\n" + "\tx++\n" * 16 + "}\n"

        hint = build_refactor_hint(fn("parseA") + fn("parseB"), "svc/p.go")
        self.assertIn("birlikte 'svc/p_parse.go'", hint)
        self.assertNotIn("import", hint)


if __name__ == "__main__":
    unittest.main()
