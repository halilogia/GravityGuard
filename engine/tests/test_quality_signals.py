import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gravityguard_engine.quality_signals import (
    check_single_implementation,
    find_evasion_markers,
    oe_single_impl_mode,
)


class EvasionMarkerTests(unittest.TestCase):
    def test_detects_suppression_markers(self):
        text = "x = f()  # type: ignore\n// eslint-disable-next-line\ncatch (e) { void e; }\n"
        self.assertEqual(find_evasion_markers(text), ["type-ignore", "eslint-disable", "discarded-error"])

    def test_real_fix_has_no_markers(self):
        self.assertEqual(find_evasion_markers("except ValueError as e:\n    logger.error(e)\n    raise\n"), [])

    def test_empty(self):
        self.assertEqual(find_evasion_markers(""), [])


class SingleImplementationTests(unittest.TestCase):
    def test_ts_interface_with_one_implementer(self):
        text = "interface Store { get(): string }\nclass FileStore implements Store {\n get() { return '' }\n}\n"
        hit, msg = check_single_implementation(text, is_python=False)
        self.assertTrue(hit)
        self.assertIn("Store", msg)

    def test_ts_interface_with_two_implementers(self):
        text = ("interface Store { get(): string }\nclass A implements Store {\n}\n"
                "class B implements Store {\n}\n")
        self.assertFalse(check_single_implementation(text, is_python=False)[0])

    def test_ts_type_only_interface_is_not_flagged(self):
        self.assertFalse(check_single_implementation("interface Props { id: string }\n", is_python=False)[0])

    def test_python_abc_with_one_subclass(self):
        text = "class Repo(ABC):\n    pass\n\nclass SqlRepo(Repo):\n    pass\n"
        self.assertTrue(check_single_implementation(text, is_python=True)[0])

    def test_python_protocol_with_two_subclasses(self):
        text = "class Repo(Protocol):\n    pass\nclass A(Repo):\n    pass\nclass B(Repo):\n    pass\n"
        self.assertFalse(check_single_implementation(text, is_python=True)[0])

    def test_mode_defaults_to_shadow(self):
        self.assertEqual(oe_single_impl_mode(None), "shadow")
        self.assertEqual(oe_single_impl_mode({"rules": {"OE_SINGLE_IMPL": {"mode": "warn"}}}), "warn")
        self.assertEqual(oe_single_impl_mode({"rules": {"OE_SINGLE_IMPL": "off"}}), "off")


if __name__ == "__main__":
    unittest.main()
