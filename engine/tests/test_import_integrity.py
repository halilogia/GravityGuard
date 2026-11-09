#!/usr/bin/env python3
"""Every name imported from a sibling engine module must exist there.

Module splits left `from .x import name` lines pointing at names that no longer
existed. Because those imports are often inside functions, the hook crashed only
at run time (184 crashes on 2026-11-06, 89 on 2026-11-09).
"""
import ast
import importlib
import os
import sys
import unittest
from pathlib import Path

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

_PKG_DIR = Path(_ENGINE_DIR) / "gravityguard_engine"
_PKG = "gravityguard_engine"


def _target_module(node: ast.ImportFrom, current: str) -> str | None:
    if node.level == 0:
        return node.module if node.module and node.module.split(".")[0] == _PKG else None
    base = current.split(".")[: -node.level] if node.level else current.split(".")
    return ".".join(base + ([node.module] if node.module else []))


class ImportIntegrityTests(unittest.TestCase):
    def test_every_engine_module_imports(self):
        for path in sorted(_PKG_DIR.glob("*.py")):
            name = f"{_PKG}.{path.stem}" if path.stem != "__init__" else _PKG
            with self.subTest(module=name):
                self.assertEqual(importlib.import_module(name).__name__, name)

    def test_imported_names_exist_in_sibling_modules(self):
        problems = []
        for path in sorted(_PKG_DIR.glob("*.py")):
            current = f"{_PKG}.{path.stem}"
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                target = _target_module(node, current)
                if not target:
                    continue
                try:
                    mod = importlib.import_module(target)
                except ImportError as exc:
                    problems.append(f"{path.name}:{node.lineno} cannot import {target}: {exc}")
                    continue
                for alias in node.names:
                    if alias.name == "*" or hasattr(mod, alias.name):
                        continue
                    try:
                        importlib.import_module(f"{target}.{alias.name}")
                    except ImportError:
                        problems.append(f"{path.name}:{node.lineno} {target} has no name '{alias.name}'")
        self.assertEqual(problems, [], "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
