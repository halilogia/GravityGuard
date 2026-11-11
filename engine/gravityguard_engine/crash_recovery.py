#!/usr/bin/env python3
"""
GravityGuard Engine — Crash Telemetry, LKG Fallback & Fail-Closed CLI Wrapper.
Ensures engine defects are logged, audited, and recovered via last-known-good or repair mode.
Zero external dependencies.
"""
import contextlib
import io
import json
import os
import sys
from typing import Optional

from .engine_integrity import repair_reason, run_lkg
from .hook_output import finalize

_CRASH_CONTEXT: dict = {}


def _log_cli_error(tb_text: str) -> None:
    """Persist a crash traceback to the global and project-local error logs (best effort)."""
    from datetime import datetime
    # A known call context names the event; argv flags (any host/test-runner option) are only a fallback.
    event = (
        ("stop" if _CRASH_CONTEXT.get("stop") else "pre-tool")
        if _CRASH_CONTEXT
        else next((a for a in sys.argv[1:] if a.startswith("--")), "unknown")
    )
    who = (
        f" tool={_CRASH_CONTEXT.get('tool', '')!r} conversation={_CRASH_CONTEXT.get('conversation_id', '')!r}"
        if _CRASH_CONTEXT
        else ""
    )
    entry = f"[{datetime.now().isoformat()}] hook_event={event}{who} argv={sys.argv!r}\n{tb_text}\n"
    for path in (
        os.path.expanduser("~/.gemini/config/plugins/gravityguard/logs/gravityguard_errors.log"),
        os.path.join(".gravityguard", "runtime", "gravityguard_errors.log"),
    ):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(entry)
        except OSError as log_err:
            sys.stderr.write(f"[GravityGuard] could not write error log {path}: {type(log_err).__name__}\n")


def _audit_guard_unavailable(exc: BaseException) -> None:
    """Record the fail-closed denial in the permanent audit stream so engine outages are not blind spots in telemetry."""
    from . import dispatcher as _disp
    try:
        _disp.log_event(
            "stop" if _CRASH_CONTEXT.get("stop") else (_CRASH_CONTEXT.get("tool") or "unknown"),
            "BLOCKED",
            "engine",
            f"[GUARD_UNAVAILABLE]: {type(exc).__name__}: {str(exc)[:200]}",
            rule_id="GUARD_UNAVAILABLE",
            conversation_id=_CRASH_CONTEXT.get("conversation_id") or None,
        )
    except Exception as audit_err:
        sys.stderr.write(f"[GravityGuard] could not audit GUARD_UNAVAILABLE: {type(audit_err).__name__}\n")


def _recover_from_crash() -> Optional[dict]:
    """Keep the guard useful after an engine defect without failing open."""
    from . import dispatcher as _disp
    raw = _CRASH_CONTEXT.get("raw") or ""
    if not raw.strip():
        return None
    answer = _disp.run_lkg(raw, sys.argv)
    if answer is not None:
        return {**answer, "_recovery": "GUARD_FALLBACK_LKG"}
    reason = _disp.repair_reason(raw)
    return {"decision": "allow", "reason": reason, "_recovery": "GUARD_REPAIR_MODE"} if reason else None


def _audit_recovery(recovery: str, exc: BaseException) -> None:
    from . import dispatcher as _disp
    try:
        _disp.log_event(
            "stop" if _CRASH_CONTEXT.get("stop") else (_CRASH_CONTEXT.get("tool") or "unknown"),
            "WARNING",
            "engine",
            f"[{recovery}]: engine defect {type(exc).__name__}: {str(exc)[:160]}",
            rule_id=recovery,
            conversation_id=_CRASH_CONTEXT.get("conversation_id") or None,
        )
    except Exception as audit_err:
        sys.stderr.write(f"[GravityGuard] could not audit {recovery}: {type(audit_err).__name__}\n")


def run_cli() -> None:
    from . import dispatcher as _disp
    real_stdout = sys.stdout
    buf = io.StringIO()
    exit_code = None
    try:
        with contextlib.redirect_stdout(buf):
            try:
                _disp.validate_gravityguard()
            except SystemExit as done:
                exit_code = done.code
    except Exception as crash:
        real_stdout.write(buf.getvalue())
        import traceback
        _log_cli_error(traceback.format_exc())
        recovered = _recover_from_crash()
        if recovered is not None:
            recovery = recovered.pop("_recovery")
            _audit_recovery(recovery, crash)
            print(json.dumps(recovered))
            return
        _audit_guard_unavailable(crash)
        print("[GravityGuard] validation failed; operation was not validated", file=sys.stderr)
        print(json.dumps({"decision": "continue" if "--stop" in sys.argv else "deny",
                          "reason": "[GUARD_UNAVAILABLE]: Validation could not complete"}))
        return
    out = finalize(buf.getvalue(), bool(_CRASH_CONTEXT.get("stop")), str(_CRASH_CONTEXT.get("conversation_id") or ""), _CRASH_CONTEXT)
    real_stdout.write(out)
    real_stdout.flush()
    if exit_code is not None:
        sys.exit(exit_code)
