#!/usr/bin/env python3
"""Warn-only unsafe code construct detection (TLS off, shell=True, SQL string building, innerHTML, deserialization)."""
import os
import sys
import unittest

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine.security_rules import check_unsafe_code_patterns


class UnsafeCodePatterns(unittest.TestCase):
    FLAGGED = (
        ("requests.get(url, verify=False)", "TLS"),
        ("const agent = new https.Agent({ rejectUnauthorized: false })", "TLS"),
        ("subprocess.run(cmd, shell=True)", "shell=True"),
        ('os.system(f"rm {name}")', "os.system"),
        ('os.popen("ls " + user_dir)', "os.system"),
        ("exec(base64.b64decode(blob))", "eval/exec"),
        ("eval(input())", "eval/exec"),
        ('cur.execute(f"SELECT * FROM t WHERE id = {uid}")', "SQL"),
        ('cur.execute("SELECT * FROM t WHERE id = %s" % uid)', "SQL"),
        ("el.innerHTML = userComment", "innerHTML"),
        ("el.innerHTML += userComment", "innerHTML"),
        ('res.setHeader("Access-Control-Allow-Origin", "*")', "CORS"),
        ("obj = pickle.loads(data)", "deserialization"),
        ("cfg = yaml.load(stream)", "deserialization"),
        ("digest = hashlib.md5(password.encode())", "özet"),
    )
    CLEAN = (
        "requests.get(url, verify=True, timeout=5)",
        "subprocess.run(['git', 'status'], check=True)",
        'cur.execute("SELECT * FROM t WHERE id = %s", (uid,))',
        "el.textContent = userComment",
        "if (a.innerHTML == b.innerHTML) {}",
        "cfg = yaml.safe_load(stream)",
        "cfg = yaml.load(stream, Loader=yaml.SafeLoader)",
        "digest = hashlib.sha256(payload).hexdigest()",
        "os.system('clear')",
    )

    def test_flags_risky_constructs(self):
        for code, hint in self.FLAGGED:
            with self.subTest(code=code):
                found = check_unsafe_code_patterns(code)
                self.assertTrue(found, code)
                self.assertTrue(any(hint.lower() in label.lower() for label in found), (code, found))

    def test_clean_code_is_not_flagged(self):
        for code in self.CLEAN:
            with self.subTest(code=code):
                self.assertEqual(check_unsafe_code_patterns(code), [], code)

    def test_labels_are_deduplicated(self):
        found = check_unsafe_code_patterns("a(verify=False)\nb(verify=False)\nc(shell=True)")
        self.assertEqual(len(found), 2)


if __name__ == "__main__":
    unittest.main()
