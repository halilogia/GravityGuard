"""Shared command-text checks; intentionally not a shell interpreter or sandbox."""
import fnmatch
import re

from .security_rules import check_g0_secret_leak, is_protected_env_file

_SEGMENTS = re.compile(r"[;&|\n(`]+")
_ENV = re.compile(r"(?<![\w.-])(?:[^\s\"';&|]*[/\\])?\.env(?:\.[\w-]+)?(?![\w.-])", re.IGNORECASE)
# Private credential stores (SSH keys, cloud/CLI tokens). `.pub` files are public and stay readable.
_CREDENTIAL = re.compile(
    r"(?<![\w.-])(?:[^\s\"';&|]*[/\\])?(?:\.ssh[/\\]id_(?:rsa|dsa|ecdsa|ed25519)|\.aws[/\\]credentials"
    r"|\.gnupg[/\\]private-keys[^\s\"';&|]*|\.docker[/\\]config\.json|\.kube[/\\]config|\.config[/\\]gh[/\\]hosts\.yml)(?![\w.-])",
    re.IGNORECASE,
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
# Approving or reverting an agent's hook proposal is the user's decision: an agent may not run the trusted command.
_TRUSTED_HOOK_ACTION = re.compile(
    r"python[\w.]*(?:\s+-\S+)*\s+[\"']?[^\s\"']*hook_proposal_control"
    r"|gravityguard(?:_cli\.py|\.cmd)?[\"']?\s+hooks\s+(?:approve|revert)\b"
    r"|hook_proposals\b[^\n]*\b(?:approve|revert)\s*\("
    r"|gravityguard(?:_cli\.py|\.cmd)?[\"']?\s+pause\s+(?:on|off|status)\b|pause_switch\b[^\n]*\b(?:pause|resume)\s*\(|\.gravityguard[/\\]+pause\.json",
    re.IGNORECASE,
)
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
    from .shell_danger import parse_command
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


def check_shell_command(args: dict, cwd: str | None = None, conversation_id: str | None = None) -> str:
    """`conversation_id` selects the file targets a file tool already refused in it (session quarantine)."""
    command = command_text(args)
    if command is None:
        return ""
    from .session_quarantine import denied_targets  # lazy: only command tools pay for the shell rule modules
    from .shell_control_guard import writes_control_file, writes_denied_target
    from .shell_danger import dangerous_command_reason
    from .shell_patch_guard import patch_script_reason
    blocked, reason, _ = check_g0_secret_leak(command)
    if blocked:
        return f"[G0_SECRET_LEAK]: {reason}"
    if _TRUSTED_HOOK_ACTION.search(command):
        return ("[POLICY_INTEGRITY]: Hook proposals are approved or reverted only by the user "
                "(GravityGuard panel or the user's own terminal)")
    danger = dangerous_command_reason(command)
    if danger:
        return f"[G0_DANGEROUS_COMMAND]: Blocked {danger}"
    if writes_denied_target(command, denied_targets(conversation_id) if conversation_id else (), cwd):
        return ("[HOOK_EVASION_DETECTED]: A file tool was already denied a write to a file this command writes; "
                "doing the same change through the shell is an evasion attempt. Fix the cause of the denial instead")
    if writes_control_file(command, cwd):
        return ("[POLICY_INTEGRITY]: Installed guard hooks, receipts and runtime state require a trusted host action; "
                "shell writes, moves, deletes and interpreter scripts targeting them are denied")
    patcher = patch_script_reason(command, cwd)
    if patcher:
        return (f"[SCRATCH_PATCH_DENY]: '{patcher}' rewrites project source files behind the edit-tool guards. "
                "If an edit failed (CRLF, quoting) fix the edit with the file tool or shrink the file first; "
                "a script cannot be used to escape it. Scratch scripts that only analyse data stay allowed")
    for segment in _SEGMENTS.split(command):
        reason = _protected_read_reason(segment)
        if reason:
            return reason
    return ""
