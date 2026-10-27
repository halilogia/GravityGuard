"""Destructive / remote-code shell command detection in linear time.

Deliberately token based instead of one regex per rule with unbounded gaps (`curl ...  | sh`): such regexes are quadratic
on repeated anchors (a ReDoS that lets crafted tool input stall the guard) and a long filler between the parts would be an
easy bypass. Here a command is split once into chain segments and pipeline stages, each stage into tokens, and every rule
inspects tokens, so work is proportional to the command length. Intentionally not a shell interpreter or sandbox.
"""
import re
from typing import List, Optional, Tuple

_CHAIN = re.compile(r"[;&\n]+")
_WRAPPERS = frozenset({"sudo", "env", "nohup", "command", "exec", "time", "doas"})
_SUDO_ARG_FLAGS = frozenset({"-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U"})
_SHELLS = re.compile(r"(?:(?:ba|z|da|k|c|fi)?sh|python[0-9.]*|node|perl|ruby|php)")
_DOWNLOADERS = frozenset({"curl", "wget", "fetch"})
_PS_DOWNLOADERS = frozenset({"iwr", "irm", "invoke-webrequest", "invoke-restmethod", "curl"})
_IEX = frozenset({"iex", "invoke-expression"})
_BASE64_BLOB = re.compile(r"[A-Za-z0-9+/=]{20,}")
_ROOT_TARGET = re.compile(r"(?:/\*?|~/?\*?|\$\{?HOME\}?/?\*?)")
_RM_RECURSIVE = re.compile(r"-[a-zA-Z]*[rR][a-zA-Z]*")
_DRIVE_ROOT = re.compile(r"[a-zA-Z]:\\\*?")
_DEVICE = re.compile(r"of=/dev/(?:sd[a-z]|nvme\d|hd[a-z]|disk\d)")
_SUBSTITUTION = re.compile(r"\b(?:ba|z|da)?sh\s+(?:-c\s+)?[\"']?\$\(\s*(?:curl|wget)\b|<\(\s*(?:curl|wget)\b", re.IGNORECASE)
_REVERSE_SHELL = re.compile(r"/dev/(?:tcp|udp)/|\bbash\s+-i\s*>&", re.IGNORECASE)
_FORK_BOMB = re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:")
_WRAPPED_EXEC = re.compile(
    r"\b(?:(?:ba|z|da|k|c)?sh|cmd|powershell|pwsh)(?:\.exe)?\s+(?:-[a-zA-Z]*c[a-zA-Z]*|/[ck])\s+[\"'](.*?)[\"']",
    re.IGNORECASE | re.DOTALL,
)

Command = Tuple[str, List[str]]  # (lower-case command word, remaining tokens)


def _command(stage: str) -> Optional[Command]:
    """Command word (path and `.exe` stripped, wrappers such as sudo/env skipped) and its arguments."""
    tokens = stage.split()
    index = 0
    while index < len(tokens):
        word = tokens[index].strip("()`\"'")
        base = word.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if base.endswith(".exe"):
            base = base[:-4]
        if base in _WRAPPERS or "=" in word.split("/")[0] and not word.startswith("-"):
            index += 1
            while index < len(tokens) and tokens[index].startswith("-"):
                index += 2 if tokens[index] in _SUDO_ARG_FLAGS else 1
            continue
        return base, tokens[index + 1:]
    return None


parse_command = _command  # public name for sibling rule modules (command word + arguments of one pipeline stage)


def _targets(args: List[str]) -> List[str]:
    return [a.strip("\"'") for a in args if not a.startswith("-")]


