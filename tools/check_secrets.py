"""Scan staged added text before publication; print redacted findings only."""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from gravityguard_engine.publication_guard import scan_git_secrets

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="", help="Compare a trusted commit SHA or HEAD^ to HEAD")
    args = parser.parse_args()
    findings = scan_git_secrets(Path.cwd(), staged_only=True, require_repo=True, base=args.base)
    for finding in findings:
        print(finding)
    print(f"Secret gate: {'BLOCKED' if findings else 'PASS'}")
    sys.exit(1 if findings else 0)
