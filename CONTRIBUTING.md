# Contributing to GravityGuard

The easiest contribution is a new rule. A rule is one small Python file; you do not touch the dispatcher.

## Add a rule in five minutes

```bash
python tools/new_rule.py NO_TODO_WITHOUT_OWNER          # add --deny only if the edit must be blocked
```

This creates `engine/gravityguard_engine/rules/no_todo_without_owner.py`. Fill in the placeholders:

```python
from gravityguard_engine.plugin_rules import regex_rule

RULE = regex_rule(
    id="NO_TODO_WITHOUT_OWNER",
    pattern=r"TODO(?!\()",                     # matched against every added or changed line
    message="TODO without an owner.",
    tip="Write TODO(name) so the note has somebody to ask.",
    example="# TODO(emre): handle empty input",
    extensions=(".py", ".ts"),                 # empty tuple = every file
    bad="x = 1  # TODO fix\n",                 # must trigger
    good="x = 1  # TODO(emre) fix\n",          # must not trigger
)
```

Run the tests from the repo root:

```bash
python -m unittest discover -s engine -p "test_plugin_rules.py"
```

You do not write a test. The suite loads every file in `rules/` and checks that `bad` triggers the rule and `good`
does not, that the id is unique and `UPPER_SNAKE_CASE`, and that `message`, `tip` and both samples are filled in.

## What a rule can do

| Need | Use |
|---|---|
| Match a pattern on changed lines | `regex_rule(...)` |
| Own logic (several lines, file-level checks) | `Rule(..., check=fn)` where `fn(ctx)` returns a list of `(line_number, text)` |
| Block the edit | `severity="deny"`. Default is `"warn"`, which never blocks. Prefer warn. |
| Only some files | `extensions=(".py",)` |
| Also check test files | `skip_tests=False` (test files are skipped by default) |

`ctx` has `path`, `ext`, `added` (only new or modified lines as `(line_number, text)`) and `content` (the whole file after the edit).
See `rules/design_scrollbar.py` for a rule with its own check function.

## Turning a rule off or observing it

Users control rules in `.gravityguard.json`; no code change:

```json
{ "rules": { "NO_TODO_WITHOUT_OWNER": "shadow", "NO_DEBUGGER": "off" } }
```

`shadow` records `SHADOW_TRIGGER` in the audit log without warning or blocking. A good path for a new rule: ship it as
`warn`, watch the audit log, and only then consider `deny`.

## Rules of the project

- **No self-exemption.** Rules are loaded only from `engine/gravityguard_engine/rules/`. Nothing is read from a user
  folder, so an agent cannot add or disable a rule for itself.
- **Fast and deterministic.** No network, no model calls, no AST walks over whole projects. The hook has a 15 s budget
  and most calls finish in well under 100 ms.
- **A broken rule never breaks the hook.** An exception inside a rule is skipped and written to stderr.
- **Evidence in the message.** Say what is wrong and what to do instead; the `tip` is appended to rejections.
- Files under `engine/` are guarded: keep each file under about 500 lines and add an entry to `CHANGELOG.md`.

## Before you open a pull request

```bash
npm test
npm run test:engine
```
