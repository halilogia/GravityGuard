"""Token output guard: stops context-bloating tool calls at the source.

A PreToolUse hook cannot rewrite a tool's output, but it can prevent the two
largest known causes of context bloat:
  1. Reading an entire large file instead of a bounded window.
  2. Running unbounded recursive listing/diff commands.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .operations import PATH_KEYS

READ_TOOLS = frozenset(("view_file", "read_file", "read_file_content", "view", "read", "cat"))
COMMAND_TOOLS = frozenset(("run_command", "bash", "execute_command", "shell", "cmd"))

DEFAULT_MAX_FULL_READ_BYTES = 150_000
DEFAULT_MAX_RANGE_LINES = 800

# Source files above this size are mapped first (token-lens outline) instead of read whole.
CODE_EXTS = frozenset((".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".gd", ".cs",
                       ".go", ".rs", ".java", ".kt"))
CODE_OUTLINE_LINES = 500
# Read returns these as images/pages, not lines: the size rules do not apply.
NON_TEXT_EXTS = frozenset((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".ico",
                           ".pdf", ".ipynb"))

RULE_ID = "TOOL_OUTPUT_BLOAT"


@dataclass(frozen=True)
class TokenGuardResult:
    level: str  # "deny" | "warn"
    rule_id: str
    reason: str


def _first_path(args: Dict[str, Any]) -> Optional[str]:
    for key in PATH_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _resolve(path: str, cwd: str, project_root: Optional[str]) -> str:
    if os.path.isabs(path):
        return os.path.realpath(path)
    base = cwd if os.path.isabs(cwd or "") else (project_root or os.getcwd())
    return os.path.realpath(os.path.join(base, path))


def _count_lines(path: str, limit: int = 200_000) -> int:
    count = 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for _ in handle:
                count += 1
                if count >= limit:
                    break
    except OSError:
        return 0
    return count


def _int_arg(args: Dict[str, Any], *keys: str) -> Optional[int]:
    for key in keys:
        value = args.get(key)
        if type(value) is int:
            return value
    return None


def _code_outline_hint(path: str, start: Optional[int], end: Optional[int]) -> Optional[TokenGuardResult]:
    """Large source file read whole (or in a huge window): send the agent to token-lens first."""
    if os.path.splitext(path)[1].lower() not in CODE_EXTS:
        return None
    if start is not None and end is not None and end - start + 1 <= CODE_OUTLINE_LINES:
        return None
    total = _count_lines(path)
    if total <= CODE_OUTLINE_LINES:
        return None
    if start is not None and end is None and total - start + 1 <= CODE_OUTLINE_LINES:
        return None
    name = os.path.basename(path)
    return TokenGuardResult(
        "deny",
        RULE_ID,
        (
            f"Baglam korumasi: '{name}' {total:,} satirlik kaynak dosya; tamami okunmaz. "
            f"1) token-lens `read_outline` ile sembol haritasini al (Claude Code'da once ToolSearch "
            f"'select:mcp__token-lens__read_outline,mcp__token-lens__read_symbol,mcp__token-lens__find_symbol'), "
            f"2) gereken fonksiyonu `read_symbol` ile oku. Satir araligi biliniyorsa en fazla "
            f"{CODE_OUTLINE_LINES} satirlik pencere oku (Read: offset+limit, Antigravity: StartLine/EndLine)."
        ),
    )


def evaluate_read_guard(
    tool_name: str,
    args: Dict[str, Any],
    cwd: str = "",
    project_root: Optional[str] = None,
    max_bytes: int = DEFAULT_MAX_FULL_READ_BYTES,
    max_range_lines: int = DEFAULT_MAX_RANGE_LINES,
) -> Optional[TokenGuardResult]:
    if tool_name.lower() not in READ_TOOLS:
        return None
    raw_path = _first_path(args)
    if not raw_path:
        return None
    path = _resolve(raw_path, cwd, project_root)
    if not os.path.isfile(path) or os.path.splitext(path)[1].lower() in NON_TEXT_EXTS:
        return None
    try:
        size = os.path.getsize(path)
    except OSError:
        return None

    start = _int_arg(args, "StartLine", "start_line", "start", "offset")
    end = _int_arg(args, "EndLine", "end_line", "end")
    limit = _int_arg(args, "limit")
    if limit is not None and limit > 0 and end is None:
        # Claude Code / Codex Read: offset (1-based line) + limit.
        end = (start or 1) + limit - 1
        start = start or 1

    code_hint = _code_outline_hint(path, start, end)
    if code_hint:
        return code_hint
    if size <= max_bytes:
        return None
    total_lines = _count_lines(path)
    name = os.path.basename(path)
    kb = size // 1024

    if start is not None and end is not None:
        span = end - start + 1
        if span <= max_range_lines:
            return None
        return TokenGuardResult(
            "deny",
            RULE_ID,
            (
                f"Baglam korumasi: '{name}' icin istenen aralik {span:,} satir; ust sinir {max_range_lines}. "
                f"Dosya {total_lines:,} satir / {kb:,} KB. Daha kucuk bir StartLine/EndLine penceresi sec "
                f"veya `tsave run` / token-lens kullan."
            ),
        )

    if start is not None and end is None:
        remaining = max(0, total_lines - start + 1)
        if remaining <= max_range_lines:
            return None

    return TokenGuardResult(
        "deny",
        RULE_ID,
        (
            f"Baglam korumasi: '{name}' dosyasinin tamami okunamaz ({total_lines:,} satir / {kb:,} KB). "
            f"StartLine ve EndLine ile en fazla {max_range_lines} satirlik pencere oku "
            f"(ornek: StartLine=1, EndLine=400) ya da sembol aramasi kullan."
        ),
    )


_RECURSIVE_LIST = re.compile(r"(dir\s+/s\b)|(Get-ChildItem[^\n|]*-Recurse)|(\bfind\s+/\s)|(grep\s+-r\s+/)", re.IGNORECASE)
# Output already narrowed: a depth limit, a count flag, or a pipe into a filter/reducer.
_LIMITED = re.compile(
    r"(-Depth\b)|(-TotalCount)|(-(First|Last|Take|Tail|Head)\s+\d+)"
    r"|(\|\s*(Select-Object|Select|Measure-Object|Measure|Where-Object|Where|Select-String|findstr|grep|rg|head|tail|wc|more|less)\b)",
    re.IGNORECASE)
_GIT_LOG_UNBOUNDED = re.compile(r"\bgit\s+log\b(?!.*(-n\s*\d+|(?<![\w-])-\d+\b|--max-count|--oneline\s+-n|\|\s*head|\|\s*Select-Object))", re.IGNORECASE)
_GIT_DIFF_UNBOUNDED = re.compile(r"\bgit\s+diff\s*$", re.IGNORECASE)
_BIG_CAT = re.compile(r"\b(cat|type|Get-Content)\s+[\"']?([^\"'\s|>]+)", re.IGNORECASE)


def evaluate_command_guard(
    tool_name: str,
    args: Dict[str, Any],
    cwd: str = "",
    project_root: Optional[str] = None,
    max_bytes: int = DEFAULT_MAX_FULL_READ_BYTES,
) -> Optional[TokenGuardResult]:
    if tool_name.lower() not in COMMAND_TOOLS:
        return None
    command = ""
    for key in ("CommandLine", "command", "cmd", "script"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            command = value
            break
    if not command:
        return None

    reason: Optional[str] = None
    if _RECURSIVE_LIST.search(command) and not _LIMITED.search(command):
        reason = "Sinirsiz ozyinelemeli dizin listeleme tespit edildi; cikti binlerce satir olabilir."
    elif _GIT_LOG_UNBOUNDED.search(command) and not _LIMITED.search(command):
        reason = "Sinirsiz `git log` tespit edildi; `-n 20` veya `--max-count` ekleyin."
    elif _GIT_DIFF_UNBOUNDED.search(command) and not _LIMITED.search(command):
        reason = "Sinirsiz `git diff` tespit edildi; `--stat`, dosya yolu veya `HEAD~1` siniri ekleyin."
    else:
        match = _BIG_CAT.search(command)
        if match and not _LIMITED.search(command):
            target = match.group(2)
            path = _resolve(target, cwd, project_root)
            try:
                if os.path.isfile(path) and os.path.getsize(path) > max_bytes:
                    reason = (
                        f"'{os.path.basename(path)}' dosyasi {os.path.getsize(path) // 1024:,} KB; "
                        "tamamini tek seferde okumak baglami sisirir."
                    )
            except OSError:
                pass

    if not reason:
        return None
    return TokenGuardResult(
        "warn",
        RULE_ID,
        (
            f"Baglam uyarisi: {reason} Komutu `tsave run -- <komut>` ile calistirarak "
            "ciktiyi otomatik sikistirin veya komutu daraltin."
        ),
    )


def evaluate_token_guard(
    tool_name: str,
    args: Dict[str, Any],
    cwd: str = "",
    project_root: Optional[str] = None,
    conversation_id: str = "",
) -> Optional[TokenGuardResult]:
    """Returns the strongest finding: a deny beats a warn. A warn is said once per conversation (when an id is given)."""
    if not isinstance(args, dict):
        return None
    read = evaluate_read_guard(tool_name, args, cwd, project_root)
    if read and read.level == "deny":
        return read
    finding = read or evaluate_command_guard(tool_name, args, cwd, project_root)
    if finding and conversation_id:
        from .hook_output import drop_repeated_warnings

        if not drop_repeated_warnings([(finding.rule_id, "context-bloat warning")], conversation_id, ""):
            return None
    return finding
