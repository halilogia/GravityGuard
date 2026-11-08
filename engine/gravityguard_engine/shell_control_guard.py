"""Shell commands that write, move or delete guard control files, or finish a write a file tool was already denied.

File tools are checked by the dispatcher, so the detour is the shell: `python scratch/temp.py` whose body does
`open(<protected file>, "w")`, `Set-Content`, `> file`, `mv`, `rm`. Everything here reads command text (and the body of a
script the command runs); like the rest of the shell rules it is not a shell interpreter and not an OS sandbox.
"""
import os
import re
from collections.abc import Callable, Sequence
from typing import NamedTuple

from .policy_integrity import is_runtime_control_file
from .shell_tokens import split_command

_SEGMENTS = re.compile(r"[;&|\n(`]+")
_WORD = re.compile(r"[a-z][a-z0-9_.-]*")
_REDIRECT = re.compile(r"""\d?>>?\|?[ \t]*("[^"\n]*"|'[^'\n]*'|[^\s;&|<>"']+)""")
_SED_INPLACE = re.compile(r"(?<!\S)(?:-[a-z]*i[a-z]*|--in-place)(?!\S)")
_WRITE_API = re.compile(
    r"open\s*\([^)\n]{0,300}?,\s*(?:mode\s*=\s*)?[\"'][rbt]*[wax+]|mode\s*=\s*[\"'][rbt]*[wax+]"
    r"|write|unlink|rmtree|truncate|shutil|os\.(?:remove|rename|replace)|fs\.(?:rm|rename|copy|append)"
    r"|set-content|out-file|add-content|new-item|remove-item|move-item|copy-item|appendfile"
)

_DESTROY = frozenset({"rm", "del", "erase", "rd", "rmdir", "remove-item", "ri", "mv", "move", "move-item", "mi",
                      "rename-item", "rni", "ren", "unlink", "shred", "truncate"})
_WRITE = frozenset({"set-content", "sc", "add-content", "ac", "out-file", "clear-content", "clc", "new-item", "ni",
                    "tee", "tee-object", "robocopy", "xcopy"})
_COPY = frozenset({"cp", "copy", "copy-item", "cpi"})
_INTERPRETERS = frozenset({"python", "python3", "py", "pythonw", "node", "deno", "bun", "ruby", "perl", "php", "bash",
                           "sh", "zsh", "pwsh", "powershell", "cmd", "wscript", "cscript"})
