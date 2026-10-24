"""Mandatory security floor and control-plane write protection.

This is hook enforcement, not an OS permission boundary. Human-owned policy
and runtime files still require host filesystem protection against shell writes.
"""
import json
from pathlib import Path

MANDATORY_RULES = frozenset(("G0_SECRET_LEAK", "G0_ENV_PROTECTION", "POLICY_INTEGRITY",
                             "TOOL_SCHEMA_UNSUPPORTED", "PROJECTION_UNSUPPORTED"))


def check_policy_change(target: str, projected: str) -> str:
    """Return a reason when an agent attempts to disable mandatory protection."""
    path = Path(target)
    if path.name.lower() == ".gravityguard.json":
        try:
            cfg = json.loads(projected)
        except (ValueError, TypeError):
            return "Policy must be a valid JSON object"
        if not isinstance(cfg, dict):
            return "Policy must be a JSON object"
        rules = cfg.get("rules", {})
        if not isinstance(rules, dict):
            return "Policy rules must be an object"
        for rule in MANDATORY_RULES:
            entry = rules.get(rule)
            if entry is not None and entry not in ("enforce", "block"):
                if not isinstance(entry, dict) or entry.get("mode", "enforce") not in ("enforce", "block"):
                    return f"Mandatory security rule cannot be weakened: {rule}"
    return ""


def is_runtime_control_file(target: str) -> bool:
    """Installed hooks, receipts and guard runtime are agent-read-only."""
    path = Path(target).resolve()
    parts = [part.lower() for part in path.parts]
    if path.name.lower() == "hooks.json" and any(part in parts for part in (".agents", ".gemini")):
        return True
    if ".claude" in parts and path.name.lower() in ("settings.json", "settings.local.json"):
        return True
    if ".gravityguard" in parts and any(part in parts for part in ("runtime", "reviews")):
        return True
    home = Path.home()
    for folder in (".antigravity-ide", ".vscode"):
        extensions = home / folder / "extensions"
        try:
            relative = path.relative_to(extensions.resolve())
            if relative.parts and relative.parts[0].lower().startswith("halilogia.gravityguard-"):
                return True
        except ValueError:
            pass
    installed = home / ".gemini" / "config" / "plugins" / "gravityguard"
    try:
        path.relative_to(installed.resolve())
        return True
    except ValueError:
        return False
