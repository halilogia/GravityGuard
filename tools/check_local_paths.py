"""Commit gate: block staged ADDED lines that contain a real local user path (C:\\Users\\<name>\\, /Users/<name>/, /home/<name>/).

Policy lives in .gravityguard.json:
  "publication": { "localPaths": "block" | "warn" | "off", "allowLocalPaths": ["test/**"] }
One-off escape: GRAVITYGUARD_ALLOW_LOCAL_PATHS=1 or `git commit --no-verify`.
Findings print the user name only, never the rest of the path.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from gravityguard_engine.local_paths import check_local_paths, load_policy


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def main() -> int:
    policy = load_policy(".")
    if policy["mode"] == "off":
        print("Local path gate: OFF")
        return 0
    findings = []
    for rel in [f for f in git("diff", "--cached", "--name-only", "--diff-filter=ACM").splitlines() if f.strip()]:
        diff = git("diff", "--cached", "-U0", "--no-color", "--no-ext-diff", "--", rel)
        added = "\n".join(l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
        findings += [(rel, m) for m in check_local_paths(rel, added, policy)]
    for rel, msg in findings:
        print(f"[LOCAL_PATH] {rel}: {msg}")
    if findings and policy["mode"] == "block":
        print("Local path gate: BLOCKED (replace with a placeholder, or allow via .gravityguard.json publication.allowLocalPaths)")
        return 1
    print("Local path gate: " + ("WARN" if findings else "PASS"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
