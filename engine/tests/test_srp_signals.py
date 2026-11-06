"""False-positive / false-negative coverage for the SRP engine (srp_python.py, srp_signals.py)."""
import unittest

from gravityguard_engine.srp_python import analyze_python_srp, import_kinds
from gravityguard_engine.srp_signals import analyze_python_responsibility_mix, analyze_ts_responsibility_mix


def _pad(lines: int) -> str:
    return "".join(f"value_{i} = {i}\n" for i in range(lines))


def _big_class(name: str, bases: str = "", decorator: str = "") -> str:
    body = "".join(f"    field_{i}: int = {i}\n" for i in range(30))
    return f"{decorator}class {name}{bases}:\n{body}\n"


class SrpFalsePositiveTests(unittest.TestCase):
    def test_small_gui_downloader_is_not_blocked(self):
        content = "import tkinter\nimport urllib.request\n" + _pad(60)
        self.assertFalse(analyze_python_srp(content, "tools/updater.py")[0])

    def test_big_ui_plus_network_file_is_still_blocked(self):
        content = "import tkinter\nimport httpx\n" + _pad(200)
        violates, reason = analyze_python_srp(content, "src/app.py")
        self.assertTrue(violates)
        self.assertIn("Sorumluluk Çakışması", reason)

    def test_urllib_parse_and_http_status_are_not_network(self):
        self.assertEqual(import_kinds("urllib.parse"), set())
        self.assertEqual(import_kinds("urllib.error"), set())
        self.assertEqual(import_kinds("http", ("HTTPStatus",)), set())
        self.assertEqual(import_kinds("urllib.request"), {"net"})
        self.assertEqual(import_kinds("urllib", ("request",)), {"net"})
        self.assertEqual(import_kinds("http.client"), {"net"})

    def test_package_match_is_not_a_substring_match(self):
        self.assertEqual(import_kinds("awxlib"), set())
        self.assertEqual(import_kinds("mysocketutils"), set())
        self.assertEqual(import_kinds("PyQt5.QtWidgets"), {"ui"})

    def test_parse_only_ui_file_is_not_blocked(self):
        content = "import tkinter\nfrom urllib.parse import quote\n" + _pad(300)
        self.assertFalse(analyze_python_srp(content, "src/view.py")[0])

    def test_data_holders_do_not_count_as_god_module(self):
        content = "\n".join([
            "from dataclasses import dataclass",
            "from typing import NamedTuple, TypedDict, Protocol",
            "from enum import Flag",
            _big_class("A", decorator="@dataclass(frozen=True)\n"),
            _big_class("B", "(NamedTuple)"),
            _big_class("C", "(TypedDict)"),
            _big_class("D", "(Protocol[int])"),
            _big_class("E", "(Flag)"),
        ])
        self.assertFalse(analyze_python_srp(content, "src/shapes.py")[0])

    def test_tiny_helper_classes_do_not_count(self):
        content = "\n".join(f"class Helper{i}:\n    def run(self):\n        return {i}\n" for i in range(8))
        self.assertFalse(analyze_python_srp(content, "src/helpers.py")[0])

    def test_four_real_classes_are_still_a_god_module(self):
        content = "\n".join(_big_class(f"Service{i}") for i in range(4))
        violates, reason = analyze_python_srp(content, "src/services.py")
        self.assertTrue(violates)
        self.assertIn("God Module", reason)

    def test_test_files_are_exempt(self):
        content = "\n".join(_big_class(f"Case{i}") for i in range(6))
        self.assertFalse(analyze_python_srp(content, "tests/test_things.py")[0])
        self.assertFalse(analyze_python_srp(content, "conftest.py")[0])


