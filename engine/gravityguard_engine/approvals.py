"""User approval tickets: a denial can be lifted by the human, never by the agent.

A rejection names a rule and the exact action that tripped it. The agent cannot approve its own
denial: an approval is written only by the trusted CLI/panel command, which the shell rule denies
to agents (POLICY_INTEGRITY). Tickets live in the user's home, outside every project and the
agent-writable plugin tree, so a project checkout cannot carry one in.

A ticket is bound to one fingerprint (rule + tool + target + command), expires, and is consumed by
the call it lets through. "The user said yes" therefore never means "this rule is off".
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

DEFAULT_TTL_MINUTES = 30
MAX_TTL_MINUTES = 120
DEFAULT_USES = 1
MAX_USES = 10
_MAX_PENDING = 200
_RULE_IN_REASON = re.compile(r"\[([A-Z][A-Z0-9_]+)\]")
_WHITESPACE = re.compile(r"\s+")


class ApprovalError(ValueError):
    """A request that cannot be honoured (unknown id, expired ticket, missing fields)."""


def _root() -> Path:
    override = os.environ.get("GRAVITYGUARD_APPROVAL_DIR")
    if override:
        return Path(override)
    log_dir = os.environ.get("GRAVITYGUARD_LOG_DIR")  # tests and embedded hosts keep their state here
    if log_dir:
        return Path(log_dir) / "approvals"
    return Path.home() / ".gravityguard" / "approvals"


def pending_path(key: str) -> Path:
    return _root() / "pending" / f"{key}.json"


def receipt_path(key: str) -> Path:
    return _root() / "receipts" / f"{key}.json"


def rule_of(reason: str) -> str:
    """The `[RULE]` tag a rejection carries, '' when it has none."""
    match = _RULE_IN_REASON.search(str(reason or ""))
    return match.group(1) if match else ""


def normalize(action: dict | None) -> dict:
    """The displayable part of a tool call: counts, line numbers and temp paths must not change the key."""
    action = action if isinstance(action, dict) else {}
    target = str(action.get("target") or "").replace("\\", "/").strip()
    command = _WHITESPACE.sub(" ", str(action.get("command") or "")).strip()
    return {"tool": str(action.get("tool") or "").strip(), "target": target, "command": command[:400]}


def _content_digest(action: dict) -> str:
    """Hash of the call arguments, so a ticket approves one exact change, not every change to that file."""
    args = action.get("args")
    if not isinstance(args, dict):
        return ""
    try:
        text = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = repr(sorted(map(str, args.items())))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def action_key(rule: str, action: dict | None) -> str:
    """One fingerprint per (rule, tool, exact arguments). Approving it approves exactly that call."""
    action = action if isinstance(action, dict) else {}
    parts = normalize(action)
    identity = _content_digest(action) or "|".join((parts["tool"], parts["target"], parts["command"]))
    text = f"{rule}|{parts['tool']}|{identity}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _now() -> float:
    return time.time()


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _prune(folder: Path) -> None:
    """Keep the pending store bounded: expired tickets go first, then the oldest ones."""
    try:
        files = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime)
    except OSError as err:
        sys.stderr.write(f"[GravityGuard] approval store unreadable: {err}\n")
        return
    now = _now()
    keep = []
    for path in files:
        ticket = _read(path)
        expired = bool(ticket) and ticket.get("status") == "pending" and float(ticket.get("expires_at") or 0) <= now
        if ticket and not expired:
            keep.append(path)
            continue
        try:
            path.unlink()
        except OSError as err:
            sys.stderr.write(f"[GravityGuard] could not prune {path.name}: {err}\n")
    for path in keep[:max(0, len(keep) - _MAX_PENDING)]:
        try:
            path.unlink()
        except OSError as err:
            sys.stderr.write(f"[GravityGuard] could not prune {path.name}: {err}\n")


def record_block(rule: str, reason: str, action: dict | None, ttl_minutes: int = DEFAULT_TTL_MINUTES) -> dict:
    """Register (or refresh) the pending ticket a denial offers the user. Never reopens a decided one."""
    key = action_key(rule, action)
    path = pending_path(key)
    existing = _read(path)
    decided = _read(receipt_path(key))
    if decided is not None:  # the user already answered: a repeat denial must not ask again
        return existing or {"id": key, "status": decided.get("status"), "rule": rule,
                            "action": normalize(action), "reason": str(reason or "")[:600]}
    now = _now()
    if existing and existing.get("status") == "pending":
        existing["seen"] = int(existing.get("seen") or 1) + 1
        existing["last_seen"] = now
        existing["reason"] = str(reason or "")[:600]
        _write(path, existing)
        _prune(path.parent)
        return existing
    ticket = {
        "id": key,
        "status": "pending",
        "rule": rule,
        "reason": str(reason or "")[:600],
        "action": normalize(action),
        "created_at": now,
        "last_seen": now,
        "seen": 1,
        "expires_at": now + max(1, min(int(ttl_minutes), MAX_TTL_MINUTES)) * 60,
    }
    _write(path, ticket)
    _prune(path.parent)
    return ticket


def approved(key: str, now: float | None = None) -> dict | None:
    """The live approval for this fingerprint, or None (missing, denied, expired, already used)."""
    receipt = _read(receipt_path(key))
    if not receipt or receipt.get("status") != "approved":
        return None
    moment = _now() if now is None else now
    if float(receipt.get("expires_at") or 0) <= moment:
        return None
    if int(receipt.get("remaining") or 0) <= 0:
        return None
    return receipt


def consume(key: str) -> dict | None:
    """Spend one use of an approval. A one-shot ticket ends up `consumed`."""
    receipt = _read(receipt_path(key))
    if not receipt:
        return None
    remaining = max(0, int(receipt.get("remaining") or 0) - 1)
    receipt["remaining"] = remaining
    receipt["used_at"] = _now()
    if remaining <= 0:
        receipt["status"] = "consumed"
    _write(receipt_path(key), receipt)
    return receipt


def list_pending() -> list[dict]:
    """Unapproved tickets, newest first; expired ones are dropped from the list."""
    out = []
    now = _now()
    folder = _root() / "pending"
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        ticket = _read(path)
        if not ticket or ticket.get("status") != "pending":
            continue
        if float(ticket.get("expires_at") or 0) > now:
            out.append(ticket)
    return sorted(out, key=lambda t: float(t.get("last_seen") or 0), reverse=True)


def list_receipts() -> list[dict]:
    folder = _root() / "receipts"
    return [r for r in (_read(p) for p in sorted(folder.glob("*.json"))) if r] if folder.is_dir() else []


def preview(key: str) -> dict:
    ticket = _read(pending_path(key))
    receipt = _read(receipt_path(key))
    if not ticket and not receipt:
        raise ApprovalError(f"Bilinmeyen onay kimliği: {key}")
    return {"ticket": ticket, "receipt": receipt}


def approve(key: str, actor: str = "user", minutes: int = DEFAULT_TTL_MINUTES, uses: int = DEFAULT_USES) -> dict:
    """Grant the ticket. Only a trusted (user) caller reaches this; agents are denied the command."""
    ticket = _read(pending_path(key))
    if not ticket:
        raise ApprovalError(f"Onay bekleyen kayıt yok: {key}")
    if ticket.get("status") not in ("pending", "rejected", "revoked"):
        raise ApprovalError(f"Kayıt onaya açık değil: {ticket.get('status')}")
    minutes = max(1, min(int(minutes), MAX_TTL_MINUTES))
    uses = max(1, min(int(uses), MAX_USES))
    now = _now()
    receipt = {
        "id": key,
        "status": "approved",
        "rule": ticket.get("rule"),
        "action": ticket.get("action"),
        "remaining": uses,
        "uses": uses,
        "approved_at": now,
        "expires_at": now + minutes * 60,
        "actor": actor,
    }
    _write(receipt_path(key), receipt)
    ticket["status"] = "approved"
    ticket["decided_at"] = now
    _write(pending_path(key), ticket)
    return receipt


def reject(key: str, reason: str = "", actor: str = "user") -> dict:
    ticket = _read(pending_path(key))
    if not ticket:
        raise ApprovalError(f"Onay bekleyen kayıt yok: {key}")
    now = _now()
    receipt = {
        "id": key,
        "status": "rejected",
        "rule": ticket.get("rule"),
        "action": ticket.get("action"),
        "reason": str(reason or "")[:500],
        "approved_at": None,
        "decided_at": now,
        "actor": actor,
    }
    _write(receipt_path(key), receipt)
    ticket["status"] = "rejected"
    ticket["decided_at"] = now
    _write(pending_path(key), ticket)
    return receipt


def revoke(key: str, actor: str = "user") -> dict:
    """Withdraw a live approval before it is spent."""
    receipt = _read(receipt_path(key))
    if not receipt or receipt.get("status") != "approved":
        raise ApprovalError(f"Geri alınacak onay yok: {key}")
    receipt["status"] = "revoked"
    receipt["decided_at"] = _now()
    receipt["remaining"] = 0
    receipt["actor"] = actor
    _write(receipt_path(key), receipt)
    return receipt
