"""Local user path gate: real user names are caught, placeholders and system accounts pass."""
import unittest

from gravityguard_engine.local_paths import check_local_paths, find_local_paths, is_allowed

BLOCK = {"mode": "block", "allow": []}


class LocalPathTests(unittest.TestCase):
    def test_detects_windows_unix_and_escaped_paths(self):
        for text in ("C:\\Users\\Halil Emre\\Desktop\\x", "c:/Users/Halil Emre/Desktop", "C:\\\\Users\\\\ali\\\\proje",
                     "cd /Users/ayse/proje", "ls /home/mehmet/.config"):
            self.assertTrue(find_local_paths(text), text)

    def test_placeholders_and_system_accounts_pass(self):
        for text in ("C:\\Users\\<kullanici>\\x", "C:\\Users\\%USERNAME%\\x", "C:\\Users\\Public\\Documents", "/home/runner/work",
                     "/Users/<name>/x", "C:\\Users\\${USER}\\x", "~/Desktop", "src/users/list.ts", "https://example.com/Users/"):
            self.assertEqual(find_local_paths(text), [], text)

    def test_finding_does_not_leak_rest_of_path(self):
        msg = check_local_paths("a.md", "C:\\Users\\Halil Emre\\Desktop\\gizli\\x", BLOCK)
        self.assertEqual(len(msg), 1)
        self.assertNotIn("gizli", msg[0])

    def test_allow_list_and_modes(self):
        self.assertTrue(is_allowed("test\\a.ts", ["test/**"]))
        self.assertEqual(check_local_paths("test/a.ts", "C:\\Users\\ali\\x", {"mode": "block", "allow": ["test/**"]}), [])
        self.assertEqual(check_local_paths("a.md", "C:\\Users\\ali\\x", {"mode": "off", "allow": []}), [])


if __name__ == "__main__":
    unittest.main()
