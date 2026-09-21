import sys
import json
import os
import re
import ast
import time
import difflib
import subprocess
import fnmatch
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Tuple, List, Optional, Set, Dict, Any

# ============================================================================
# 0. UTF-8 STREAM HARDENING (Windows cp1252 defence)
# ============================================================================
# WHY THIS EXISTS:
#   hooks.json launches this guard as `python scripts/srp-validator.py`. On
#   Windows a bare `python` does NOT enable UTF-8: measured on this host,
#   sys.stdin/sys.stdout/sys.stderr all default to cp1252 and
#   sys.flags.utf8_mode == 0, while the harness writes its JSON payload as
#   UTF-8 bytes. Two failures followed from that single mismatch:
#     1. Lossy decode. Any payload carrying non-ASCII text (e.g. a Turkish
#        path) was decoded as cp1252 and reinterpreted as mojibake
#        ("Propogandasının söylem" -> "PropogandasÄ±nÄ±n sÃ¶ylem"). The guard
#        then asked the filesystem about a path that does not exist and
#        silently lost the target file's real content.
#     2. Hard crash. Characters absent from cp1252 (U+201D, the typographic
#        right double quote Word inserts automatically; also U+200D) decode to
#        lone surrogates, so ast.parse() raised UnicodeEncodeError and the
#        process exited 1 with EMPTY stdout.
#   A crashed hook does not block the write: the harness received no decision
#   at all, so the guard failed OPEN and the write went through unguarded.
#   Reconfiguring the streams here makes the guard correct regardless of how it
#   is invoked, instead of depending on a launcher flag that lives outside
#   version control.
def _harden_streams_to_utf8() -> None:
    """Forces stdin/stdout/stderr to UTF-8 with replacement (never raises)."""
    for stream_name in ("stdin", "stdout", "stderr"):
        try:
            getattr(sys, stream_name).reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError, LookupError):
            # Python < 3.7, a detached/closed stream, or a stream object without
            # reconfigure(). Best-effort by design: a guard must never fail
            # because of its own hardening step, so skip the unusable stream.
            continue


_harden_streams_to_utf8()


# ============================================================================
# 1. LOGGING & AUDIT STREAM (srp_guardian_live.json)
# ============================================================================

def _resolve_log_dir() -> str:
    """Resolves the audit-log directory.

    GRAVITYGUARD_LOG_DIR lets the test suite / CI redirect the audit stream to a
    temp directory. Without it every validator subprocess the suite spawns appends
    to the *real* user log, and since only the last 50 events are kept, a single
    suite run evicts all genuine security events and the Live Security Monitor
    ends up displaying test fixtures as if they were real activity.
    """
    override = os.environ.get("GRAVITYGUARD_LOG_DIR", "").strip()
    if override:
        return os.path.expanduser(override)
    return os.path.expanduser(r"~/.gemini/logs")


