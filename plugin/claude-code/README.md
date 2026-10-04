# GravityGuard for Claude Code

A thin adapter that lets Claude Code use the **unchanged** GravityGuard engine. It translates Claude Code's hook events into the engine's payload, runs `engine/gravity-validator.py`, and translates the answer back. Rules, state files and the audit log are the same as under Antigravity.

## Install

1. Copy `settings.example.json` into your project's `.claude/settings.json` (or `~/.claude/settings.json`) and replace `<GRAVITYGUARD>` with the absolute path of this repository. Use forward slashes on Windows.
2. Start Claude Code and run `/hooks` once to confirm both hooks are listed.

Python 3.10+ is the only requirement; the engine has no dependencies. To use an engine somewhere else, set `GRAVITYGUARD_ENGINE` to the full path of its `gravity-validator.py`.

## What it does

| Claude Code event | What the adapter does |
|---|---|
| `PreToolUse` — `Write`, `Edit`, `MultiEdit` | Runs the file rules (G0 secrets, G1 silent exceptions, G2 test integrity, G3, G4, SRP, …). A BLOCK becomes a `deny` with the engine's reason; a warning is handed to the model as context and never as an `allow`, so your own permission prompt still appears. |
| `Stop` | Runs the lifecycle gate. Unfinished test/doc obligations of **this session** make Claude continue (`{"decision":"block"}`). Asked on **every** stop, including the ones Claude Code flags with `stop_hook_active`, so an agent cannot leave after one extra turn: the loop ends when the obligations are cleared, when the engine's circuit breaker releases the stop (after 5 blocked retries of the session), or when Claude Code overrides a Stop hook that blocked 8 times in a row. |

Each session is tracked as `claude:<session_id>`, so two Claude Code windows (or Claude Code and Antigravity) on the same project never block each other's Stop.

## What it does not do

- **`Bash` is not inspected.** A shell command cannot be reduced reliably to "these lines were added to that file", so `echo > file` or `sed -i` never reach the file rules. The git pre-commit secret net and the Stop gate are the backstops.
- **Fail-open.** If the engine is missing or crashes, the tool call proceeds and the reason is written to stderr (visible in Claude Code's verbose mode).
- **Cost.** Every guarded write starts two short Python processes (the adapter, then the engine): expect a few hundred milliseconds per `Write` / `Edit`.
- Language coverage is the engine's: GDScript and other languages get the secret rules and the generic ones, not the Python-specific ones (G1 looks for a literal `pass` in an `except`).

## Trying it on an existing codebase: shadow mode first

Some rules fire on code that is deliberate (a codebase with many intentional `except: pass` blocks would be blocked at every write). Run them in shadow mode first: they are logged but never block or warn. Put this in the project's `.gravityguard.json`:

```json
{
  "rules": {
    "G1_SILENT_EXCEPTION": { "mode": "shadow" }
  }
}
```

Look at the audit log after a few sessions, then decide per rule whether to keep it in shadow, tune it, or switch it on.
