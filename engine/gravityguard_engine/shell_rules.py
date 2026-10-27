"""Shared command-text checks; intentionally not a shell interpreter or sandbox."""
import re
from .security_rules import check_g0_secret_leak, is_protected_env_file

_SEGMENTS = re.compile(r"[;&|\n(`]+")
_READ = re.compile(r"^\s*(?:sudo\s+)?(?:cat|type|less|more|head|tail|grep|rg|sed|awk|cp|copy|xxd|base64|source|Get-Content|gc|Select-String|sls|Copy-Item|cpi|Import-Csv|\.)\s+(.*)$", re.I)
_ENV = re.compile(r"(?<![\w.-])(?:[^\s\"';&|]*[/\\])?\.env(?:\.[\w-]+)?(?![\w.-])", re.I)
# Private credential stores (SSH keys, cloud/CLI tokens). `.pub` files are public and stay readable.
_CREDENTIAL = re.compile(
    r"(?<![\w.-])(?:[^\s\"';&|]*[/\\])?(?:\.ssh[/\\]id_(?:rsa|dsa|ecdsa|ed25519)|\.aws[/\\]credentials"
    r"|\.gnupg[/\\]private-keys[^\s\"';&|]*|\.docker[/\\]config\.json|\.kube[/\\]config|\.config[/\\]gh[/\\]hosts\.yml)(?![\w.-])",
    re.I,
)

# High-confidence destructive / remote-code patterns only: a false positive here denies a legitimate tool call,
# so routine commands (`rm -rf node_modules`, `curl -o file`, `chmod 755 x`) must never match.
_ROOT_TARGET = r"(?:--no-preserve-root\s+)?(?:/\*?|~/?\*?|\$\{?HOME\}?/?\*?)"
_INTERPRETER = r"(?:sudo\s+(?:-\S+\s+)*)?(?:(?:ba|z|da|k|c|fi)?sh|python[0-9.]*|node|perl|ruby|php)\b"
_DANGEROUS = (
    (re.compile(r"\b(?:curl|wget)\b[^\n;&]*?\|\s*" + _INTERPRETER, re.I), "remote download piped into an interpreter (curl | sh)"),
    (re.compile(r"\b(?:ba|z|da)?sh\s+(?:-c\s+)?[\"']?\$\(\s*(?:curl|wget)\b|<\(\s*(?:curl|wget)\b", re.I), "remote script run through command/process substitution"),
    (re.compile(
        r"\b(?:iex|invoke-expression)\b[^\n]*\b(?:iwr|irm|invoke-webrequest|invoke-restmethod|downloadstring|net\.webclient)\b"
        r"|\b(?:iwr|irm|invoke-webrequest|invoke-restmethod|curl)\b[^\n]*\|\s*(?:iex|invoke-expression)\b", re.I),
     "remote PowerShell content executed with Invoke-Expression"),
    (re.compile(r"\b(?:powershell|pwsh)(?:\.exe)?\b[^\n]*\s-e(?:nc(?:odedcommand)?)?\s+[A-Za-z0-9+/=]{20,}", re.I), "Base64-obfuscated PowerShell command"),
    (re.compile(r"\bbase64\s+(?:-d|-D|--decode)\b[^\n;&]*\|\s*" + _INTERPRETER, re.I), "decoded Base64 piped into an interpreter"),
    (re.compile(r"\brm\s+(?:-[a-zA-Z-]+\s+)*(?:-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\s+(?:-[a-zA-Z-]+\s+)*" + _ROOT_TARGET + r"(?=[\s;&|\"']|$)", re.I),
     "recursive delete of the filesystem root or home directory"),
    (re.compile(r"\b(?:del|erase)\s+(?:/[a-z]\s+)+[a-z]:\\\*?(?=[\s\"']|$)|\b(?:rd|rmdir)\s+(?:/[sq]\s+)+[a-z]:\\?(?=[\s\"']|$)"
                r"|\bRemove-Item\b[^\n]*-Recurse[^\n]*\s[a-z]:\\\*?(?=[\s\"']|$)|\bformat\s+[a-z]:", re.I),
     "recursive delete or format of a Windows drive root"),
    (re.compile(r"/dev/(?:tcp|udp)/|\b(?:nc|ncat|netcat)\b[^\n]*\s-[a-z]*e\s|\bbash\s+-i\s*>&", re.I), "reverse shell"),
    (re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"), "fork bomb"),
    (re.compile(r"\bchmod\s+(?:-[a-zA-Z]+\s+)*0?777\s+(?:-[a-zA-Z]+\s+)*/(?=[\s\"']|$)", re.I), "world-writable permissions on the filesystem root"),
    (re.compile(r"\bdd\b[^\n]*\bof=/dev/(?:sd[a-z]|nvme\d|hd[a-z]|disk\d)|\bmkfs(?:\.\w+)?\s+/dev/", re.I), "raw disk overwrite or format"),
)


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
    for pattern, label in _DANGEROUS:
        if pattern.search(command):
            return f"[G0_DANGEROUS_COMMAND]: Blocked {label}"
    for segment in _SEGMENTS.split(command):
        read = _READ.match(segment)
        if read:
            for match in _ENV.finditer(read.group(1)):
                if is_protected_env_file(match.group(0)):
                    return "[G0_ENV_PROTECTION]: Shell access to a live .env file is denied"
            if _CREDENTIAL.search(read.group(1)):
                return "[G0_CREDENTIAL_PROTECTION]: Shell access to a private credential file is denied"
    return ""