def log_event(action: str, status: str, target_file: str, reason: str, rule_id: str = "SRP"):
    log_dir = _resolve_log_dir()
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "srp_guardian_live.json")
        
        current_data = {"activeGuard": "GravityGuard", "status": "ONLINE", "events": []}
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    current_data = json.load(f)
            except Exception:
                current_data = {"activeGuard": "GravityGuard", "status": "ONLINE", "events": []}
                
        event = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "status": status,
            "ruleId": rule_id,
            "target": target_file,
            "reason": reason
        }
        
        events = current_data.get("events", [])
        events.insert(0, event)
        current_data["events"] = events[:50]  # keep last 50
        current_data["lastCheck"] = event["timestamp"]
        
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(current_data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ============================================================================
# 2. DIFF & CONTENT SIMULATION (No Git Command Required - Zero Dependencies)
# ============================================================================

def get_projected_and_old_content(target_file: str, tool_name: str, args: dict) -> Tuple[str, str]:
    """
    Simulates the before and after state of the file without calling any external git CLI.
    Returns: (old_full_content, projected_full_content)
    """
    existing_content = ""
    if os.path.exists(target_file):
        try:
            with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
                existing_content = f.read()
        except (IOError, OSError):
            existing_content = ""

    if tool_name == "write_to_file":
        new_content = args.get("CodeContent", "")
        return existing_content, new_content

    if tool_name == "replace_file_content":
        target = args.get("TargetContent", "")
        repl = args.get("ReplacementContent", "")
        allow_multiple = args.get("AllowMultiple", False)
        if existing_content:
            count = -1 if allow_multiple else 1
            if target and target in existing_content:
                projected = existing_content.replace(target, repl, count)
            elif repl:
                projected = existing_content + "\n" + repl
            else:
                projected = existing_content
            return existing_content, projected
        else:
            # File does not exist on disk (mock/virtual payload in tests or new file)
            return target, repl

    if tool_name == "multi_replace_file_content":
        chunks = args.get("ReplacementChunks", [])
        if existing_content:
            projected = existing_content
            for chunk in chunks:
                if isinstance(chunk, dict):
                    t = chunk.get("TargetContent", "")
                    r = chunk.get("ReplacementContent", "")
                    m = chunk.get("AllowMultiple", False)
                    if t and t in projected:
                        c = -1 if m else 1
                        projected = projected.replace(t, r, c)
            return existing_content, projected
        else:
            old_parts = [chunk.get("TargetContent", "") for chunk in chunks if isinstance(chunk, dict)]
            new_parts = [chunk.get("ReplacementContent", "") for chunk in chunks if isinstance(chunk, dict)]
            return "\n".join(old_parts), "\n".join(new_parts)

    return existing_content, existing_content


def get_diff_analysis(old_content: str, projected_content: str) -> Tuple[List[str], str, Set[int]]:
    """
    Extracts strictly added/modified lines using difflib.SequenceMatcher.
    Zero git commands executed.
    Returns:
      - added_lines: list of newly introduced lines
      - added_text: joined string of added lines
      - added_line_numbers: set of 1-indexed line numbers in projected_content that are new or modified
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = projected_content.splitlines(keepends=True)

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    added_lines: List[str] = []
    added_line_numbers: Set[int] = set()

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ('insert', 'replace'):
            for new_line_idx in range(j1, j2):
                added_lines.append(new_lines[new_line_idx])
                added_line_numbers.add(new_line_idx + 1)

    added_text = "".join(added_lines)
    return added_lines, added_text, added_line_numbers


def extract_diff_and_projected(target_file: str, tool_name: str, args: dict) -> Tuple[str, str, str]:
    """Compatibility alias for old signature."""
    old_c, proj_c = get_projected_and_old_content(target_file, tool_name, args)
    added_lines, added_text, _ = get_diff_analysis(old_c, proj_c)
    return old_c, added_text, proj_c


# ============================================================================
# 3. HIGH-CONFIDENCE GUARDS (Phase 1.1 Hardened + G0 Secret Leak)
# ============================================================================

# --- G0: SECRET LEAK GUARD (BLOCK / WARN) ---

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

# PEM govdesini baslik ile bitis arasinda yakalar.
_PEM_BODY_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----(.*?)-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)


def is_elided_pem_fixture(added_text: str, start: int, span: int = 400) -> bool:
    """Tekil Sorumluluk: PEM basliginin test/dokuman ornegi oldugunu belirlemek.

    Gercek bir ozel anahtarin govdesi YUZLERCE base64 karakteridir ve icinde
    '.' BULUNAMaz (nokta base64 alfabesinde yoktur). Bu yuzden elips ('...')
    veya cok kisa bir govde, degerin canli anahtar degil ornek veri oldugunun
    KESIN kanitidir.

    Bu kontrol olmadan, icinde ornek PEM blogu bulunan bir test veya dokuman
    yazmak G0 tarafindan BLOKLANIR — koruma mesru is akisini engeller hale
    gelir. Esik bilerek cok dusuktur: en kisa gercek anahtar bile ~64 base64
    karakterdir, bu yuzden gercek bir anahtarin atlanmasi beklenmez.
    """
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


# --- G1: SILENT EXCEPTION (BLOCK) ---
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
        if py_empty_pattern.search(added_text):
            return True, "Yeni eklenen boş exception handler tespit edildi ('except: pass' / 'except: ...'). Hatalar loglanmalı veya fırlatılmalıdır."

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
                            return True, "Yeni eklenen boş exception handler (AST: except pass/ellipsis). Sessizce yutulan hatalar yasaktır."
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
            return True, "Yeni eklenen boş catch bloğu tespit edildi ('catch {}'). Hatalar sessizce yutulamaz."

    return False, ""


# --- G2: TEST INTEGRITY (BLOCK / WARN) ---
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
    # Notice: pytest.mark.xfail is completely removed from BLOCK.
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


# --- G3: COMPILER & LINTER BYPASS (WARN ONLY) ---
def check_g3_compiler_bypass(added_text: str) -> List[str]:
    """
    Detects newly added compiler/linter suppressions.
    Returns list of matched bypass descriptions.
    Never blocks; only produces warning events.
    """
    if not added_text.strip():
        return []

    bypass_rules = [
        (r"@ts-ignore\b", "@ts-ignore"),
        (r"@ts-nocheck\b", "@ts-nocheck"),
        (r"eslint-disable(?:-next-line)?\b", "eslint-disable"),
        (r"#\s*noqa(?::\s*[\w\d,\s]+)?\b", "# noqa"),
        (r"#\s*type:\s*ignore\b", "# type: ignore"),
    ]

    detected = []
    for pattern, name in bypass_rules:
        if re.search(pattern, added_text):
            detected.append(name)

    return detected


# --- G4: IMPORT MATRIX (BLOCK) ---
def load_gravityguard_config(target_file: str) -> Optional[dict]:
    """Traverse upward looking for .gravityguard.json config."""
    try:
        p = Path(target_file)
        current_dir = p if p.is_dir() else p.parent
    except (ValueError, OSError):
        current_dir = Path(os.getcwd())

    for _ in range(6):  # up to 6 levels up
        cfg_file = current_dir / ".gravityguard.json"
        if cfg_file.is_file():
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return None
        if current_dir.parent == current_dir:
            break
        current_dir = current_dir.parent

    # Check cwd as fallback
    cwd_cfg = Path(os.getcwd()) / ".gravityguard.json"
    if cwd_cfg.is_file():
        try:
            with open(cwd_cfg, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    return None


def check_g4_import_matrix(target_file: str, added_text: str) -> Tuple[bool, str]:
    """
    Enforces architectural layer boundaries defined in .gravityguard.json.
    Supports Python relative imports (e.g. from .network import ..., from ..network.client import ...)
    and TypeScript side-effect imports (import '../network').
    Uses exact path segment matching to prevent false positives (e.g. 'networking' vs 'network').
    """
    if not added_text.strip():
        return False, ""

    cfg = load_gravityguard_config(target_file)
    if not cfg or "layers" not in cfg:
        return False, ""

    normalized_path = target_file.replace("\\", "/").lower()
    layers = cfg.get("layers", {})

    # 1. Python imports
    py_from_imports = re.findall(r"^\s*from\s+([\.\w]+)\s+import", added_text, re.MULTILINE)
    py_direct_imports = re.findall(r"^\s*import\s+([^\n#;]+)", added_text, re.MULTILINE)

    # 2. TypeScript/JavaScript imports
    ts_from_imports = re.findall(r"^\s*import\s+.*?from\s+[\"']([^\"']+)[\"']", added_text, re.MULTILINE)
    ts_side_effect_imports = re.findall(r"^\s*import\s+[\"']([^\"']+)[\"']", added_text, re.MULTILINE)
    ts_require_imports = re.findall(r"\brequire\s*\(\s*[\"']([^\"']+)[\"']\s*\)", added_text, re.MULTILINE)

    imported_modules: Set[str] = set()
    for imp in py_from_imports:
        if imp:
            imported_modules.add(imp.lower())
    for imp_line in py_direct_imports:
        for part in imp_line.split(","):
            mod = part.strip().split()[0] if part.strip() else ""
            if mod:
                imported_modules.add(mod.lower())
    for imp in ts_from_imports + ts_side_effect_imports + ts_require_imports:
        if imp:
            imported_modules.add(imp.lower())

    if not imported_modules:
        return False, ""

    for layer_name, layer_cfg in layers.items():
        layer_marker = f"/{layer_name.lower()}/"
        if layer_marker in normalized_path or normalized_path.startswith(f"{layer_name.lower()}/"):
            forbidden_list = layer_cfg.get("forbiddenImports", [])
            for forbidden in forbidden_list:
                forbidden_clean = forbidden.lower().strip()
                forb_segs = [s.strip(".") for s in re.split(r"[\./\\]", forbidden_clean) if s.strip(".")]
                if not forb_segs:
                    continue

                for imported in imported_modules:
                    imp_segs = [s.strip(".") for s in re.split(r"[\./\\]", imported) if s.strip(".")]
                    if not imp_segs:
                        continue

                    # Exact path segment or contiguous subsequence match
                    f_len = len(forb_segs)
                    matched = False
                    for i in range(len(imp_segs) - f_len + 1):
                        if imp_segs[i:i + f_len] == forb_segs:
                            matched = True
                            break

                    if matched:
                        return True, (
                            f"Katman Mimari İhlali (ARCH01_LAYER_VIOLATION): '{layer_name}' katmanındaki "
                            f"bir dosya doğrudan '{forbidden}' katmanını import edemez! "
                            f"(Tespit edilen import: '{imported}'). Araya bir controller/servis katmanı koyun."
                        )

    return False, ""


# --- OE_SPIKE: OVER-ENGINEERING DETECTION (WARN ONLY) ---
def check_oe_spike(added_text: str) -> Tuple[bool, str]:
    """
    Lightweight heuristic for premature abstraction spikes in small changes.
    Never blocks; only produces an informative warning.
    Criteria: small change (< 50 LOC) introducing 2+ new abstractions (classes/interfaces).
    """
    lines = [line.strip() for line in added_text.splitlines() if line.strip() and not line.strip().startswith(("#", "//", "/*"))]
    loc_count = len(lines)

    if 0 < loc_count <= 50:
        abstractions = re.findall(r"\b(?:class|interface|abstract\s+class)\s+([A-Za-z0-9_]+)", added_text)
        if len(abstractions) >= 2:
            return True, (
                f"Aşırı Soyutlama Uyarısı (OE_SPIKE): Küçük bir kod değişikliğinde ({loc_count} LOC) "
                f"{len(abstractions)} yeni soyutlama ({', '.join(abstractions)}) eklendi. "
                f"YAGNI kuralını gözetin; tekil kullanım için erken soyutlamadan kaçının."
            )

    return False, ""


# --- ARCH_FILE_GROWTH: LARGE FILE & RAPID GROWTH DETECTION (WARN ONLY) ---
def check_arch_file_growth(
    target_file: str,
    old_full_content: str,
    projected_content: str,
    added_lines: List[str],
    is_test_file: bool = False
) -> Tuple[bool, str]:
    """
    Lightweight heuristic to prevent monolithic file accumulation.
    Never blocks; produces an informative warning to guide AI toward modularity.
    Exempts test files, minified/vendor or explicitly exempted cohesive modules.

    Criteria (any of the following):
    A) projected_loc >= 1000
    B) single tool-call additions >= 180 LOC
    C) old_loc >= 800 AND added_lines >= 80 LOC
    """
    if is_test_file:
        return False, ""

    if is_cohesive_module_by_filename(target_file):
        return False, ""

    old_lines = [line for line in old_full_content.splitlines() if line.strip()]
    proj_lines = [line for line in projected_content.splitlines() if line.strip()]
    added_clean = [line for line in added_lines if line.strip() and not line.strip().startswith(("#", "//", "/*", "*"))]

    old_loc = len(old_lines)
    projected_loc = len(proj_lines)
    added_count = len(added_clean)

    reasons = []
    if projected_loc >= 1000:
        reasons.append(f"toplam satır sayısı 1000 sınırını aşıyor ({projected_loc} LOC)")
    elif old_loc >= 800 and added_count >= 80:
        reasons.append(f"800+ satırlık mevcut dosyaya belirgin ekleme yapıldı ({old_loc} -> {projected_loc} LOC, +{added_count} LOC)")
    elif added_count >= 180:
        reasons.append(f"tek seferde büyük kod bloğu eklendi (+{added_count} LOC)")

    if reasons:
        reason_str = "; ".join(reasons)
        basename = os.path.basename(target_file) if target_file else "dosya"
        return True, (
            f"Modülerlik Uyarısı (ARCH_FILE_GROWTH): '{basename}' için {reason_str}. "
            f"Yeni sorumlulukları aynı büyük dosyada biriktirmek yerine ilgili sorumlulukları "
            f"bağımsız ve cohesive modüllere ayırmayı değerlendirin."
        )

    return False, ""


# --- STATIC LINTER & COMPILER DIAGNOSTIC FEEDBACK (FAST PATH READER) ---
def read_recent_diagnostics(target_file: str) -> List[Tuple[str, str]]:
    """
    Reads background static diagnostics (.gravityguard/runtime/diagnostics.json)
    if available. Validates freshness against target file mtime / content hash.
    Execution latency: < 0.5 ms.
    Returns: List of (rule_id, warning_message)
    """
    if not target_file:
        return []

    diagnostics_path = None
    try:
        p = Path(target_file).resolve()
        for parent in [p.parent] + list(p.parents):
            cand = parent / ".gravityguard" / "runtime" / "diagnostics.json"
            if cand.is_file():
                diagnostics_path = cand
                break
    except (OSError, RuntimeError) as e:
        return []

    if not diagnostics_path or not diagnostics_path.exists():
        return []

    try:
        with open(diagnostics_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        entries = data.get("entries", {})
        norm_target = str(Path(target_file).resolve()).replace("\\", "/")

        matched_entry = None
        for path_key, entry in entries.items():
            norm_key = str(Path(path_key).resolve()).replace("\\", "/") if os.path.isabs(path_key) else path_key
            if norm_key == norm_target or norm_target.endswith(path_key.replace("\\", "/")):
                matched_entry = entry
                break

        if not matched_entry:
            return []

        # Freshness check: timestamp must be within last 600s
        entry_time = matched_entry.get("timestamp", 0)
        if time.time() - entry_time > 600:
            return []

        # Stale check: if file on disk has mtime newer than entry by > 2 seconds, diagnostic is likely stale
        if os.path.exists(target_file):
            file_mtime = os.path.getmtime(target_file)
            if file_mtime - entry_time > 2.0:
                return []

        tool = matched_entry.get("tool", "linter")
        errors = matched_entry.get("errors", [])
        if errors:
            first_err = errors[0]
            err_summary = first_err.get("message", "Lint issue")
            rule = first_err.get("rule", "")
            rule_disp = f" [{rule}]" if rule else ""
            msg = (
                f"Statik Doğrulama Uyarısı (STATIC_LINTER_DIAGNOSTIC): '{tool}' önceki yazımda "
                f"{len(errors)} hata tespit etti{rule_disp}: {err_summary}"
            )
            return [("STATIC_LINTER_DIAGNOSTIC", msg)]
    except (IOError, OSError, json.JSONDecodeError, ValueError) as e:
        return []


# --- ASYNC STATIC VALIDATION ORCHESTRATION (HIDDEN BACKGROUND RUNNER) ---

# Windows console-window suppression.
# CREATE_NO_WINDOW (0x08000000) gives the child process a *hidden* console, which
# every console program it later spawns (cmd.exe, npx, ruff, godot, node) inherits.
# DETACHED_PROCESS (0x00000008) is deliberately NOT used: a detached process has no
# console at all, so each console child it spawns allocates a brand-new *visible*
# console window -- that was the source of the flashing terminal windows.
_CREATE_NO_WINDOW = 0x08000000


def _hidden_console_kwargs() -> dict:
    """Returns Popen kwargs that run a background process with no visible window."""
    kwargs = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs["creationflags"] = _CREATE_NO_WINDOW
        kwargs["startupinfo"] = startupinfo
    else:
        kwargs["start_new_session"] = True
    return kwargs


def trigger_background_validation(target_file: str) -> None:
    """
    Spawns async_runner.py in a fully hidden background subprocess.
    Never blocks the AI tool-call loop: returns in ~1ms without waiting for completion.
    Only triggers for supported code files (.py, .ts, .tsx, .js, .jsx, .gd).

    GravityGuard is a PreToolUse hook: it fires BEFORE the AI tool call writes the
    file to disk, so the target file may legitimately not exist yet. Existence is
    therefore NOT checked here -- async_runner.py handles that on its own side.
    """
    if not target_file:
        return

    # Kill switch: tests/CI disable all background spawning so a suite run can
    # never launch real workers that then outlive the test process.
    if os.environ.get("GRAVITYGUARD_DISABLE_ASYNC", "").strip() == "1":
        return

    file_lower = target_file.lower()
    if not file_lower.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".gd")):
        return

    runner_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "async_runner.py")
    if not os.path.exists(runner_path):
        return

    try:
        subprocess.Popen(
            [sys.executable, runner_path, "--file", target_file],
            close_fds=True,
            **_hidden_console_kwargs()
        )
    except (OSError, ValueError):
        return




# ============================================================================
# 4. EXISTING SRP VALIDATION ENGINE (Cohesive Module & AST)
# ============================================================================

def is_ts_cohesive_monolith(content: str) -> bool:
    if re.search(r"(?://|/\*)\s*srp:\s*(?:allow-monolith|cohesive-monolith|bypass|noqa)\b", content, re.IGNORECASE):
        return True

    tab_switches = len(re.findall(r"activeTab\s*===", content))
    scroll_ids = len(re.findall(r"scrollToSection\s*\(", content))
    card_groups = len(re.findall(r"glass-card", content))
    grid_blocks = len(re.findall(r"display:\s*'grid'", content))
    section_markers = len(re.findall(r"(?:/\*|<!--)\s*(?:SECTION|BLOCK|TAB|PART)\b", content, re.IGNORECASE))
    
    multi_section = tab_switches >= 2 or scroll_ids >= 3 or section_markers >= 2
    multi_card = card_groups >= 3 and grid_blocks >= 3
    
    return not (multi_section or multi_card)


def is_py_cohesive_monolith(content: str) -> bool:
    if re.search(r"#\s*(?:srp:\s*(?:allow-monolith|cohesive-monolith|bypass|noqa)|noqa:\s*srp)\b", content, re.IGNORECASE):
        return True
    return False


COHESIVE_MODULE_PATTERNS: Set[str] = {
    "_models.py", "models.py",
    "_types.py", "types.py",
    "_events.py", "events.py",
    "_schemas.py", "schemas.py", "schema.py",
    "_dtos.py", "dtos.py",
    "_interfaces.py", "interfaces.py",
    "_protocols.py", "protocols.py",
    "_properties.py", "properties.py",
    "_operators.py", "operators.py",
    "_constants.py", "constants.py",
    "_exceptions.py", "exceptions.py",
}


def is_cohesive_module_by_filename(file_path: str) -> bool:
    if not file_path:
        return False
    base_name = os.path.basename(file_path.replace("\\", "/")).lower()
    return any(base_name == pat or base_name.endswith(pat) for pat in COHESIVE_MODULE_PATTERNS)


def _get_base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_exempt_class_ast(cls_node: ast.ClassDef, file_path: str) -> bool:
    EXEMPT_BASE_NAMES = {
        "Exception", "BaseException", "Error",
        "Panel", "Operator", "PropertyGroup", "Menu", "Header", "UIList",
        "BaseModel", "Schema",
        "Enum", "IntEnum", "StrEnum",
        "Protocol", "ABC",
    }
    for base in cls_node.bases:
        base_name = _get_base_name(base)
        if base_name in EXEMPT_BASE_NAMES or base_name.endswith("Error") or base_name.endswith("Exception"):
            return True

    for dec in cls_node.decorator_list:
        dec_name = _get_base_name(dec)
        if dec_name in {"dataclass", "pydantic_dataclass"}:
            return True

    file_lower = file_path.lower().replace("\\", "/")
    if ("bpy" in file_lower or "blender" in file_lower or "addon" in file_lower) and cls_node.name.startswith(("OBJECT_OT_", "MESH_OT_", "VIEW3D_PT_", "WM_OT_")):
        return True

    return False


def analyze_python_srp(content: str, file_path: str = "") -> Tuple[bool, str]:
    if is_py_cohesive_monolith(content) or is_cohesive_module_by_filename(file_path):
        return False, "Exempt cohesive module"

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return analyze_python_srp_regex_fallback(content, file_path)
    except Exception:
        # Defensive backstop: ast.parse may fail with things other than
        # SyntaxError. UnicodeEncodeError in particular (lone surrogates in the
        # content) is a ValueError and previously escaped this handler, killing
        # the whole guard process; a crashed hook yields no decision, which lets
        # the write through UNGUARDED. Falling back to the regex path keeps the
        # guard alive and still enforcing. Re-raised inside the fallback so the
        # underlying defect stays visible instead of being silently absorbed.
        try:
            return analyze_python_srp_regex_fallback(content, file_path)
        except Exception:
            raise

    has_ui_imports = False
    has_net_imports = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name.lower()
                if any(pkg in name for pkg in ["tkinter", "pyqt", "pyside", "wx", "kivy"]):
                    has_ui_imports = True
                if any(pkg in name for pkg in ["urllib", "requests", "http.client", "aiohttp", "httpx", "websockets", "socket"]):
                    has_net_imports = True
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").lower()
            if any(pkg in mod for pkg in ["tkinter", "pyqt", "pyside", "wx", "kivy"]):
                has_ui_imports = True
            if any(pkg in mod for pkg in ["urllib", "requests", "http", "aiohttp", "httpx", "websockets", "socket"]):
                has_net_imports = True

    if has_ui_imports and has_net_imports:
        return True, "Sorumluluk Çakışması: Dosya hem UI (Arayüz) hem de Network (Ağ/HTTP) kütüphanelerini aynı anda barındırıyor!"

    top_level_classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    major_classes = [c for c in top_level_classes if not _is_exempt_class_ast(c, file_path)]

    if len(major_classes) >= 4:
        names = [c.name for c in major_classes]
        return True, (
            f"Çoklu Sorumluluk İhlali (God Module): Dosya {len(major_classes)} bağımsız ana iş sınıfı "
            f"({', '.join(names[:3])}...) barındırıyor! Sınıfları ayrı dosyalara taşıyın."
        )

    return False, "SRP Compliant"


def analyze_python_srp_regex_fallback(content: str, file_path: str = "") -> Tuple[bool, str]:
    lines = content.splitlines()
    line_count = len(lines)

    has_ui = bool(re.search(r"\b(import\s+tkinter|import\s+PyQt|from\s+bpy\.types\s+import\s+.*Panel)", content, re.IGNORECASE))
    has_net = bool(re.search(r"\b(import\s+requests|import\s+urllib|import\s+aiohttp|import\s+websockets)", content, re.IGNORECASE))

    if has_ui and has_net:
        return True, "Sorumluluk Çakışması: Dosya hem UI hem de Network kütüphanelerini aynı anda barındırıyor!"

    class_matches = re.findall(r"^class\s+([A-Za-z0-9_]+)(?:\(([^)]*)\))?:", content, re.MULTILINE)
    major_classes = [name for name, bases in class_matches if not any(k in bases for k in ["Exception", "Error", "Panel", "Operator", "Enum", "ABC"])]

    if len(major_classes) >= 5:
        return True, (
            f"Çoklu Sınıf İhlali (God Module): Dosya {len(major_classes)} bağımsız ana sınıf "
            f"({', '.join(major_classes[:4])}...) barındırıyor!"
        )

    return False, f"SRP Compliant (Fallback check: {line_count} lines)"


# ============================================================================
# 5. PHASE 2: TEST EVIDENCE AIRBAG (T1, T2, T3) — WARN ONLY
# ============================================================================

# ============================================================================
# 5.1 STATEFUL TEST EVIDENCE ENGINE (v1.2.7 Pending State Management)
# ============================================================================

def get_test_evidence_file_path(project_root: Optional[Path] = None) -> Path:
    override_dir = os.environ.get("GRAVITYGUARD_LOG_DIR")
    if override_dir:
        return Path(override_dir) / "test_evidence_state.json"
    if project_root is None:
        project_root = Path.cwd()
    runtime_dir = project_root / ".gravityguard" / "runtime"
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
    except (IOError, OSError):
        return runtime_dir / "test_evidence_state.json"
    return runtime_dir / "test_evidence_state.json"


def load_test_evidence_state(project_root: Optional[Path] = None) -> Dict[str, Any]:
    path = get_test_evidence_file_path(project_root)
    if not path.exists():
        return {"version": 1, "pending": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {"version": 1, "pending": {}}
            # Prune stale pending entries older than session TTL (3600s)
            now = time.time()
            pending = data.get("pending", {})
            if isinstance(pending, dict):
                fresh_pending = {
                    k: v for k, v in pending.items()
                    if isinstance(v, dict) and (now - v.get("timestamp", now)) < 3600
                }
                data["pending"] = fresh_pending
            return data
    except (IOError, OSError, json.JSONDecodeError, ValueError):
        return {"version": 1, "pending": {}}


def save_test_evidence_state(state: Dict[str, Any], project_root: Optional[Path] = None) -> None:
    path = get_test_evidence_file_path(project_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        tmp.replace(path)
    except (IOError, OSError):
        return


def record_pending_test_evidence(
    target_file: str,
    candidate_path: Optional[str],
    expected_name: str,
    reason: str,
    project_root: Optional[Path] = None
) -> None:
    norm = target_file.replace("\\", "/")
    state = load_test_evidence_state(project_root)
    state.setdefault("pending", {})[norm] = {
        "candidate_path": candidate_path.replace("\\", "/") if candidate_path else None,
        "expected_name": expected_name,
        "timestamp": time.time(),
        "reason": reason
    }
    save_test_evidence_state(state, project_root)


def resolve_pending_test_evidence(test_file: str, project_root: Optional[Path] = None) -> List[str]:
    norm_test = test_file.replace("\\", "/").lower()
    test_path_obj = Path(norm_test)
    test_stem = test_path_obj.stem.lower()

    base_stem = test_stem
    if base_stem.startswith("test_"):
        base_stem = base_stem[5:]
    if base_stem.endswith((".test", ".spec", "_test")):
        for sfx in (".test", ".spec", "_test"):
            if base_stem.endswith(sfx):
                base_stem = base_stem[:-len(sfx)]
                break

    state = load_test_evidence_state(project_root)
    pending = state.get("pending", {})
    resolved = []

    for prod_path, entry in list(pending.items()):
        cand = (entry.get("candidate_path") or "").lower()
        exp = (entry.get("expected_name") or "").lower()
        prod_stem = Path(prod_path).stem.lower()

        matched = False
        if cand and (norm_test.endswith(cand) or cand.endswith(norm_test) or Path(cand).name == Path(norm_test).name):
            matched = True
        elif exp and (norm_test.endswith(exp) or Path(norm_test).name == exp):
            matched = True
        elif base_stem == prod_stem:
            matched = True

        if matched:
            resolved.append(prod_path)
            del pending[prod_path]

    if resolved:
        save_test_evidence_state(state, project_root)
    return resolved


def get_unresolved_test_evidence(project_root: Optional[Path] = None) -> Dict[str, Any]:
    state = load_test_evidence_state(project_root)
    return state.get("pending", {})


def clear_test_evidence_state(project_root: Optional[Path] = None) -> None:
    save_test_evidence_state({"version": 1, "pending": {}}, project_root)


DEFAULT_EXEMPT_PATTERNS: List[str] = [
    "types", "constants", "index", ".d.ts", "config", "interfaces", "schemas",
    "migration", "migrations", "fixtures", "mock", "mocks"
]

def is_exempt_from_test_evidence(target_file: str, cfg: Optional[dict] = None) -> bool:
    """
    Checks if a target file is exempt from test evidence verification (e.g. types, constants, configs).
    Supports substring patterns and fnmatch glob patterns.
    """
    normalized = target_file.replace("\\", "/").lower()
    basename = Path(normalized).name.lower()

    exempt_patterns = DEFAULT_EXEMPT_PATTERNS
    if cfg and isinstance(cfg, dict):
        te_cfg = cfg.get("testEvidence", {})
        if "exemptPatterns" in te_cfg and isinstance(te_cfg["exemptPatterns"], list):
            exempt_patterns = [p.lower() for p in te_cfg["exemptPatterns"]]

    for pat in exempt_patterns:
        pat_clean = pat.lstrip("/")
        if (
            pat in basename or
            f"/{pat}/" in normalized or
            fnmatch.fnmatch(basename, pat) or
            fnmatch.fnmatch(normalized, pat) or
            fnmatch.fnmatch(normalized, f"*/{pat_clean}") or
            fnmatch.fnmatch(normalized, f"*{pat_clean}")
        ):
            return True

    if normalized.endswith(".d.ts"):
        return True
    if not normalized.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
        return True

    return False


def resolve_candidate_test_file(target_file: str, cfg: Optional[dict] = None) -> Tuple[Optional[str], str]:
    """
    Given a production file, searches for its candidate test file using standard naming conventions.
    Returns: (found_path_or_None, primary_expected_name)
    """
    normalized = target_file.replace("\\", "/")
    target_path = Path(normalized)
    stem = target_path.stem
    suffix = target_path.suffix.lower()
    parent_dir = target_path.parent

    # Candidate file names
    candidate_names = []
    if suffix == ".py":
        candidate_names = [f"test_{stem}.py", f"{stem}_test.py"]
    elif suffix in [".ts", ".tsx", ".js", ".jsx"]:
        candidate_names = [f"{stem}.test{suffix}", f"{stem}.spec{suffix}"]
    else:
        candidate_names = [f"test_{stem}{suffix}"]

    primary_expected = candidate_names[0] if candidate_names else f"test_{stem}.py"

    # 1. Search in the same directory
    for name in candidate_names:
        candidate = parent_dir / name
        if candidate.is_file():
            return str(candidate).replace("\\", "/"), primary_expected

    # 2. Search in common test root directories
    search_dirs = [parent_dir]
    curr = parent_dir
    for _ in range(5):
        if curr.parent == curr:
            break
        curr = curr.parent
        search_dirs.append(curr)

    test_roots = ["tests", "__tests__", "test"]
    if cfg and isinstance(cfg, dict):
        te_cfg = cfg.get("testEvidence", {})
        if "testRoots" in te_cfg and isinstance(te_cfg["testRoots"], list):
            test_roots = te_cfg["testRoots"]

    source_roots = ["src", "lib", "app", "core", "agent", "engine"]
    if cfg and isinstance(cfg, dict):
        te_cfg = cfg.get("testEvidence", {})
        if "sourceRoots" in te_cfg and isinstance(te_cfg["sourceRoots"], list):
            source_roots = [r.lower() for r in te_cfg["sourceRoots"]]

    for root_cand in search_dirs:
        for tr in test_roots:
            td = root_cand / tr
            if td.is_dir():
                for name in candidate_names:
                    tfile = td / name
                    if tfile.is_file():
                        return str(tfile).replace("\\", "/"), primary_expected
                    try:
                        rel = target_path.relative_to(root_cand)
                        rel_parts = list(rel.parts)
                        if rel_parts and rel_parts[0].lower() in source_roots:
                            rel_parts.pop(0)
                        if rel_parts:
                            rel_parts[-1] = name
                            mirrored = td / Path(*rel_parts)
                            if mirrored.is_file():
                                return str(mirrored).replace("\\", "/"), primary_expected
                    except ValueError:
                        continue

    return None, primary_expected


def check_t1_missing_test(
    target_file: str,
    added_text: str,
    cfg: Optional[dict] = None
) -> Tuple[bool, str, Optional[str]]:
    """
    T1 — MISSING_RELATED_TEST (WARN ONLY).
    Triggers when production code changes but no candidate test file exists on disk,
    or candidate test file exists but was not updated in the active session window.
    Returns: (warn_triggered, warn_message, candidate_test_path)
    """
    if not added_text.strip():
        return False, "", None

    if is_exempt_from_test_evidence(target_file, cfg):
        return False, "", None

    candidate_path, expected_name = resolve_candidate_test_file(target_file, cfg)

    if not candidate_path or not os.path.exists(candidate_path):
        return True, (
            f"Test Kanıtı Uyarısı (T1_MISSING_RELATED_TEST): Üretim kodunda değişiklik yapıldı "
            f"ancak ilişkili test dosyası ('{expected_name}') diskte bulunamadı. "
            f"Davranış değişikliği için ilgili test dosyasını oluşturmayı veya güncellemeyi değerlendirin."
        ), None

    session_window = 300
    if cfg and isinstance(cfg, dict):
        session_window = cfg.get("testEvidence", {}).get("sessionWindowSeconds", 300)

    try:
        test_mtime = os.path.getmtime(candidate_path)
        if (time.time() - test_mtime) > session_window:
            return True, (
                f"Test Kanıtı Uyarısı (T1_MISSING_RELATED_TEST): Üretim kodu değiştirildi ancak "
                f"ilişkili test dosyası ('{candidate_path}') bu oturumda ({session_window}s) güncellenmedi."
            ), candidate_path
    except OSError:
        test_mtime = 0.0

    return False, "", candidate_path


def check_t2_observable_assertion(
    added_lines: List[str],
    added_text: str,
    is_python: bool,
    is_ts: bool,
    projected_content: str = "",
    added_line_numbers: Optional[Set[int]] = None
) -> Tuple[bool, str]:
    """
    T2 — NO_OBSERVABLE_ASSERTION (WARN ONLY).
    Triggers when an individual test case (def test_..., it(...), test(...)) is added or modified,
    but no observable assertion pattern is detected in THAT SPECIFIC test case's body.
    Exempts setup/teardown/describe blocks (beforeEach, describe, setUp).
    Does not allow assertions in another test case to mask an unasserted test case.
    """
    if not added_text.strip():
        return False, ""

    if not projected_content:
        projected_content = added_text
    if added_line_numbers is None:
        added_line_numbers = set(range(1, added_text.count("\n") + 2))

    unasserted_tests: List[str] = []

    if is_python:
        # 1. AST extraction from projected_content
        ast_worked = False
        try:
            tree = ast.parse(projected_content)
            lines = projected_content.splitlines()
            funcs = []
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    funcs.append(node)
                elif isinstance(node, ast.ClassDef):
                    for sub in node.body:
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            funcs.append(sub)

            for fn in funcs:
                name = fn.name
                if not (name.startswith("test_") or name.startswith("test")):
                    continue
                if name in ("setUp", "tearDown", "setUpClass", "tearDownClass"):
                    continue
                start_line = getattr(fn, "lineno", 1)
                end_line = getattr(fn, "end_lineno", start_line)
                fn_lines = set(range(start_line, end_line + 1))
                if fn_lines & added_line_numbers:
                    body_slice = lines[start_line - 1 : end_line]
                    body_text = "\n".join(body_slice)
                    has_assert = bool(re.search(
                        r"\b(?:assert\b|self\.assert[A-Za-z0-9_]+|pytest\.raises|pytest\.approx)",
                        body_text
                    ))
                    if not has_assert:
                        unasserted_tests.append(name)
            ast_worked = True
        except Exception:
            ast_worked = False

        # Fallback to regex on added_text if AST fails
        if not ast_worked:
            py_test_defs = re.findall(r"^\s*def\s+(test_[a-zA-Z0-9_]+)\s*\(", added_text, re.MULTILINE)
            if py_test_defs:
                has_assert = bool(re.search(
                    r"\b(?:assert\b|self\.assert[A-Za-z0-9_]+|pytest\.raises|pytest\.approx)",
                    added_text
                ))
                if not has_assert:
                    unasserted_tests.extend(py_test_defs)

    if is_ts or not is_python:
        # TS/JS test case extraction from projected_content
        pattern = re.compile(r"^\s*(?:it|test)\s*\(\s*[\"'\`]([^\"'\`]+)[\"'\`]", re.MULTILINE)
        matches = list(pattern.finditer(projected_content))
        lines = projected_content.splitlines()

        if matches:
            for idx, match in enumerate(matches):
                test_name = match.group(1)
                start_char = match.start()
                start_line = projected_content[:start_char].count("\n") + 1

                if idx + 1 < len(matches):
                    end_char = matches[idx + 1].start()
                else:
                    end_char = len(projected_content)

                test_chunk = projected_content[start_char:end_char]
                end_line = start_line + test_chunk.count("\n")
                fn_lines = set(range(start_line, end_line + 1))

                if fn_lines & added_line_numbers:
                    has_assert = bool(re.search(
                        r"\b(?:expect\s*\(|assert\s*[\(\.]|\.to(?:Be|Equal|StrictEqual|Throw|HaveBeenCalled|Match|Contain|BeTruthy|BeFalsy|BeNull|BeUndefined|BeDefined|BeGreaterThan|BeLessThan|Reject|Resolve)\b|t\.(?:is|true|deepEqual|false)\b|\.should\.[a-zA-Z]+)",
                        test_chunk
                    ))
                    if not has_assert:
                        unasserted_tests.append(test_name)
        elif is_ts:
            ts_test_defs = re.findall(r"\b(?:it|test)\s*\(\s*[\"'\`]([^\"'\`]+)[\"'\`]", added_text)
            if ts_test_defs:
                has_assert = bool(re.search(
                    r"\b(?:expect\s*\(|assert\s*[\(\.]|\.to(?:Be|Equal|StrictEqual|Throw|HaveBeenCalled|Match|Contain|BeTruthy|BeFalsy|BeNull|BeUndefined|BeDefined|BeGreaterThan|BeLessThan|Reject|Resolve)\b|t\.(?:is|true|deepEqual|false)\b|\.should\.[a-zA-Z]+)",
                    added_text
                ))
                if not has_assert:
                    unasserted_tests.extend(ts_test_defs)

    if unasserted_tests:
        sample_tests = ", ".join(f"'{n}'" for n in unasserted_tests[:2])
        return True, (
            f"Test Gözlem Uyarısı (T2_NO_OBSERVABLE_ASSERTION): Eklenen/değiştirilen test case "
            f"({sample_tests}) içinde gözlemlenebilir bir assertion (assert, expect, self.assert*, pytest.raises) "
            f"tespit edilemedi. İçi boş veya assertionsız test yazılmasından kaçının."
        )

    return False, ""


def check_t3_symbol_to_test_link(
    target_file: str,
    added_text: str,
    candidate_test_path: Optional[str],
    is_python: bool,
    is_ts: bool,
    projected_content: str = "",
    added_line_numbers: Optional[Set[int]] = None
) -> Tuple[bool, str]:
    """
    T3 — SYMBOL_TO_TEST_LINK (WARN ONLY).
    Checks whether modified/added top-level functions or classes (including body-only changes)
    are referenced by name in the candidate test file.
    Only checks function/class symbols (ignores scalar constants).
    Emits WARN if at least one changed symbol is missing from the test file.
    Does not run if candidate test file does not exist (T1 covers absence).
    """
    if not added_text.strip() or not candidate_test_path:
        return False, ""

    if not os.path.isfile(candidate_test_path):
        return False, ""

    if not projected_content:
        projected_content = added_text
    if added_line_numbers is None:
        added_line_numbers = set(range(1, added_text.count("\n") + 2))

    extracted_symbols: List[str] = []

    if is_python:
        try:
            tree = ast.parse(projected_content)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    name = node.name
                    if name.startswith("_"):
                        continue
                    start_line = getattr(node, "lineno", 1)
                    end_line = getattr(node, "end_lineno", start_line)
                    if set(range(start_line, end_line + 1)) & added_line_numbers:
                        extracted_symbols.append(name)
        except Exception:
            funcs = re.findall(r"^def\s+([a-zA-Z0-9_]+)\s*\(", added_text, re.MULTILINE)
            classes = re.findall(r"^class\s+([a-zA-Z0-9_]+)", added_text, re.MULTILINE)
            extracted_symbols = [s for s in funcs + classes if not s.startswith("_")]

    elif is_ts:
        func_pattern = re.compile(
            r"^(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+([a-zA-Z0-9_]+)",
            re.MULTILINE
        )
        class_pattern = re.compile(
            r"^(?:export\s+(?:default\s+)?)?class\s+([a-zA-Z0-9_]+)",
            re.MULTILINE
        )
        arrow_pattern = re.compile(
            r"^(?:export\s+)?const\s+([a-zA-Z0-9_]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_]+)\s*=>",
            re.MULTILINE
        )
        all_defs = []
        for pat in (func_pattern, class_pattern, arrow_pattern):
            for m in pat.finditer(projected_content):
                name = m.group(1)
                if not name.startswith("_"):
                    start_char = m.start()
                    start_line = projected_content[:start_char].count("\n") + 1
                    all_defs.append((start_line, name))

        all_defs.sort(key=lambda x: x[0])
        lines = projected_content.splitlines()
        for idx, (start_line, name) in enumerate(all_defs):
            if idx + 1 < len(all_defs):
                end_line = all_defs[idx + 1][0] - 1
            else:
                end_line = len(lines)
            if set(range(start_line, end_line + 1)) & added_line_numbers:
                extracted_symbols.append(name)

        if not extracted_symbols:
            exp_funcs = re.findall(r"export\s+(?:async\s+)?function\s+([a-zA-Z0-9_]+)", added_text)
            exp_arrows = re.findall(r"export\s+const\s+([a-zA-Z0-9_]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_]+)\s*=>", added_text)
            exp_classes = re.findall(r"export\s+class\s+([a-zA-Z0-9_]+)", added_text)
            extracted_symbols = [s for s in exp_funcs + exp_arrows + exp_classes if not s.startswith("_")]

    if not extracted_symbols:
        return False, ""

    try:
        with open(candidate_test_path, "r", encoding="utf-8", errors="ignore") as f:
            test_content = f.read()
    except (IOError, OSError):
        return False, ""

    missing_symbols = []
    for sym in extracted_symbols:
        if not re.search(r"\b" + re.escape(sym) + r"\b", test_content):
            missing_symbols.append(sym)

    if missing_symbols:
        sample = ", ".join(f"'{s}'" for s in missing_symbols[:3])
        return True, (
            f"Sembol-Test İlişki Uyarısı (T3_SYMBOL_TO_TEST_LINK): Değiştirilen üretim sembolü "
            f"({sample}) ilgili test dosyasında ('{Path(candidate_test_path).name}') doğrudan referans edilmemiş. "
            f"Test dosyasının bu davranışı doğrudan veya dolaylı test ettiğinden emin olun."
        )

    return False, ""


def evaluate_test_evidence(
    target_file: str,
    is_test_file: bool,
    added_lines: List[str],
    added_text: str,
    projected_content: str = "",
    added_line_numbers: Optional[Set[int]] = None,
    cfg: Optional[dict] = None,
    is_python: bool = True,
    is_ts: bool = False
) -> List[Tuple[str, str]]:
    """
    Evaluates Phase 2 Test Evidence rules (T1, T2, T3).
    Returns a list of (rule_id, warning_message) tuples. Never blocks.
    """
    warnings = []

    if cfg and isinstance(cfg, dict):
        if not cfg.get("testEvidence", {}).get("enabled", True):
            return warnings

    if is_test_file:
        resolved = resolve_pending_test_evidence(target_file)
        if resolved:
            log_event("edit", "APPROVED", target_file, f"Resolved pending test evidence for: {', '.join(resolved)}", rule_id="T1_RESOLVED")

        t2_warn, t2_msg = check_t2_observable_assertion(
            added_lines, added_text, is_python, is_ts,
            projected_content=projected_content,
            added_line_numbers=added_line_numbers
        )
        if t2_warn:
            warnings.append(("T2_NO_OBSERVABLE_ASSERTION", t2_msg))
    else:
        t1_warn, t1_msg, candidate_path = check_t1_missing_test(target_file, added_text, cfg)
        if t1_warn:
            deferred = True
            if cfg and isinstance(cfg, dict):
                deferred = cfg.get("testEvidence", {}).get("deferredMode", True)

            if deferred:
                candidate_p, expected_n = resolve_candidate_test_file(target_file, cfg)
                record_pending_test_evidence(target_file, candidate_p, expected_n, t1_msg)
                log_event("edit", "APPROVED", target_file, f"Pending test evidence recorded ({expected_n})", rule_id="T1_PENDING")
            else:
                warnings.append(("T1_MISSING_RELATED_TEST", t1_msg))

        if candidate_path and os.path.isfile(candidate_path):
            t3_warn, t3_msg = check_t3_symbol_to_test_link(
                target_file, added_text, candidate_path, is_python, is_ts,
                projected_content=projected_content,
                added_line_numbers=added_line_numbers
            )
            if t3_warn:
                warnings.append(("T3_SYMBOL_TO_TEST_LINK", t3_msg))

    return warnings


# ============================================================================
# 6. MAIN DISPATCHER & RULE ORCHESTRATOR
# ============================================================================

def validate_gravityguard():
    start_time = time.perf_counter()

    raw_input = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not raw_input.strip():
        print(json.dumps({"decision": "allow"}))
        sys.exit(0)
        
    try:
        payload = json.loads(raw_input)
    except Exception:
        print(json.dumps({"decision": "allow"}))
        sys.exit(0)

    # 0. Lifecycle Hook Check: Stop / PostInvocation or CLI --stop flag
    if payload.get("terminationReason") or "--stop" in sys.argv:
        unresolved = get_unresolved_test_evidence()
        if unresolved:
            missing_items = [f"'{p}' (beklenen test: {info.get('expected_name', 'test')})" for p, info in unresolved.items()]
            warn_reason = f"Test Kanıtı Uyarısı (T1): Oturum tamamlandı ancak şu üretim kodları için test kanıtı bulunamadı: {', '.join(missing_items)}"
            log_event("stop", "WARNING", "workspace", warn_reason, rule_id="T1_FINAL_UNRESOLVED")
            print(json.dumps({"decision": "allow", "reason": warn_reason}))
        else:
            print(json.dumps({"decision": "allow"}))
        sys.exit(0)

    tool_call = payload.get("toolCall", {})
    args = tool_call.get("args", {})
    target_file = args.get("TargetFile") or args.get("target_file") or args.get("file_path") or ""
    tool_name = tool_call.get("name", "edit")
    
    # 1. Normalize path
    normalized_path = target_file.replace("\\\\", "/").replace("\\", "/")
    file_lower = normalized_path.lower()

    path_obj = Path(normalized_path)
    file_name_lower = path_obj.name.lower()
    parent_parts_lower = [part.lower() for part in path_obj.parent.parts]

    is_in_test_dir = any(d in parent_parts_lower for d in ("tests", "test", "__tests__"))
    is_test_name = (
        "test_" in file_name_lower or
        "_test" in file_name_lower or
        ".test." in file_name_lower or
        ".spec." in file_name_lower
    )
    is_test_file = is_in_test_dir or is_test_name
    is_vendor_or_cache = any(m in file_lower for m in [
        "/node_modules/", "/venv/", "/.venv/", "/env/", "/.env/", "/dist/", "/build/",
        "/.git/", "/__pycache__/", "/runs/", "/scratch/", "/brain/", "/.gemini/"
    ])
    is_data_or_doc = file_lower.endswith((
        ".json", ".css", ".scss", ".md", ".txt", ".yaml", ".yml", ".toml", ".ini",
        ".lock", ".svg", ".gitignore"
    ))
    is_binary_asset = file_lower.endswith((
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".blend", ".exe", ".dll",
        ".so", ".bin", ".wasm", ".zip", ".tar", ".gz"
    ))

    # Fast-pass for pure binary assets (diffing binary content is meaningless and unsafe)
    if is_binary_asset:
        if target_file:
            log_event(tool_name, "APPROVED", target_file, "Exempt file (Binary Asset)", rule_id="EXEMPT")
        print(json.dumps({"decision": "allow"}))
        sys.exit(0)

    # 3. Extract projected and old content, compute exact diff
    old_full_content, projected_content = get_projected_and_old_content(target_file, tool_name, args)
    added_lines, added_text, added_line_numbers = get_diff_analysis(old_full_content, projected_content)

    all_warnings: List[Tuple[str, str]] = []

    # ========================================================================
    # GUARD 0: G0 — SECRET LEAK GUARD (BLOCK / WARN)
    # Executed for ALL text files (code, config, docs, vendor, cache)
    # ========================================================================
    g0_violated, g0_reason, g0_warn = check_g0_secret_leak(added_text)
    if g0_warn:
        log_event(tool_name, "WARNING", target_file, g0_warn, rule_id="G0_SECRET_LEAK")
        all_warnings.append(("G0_SECRET_LEAK", g0_warn))
    if g0_violated:
        log_event(tool_name, "BLOCKED", target_file, g0_reason, rule_id="G0_SECRET_LEAK")
        print(json.dumps({
            "decision": "deny",
            "reason": f"🛑 [G0_SECRET_LEAK]: '{target_file}' - {g0_reason}"
        }))
        sys.exit(0)

    # Fast-pass for vendor, cache, and non-code text assets (ONLY AFTER G0 IS CLEAN)
    if is_vendor_or_cache or (is_data_or_doc and not file_lower.endswith((".py", ".ts", ".tsx", ".js", ".jsx"))):
        if target_file:
            log_event(tool_name, "APPROVED", target_file, "Exempt file (Vendor/Cache/Asset)", rule_id="EXEMPT")
        if all_warnings:
            warn_parts = [f"[{wid}] {wmsg}" for wid, wmsg in all_warnings]
            print(json.dumps({"decision": "allow", "reason": " ⚠ ".join(warn_parts)}))
        else:
            print(json.dumps({"decision": "allow"}))
        sys.exit(0)

    is_python = file_lower.endswith(".py")
    is_ts = file_lower.endswith((".ts", ".tsx", ".js", ".jsx"))

    # ========================================================================
    # GUARD 1: G1 — SILENT EXCEPTION (BLOCK)
    # ========================================================================
    if not is_test_file:
        g1_violated, g1_reason = check_g1_silent_exception(
            added_lines, added_text, added_line_numbers, projected_content, is_python, is_ts
        )
        if g1_violated:
            log_event(tool_name, "BLOCKED", target_file, g1_reason, rule_id="G1_SILENT_EXCEPTION")
            print(json.dumps({
                "decision": "deny",
                "reason": f"🛑 [G1_SILENT_EXCEPTION]: '{target_file}' - {g1_reason}"
            }))
            sys.exit(0)

    # ========================================================================
    # GUARD 2: G2 — TEST INTEGRITY (BLOCK / WARN)
    # ========================================================================
    if is_test_file:
        g2_violated, g2_reason, g2_warn = check_g2_test_integrity(
            added_text, old_full_content, projected_content, is_test_file
        )
        if g2_warn:
            log_event(tool_name, "WARNING", target_file, g2_warn, rule_id="G2_TEST_INTEGRITY")
            all_warnings.append(("G2_TEST_INTEGRITY", g2_warn))
        if g2_violated:
            log_event(tool_name, "BLOCKED", target_file, g2_reason, rule_id="G2_TEST_INTEGRITY")
            print(json.dumps({
                "decision": "deny",
                "reason": f"🛑 [G2_TEST_INTEGRITY]: '{target_file}' - {g2_reason}"
            }))
            sys.exit(0)

    # ========================================================================
    # GUARD 3: G3 — COMPILER & LINTER BYPASS (WARN ONLY)
    # ========================================================================
    g3_matches = check_g3_compiler_bypass(added_text)
    if g3_matches:
        warn_msg = f"Yeni linter/derleyici susturması eklendi ({', '.join(g3_matches)}). Hatanın kök nedenini çözmeyi değerlendirin."
        log_event(tool_name, "WARNING", target_file, warn_msg, rule_id="G3_COMPILER_BYPASS")
        all_warnings.append(("G3_COMPILER_BYPASS", warn_msg))

    # ========================================================================
    # GUARD 4: G4 — IMPORT MATRIX (BLOCK)
    # ========================================================================
    g4_violated, g4_reason = check_g4_import_matrix(target_file, added_text)
    if g4_violated:
        log_event(tool_name, "BLOCKED", target_file, g4_reason, rule_id="G4_IMPORT_MATRIX")
        print(json.dumps({
            "decision": "deny",
            "reason": f"🛑 [G4_IMPORT_MATRIX]: '{target_file}' - {g4_reason}"
        }))
        sys.exit(0)

    # ========================================================================
    # GUARD 5: OE_SPIKE — OVER-ENGINEERING (WARN ONLY)
    # ========================================================================
    oe_triggered, oe_msg = check_oe_spike(added_text)
    if oe_triggered:
        log_event(tool_name, "WARNING", target_file, oe_msg, rule_id="OE_SPIKE")
        all_warnings.append(("OE_SPIKE", oe_msg))

    # ========================================================================
    # GUARD 6: ARCH_FILE_GROWTH — LARGE FILE & RAPID GROWTH (WARN ONLY)
    # ========================================================================
    arch_triggered, arch_msg = check_arch_file_growth(
        target_file=target_file,
        old_full_content=old_full_content,
        projected_content=projected_content,
        added_lines=added_lines,
        is_test_file=is_test_file
    )
    if arch_triggered:
        log_event(tool_name, "WARNING", target_file, arch_msg, rule_id="ARCH_FILE_GROWTH")
        all_warnings.append(("ARCH_FILE_GROWTH", arch_msg))

    # ========================================================================
    # GUARD 7: EXISTING SRP (Single Responsibility Principle)
    # ========================================================================
    if not is_test_file:
        if is_python:
            is_violation, reason = analyze_python_srp(projected_content, file_path=target_file)
            if is_violation:
                log_event(tool_name, "BLOCKED", target_file, reason, rule_id="SRP_BOUNDARY")
                print(json.dumps({
                    "decision": "deny",
                    "reason": f"🛑 [SRP_BOUNDARY]: '{target_file}' - {reason}"
                }))
                sys.exit(0)

        elif is_ts:
            tab_matches = len(re.findall(r"activeTab\s*===", projected_content))
            card_matches = len(re.findall(r"glass-card", projected_content))
            grid_blocks = len(re.findall(r"display:\s*'grid'", projected_content))
            scroll_ids = len(re.findall(r"scrollToSection\s*\(", projected_content))
            multi_job = (tab_matches >= 2 and card_matches >= 3) or (scroll_ids >= 3 and grid_blocks >= 3)
            
            if multi_job and not is_ts_cohesive_monolith(projected_content):
                reason_msg = f"SRP İhlali: Dosya {tab_matches} sekme, {card_matches} kart ve {grid_blocks} grid bloğu içeriyor."
                log_event(tool_name, "BLOCKED", target_file, reason_msg, rule_id="SRP_BOUNDARY")
                print(json.dumps({
                    "decision": "deny",
                    "reason": f"🛑 [SRP_BOUNDARY]: '{target_file}' - {reason_msg}"
                }))
                sys.exit(0)

    # ========================================================================
    # GUARD 8: PHASE 2 TEST EVIDENCE AIRBAG (T1, T2, T3) — WARN ONLY
    # ========================================================================
    cfg = load_gravityguard_config(target_file)
    test_evidence_warnings = evaluate_test_evidence(
        target_file=target_file,
        is_test_file=is_test_file,
        added_lines=added_lines,
        added_text=added_text,
        projected_content=projected_content,
        added_line_numbers=added_line_numbers,
        cfg=cfg,
        is_python=is_python,
        is_ts=is_ts
    )
    for rule_id, warn_msg in test_evidence_warnings:
        log_event(tool_name, "WARNING", target_file, warn_msg, rule_id=rule_id)
        all_warnings.append((rule_id, warn_msg))

    # ========================================================================
    # GUARD 9: STATIC LINTER & COMPILER DIAGNOSTIC FEEDBACK (WARN ONLY)
    # ========================================================================
    diag_warnings = read_recent_diagnostics(target_file)
    for d_rule, d_msg in diag_warnings:
        log_event(tool_name, "WARNING", target_file, d_msg, rule_id=d_rule)
        all_warnings.append((d_rule, d_msg))

    # ========================================================================
    # PASS / APPROVED
    # ========================================================================
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    log_event(tool_name, "APPROVED", target_file, f"All Guards Passed ({elapsed_ms:.1f}ms)", rule_id="PASS")
    res_payload = {"decision": "allow"}
    if all_warnings:
        # NOTE: the hook schema (hooks.md -> PreToolUse Output) allows ONLY
        # `decision`, `reason`, `permissionOverrides` and `overwrite`. Payloads are
        # protojson-encoded, and protojson REJECTS unknown fields — emitting
        # `warnings` / `warning_rule_ids` made the harness throw away the whole
        # response (`proto: unknown field "warnings"`), which turned a WARN into a
        # hard tool failure and blocked the write. Warnings therefore travel inside
        # `reason`, the only schema-valid field surfaced to the user/agent, with a
        # `[RULE_ID]` prefix so they remain machine-readable.
        res_payload["reason"] = " ⚠ ".join(
            f"[{rule_id}] {msg}" for rule_id, msg in all_warnings
        )
    print(json.dumps(res_payload))
    trigger_background_validation(target_file)
    sys.exit(0)



if __name__ == "__main__":
    validate_gravityguard()
