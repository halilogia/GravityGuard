"""Leftover debugger statements in committed code."""
from gravityguard_engine.plugin_rules import regex_rule

RULE = regex_rule(
    id="NO_DEBUGGER",
    pattern=r"^\s*(debugger\s*;?|breakpoint\(\)|import\s+pdb\b|pdb\.set_trace\(\))",
    message="Debugger statement left in code.",
    tip="Remove the debugger statement before finishing; use a log call if the trace is still needed.",
    example="log.debug('state=%s', state)",
    extensions=(".py", ".js", ".ts", ".tsx", ".jsx"),
    bad="def f():\n    breakpoint()\n    return 1\n",
    good="def f():\n    return 1\n",
)
