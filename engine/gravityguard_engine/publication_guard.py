"""Independent Git added-text secret gate for Stop and pre-commit boundaries."""
import subprocess
import re
from pathlib import Path
from .security_rules import check_g0_secret_leak, is_protected_env_file

MAX_SCAN_BYTES = 16 * 1024 * 1024
_PRIVATE_KEY_FILE = re.compile(r"(?:^|[/\\])(?:id_(?:rsa|dsa|ecdsa|ed25519)|\.aws[/\\]credentials)$", re.I)


def _is_binary_chunk(data: bytes) -> bool:
    """True when the leading chunk contains NUL bytes (actual binary asset/media/model)."""
    return b"\x00" in data[:8192]


def _is_protected_path(path: str) -> bool:
    """Live .env files and private key / cloud credential files must never be published, whatever their content."""
    return is_protected_env_file(path) or bool(_PRIVATE_KEY_FILE.search(path))


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
            proc = git("diff", *extra, "--no-ext-diff", "--no-textconv", "--unified=0", "--")
            if proc.returncode or len(proc.stdout) > MAX_SCAN_BYTES:
                return ["[SECURITY_SCAN_UNAVAILABLE]: Git diff failed or exceeded the scan limit"]
            added = "\n".join(line[1:] for line in proc.stdout.decode("utf-8", "replace").splitlines()
                              if line.startswith("+") and not line.startswith("+++"))
            blocked, reason, _ = check_g0_secret_leak(added)
            if blocked:
                findings.append(f"[G0_SECRET_LEAK]: Git added-text scan: {reason}")
            names = git("diff", *extra, "--name-only", "-z", "--")
            if names.returncode:
                return ["[SECURITY_SCAN_UNAVAILABLE]: Could not list changed files"]
            if any(raw and _is_protected_path(raw.decode("utf-8", "surrogateescape")) for raw in names.stdout.split(b"\0")):
                findings.append("[G0_ENV_PROTECTION]: Git change set includes a protected credential file (.env / private key)")
        if not staged_only and not base:
            proc = git("ls-files", "--others", "--exclude-standard", "-z")
            if proc.returncode:
                return ["[SECURITY_SCAN_UNAVAILABLE]: Could not enumerate untracked files"]
            for raw in proc.stdout.split(b"\0"):
                if not raw:
                    continue
                file = root / raw.decode("utf-8", "surrogateescape")
                if _is_protected_path(raw.decode("utf-8", "surrogateescape")):
                    findings.append("[G0_ENV_PROTECTION]: Untracked file is a protected credential file (.env / private key)")
                    continue
                if file.is_symlink() or not file.is_file():
                    continue
                with file.open("rb") as fh:
                    head = fh.read(8192)
                    if _is_binary_chunk(head):
                        continue
                    if file.stat().st_size > MAX_SCAN_BYTES:
                        return ["[SECURITY_SCAN_UNAVAILABLE]: Untracked file exceeds the scan limit"]
                    raw_bytes = head + fh.read()
                blocked, reason, _ = check_g0_secret_leak(raw_bytes.decode("utf-8", "replace"))
                if blocked:
                    findings.append(f"[G0_SECRET_LEAK]: Untracked-file scan: {reason}")
        return findings
    except (OSError, subprocess.SubprocessError):
        return ["[SECURITY_SCAN_UNAVAILABLE]: Git security scan could not complete"]
