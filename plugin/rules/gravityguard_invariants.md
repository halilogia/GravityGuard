---
description: GravityGuard Deterministic Architectural Invariants and Safety Rules
always_on: true
---

# GravityGuard Standing Architectural Invariants

GravityGuard executes deterministic deterministic gatekeeping (G0-G4, SRP, and test evidence verification) on every tool call and session termination. As an agent operating in this codebase or workspaces with GravityGuard installed, you must uphold the following mechanical invariants:

1. **G0 — Secret Leak Prevention (HARD BLOCK)**:
   - NEVER embed plaintext secrets, credentials, API keys (`sk-`, `ghp_`, `AKIA...`), or private keys in any file (code, docs, json, yaml, svg, tests).
   - Use environment variables (`os.environ.get(...)`) or secure secrets managers.

2. **G1 — No Silent Exception Swallowing (HARD BLOCK)**:
   - Bare `except: pass`, `except: ...`, or empty `catch (e) {}` blocks are strictly forbidden.
   - Always handle errors explicitly: log the error, provide fallback return values, or re-raise.

3. **G2 — Test Integrity & Anti-Tampering (HARD BLOCK)**:
   - Never delete existing test files or weaken assertions to make tests "turn green".
   - Never inject artificial `# gravityguard: exempt` escape-hatches to bypass security rules.

4. **G4 — Layer Import Matrix (HARD BLOCK)**:
   - Respect architectural boundaries defined in `.gravityguard.json` (e.g. `ui` layer cannot directly import `network` or `db`).
   - Use dependency inversion or shared service layers for cross-layer communication.

5. **T1/T2 — Test Evidence & Observable Assertions (WARN / STOP CHECK)**:
   - Production code changes must be accompanied by corresponding candidate test files (`test_<module>.py` or `<module>.test.ts`).
   - All tests must contain observable assertions (`assert`, `expect(...).toBe(...)`, `pytest.raises`). Empty or assert-free test bodies trigger warnings.

6. **§6 Same-Commit Documentation Rule (STOP CHECK)**:
   - If you modify behavioral code in a project with doc governance enabled, update `CHANGELOG.md` in the same commit before completing the turn.

7. **DESIGN_RESPONSIVE_RULE — Mobile Layout (HARD BLOCK / WARN)**:
   - Every HTML page needs `<meta name="viewport" content="width=device-width, initial-scale=1">` in `<head>`; a missing or invalid viewport is denied.
   - Fixed CSS widths of 1000px or more (`width`, `min-width`, `inline-size`, `min-inline-size`) trigger a warning; use `max-width`, `%` or fluid units.

8. **DESIGN_RAW_CONTROLS_RULE — No Raw Browser Controls (HARD BLOCK)**:
   - An unstyled `<input type="file">` is denied: hide it behind a custom button or style it with `::file-selector-button`.
   - An unstyled `<input type="number">` is denied: hide the stepper with `::-webkit-inner-spin-button { display: none }` and `appearance: textfield`.
   - Default scrollbars stay covered by `DESIGN_SCROLLBAR_RULE` (warn): give overflowing areas a thin, themed scrollbar.
   - Only the lines you add or change are checked; the rejection names the exact line and snippet.
