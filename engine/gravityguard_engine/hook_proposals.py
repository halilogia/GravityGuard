"""Agent-proposed hooks, installed only by a trusted user action.

An agent may not write `.claude/settings.json` or `.agents/hooks.json` (POLICY_INTEGRITY). It writes a proposal to
`.gravityguard/proposals/hooks/<id>.json` instead. The user reviews the diff and approves it from the extension or a
terminal; only then is the hook merged into the target file. A proposal can only ADD one hook: it cannot remove or
change existing hooks, cannot name GravityGuard, and its command may only print a project file or run a project
script. Every decision writes a receipt under `.gravityguard/runtime/hook-receipts/` (agent-read-only) and an
audit event, and an installed proposal can be reverted.
"""
import difflib
import hashlib
import json
import os
import re
import shlex
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .shell_rules import check_shell_command

PROPOSALS_DIR = Path(".gravityguard") / "proposals" / "hooks"
RECEIPTS_DIR = Path(".gravityguard") / "runtime" / "hook-receipts"

# PreToolUse / PermissionRequest hooks can answer "allow" and skip the user's permission prompt, so an agent may not
# propose them; the user writes those by hand.
ALLOWED_EVENTS = {
    "claude": ("UserPromptSubmit", "SessionStart", "SessionEnd", "PostToolUse", "Stop", "SubagentStop",
               "Notification", "PreCompact"),
    "antigravity": ("SessionStart", "PostToolUse", "Stop"),
}
TARGET_ALIASES = {"claude": "claude", "antigravity": "antigravity", "agents": "antigravity"}
REQUIRED = ("id", "target", "event", "command", "rationale", "test")
OPTIONAL = ("scope", "matcher", "timeout", "complaint", "created_by", "created_at")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
_PROJECT_VARS = re.compile(r"^(?:\$\{?(?:CLAUDE|GEMINI|ANTIGRAVITY)_PROJECT_DIR\}?|%(?:CLAUDE|GEMINI|ANTIGRAVITY)_PROJECT_DIR%)")
_NULL_REDIRECT = re.compile(r"^[012]?>>?(?:/dev/null|nul|\$null)$|^[012]?>&[12]$", re.I)
_SEPARATORS = re.compile(r"&&|\|\||;|\|")
_INFO_VERBS = {"true", "echo", "printf", ":", "exit"}
_READERS = {"cat", "type", "get-content", "head", "tail"}
_INTERPRETERS = {"python", "python3", "py", "node", "bash", "sh", "pwsh", "powershell"}
_INLINE_FLAGS = {"-c", "-e", "-p", "-m", "--eval", "--print", "-command", "-encodedcommand", "-enc", "-ec"}
_VALUE_FLAGS = {"-x", "-w", "-executionpolicy", "-ep"}
_GUARD_NAMES = re.compile(r"gravityguard|gravity-validator|srp-validator|hook_proposal", re.I)


class ProposalError(ValueError):
    """A proposal that may not be installed; the message says why, in plain words."""


# ----------------------------------------------------------------------------- command check

def _project_path(token: str, root: Path) -> Optional[Path]:
    """The file a command argument names, when it stays inside the project; None otherwise."""
    raw = token.strip("\"'")
    if _PROJECT_VARS.match(raw):
        raw = _PROJECT_VARS.sub("", raw).lstrip("/\\")
    candidate = Path(raw)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved


def _segment_reason(segment: str, root: Path) -> str:
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError as exc:
        return f"komut çözümlenemedi ({exc})"
    words: List[str] = []
    skip = False
    for index, token in enumerate(tokens):
        if skip:
            skip = False
            continue
        if _NULL_REDIRECT.match(token):
            continue
        if token in (">", "2>", ">>", "2>>") and index + 1 < len(tokens) and _NULL_REDIRECT.match("2>" + tokens[index + 1]):
            skip = True
            continue
        if any(ch in token for ch in "<>&") or "$(" in token or "`" in token:
            return f"'{token}': dosyaya yönlendirme, alt komut ve arka plan çalıştırma yasak"
        words.append(token)
    if not words:
        return "boş komut parçası"
    verb = os.path.basename(words[0]).lower().removesuffix(".exe")
    args = words[1:]
    if verb in _INFO_VERBS:
        return ""
    if verb in _READERS:
        files = [arg for arg in args if not arg.startswith("-")]
        if not files:
            return f"'{verb}' hangi dosyayı okuyacağını söylemiyor"
        outside = [arg for arg in files if _project_path(arg, root) is None]
        return f"'{outside[0]}' proje dışında; kanca yalnızca proje dosyası okuyabilir" if outside else ""
    if verb in _INTERPRETERS:
        script = None
        skip_value = False
        for arg in args:
            low = arg.lower()
            if skip_value:
                skip_value = False
                continue
            if low in _INLINE_FLAGS:
                return f"'{verb} {arg}': satır içi kod yasak, komut repodaki bir betiği çalıştırmalı"
            if low in _VALUE_FLAGS:
                skip_value = True
                continue
            if low.startswith("-"):
                continue
            script = arg
            break
        if script is None:
            return f"'{verb}' hangi betiği çalıştıracağını söylemiyor"
        path = _project_path(script, root)
        if path is None:
            return f"'{script}' proje dışında; kanca yalnızca projedeki bir betiği çalıştırabilir"
        if not path.is_file():
            return f"'{script}' bulunamadı; önce betiği repoya ekleyin"
        return ""
    return f"'{words[0]}' izinli değil (izinli: {', '.join(sorted(_READERS | _INTERPRETERS | _INFO_VERBS))})"


