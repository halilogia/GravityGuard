"""Shared command-text checks; intentionally not a shell interpreter or sandbox."""
import re
from .security_rules import check_g0_secret_leak, is_protected_env_file

_SEGMENTS = re.compile(r"[;&|\n(`]+")
_READ = re.compile(r"^\s*(?:sudo\s+)?(?:cat|type|less|more|head|tail|grep|rg|sed|awk|cp|copy|xxd|base64|source|Get-Content|gc|Select-String|sls|Copy-Item|cpi|Import-Csv|\.)\s+(.*)$", re.I)
_ENV = re.compile(r"(?<![\w.-])(?:[^\s\"';&|]*[/\\])?\.env(?:\.[\w-]+)?(?![\w.-])", re.I)


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
    for segment in _SEGMENTS.split(command):
        read = _READ.match(segment)
        if read:
            for match in _ENV.finditer(read.group(1)):
                if is_protected_env_file(match.group(0)):
                    return "[G0_ENV_PROTECTION]: Shell access to a live .env file is denied"
    return ""