class SrpFalseNegativeTests(unittest.TestCase):
    def _procedural(self, loc: int) -> str:
        head = "import sqlite3\nimport requests\nimport shutil\n"
        return head + _pad(loc)

    def test_classless_procedural_monolith_with_three_concerns_warns(self):
        src = self._procedural(500) + "def go():\n    sqlite3.connect('x')\n    requests.get('u')\n    shutil.copy('a', 'b')\n"
        self.assertFalse(analyze_python_srp(src, "src/job.py")[0])  # blocking check cannot see it
        msgs = analyze_python_responsibility_mix(src, "src/job.py")
        self.assertTrue(any("Karışık Sorumluluk" in m and "db" in m and "net" in m and "fs" in m for m in msgs))

    def test_sql_strings_and_open_count_as_concerns_in_a_very_large_file(self):
        src = "def load():\n    with open('f') as fh:\n        fh.read()\n    return 'SELECT id FROM users'\n" + _pad(800)
        self.assertTrue(analyze_python_responsibility_mix(src, "src/load.py"))

    def test_giant_function_mixing_concerns_warns(self):
        body = "".join(f"    x{i} = {i}\n" for i in range(130))
        src = "import sqlite3\nimport requests\n\ndef sync():\n    sqlite3.connect('x')\n    requests.get('u')\n" + body
        msgs = analyze_python_responsibility_mix(src, "src/sync.py")
        self.assertTrue(any("Dev İşlev" in m and "sync" in m for m in msgs))

    def test_small_or_single_concern_files_stay_quiet(self):
        self.assertEqual(analyze_python_responsibility_mix("import sqlite3\nimport requests\nimport shutil\n" + _pad(50), "a.py"), [])
        self.assertEqual(analyze_python_responsibility_mix("import sqlite3\n" + _pad(900), "a.py"), [])

    def test_marker_and_test_files_silence_the_warning(self):
        src = "# srp: allow-monolith\n" + self._procedural(500) + "sqlite3.connect('x')\nrequests.get('u')\nshutil.copy('a','b')\n"
        self.assertEqual(analyze_python_responsibility_mix(src, "src/job.py"), [])
        self.assertEqual(analyze_python_responsibility_mix(src.replace("# srp: allow-monolith\n", ""), "tests/test_job.py"), [])

    def test_ts_service_without_tab_or_card_words_still_warns(self):
        src = ("import fs from 'node:fs';\nimport { Pool } from 'pg';\n"
               + "".join(f"const v{i} = {i};\n" for i in range(450))
               + "export async function sync() { await fetch('u'); }\n")
        msgs = analyze_ts_responsibility_mix(src, "src/service.ts")
        self.assertTrue(any("Karışık Sorumluluk" in m for m in msgs))

    def test_ts_kitchen_sink_module_warns_and_marker_silences(self):
        src = "".join(f"export function f{i}() {{ return {i}; }}\n" for i in range(30)) + _pad(400)
        self.assertTrue(any("Her Şey Bir Arada" in m for m in analyze_ts_responsibility_mix(src, "src/utils.ts")))
        self.assertEqual(analyze_ts_responsibility_mix("// srp: allow-monolith\n" + src, "src/utils.ts"), [])


class WriteSignalsTests(unittest.TestCase):
    def test_collects_mix_and_ratchet_signals_without_writing_the_store(self):
        import os
        import tempfile
        from gravityguard_engine.project_context import DEFAULT_COMPLEXITY_THRESHOLDS
        from gravityguard_engine.write_signals import collect_write_signals
        src = "import sqlite3\nimport requests\nimport shutil\n" + _pad(500) + "sqlite3.connect('x')\nrequests.get('u')\nshutil.copy('a', 'b')\n"
        with tempfile.TemporaryDirectory() as root:
            target = os.path.join(root, "job.py")
            ids = [rid for rid, _ in collect_write_signals(root, target, src, DEFAULT_COMPLEXITY_THRESHOLDS, True, False)]
            self.assertIn("SRP_RESPONSIBILITY_MIX", ids)
            self.assertFalse(os.path.exists(os.path.join(root, ".gravityguard")))


if __name__ == "__main__":
    unittest.main()
