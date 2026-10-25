"""Trusted extension command: waive advisory debts through the engine lock."""
import json
import os
from pathlib import Path
import sys

from gravityguard_engine.governance import governance_transaction
from gravityguard_engine.audit import log_event


def waive_advisory(root: Path, target=None) -> int:
    def same(value):
        return target is None or os.path.normcase(os.path.realpath(value)) == os.path.normcase(os.path.realpath(target))

    count = 0
    with governance_transaction(root) as state:
        containers = [state, *[value for value in state.get("sessions", {}).values() if isinstance(value, dict)]]
        for container in containers:
            for category in ("test_obligations", "doc_obligations"):
                pending = container.get(category, {}).get("pending", {})
                for key in list(pending):
                    if same(key):
                        del pending[key]
                        count += 1
            if target is None:
                container["stop_retries"] = 0
        state["resolution_intents"] = [intent for intent in state.get("resolution_intents", [])
            if not same(intent.get("target_file", intent.get("target_path", "")))]
        state.setdefault("waivers", []).append({"actor": "extension-user-action", "target": target, "kind": "advisory"})
        state["waivers"] = state["waivers"][-100:]
    log_event("user_waiver", "WARNING", target or str(root), "Advisory obligations waived through the extension", rule_id="USER_ADVISORY_WAIVER")
    return count


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "scan":
        # Tier 4 deep scan: standalone command, never reachable from the hook fast path.
        from gravityguard_engine.security_audit import main as scan_main
        sys.exit(scan_main(sys.argv[2:]))
    try:
        payload = json.load(sys.stdin)
        roots = payload["roots"]
        target = payload.get("target")
        if not isinstance(roots, list) or not all(isinstance(root, str) and Path(root).is_absolute() for root in roots):
            raise ValueError("Invalid roots")
        if target is not None and not isinstance(target, str):
            raise ValueError("Invalid target")
        count = 0
        for root in dict.fromkeys(roots):
            if (Path(root) / ".gravityguard" / "runtime" / "governance.json").is_file():
                count += waive_advisory(Path(root), target)
        print(json.dumps({"count": count}))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("Governance mutation failed", file=sys.stderr)
        sys.exit(1)
