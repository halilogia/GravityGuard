#!/usr/bin/env python3
"""
GravityGuard Engine — High-Confidence Security Rules Subsystem.
Implements:
- G0: Secret, Token & Private Key Leak Guard (BLOCK / WARN)
- G1: Silent Exception & Empty Catch Block Guard (BLOCK)
- G2: Test Tampering & Deletion Guard (BLOCK / WARN)
- Escape Hatch Tampering Guard (BLOCK)
Zero external dependencies.
"""
import ast
import re
from collections import Counter
from typing import List, Optional, Set, Tuple

PLACEHOLDER_KEYWORDS = (
    "example", "your_api_key", "your_token", "your-api-key", "your-key",
    "placeholder", "dummy", "mock", "test_token", "changeme",
    "insert_key", "sample", "replace_me", "xxxxxxxx", "00000000"
)


def is_placeholder(val: str) -> bool:
    val_lower = val.lower()
    if any(kw in val_lower for kw in PLACEHOLDER_KEYWORDS):
        return True
    if val_lower.startswith("<") or val_lower.endswith(">"):
        return True
    return False


def redact_token(token: str) -> str:
    token = token.strip()
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}****...****{token[-3:]}"


_PEM_BODY_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----(.*?)-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)


def is_elided_pem_fixture(added_text: str, start: int, span: int = 400) -> bool:
    """Determine if a PEM key block is a test/doc placeholder rather than a real key."""
    window = added_text[start:start + span]
    if "..." in window or "\u2026" in window:
        return True

    body_match = _PEM_BODY_RE.match(window)
    if body_match:
        b64_chars = re.findall(r"[A-Za-z0-9+/=]", body_match.group(1))
        if len(b64_chars) < 48:
            return True

    return False