def command_reason(command: Any, root: Path) -> str:
    """Why a hook command may not be installed, '' when it may."""
    if not isinstance(command, str) or not command.strip():
        return "komut boş"
    if len(command) > 1000 or "\n" in command or "\0" in command:
        return "komut tek satır ve en çok 1000 karakter olmalı"
    if _GUARD_NAMES.search(command):
        return "GravityGuard'ın kendi kancalarına ve onay araçlarına dokunan öneri kabul edilmez"
    shell = check_shell_command({"command": command})
    if shell:
        return shell
    for segment in _SEPARATORS.split(command):
        reason = _segment_reason(segment, root)
        if reason:
            return reason
    return ""


# ----------------------------------------------------------------------------- proposal model

def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def proposal_path(root: Path, proposal_id: str) -> Path:
    if not isinstance(proposal_id, str) or not _ID.match(proposal_id):
        raise ProposalError("öneri kimliği küçük harf, rakam ve tire olmalı (3-64 karakter)")
    return Path(root) / PROPOSALS_DIR / f"{proposal_id}.json"


def receipt_path(root: Path, proposal_id: str) -> Path:
    proposal_path(root, proposal_id)
    return Path(root) / RECEIPTS_DIR / f"{proposal_id}.json"


def target_file(root: Path, proposal: Dict[str, Any]) -> Path:
    if proposal["target"] == "claude":
        name = "settings.local.json" if proposal.get("scope") == "local" else "settings.json"
        return Path(root) / ".claude" / name
    return Path(root) / ".agents" / "hooks.json"


def validate(proposal: Any, root: Path, expected_id: str = "") -> Dict[str, Any]:
    """Normalized proposal, or ProposalError with the reason."""
    if not isinstance(proposal, dict):
        raise ProposalError("öneri bir JSON nesnesi olmalı")
    unknown = sorted(set(proposal) - set(REQUIRED) - set(OPTIONAL))
    if unknown:
        raise ProposalError(f"bilinmeyen alan: {', '.join(unknown)}. Öneri yalnızca tek bir kanca EKLEYEBİLİR; "
                            "mevcut kancaları silemez ya da değiştiremez")
    missing = [key for key in REQUIRED if not proposal.get(key)]
    if missing:
        raise ProposalError(f"eksik alan: {', '.join(missing)}")
    if expected_id and proposal["id"] != expected_id:
        raise ProposalError("öneri kimliği dosya adıyla aynı olmalı")
    proposal_path(root, proposal["id"])
    target = TARGET_ALIASES.get(str(proposal["target"]).lower())
    if not target:
        raise ProposalError(f"hedef '{proposal['target']}' desteklenmiyor (claude, antigravity)")
    event = proposal["event"]
    if event not in ALLOWED_EVENTS[target]:
        raise ProposalError(f"'{event}' olayı önerilemez. İzinli: {', '.join(ALLOWED_EVENTS[target])}. "
                            "PreToolUse/PermissionRequest izin kararı verebildiği için yalnızca elle eklenir")
    scope = proposal.get("scope", "project")
    if scope not in ("project", "local") or (scope == "local" and target != "claude"):
        raise ProposalError("kapsam 'project' ya da (yalnız claude için) 'local' olmalı")
    matcher = proposal.get("matcher", "")
    if not isinstance(matcher, str) or len(matcher) > 200 or "\n" in matcher:
        raise ProposalError("matcher en çok 200 karakterlik tek satır olmalı")
    timeout = proposal.get("timeout", 10)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 120:
        raise ProposalError("timeout 1-120 saniye arası tam sayı olmalı")
    for key in ("rationale", "complaint", "created_by", "created_at"):
        if key in proposal and (not isinstance(proposal[key], str) or len(proposal[key]) > 2000):
            raise ProposalError(f"'{key}' en çok 2000 karakterlik metin olmalı")
    for key in ("command", "test"):
        reason = command_reason(proposal[key], Path(root))
        if reason:
            raise ProposalError(f"{'komut' if key == 'command' else 'test komutu'} reddedildi: {reason}")
    normalized = {key: proposal[key] for key in REQUIRED + OPTIONAL if key in proposal}
    normalized.update(target=target, scope=scope, matcher=matcher, timeout=timeout)
    return normalized


