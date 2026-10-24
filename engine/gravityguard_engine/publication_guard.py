"""Independent Git added-text secret gate for Stop and pre-commit boundaries."""
import subprocess
import re
from pathlib import Path
from .security_rules import check_g0_secret_leak

MAX_SCAN_BYTES = 4 * 1024 * 1024


def scan_git_secrets(root: Path, staged_only: bool = False, require_repo: bool = False, base: str = "") -> list:
    """Return redacted findings; never place diff/file contents in diagnostics."""
    def git(*args):
        return subprocess.run(["git", *args], cwd=str(root), capture_output=True, timeout=10)

    try:
        probe = git("rev-parse", "--is-inside-work-tree")
        if probe.returncode != 0:
            return ["[SECURITY_SCAN_UNAVAILABLE]: Not a Git worktree"] if require_repo else []
        findings = []
        if base and not re.fullmatch(r"(?:[a-fA-F0-9]{40}|HEAD\^)", base):
            return ["[SECURITY_SCAN_UNAVAILABLE]: Invalid base revision"]
        switches = [(base, "HEAD")] if base else [("--cached",)] if staged_only else [("--cached",), ()]
        for extra in switches:
            proc = git("diff", *extra, "--no-ext-diff", "--no-textconv", "--text", "--unified=0", "--")
            if proc.returncode or len(proc.stdout) > MAX_SCAN_BYTES:
                return ["[SECURITY_SCAN_UNAVAILABLE]: Git diff failed or exceeded the scan limit"]
            added = "\n".join(line[1:] for line in proc.stdout.decode("utf-8", "replace").splitlines()
                              if line.startswith("+") and not line.startswith("+++"))
            blocked, reason, _ = check_g0_secret_leak(added)
            if blocked:
                findings.append(f"[G0_SECRET_LEAK]: Git added-text scan: {reason}")
        if not staged_only and not base:
            proc = git("ls-files", "--others", "--exclude-standard", "-z")
            if proc.returncode:
                return ["[SECURITY_SCAN_UNAVAILABLE]: Could not enumerate untracked files"]
            for raw in proc.stdout.split(b"\0"):
                if not raw:
                    continue
                file = root / raw.decode("utf-8", "surrogateescape")
                if file.is_symlink() or not file.is_file():
                    continue
                if file.stat().st_size > MAX_SCAN_BYTES:
                    return ["[SECURITY_SCAN_UNAVAILABLE]: Untracked file exceeds the scan limit"]
                blocked, reason, _ = check_g0_secret_leak(file.read_bytes().decode("utf-8", "replace"))
                if blocked:
                    findings.append(f"[G0_SECRET_LEAK]: Untracked-file scan: {reason}")
        return findings
    except (OSError, subprocess.SubprocessError):
        return ["[SECURITY_SCAN_UNAVAILABLE]: Git security scan could not complete"]