def check_g0_secret_leak(added_text: str) -> Tuple[bool, str, Optional[str]]:
    """
    Guards against secret, API key, and credential leaks in newly added code lines.
    Diff-safe: Only checks added_text.
    Returns: (is_blocked, block_reason, warn_reason_or_None)
    """
    if not added_text.strip():
        return False, "", None

    # 1. HIGH-CONFIDENCE BLOCK RULES
    # A) Private Keys (PEM / OpenSSH)
    pk_match = re.search(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----", added_text)
    if pk_match and not is_elided_pem_fixture(added_text, pk_match.start()):
        return True, "Özel anahtar (Private Key) başlığı tespit edildi. Private key'ler asla depoya commit edilemez!", None

    # B) GitHub Tokens (ghp_, github_pat_, gho_, ghu_, ghs_, ghr_)
    gh_match = re.search(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[a-zA-Z0-9_]{16,}\b", added_text)
    if gh_match:
        raw_token = gh_match.group(0)
        if not is_placeholder(raw_token):
            return True, f"GitHub Personal Access / OAuth Token tespit edildi: {redact_token(raw_token)}. SecretStorage veya env kullanın.", None

    # C) Anthropic / Claude API Keys (sk-ant-api..., sk-ant-admin...)
    claude_match = re.search(r"\bsk-ant-(?:api|admin)[0-9]{0,2}-[a-zA-Z0-9_\-]{20,}\b", added_text)
    if claude_match:
        raw_token = claude_match.group(0)
        if not is_placeholder(raw_token):
            return True, f"Anthropic / Claude API anahtarı tespit edildi: {redact_token(raw_token)}. Ortam değişkeni kullanın.", None

    # D) OpenAI Modern Keys (sk-proj-..., sk-svcacct-..., sk-admin-...)
    openai_match = re.search(r"\bsk-(?:proj|svcacct|admin)-[a-zA-Z0-9_\-]{20,}\b", added_text)
    if openai_match:
        raw_token = openai_match.group(0)
        if not is_placeholder(raw_token):
            return True, f"OpenAI API anahtarı tespit edildi: {redact_token(raw_token)}. Ortam değişkeni kullanın.", None

    # D2) OpenAI legacy keys: sk- + 48 letters/digits (no hyphens), or the older sk-<20>T3BlbkFJ<20> form.
    # `\b` before "sk-" keeps words such as "task-report-..." or "risk-..." out; the fixed hyphen-free length keeps
    # kebab-case slugs that merely start with "sk-" out.
    legacy_match = re.search(r"\bsk-(?:[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20}|[A-Za-z0-9]{48})\b", added_text)
    if legacy_match:
        raw_token = legacy_match.group(0)
        if not is_placeholder(raw_token):
            return True, f"OpenAI API anahtarı (eski biçim) tespit edildi: {redact_token(raw_token)}. Ortam değişkeni kullanın.", None

    # E) Google / Gemini API Keys (AIza...)
    gemini_match = re.search(r"\bAIza[0-9A-Za-z\-_]{35,40}\b", added_text)
    if gemini_match:
        raw_token = gemini_match.group(0)
        if not is_placeholder(raw_token):
            return True, f"Google / Gemini API anahtarı tespit edildi: {redact_token(raw_token)}. Ortam değişkeni kullanın.", None

    # F) Slack Tokens (xoxb-, xoxa-, xoxp-, xoxr-)
    slack_match = re.search(r"\bxox[baprs]-[0-9a-zA-Z]{10,}\b", added_text)
    if slack_match:
        raw_token = slack_match.group(0)
        if not is_placeholder(raw_token):
            return True, f"Slack Token tespit edildi: {redact_token(raw_token)}. Ortam değişkeni kullanın.", None

    # G) AWS Access Key ID (AKIA, ASIA, ABIA, ACCA)
    aws_match = re.search(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b", added_text)
    if aws_match:
        raw_token = aws_match.group(0)
        if not is_placeholder(raw_token):
            return True, f"AWS Access Key ID tespit edildi: {redact_token(raw_token)}. Ortam değişkeni (AWS_ACCESS_KEY_ID) veya IAM role kullanın.", None

    # 2. MEDIUM-CONFIDENCE WARNING RULES (WARN ONLY, Never Blocks)
    warn_reason: Optional[str] = None

    # A) Generic Bearer Token in Added Code
    bearer_match = re.search(r"['\"]?Authorization['\"]?\s*[:=]\s*['\"]Bearer\s+([a-zA-Z0-9_\-\.]{30,})['\"]", added_text, re.IGNORECASE)
    if bearer_match:
        raw_bearer = bearer_match.group(1)
        if not is_placeholder(raw_bearer):
            warn_reason = f"Şüpheli Bearer kimlik doğrulama belirteci tespit edildi ({redact_token(raw_bearer)}). Sabit token yerine oturum yönetimi kullanın."

    # B) Connection URI with embedded password
    db_uri_match = re.search(r"\b(?:postgres|postgresql|mysql|mongodb(?:\+srv)?):\/\/[^\s:]+:([^\s@]+)@[^\s]+", added_text, re.IGNORECASE)
    if db_uri_match:
        raw_pass = db_uri_match.group(1)
        if not is_placeholder(raw_pass):
            warn_reason = "Veritabanı bağlantı URI'sinde gömülü kimlik bilgisi tespit edildi. Parolaları connection string içinde saklamayın."

    return False, "", warn_reason


def check_g1_silent_exception(
    added_lines: List[str],
    added_text: str,
    added_line_numbers: Set[int],
    projected_content: str,
    is_python: bool,
    is_ts: bool
) -> Tuple[bool, str]:
    """
    Detects newly introduced empty catch/except blocks.
    Strictly diff-safe: Only flags handlers created or modified in this change.
    Pre-existing handlers in unchanged lines are never flagged.
    Does NOT block recovery fallbacks like 'return None' or 'return []'.
    """
    if not added_text.strip():
        return False, ""

    if is_python:
        # 1. Regex check on newly added text lines
        py_empty_pattern = re.compile(
            r"except(?:\s+[^:]+)?:\s*(?:\r?\n\s*)+(?:pass|\.\.\.)(?!\w)",
            re.MULTILINE
        )
        py_m = py_empty_pattern.search(added_text)
        if py_m:
            base_txt = projected_content if projected_content and py_empty_pattern.search(projected_content) else added_text
            m_found = py_empty_pattern.search(base_txt)
            line_num = base_txt[:m_found.start()].count("\n") + 1 if m_found else 1
            return True, f"Yeni eklenen boş exception handler tespit edildi (Satır {line_num}: 'except: pass' / 'except: ...'). Hatalar sessizce yutulamaz; hata loglanmalı, anlamlı bir kurtarma/fallback davranışı tanımlanmalı veya yeniden fırlatılmalıdır."

        # 2. AST inspection on projected content: verify line numbers intersect with added_line_numbers
        try:
            tree = ast.parse(projected_content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    is_empty = False
                    if len(node.body) == 1:
                        first = node.body[0]
                        if isinstance(first, ast.Pass):
                            is_empty = True
                        elif (
                            isinstance(first, ast.Expr) and
                            isinstance(first.value, ast.Constant) and
                            first.value.value is Ellipsis
                        ):
                            is_empty = True
                    if is_empty:
                        start_line = node.lineno
                        end_line = getattr(node, "end_lineno", node.lineno)
                        handler_lines = set(range(start_line, end_line + 1))
                        # Trigger only if this handler is part of newly added/modified lines
                        if handler_lines.intersection(added_line_numbers):
                            return True, f"Yeni eklenen boş exception handler (Satır {start_line}: except pass/ellipsis). Hatalar sessizce yutulamaz; hata loglanmalı, anlamlı bir kurtarma/fallback davranışı tanımlanmalı veya yeniden fırlatılmalıdır."
        except (SyntaxError, ValueError):
            tree = None

    if is_ts:
        # Regex for TypeScript/JavaScript empty catch blocks:
        # catch { } OR catch (e) { } OR catch (err) { \n }
        ts_empty_pattern = re.compile(
            r"catch\s*(?:\([^)]*\))?\s*\{\s*\}",
            re.MULTILINE
        )
        if ts_empty_pattern.search(added_text):
            base_txt = projected_content if projected_content and ts_empty_pattern.search(projected_content) else added_text
            m_found = ts_empty_pattern.search(base_txt)
            line_num = base_txt[:m_found.start()].count("\n") + 1 if m_found else 1
            return True, f"Yeni eklenen boş catch bloğu tespit edildi (Satır {line_num}: 'catch {{}}'). Hatalar sessizce yutulamaz; hata loglanmalı, anlamlı bir kurtarma/fallback davranışı tanımlanmalı veya yeniden fırlatılmalıdır."

    return False, ""


def check_g2_test_integrity(
    added_text: str,
    old_full_content: str,
    projected_content: str,
    is_test_file: bool
) -> Tuple[bool, str, Optional[str]]:
    """
    Guards test suite integrity:
    G2-A: Newly added .skip, pytest.mark.skip, xit, xdescribe -> BLOCK
          .only -> WARN (not high confidence sabotage)
          pytest.mark.xfail -> ALLOW (valid intentional test annotation)
    G2-C: Outright deletion of an existing test case -> BLOCK
    Returns: (is_blocked, block_reason, warn_reason_or_None)
    """
    if not is_test_file:
        return False, "", None

    warn_reason: Optional[str] = None

    # G2-A: Newly added disabling mechanisms (BLOCK)
    disablers = [
        (r"\.skip\s*\(", ".skip()"),
        (r"\bxit\s*\(", "xit()"),
        (r"\bxdescribe\s*\(", "xdescribe()"),
        (r"@pytest\.mark\.skip\b", "@pytest.mark.skip"),
        (r"@unittest\.skip\b", "@unittest.skip"),
    ]

    for pattern, name in disablers:
        if re.search(pattern, added_text):
            return True, f"Test devre dışı bırakma hilesi tespit edildi ({name}). Testleri susturmak yerine hatayı düzeltin.", None

    # .only is treated as warning rather than block
    if re.search(r"\.only\s*\(", added_text):
        warn_reason = "Test dosyasında '.only()' kullanımı tespit edildi (Tüm diğer testleri göz ardı eder). Geçici debug sonrası kaldırmayı unutmayın."

    # G2-C: Test case deletion verification across full file
    if old_full_content.strip():
        py_tests_old = re.findall(r"^\s*def\s+(test_\w+)\s*\(", old_full_content, re.MULTILINE)
        js_tests_old = re.findall(r"^\s*(?:it|test)(?:\.\w+)*\s*\(\s*[\"']([^\"']+)[\"']", old_full_content, re.MULTILINE)
        old_counts = Counter(py_tests_old + js_tests_old)

        if old_counts:
            py_tests_proj = re.findall(r"^\s*def\s+(test_\w+)\s*\(", projected_content, re.MULTILINE)
            js_tests_proj = re.findall(r"^\s*(?:it|test)(?:\.\w+)*\s*\(\s*[\"']([^\"']+)[\"']", projected_content, re.MULTILINE)
            proj_counts = Counter(py_tests_proj + js_tests_proj)

            deleted = []
            for test_name, old_qty in old_counts.items():
                proj_qty = proj_counts.get(test_name, 0)
                if proj_qty < old_qty:
                    deleted.append(test_name)

            if deleted:
                sample_deleted = deleted[:2]
                return True, f"Mevcut test senaryosu silindi: {', '.join(sample_deleted)}. Var olan testleri silmek yasaktır.", None

    return False, "", warn_reason


def check_escape_hatch_tampering(added_text: str, old_full_content: str) -> Tuple[bool, str]:
    """
    Blocks AI attempts to inject escape hatch comments (e.g. `srp: allow-monolith`, `srp: bypass`)
    to silence architectural / SRP guards.
    Only human developers can add these markers; newly added markers in AI tool calls are blocked.
    """
    marker_pattern = r"(?://|/\*|#)\s*(?:srp\s*:\s*(?:allow-monolith|cohesive-monolith|bypass|noqa)|noqa\s*:\s*srp)\b"
    if re.search(marker_pattern, added_text, re.IGNORECASE):
        if not re.search(marker_pattern, old_full_content, re.IGNORECASE):
            return True, (
                "Güvenlik/Mimari susturma hilesi tespit edildi ('srp: allow-monolith' / 'srp: bypass'). "
                "Yapay zeka ajanları kendi kendilerine guard muafiyeti veya bypass belirteci ekleyemez; "
                "bu belirteç yalnızca insan geliştirici tarafından elle eklenebilir."
            )
    return False, ""