def _hook_entry(proposal: Dict[str, Any]) -> Dict[str, Any]:
    hook = {"type": "command", "command": proposal["command"], "timeout": proposal["timeout"]}
    if proposal["target"] == "claude":
        group: Dict[str, Any] = {"hooks": [hook]}
        if proposal["matcher"]:
            group = {"matcher": proposal["matcher"], **group}
        return group
    return {"matcher": proposal["matcher"], "hooks": [hook]} if proposal["matcher"] else hook


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig") or "{}")
    except ValueError as exc:
        raise ProposalError(f"{path.name} geçerli JSON değil; dosya bozulmasın diye hiçbir şey yazılmadı ({exc})")
    if not isinstance(data, dict):
        raise ProposalError(f"{path.name} bir JSON nesnesi değil")
    return data


def _commands(node: Any) -> List[str]:
    if isinstance(node, dict):
        found = [node["command"]] if isinstance(node.get("command"), str) else []
        return found + [c for value in node.values() for c in _commands(value)]
    if isinstance(node, list):
        return [c for item in node for c in _commands(item)]
    return []


def merged(current: Dict[str, Any], proposal: Dict[str, Any]) -> Tuple[Dict[str, Any], Any]:
    """Target content after the proposal is added, plus the exact entry added. Existing hooks stay untouched."""
    data = json.loads(json.dumps(current))
    entry = _hook_entry(proposal)
    if proposal["target"] == "claude":
        hooks = data.setdefault("hooks", {})
        if not isinstance(hooks, dict) or not isinstance(hooks.get(proposal["event"], []), list):
            raise ProposalError("hedef dosyadaki 'hooks' alanı beklenen biçimde değil")
        existing = hooks.get(proposal["event"], [])
        if proposal["command"] in _commands(existing):
            raise ProposalError("bu komut bu olay için zaten kurulu")
        hooks[proposal["event"]] = [*existing, entry]
    else:
        name = f"proposal-{proposal['id']}"
        if name in data:
            raise ProposalError(f"'{name}' adlı kanca zaten var")
        if proposal["command"] in _commands(data):
            raise ProposalError("bu komut zaten kurulu")
        data[name] = {"enabled": True, proposal["event"]: [entry]}
    return data, entry


def _dump(data: Dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temp, path)
    except BaseException:
        if os.path.exists(temp):
            os.unlink(temp)
        raise


# ----------------------------------------------------------------------------- read side

def preview(root: Path, proposal_id: str) -> Dict[str, Any]:
    """Everything the user needs to decide: proposal, target file, diff, content hash, or why it is invalid."""
    root = Path(root)
    path = proposal_path(root, proposal_id)
    raw = path.read_text(encoding="utf-8-sig")
    view: Dict[str, Any] = {"id": proposal_id, "path": str(path), "sha256": _sha(raw), "valid": False}
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        view.update(error=f"öneri geçerli JSON değil ({exc})", raw=raw[:2000])
        return view
    try:
        proposal = validate(parsed, root, proposal_id)
    except ProposalError as exc:
        view.update(error=str(exc), proposal=parsed)
        return view
    target = target_file(root, proposal)
    try:
        before = target.read_text(encoding="utf-8-sig") if target.is_file() else ""
        after = _dump(merged(_load_json(target), proposal)[0])
    except ProposalError as exc:
        view.update(proposal=proposal, error=str(exc), target_file=str(target))
        return view
    rel = target.relative_to(root).as_posix()
    diff = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), f"a/{rel}", f"b/{rel}"))
    view.update(valid=True, proposal=proposal, target_file=str(target), diff=diff)
    return view


def list_pending(root: Path) -> List[Dict[str, Any]]:
    folder = Path(root) / PROPOSALS_DIR
    if not folder.is_dir():
        return []
    views = []
    for path in sorted(folder.glob("*.json")):
        try:
            views.append(preview(root, path.stem))
        except (OSError, ProposalError) as exc:
            views.append({"id": path.stem, "path": str(path), "valid": False, "error": str(exc)})
    return views