_SHELL_SCRIPTS = (".sh", ".ps1", ".bat", ".cmd")
_SCRIPT_SUFFIXES = _SHELL_SCRIPTS + (".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".php", ".vbs")
_CHANGE_DIR = frozenset({"cd", "pushd", "chdir", "set-location"})
_NULL_DEVICES = frozenset({"nul", "/dev/null", "$null"})
_MAX_TEXT = 200_000
_MAX_SCRIPT_BYTES = 512 * 1024
_MAX_SCRIPTS = 5
_MAX_RESOLVED = 256
_MAX_SHLEX_CHARS = 8_000


class _Target(NamedTuple):
    """What a command must not write: `text` judges normalized free text, `token` one raw command argument."""
    text: Callable[[str], bool]
    token: Callable[[str], bool]


def _norm(text: str) -> str:
    return text.lower().replace("\\\\", "/").replace("\\", "/")


def _control_text(norm: str) -> bool:
    if "halilogia.gravityguard-" in norm or ".gemini/config/plugins/gravityguard" in norm:
        return True
    if "hooks.json" in norm and (".agents" in norm or ".gemini" in norm):
        return True
    if (".claude" in norm) and ("settings.json" in norm or "settings.local.json" in norm):
        return True
    return ".gravityguard" in norm and ("runtime" in norm or "reviews" in norm)


def _control_target(cwd: str) -> _Target:
    budget = [_MAX_RESOLVED]  # filesystem resolutions per command; text matching is not limited

    def token(raw: str) -> bool:
        value = raw.strip("\"'")
        if _control_text(_norm(value)):
            return True
        if not value or len(value) > 500 or value.lower() in _NULL_DEVICES or any(c in value for c in "*?<>|\n"):
            return False
        budget[0] -= 1
        if budget[0] < 0:
            return False
        expanded = os.path.expandvars(os.path.expanduser(value))
        if not cwd and not os.path.isabs(expanded):
            return False  # the command changes directory first: a relative name cannot be resolved here
        try:
            return is_runtime_control_file(os.path.join(cwd, expanded))
        except (OSError, ValueError):
            return False

    return _Target(_control_text, token)


def _denied_target(cwd: str, denied: Sequence[str]) -> _Target:
    exact = {_norm(d) for d in denied}
    needles = set()
    for path in exact:
        parts = path.split("/")
        needles.add(path)
        needles.add("/".join(parts[-2:]))
        if len(parts[-1]) >= 4:  # "a.c" would match half the commands
            needles.add(parts[-1])

    pattern = re.compile("|".join(re.escape(n) for n in sorted(needles, key=len, reverse=True)))
    budget = [_MAX_RESOLVED]

    def text(norm: str) -> bool:
        return pattern.search(norm) is not None

    def token(raw: str) -> bool:
        value = raw.strip("\"'")
        if not value:
            return False
        if text(_norm(value)):
            return True
        budget[0] -= 1
        resolvable = budget[0] >= 0 and (bool(cwd) or os.path.isabs(value))
        return resolvable and _norm(os.path.abspath(os.path.join(cwd, value))) in exact

    return _Target(text, token)


def _tokens(segment: str) -> list[str]:
    return split_command(segment)


def _script_files(tokens: Sequence[str], cwd: str) -> list[str]:
    found = []
    candidates = dict.fromkeys(t.strip("\"'") for t in tokens)  # repeated names cost one filesystem probe
    for value in candidates:
        if value.lower().endswith(_SCRIPT_SUFFIXES) and (cwd or os.path.isabs(value)):
            path = os.path.join(cwd, value)
            if os.path.isfile(path):
                found.append(path)
                if len(found) == _MAX_SCRIPTS:
                    break
    return found


def _read_script(path: str) -> str:
    try:
        if os.path.getsize(path) > _MAX_SCRIPT_BYTES:
            return ""
        with open(path, encoding="utf-8", errors="replace") as handle:
            return _norm(handle.read())
    except OSError:
        return ""


def _script_writes(path: str, target: _Target, cwd: str, depth: int) -> bool:
    body = _read_script(path)
    if not body:
        return False
    if _WRITE_API.search(body) and target.text(body):
        return True
    return depth < 1 and path.lower().endswith(_SHELL_SCRIPTS) and _writes(body, target, cwd, depth + 1)


def _interpreter_writes(tokens: Sequence[str], target: _Target, cwd: str, depth: int) -> bool:
    named = next((t for t in tokens if t.strip("\"'").lower().endswith(_SCRIPT_SUFFIXES)), None)
    for token in dict.fromkeys(tokens):  # repeated arguments are judged once
        value = token.strip("\"'")
        if token == named or any(c.isspace() for c in value):
            continue  # the script itself is judged by its body; quoted inline code is judged with the whole command
        if not value.startswith("-") and target.text(_norm(value)):
            return True  # `python script.py <protected path>`
    return any(_script_writes(path, target, cwd, depth) for path in _script_files(tokens, cwd))


def _segment_writes(segment: str, target: _Target, cwd: str, depth: int) -> bool:
    norm = _norm(segment)
    words = set(_WORD.findall(norm))
    tokens = _tokens(segment)
    writer = words & (_DESTROY | _WRITE) or ("sed" in words and _SED_INPLACE.search(norm))
    if writer and (target.text(norm) or any(target.token(t) for t in tokens)):
        return True
    if words & _COPY and tokens:
        destination = [tokens[-1]] + [tokens[i + 1] for i, t in enumerate(tokens[:-1]) if t.lower() in ("-destination", "-dest")]
        if any(target.token(t) for t in destination):
            return True
    return bool(words & _INTERPRETERS) and _interpreter_writes(tokens, target, cwd, depth)


def _writes(command: str, target: _Target, cwd: str, depth: int = 0) -> bool:
    text = command[:_MAX_TEXT]
    if any(target.token(m.group(1)) for m in _REDIRECT.finditer(text)):
        return True
    if depth == 0:  # inline code and heredocs are split across segments, so judge them as one text
        norm = _norm(text)
        if set(_WORD.findall(norm)) & _INTERPRETERS and _WRITE_API.search(norm) and target.text(norm):
            return True
    return any(_segment_writes(segment, target, cwd, depth) for segment in _SEGMENTS.split(text))


def _base_dir(command: str, cwd: str | None) -> str:
    """Directory relative names resolve against, '' when the command moves elsewhere first (`cd x && echo > a`)."""
    if set(_WORD.findall(_norm(command[:_MAX_TEXT]))) & _CHANGE_DIR:
        return ""
    return cwd if isinstance(cwd, str) and cwd else os.getcwd()


def writes_control_file(command: str, cwd: str | None = None) -> bool:
    """True when the command writes, moves, deletes or hands a protected guard control file to an interpreter."""
    cwd = _base_dir(command, cwd)
    return _writes(command, _control_target(cwd), cwd)


def writes_denied_target(command: str, denied: Sequence[str], cwd: str | None = None) -> bool:
    """True when the command writes one of the targets a file tool already denied in this conversation."""
    if not denied:
        return False
    cwd = _base_dir(command, cwd)
    return _writes(command, _denied_target(cwd, denied), cwd)