def _stage_reason(base: str, args: List[str]) -> str:
    lowered = [a.lower() for a in args]
    if base == "rm":
        recursive = any(_RM_RECURSIVE.fullmatch(a) for a in args) or "--recursive" in lowered
        if recursive and any(_ROOT_TARGET.fullmatch(t) for t in _targets(args)):
            return "recursive delete of the filesystem root or home directory"
    elif base == "chmod":
        if any(re.fullmatch(r"0?777", a) for a in args) and "/" in _targets(args):
            return "world-writable permissions on the filesystem root"
    elif base == "dd":
        if any(_DEVICE.match(a) for a in args):
            return "raw disk overwrite or format"
    elif base.startswith("mkfs"):
        if any(a.startswith("/dev/") for a in args):
            return "raw disk overwrite or format"
    elif base in ("del", "erase"):
        if any(re.fullmatch(r"/[a-z]", a, re.IGNORECASE) for a in args) and any(_DRIVE_ROOT.fullmatch(t) for t in _targets_win(args)):
            return "recursive delete or format of a Windows drive root"
    elif base in ("rd", "rmdir"):
        if any(re.fullmatch(r"/[sq]", a, re.IGNORECASE) for a in args) and any(re.fullmatch(r"[a-zA-Z]:\\?", t) for t in _targets_win(args)):
            return "recursive delete or format of a Windows drive root"
    elif base in ("remove-item", "ri"):
        if "-recurse" in lowered and any(_DRIVE_ROOT.fullmatch(t) for t in _targets_win(args)):
            return "recursive delete or format of a Windows drive root"
    elif base == "format":
        if any(re.fullmatch(r"[a-zA-Z]:", a) for a in args):
            return "recursive delete or format of a Windows drive root"
    elif base in ("nc", "ncat", "netcat"):
        if any(re.fullmatch(r"-[a-z]*e", a, re.IGNORECASE) for a in args):
            return "reverse shell"
    elif base in ("powershell", "pwsh"):
        for position, token in enumerate(lowered):
            if token in ("-e", "-enc", "-encodedcommand") and position + 1 < len(args) and _BASE64_BLOB.fullmatch(args[position + 1]):
                return "Base64-obfuscated PowerShell command"
    elif base in _IEX:
        if any(a.lower().strip("()\"'") in ("iwr", "irm") or re.search(r"downloadstring|net\.webclient|invoke-webrequest|invoke-restmethod", a, re.IGNORECASE) for a in args):
            return "remote PowerShell content executed with Invoke-Expression"

    # Wrapped inline execution (e.g. bash -c "...", powershell -Command "...", cmd /c "...")
    if base in ("bash", "sh", "zsh", "ksh", "dash", "csh", "powershell", "pwsh", "cmd"):
        for pos, arg in enumerate(args):
            flag = arg.lower()
            if flag in ("-c", "-command", "/c", "/k") and pos + 1 < len(args):
                inner_cmd = " ".join(args[pos + 1:]).strip("\"'")
                inner_reason = dangerous_command_reason(inner_cmd)
                if inner_reason:
                    return f"wrapped dangerous command ({inner_reason})"
    return ""


def _targets_win(args: List[str]) -> List[str]:
    """Non-flag arguments for Windows commands, where flags look like `/s` (a bare drive such as `C:\\` is a target)."""
    return [a.strip("\"'") for a in args if not (a.startswith("-") or re.fullmatch(r"/[a-zA-Z]", a))]


def _pipeline_reason(stages: List[str]) -> str:
    """Remote or encoded content piped into an interpreter; one pass with running flags (no stage-pair scan)."""
    downloaded = decoded = ps_downloaded = False
    for stage in stages:
        parsed = _command(stage)
        if parsed is None:
            continue
        base, args = parsed
        if _SHELLS.fullmatch(base):
            if downloaded:
                return "remote download piped into an interpreter (curl | sh)"
            if decoded:
                return "decoded Base64 piped into an interpreter"
        if base in _IEX and ps_downloaded:
            return "remote PowerShell content executed with Invoke-Expression"
        downloaded = downloaded or base in _DOWNLOADERS
        ps_downloaded = ps_downloaded or base in _PS_DOWNLOADERS
        decoded = decoded or (base == "base64" and any(a in ("-d", "-D", "--decode") for a in args))
    return ""


def dangerous_command_reason(command: str) -> str:
    """Human-readable label of the first destructive / remote-code pattern found, or '' for an ordinary command."""
    if _SUBSTITUTION.search(command):
        return "remote script run through command/process substitution"
    if _REVERSE_SHELL.search(command):
        return "reverse shell"
    if _FORK_BOMB.search(command):
        return "fork bomb"
    wrapped_match = _WRAPPED_EXEC.search(command)
    if wrapped_match:
        inner = wrapped_match.group(1).strip()
        inner_reason = dangerous_command_reason(inner)
        if inner_reason:
            return f"wrapped dangerous command ({inner_reason})"
    for segment in _CHAIN.split(command):
        stages = segment.split("|")
        reason = _pipeline_reason(stages)
        if reason:
            return reason
        for stage in stages:
            parsed = _command(stage)
            reason = _stage_reason(*parsed) if parsed else ""
            if reason:
                return reason
    return ""
