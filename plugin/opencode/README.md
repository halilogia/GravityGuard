# GravityGuard — OpenCode adapter

Connects OpenCode (v2, global config `~/.config/opencode`) to the GravityGuard engine. Every OpenCode tool call
is checked before execution and every session end runs the Stop hook, so OpenCode sessions land in the same
`~/.gemini/logs/srp_guardian_live.json` stream and permanent audit log as Antigravity, Claude Code and Codex —
attributed to the `OpenCode` agent (⚫ `OpenCode CLI` badge in the panel).

## Files

| File | Role |
| --- | --- |
| `gravityguard_opencode_hook.py` | Adapter: OpenCode event -> engine payload -> `{"block": bool, "reason": str}` |
| `gravityguard_opencode_plugin.ts` | OpenCode **v2** plugin: `export default { id: "gravityguard", setup }` (same shape as `Plugin.define`, written without an npm import so a bare local plugin file needs no dependency) |
| `install.py` | Copies the plugin to `~/.config/opencode/plugins/gravityguard.ts`, backs up, verifies |

## Install

```
python plugin/opencode/install.py          # install / update (+ engine check)
python plugin/opencode/install.py --check  # drift check only
```

`~/.config/opencode/plugins/` is a watched directory: OpenCode v2 hot-reloads the plugin on write. If the panel
still shows a stale failure, run `opencode service restart`.

Verify with `opencode plugin list` — it must list `gravityguard  local  .../gravityguard.ts`.

## Hooks used

| OpenCode v2 API | Purpose |
| --- | --- |
| `ctx.tool.hook("execute.before")` | Engine check on `write` / `edit` / `multiedit` / `patch` / `read` / `bash`; `deny` throws, which aborts the call |
| `ctx.event.subscribe({ types: ["session.idle"] })` | Engine Stop hook: obligations, T1 test-evidence warnings, final secret scan, task archiving (logged, not forced continuation) |


## Coverage

| OpenCode tool | Engine dialect | Guard |
| --- | --- | --- |
| `write` | `write_to_file` | G0-G4, SRP, doc/test obligations |
| `edit` | `replace_file_content` | same |
| `multiedit` | `multi_replace_file_content` | same |
| `read` | `read_file` | `.env` protection, token guard |
| `bash` | `bash` (passthrough) | shell security + token guard |
| `patch` | `apply_diff` (diff text) | explicitly denied — a unified diff cannot be checked as a file operation |

Stop hook (`session.idle`): obligations, T1 test evidence warnings, final secret scan, task archiving. OpenCode v2
has no forced-continuation stop gate, so a `continue` verdict is surfaced in the server log (`[GravityGuard] ...`) while
the event itself is audited — unlike Antigravity, Claude Code and Codex, where Stop blocks the session.

## Identity

The adapter prefixes the conversation id with `opencode:`; the engine maps that prefix to `OpenCode`
(`engine/gravityguard_engine/audit.py`, `detect_agent_name`), and the panel renders the ⚫ badge
(`src/webview/tabs/live.ts`, `renderAgentBadge`).

## Fail-open contract

Missing python, missing adapter or an unreadable engine answer never wedges OpenCode: the call proceeds and the
reason is printed to stderr (`[GravityGuard] ...`). `GRAVITYGUARD_ADAPTER_FAIL_OPEN=1` disables even the
`[GUARD_UNAVAILABLE]` deny.

Environment overrides: `GRAVITYGUARD_OPENCODE_HOOK` (adapter path), `GRAVITYGUARD_ENGINE`, `GRAVITYGUARD_PYTHON`.

## Tests

```
node --test tests/opencode_adapter.test.mjs
npm run test:engine   # engine suite (agent identity included)
```
