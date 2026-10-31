"""Trusted extension command: list, approve, reject or revert hook proposals (JSON on stdin and stdout).

Called by the GravityGuard panel after the user clicks a button and confirms a modal dialog. Agents are denied this
command by the shell rule (POLICY_INTEGRITY).
"""
import json
import sys
from pathlib import Path

from gravityguard_engine import hook_proposals as hp


def handle(request: dict) -> dict:
    action = request.get("action")
    roots = request.get("roots")
    if not isinstance(roots, list) or not all(isinstance(r, str) and Path(r).is_absolute() for r in roots):
        raise ValueError("Invalid roots")
    if action == "list":
        pending, installed = [], []
        for root in dict.fromkeys(roots):
            for view in hp.list_pending(Path(root)):
                pending.append({**view, "root": root})
            for receipt in hp.list_receipts(Path(root)):
                if receipt.get("status") == "installed":
                    installed.append({**receipt, "root": root})
        return {"pending": pending, "installed": installed}
    root = request.get("root")
    if root not in roots:
        raise ValueError("Root is not a workspace root")
    proposal_id = request.get("id")
    if action == "approve":
        receipt = hp.approve(Path(root), proposal_id, str(request.get("sha256", "")), actor="user-extension")
    elif action == "reject":
        receipt = hp.reject(Path(root), proposal_id, str(request.get("reason", ""))[:500], actor="user-extension")
    elif action == "revert":
        receipt = hp.revert(Path(root), proposal_id, actor="user-extension")
    else:
        raise ValueError("Unknown action")
    return {"ok": True, "status": receipt.get("status"), "target_file": receipt.get("target_file")}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # the panel reads UTF-8; a Windows pipe defaults to the ANSI code page
    try:
        print(json.dumps(handle(json.load(sys.stdin)), ensure_ascii=False))
    except hp.ProposalError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        sys.exit(1)
