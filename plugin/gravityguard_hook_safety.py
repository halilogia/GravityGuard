"""Engine-independent degraded-mode responses shared by provider adapters."""
import os
import json


def failure_response(stop=False):
    if os.environ.get("GRAVITYGUARD_ADAPTER_FAIL_OPEN") == "1":
        return None  # Explicit operator escape hatch, never set by the adapter.
    reason = "[GUARD_UNAVAILABLE]: GravityGuard could not validate this operation. Restore the engine before continuing."
    if stop:
        return {"decision": "block", "reason": reason}
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                    "permissionDecisionReason": reason}}


def emit_failure(stop=False):
    response = failure_response(stop)
    if response is not None:
        print(json.dumps(response))
