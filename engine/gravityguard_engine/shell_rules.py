"""Shared command-text checks; intentionally not a shell interpreter or sandbox."""
import fnmatch
import re
from .security_rules import check_g0_secret_leak, is_protected_env_file
from .shell_danger import dangerous_command_reason, parse_command

_SEGMENTS = re.compile(r"[;&|\n(`]+")
_ENV = re.compile(r"(?<![\w.-])(?:[^\s\"';&|]*[/\\])?\.env(?:\.[\w-]+)?(?![\w.-])", re.I)
# Private credential stores (SSH keys, cloud/CLI tokens). `.pub` files are public and stay readable.
_CREDENTIAL = re.compile(
    r"(?<![\w.-])(?:[^\s\"';&|]*[/\\])?(?:\.ssh[/\\]id_(?:rsa|dsa|ecdsa|ed25519)|\.aws[/\\]credentials"
    r"|\.gnupg[/\\]private-keys[^\s\"';&|]*|\.docker[/\\]config\.json|\.kube[/\\]config|\.config[/\\]gh[/\\]hosts\.yml)(?![\w.-])",
    re.I,
)

# Destructive / remote-code detection lives in shell_danger.py (token based, linear time). Only high-confidence
# patterns are blocked: routine commands (`rm -rf node_modules`, `curl -o file`, `chmod 755 x`) must never match.


# Verbs that print or copy a file's content (lower-case command words as `parse_command` returns them).
_BASE_READERS = frozenset({
    "cat", "type", "less", "more", "head", "tail", "grep", "rg", "sed", "awk", "cp", "copy", "xxd", "base64", "source",
    "get-content", "gc", "select-string", "sls", "copy-item", "cpi", "import-csv", "findstr", ".",
})
# More verbs that print, copy or ship content; an input redirect (`tr a b < .env`) counts as a read too.
_EXTRA_READERS = frozenset({
    "sort", "cut", "tr", "paste", "nl", "od", "strings", "bat", "dd", "tac", "rev", "fold", "column", "jq", "yq",
    "scp", "rsync", "tar", "zip", "7z", "curl", "wget", "nc", "ncat",
})
_REDIRECT_IN = re.compile(r"<\s*([^\s<>|;&]+)")
_GLOB_CHARS = frozenset("*?[")


def _names_protected_file(token: str) -> str:
    """'env' or 'credential' when a command argument is (or can glob-expand to) a protected file, else ''."""
    base = token.strip("\"'").lstrip("@").replace("\\", "/").rsplit("/", 1)[-1]
    if _GLOB_CHARS & set(base):
        return "env" if fnmatch.fnmatchcase(".env", base) else ""
    if any(is_protected_env_file(match.group(0)) for match in _ENV.finditer(token)):
        return "env"
    return "credential" if _CREDENTIAL.search(token) else ""


def _protected_read_reason(segment: str) -> str:
    """Denial for one command segment that reads a live .env / private credential file, '' otherwise."""
    kinds = [_names_protected_file(m.group(1)) for m in _REDIRECT_IN.finditer(segment)]
    parsed = parse_command(segment)  # skips wrappers such as `sudo -u root`
    if parsed and parsed[0] in _BASE_READERS | _EXTRA_READERS:
        kinds += [_names_protected_file(token) for token in parsed[1]]
    if "env" in kinds:
        return "[G0_ENV_PROTECTION]: Shell access to a live .env file is denied"
    if "credential" in kinds:
        return "[G0_CREDENTIAL_PROTECTION]: Shell access to a private credential file is denied"
    return ""


def command_text(args: dict):
    if not isinstance(args, dict):
        return None
    for key in ("command", "CommandLine", "cmd", "script"):
        if key in args:
            return args[key] if isinstance(args[key], str) else ""
    return None


def check_shell_command(args: dict) -> str:
    command = command_text(args)
    if command is None:
        return ""
    blocked, reason, _ = check_g0_secret_leak(command)
    if blocked:
        return f"[G0_SECRET_LEAK]: {reason}"
    danger = dangerous_command_reason(command)
    if danger:
        return f"[G0_DANGEROUS_COMMAND]: Blocked {danger}"
    for segment in _SEGMENTS.split(command):
        reason = _protected_read_reason(segment)
        if reason:
            return reason
    return ""
