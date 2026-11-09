"""GravityGuard Engine — secret/credential redaction for audit records."""
import re
from typing import Any


# Centralized secret & sensitive credential redaction patterns
_SECRET_PATTERNS = [
    # Anthropic API keys (sk-ant-...) - more specific, must precede generic sk-
    (re.compile(r"\b(sk-ant-[a-zA-Z0-9_\-]{20,})\b"), r"sk-ant-***[REDACTED]***"),
    # OpenAI & generic sk- API keys (sk-...)
    (re.compile(r"\b(sk-[a-zA-Z0-9_\-]{20,})\b"), r"sk-***[REDACTED]***"),
    # GitHub Personal Access Tokens and OAuth tokens
    (re.compile(r"\b((?:ghp|gho|ghu|ghs|ghr|github_pat)_[a-zA-Z0-9_]{20,})\b"), r"ghp_***[REDACTED]***"),
    # AWS Access Key IDs
    (re.compile(r"\b((?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16})\b"), r"AKIA***[REDACTED]***"),
    # JWT tokens (must precede Bearer to preserve specific JWT token identification)
    (re.compile(r"\b(eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,})\b"), r"[REDACTED_JWT]"),
    # Bearer tokens
    (re.compile(r"(?i)\b(bearer\s+)([a-zA-Z0-9_\-\.]{20,})\b"), r"\1***[REDACTED]***"),
    # URL / URI basic auth credentials (user:password@)
    (re.compile(r"://([^:\s]+):([^@\s]+)@"), r"://\1:***@"),
    # Quoted string assignments in JSON or code: "api_key": "..." or 'api_key': '...'
    (re.compile(r"""(?i)(["']?(?:api_?key|access_?token|auth_?token|secret_?key|password|passwd|private_?key|credential|client_?secret)["']?\s*[:=]\s*")([^"\r\n]{4,})(")"""), r"\1***[REDACTED]***\3"),
    (re.compile(r"""(?i)(["']?(?:api_?key|access_?token|auth_?token|secret_?key|password|passwd|private_?key|credential|client_?secret)["']?\s*[:=]\s*')([^'\r\n]{4,})(')"""), r"\1***[REDACTED]***\3"),
    # Unquoted key-value assignments
    (re.compile(r"""(?i)(["']?(?:api_?key|access_?token|auth_?token|secret_?key|password|passwd|private_?key|credential|client_?secret)["']?\s*[:=]\s*)([^\s"',\}\]]{6,})"""), r"\1***[REDACTED]***"),
    # RSA / OpenSSH / EC Private Keys
    (re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+ PRIVATE KEY-----"), r"[REDACTED_PRIVATE_KEY]"),
]

_SENSITIVE_DICT_KEYS = {
    "api_key", "apikey", "secret", "secret_key", "password", "passwd",
    "token", "access_token", "auth_token", "private_key", "credential",
    "credentials", "authorization", "client_secret"
}


def redact_secrets(val: str) -> str:
    """Scans and scrubs sensitive API keys, tokens, and credentials from a text string."""
    if not isinstance(val, str) or not val:
        return val
    redacted = val
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_record(record: Any) -> Any:
    """Recursively redacts secrets across all fields in a dictionary, list, or primitive."""
    if isinstance(record, dict):
        scrubbed = {}
        for k, v in record.items():
            k_norm = str(k).lower().strip().replace("-", "_")
            if k_norm in _SENSITIVE_DICT_KEYS:
                scrubbed[k] = "[REDACTED_CREDENTIAL]"
            else:
                scrubbed[k] = redact_record(v)
        return scrubbed
    elif isinstance(record, list):
        return [redact_record(item) for item in record]
    elif isinstance(record, str):
        return redact_secrets(record)
    return record

