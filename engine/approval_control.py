"""Trusted extension command: list, allow, deny or revoke an approval ticket (JSON on stdin and stdout).

Called by the GravityGuard panel after the user clicks a button and confirms a modal dialog. Agents are denied this
command by the shell rule (POLICY_INTEGRITY), which is what makes "the user approved it" mean something.
"""
import json
import sys
from pathlib import Path

from gravityguard_engine import approvals as apr


def handle(request: dict) -> dict:
    action = request.get("action")
    if action == "list":
        return {"pending": apr.list_pending(),
                "live": [r for r in apr.list_receipts() if r.get("status") == "approved"]}
    ticket_id = str(request.get("id") or "")
    if not ticket_id:
        raise ValueError("Invalid id")
    if action == "show":
        return apr.preview(ticket_id)
    if action == "allow":
        receipt = apr.approve(ticket_id, actor="user-extension",
                              minutes=int(request.get("minutes") or apr.DEFAULT_TTL_MINUTES),
                              uses=int(request.get("uses") or apr.DEFAULT_USES))
        return {"ok": True, "status": receipt.get("status"), "remaining": receipt.get("remaining"),
                "expires_at": receipt.get("expires_at")}
    if action == "deny":
        receipt = apr.reject(ticket_id, str(request.get("reason", ""))[:500], actor="user-extension")
        return {"ok": True, "status": receipt.get("status")}
    if action == "revoke":
        receipt = apr.revoke(ticket_id, actor="user-extension")
        return {"ok": True, "status": receipt.get("status")}
    raise ValueError("Unknown action")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # the panel reads UTF-8; a Windows pipe defaults to the ANSI code page
    try:
        print(json.dumps(handle(json.load(sys.stdin)), ensure_ascii=False))
    except apr.ApprovalError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        sys.exit(1)