def list_receipts(root: Path) -> List[Dict[str, Any]]:
    folder = Path(root) / RECEIPTS_DIR
    receipts = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            receipts.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            receipts.append({"id": path.stem, "status": "unreadable", "error": str(exc)})
    return receipts


# ----------------------------------------------------------------------------- trusted actions

def _audit(status: str, target: str, reason: str, rule_id: str) -> None:
    from .audit import log_event
    log_event("hook_proposal", status, target, reason, rule_id=rule_id)


def _record(root: Path, proposal_id: str, event: Dict[str, Any], **fields: Any) -> Dict[str, Any]:
    path = receipt_path(root, proposal_id)
    receipt = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"id": proposal_id, "history": []}
    receipt.update(fields)
    receipt["history"].append({"at": _now(), **event})
    _atomic_write(path, _dump(receipt))
    return receipt


def approve(root: Path, proposal_id: str, expected_sha256: str, actor: str = "user") -> Dict[str, Any]:
    """Merge a reviewed proposal. `expected_sha256` must match the content the user saw."""
    root = Path(root)
    view = preview(root, proposal_id)
    if view["sha256"] != expected_sha256:
        raise ProposalError("öneri, siz inceledikten sonra değişti; yeniden inceleyin")
    if not view["valid"]:
        raise ProposalError(view["error"])
    proposal = view["proposal"]
    target = Path(view["target_file"])
    target_existed = target.is_file()
    data, entry = merged(_load_json(target), proposal)
    after_text = _dump(data)
    _atomic_write(target, after_text)
    receipt = _record(root, proposal_id, {"action": "approved", "actor": actor}, status="installed",
                      proposal=proposal, proposal_sha256=expected_sha256, target_file=str(target), added=entry,
                      target_existed=target_existed, after_sha256=_sha(after_text))
    proposal_path(root, proposal_id).unlink()
    _audit("APPROVED", str(target), f"Hook proposal '{proposal_id}' installed ({proposal['event']}) by {actor}",
           "HOOK_PROPOSAL_APPROVED")
    return receipt


def reject(root: Path, proposal_id: str, reason: str = "", actor: str = "user") -> Dict[str, Any]:
    root = Path(root)
    path = proposal_path(root, proposal_id)
    raw = path.read_text(encoding="utf-8-sig")
    try:
        proposal: Any = json.loads(raw)
    except ValueError:
        proposal = raw[:2000]  # kept verbatim in the receipt: an unparsable proposal is still worth recording
    receipt = _record(root, proposal_id, {"action": "rejected", "actor": actor, "reason": reason[:500]},
                      status="rejected", proposal=proposal, proposal_sha256=_sha(raw))
    path.unlink()
    _audit("WARNING", str(path), f"Hook proposal '{proposal_id}' rejected by {actor}: {reason[:200]}",
           "HOOK_PROPOSAL_REJECTED")
    return receipt


def revert(root: Path, proposal_id: str, actor: str = "user") -> Dict[str, Any]:
    """Remove exactly the hook an approval added; everything else in the file stays as it is now."""
    root = Path(root)
    path = receipt_path(root, proposal_id)
    if not path.is_file():
        raise ProposalError("bu öneri için kurulum kaydı yok")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("status") != "installed":
        raise ProposalError(f"öneri kurulu değil (durum: {receipt.get('status')})")
    target = Path(receipt["target_file"])
    data = _load_json(target)
    proposal, entry = receipt["proposal"], receipt["added"]
    missing = "kurulan kanca dosyada bulunamadı (elle değiştirilmiş olabilir); hiçbir şey silinmedi"
    if proposal["target"] == "claude":
        groups = data.get("hooks", {}).get(proposal["event"], [])
        if entry not in groups:
            raise ProposalError(missing)
        groups.remove(entry)
        if not groups:
            del data["hooks"][proposal["event"]]
        if not data["hooks"]:
            del data["hooks"]
    else:
        name = f"proposal-{proposal_id}"
        if data.get(name) != {"enabled": True, proposal["event"]: [entry]}:
            raise ProposalError(missing)
        del data[name]
    if not data and not receipt.get("target_existed", True):
        target.unlink()
    else:
        _atomic_write(target, _dump(data))
    receipt = _record(root, proposal_id, {"action": "reverted", "actor": actor}, status="reverted")
    _audit("WARNING", str(target), f"Hook proposal '{proposal_id}' reverted by {actor}", "HOOK_PROPOSAL_REVERTED")
    return receipt
