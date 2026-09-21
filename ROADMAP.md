# Roadmap — GravityGuard

This document outlines the strategic evolution, architectural milestones, and planned releases for **GravityGuard**.

---

## Current Status: v1.2.6 (Phase 1, Phase 2 & Phase 2.5 Released & Frozen)

### ✅ Phase 1: High-Confidence Integrity & Architecture Guards
- [x] **Universal Rebranding & Setup**: Standalone repository under `GitHub/Public/GravityGuard` with full TypeScript IDE extension + Python Guard Engine.
- [x] **G0 — Secret Leak Guard (BLOCK / WARN)**:
  - High-confidence credential airbag blocking OpenAI, Anthropic/Claude, Google/Gemini, Slack, GitHub tokens, and private keys in diffs.
  - Audit warnings for raw connection URIs and bearer tokens.
  - Strict evidence masking (`sk-ant-****...****890`) preventing secondary leaks in logs or stdout.
- [x] **G1 — Silent Exception Guard (BLOCK)**:
  - Detects newly added empty exception handlers (`except: pass`, `except: ...`, `catch {}`).
  - Strict diff-based evaluation via `difflib.SequenceMatcher` (existing unchanged handlers are preserved without false alarms).
  - Permits recovery fallbacks (`return None`, `return []`).
- [x] **G2 — Test Integrity Guard (BLOCK / WARN)**:
  - Blocks newly added test disabling tricks (`.skip()`, `xit()`, `xdescribe()`, `@pytest.mark.skip`, `@unittest.skip`).
  - Warns on focused tests (`.only()`).
  - Permits test expected failures (`@pytest.mark.xfail`).
  - Blocks outright deletion of existing test cases (`def test_...` / `it(...)`) using full-file frequency counters (`collections.Counter`).
  - Allows normal test body refactoring without false positives.
- [x] **G3 — Compiler & Linter Bypass Guard (WARN)**:
  - Detects newly added `# noqa`, `# type: ignore`, `@ts-ignore`, `@ts-nocheck`, `eslint-disable`.
  - Emits warning audit logs without blocking legitimate workarounds.
- [x] **G4 — Import Matrix Guard (BLOCK)**:
  - User-configurable layer boundaries via `.gravityguard.json` (e.g. `ui` forbidden from importing `network` or `database`).
  - Supports Python relative imports (`from .network import ...`) and TypeScript side-effects (`import './network'`).
  - Exact path-segment matching prevents false substring collisions.
  - Blocks illegal cross-layer imports deterministically in < 2ms.
- [x] **OE_SPIKE — Over-Engineering Heuristic (WARN ONLY)**:
  - Passive warning when small production changes (<50 LOC) introduce a disproportionate abstraction spike (2+ new classes/interfaces).
- [x] **SRP Boundary Guard (BLOCK)**:
  - Blocks single files mixing UI libraries and Network/HTTP libraries, or accumulating 4+ major business classes.
- [x] **Status Bar Prompt Enhancer (`Ctrl + Alt + E`)**:
  - Integrated 9Router local AI pipeline with sub-3s model failover.
- [x] **Live Security Monitor Webview**:
  - Real-time Activity Bar panel streaming audit events from `~/.gemini/logs/srp_guardian_live.json`.
- [x] **92/92 Automated Unit Tests Passing** (`engine/test_gravity_validator.py`).

---

## ✅ Phase 2: Test Evidence & Intent-Aware Enhancer (v1.1.0)
- [x] **T1 — Missing Related Test (WARN)**: Verifies that production code changes have an associated candidate test file on disk and recent modification window (`sessionWindowSeconds`, default 300s). Dynamically honors `sourceRoots` and `testRoots` from `.gravityguard.json`. Respects exemption allowlist (`types`, `constants`, `index`, `*.d.ts`, `migrations`, `config`, `schemas`).
- [x] **T2 — Observable Assertion Verification (WARN)**: Case-level verification using AST/line-span tracking that modified/added test cases contain observable assertions (`assert`, `self.assert*`, `pytest.raises`, `expect()`, `.toBe()`, `.toEqual()`, `.toThrow()`). Catches body-only modifications without declarations, prevents assertion masking across multiple tests, and protects fixture/beforeEach/describe setups from false alarms.
- [x] **T3 — Symbol-to-Test Link (WARN)**: Body-aware line-span verification that newly added or modified top-level functions, classes, and exported arrow functions are referenced by name in the candidate test file. Ignores scalar constants (`export const MAX = 3`). Emits grouped warning if any changed symbol is absent. Zero blocking.

---

## ✅ Phase 2.5: Static Validation & Architecture Guidance (v1.2.0 - FROZEN)
- [x] **ARCH_FILE_GROWTH Guard (WARN ONLY)**:
  - Detects monolithic file accumulation: (1) Projected LOC >= 1000, (2) Single tool-call addition >= 180 LOC, (3) Creeping growth on 800+ LOC file with >= 80 LOC addition.
  - Zero blocking — prompts AI toward modularity and SRP boundaries.
- [x] **Tier 2 / Tier 3 Async Static Validation Pipeline & Real Orchestration**:
  - Preserved the **< 10 ms Fast Guard Invariant**: Pre-tool path strictly runs zero external compilers or linters.
  - **Hidden Background Orchestration**: `trigger_background_validation()` launches `async_runner.py` in ~1ms without waiting for completion, using `CREATE_NO_WINDOW` + `SW_HIDE` so no console window ever appears (see v1.2.1 fix).
  - **State-Based TS Debounce Worker**: Persistent `.gravityguard/runtime/debounce_state.json` enforces a real 3.0s idle window after edit bursts before running `tsc --noEmit`. Bounded by explicit termination guards + a `max_lifetime` cap. Every exit path that leaves a state file behind now releases the `worker_running` claim first, so the guard cannot permanently block future spawns (see v1.2.1 and v1.2.3 fixes).
  - **Per-File TSC Diagnostics**: `parse_tsc_output` maps project compilation errors directly to modified target files (`auth.ts`).
  - **Per-File Lint Burst Coalescing & State Cleanup**: 300ms quiet window for single-file linters (`ruff`, `eslint`, `godot`) with state-based duplicate suppression across rapid multi-edit bursts, automatically purging finished state from `debounce_state.json`. The claim is best-effort, not a formal atomic mutex.
  - **New-File Grace Period**: since GravityGuard is a `PreToolUse` hook, the worker is spawned *before* the file exists. It waits a bounded 2.0s grace period for the target to land, lints once when it does, and exits cleanly if it never appears (see v1.2.2 fix).
  - **Diagnostics Bridge**: `.gravityguard/runtime/diagnostics.json` stores linter findings; `STATIC_LINTER_DIAGNOSTIC (WARN)` reads them in sub-millisecond time.
- [x] **Prompt Enhancer Architectural Guidance Preamble**:
  - System prompt directives favoring cohesive modules over monolithic accumulation.


### 2.2. Intent-Aware Prompt Enhancer
- [~] Intent-aware enhancement — **partially implemented, and NOT automated**:
  - The `systemPrompt` in `src/extension.ts` instructs the *downstream* model to classify intent itself. There is no local classifier, no keyword analysis and no programmatic routing in the extension, so the `[ ] Automated` label was overstated.
  - [x] **Consulting / Brainstorming Mode** — present as directive A ("İSTİŞARE / FİKİR / BEYİN FIRTINASI"): demands options, trade-offs and over-engineering risks, and explicitly forbids issuing build orders.
  - [x] **Implementation Mode** — present as directive B ("UYGULAMA / KODLAMA"): demands a defensive specification (purpose, architecture, SRP boundaries, error handling, tests).
  - [ ] **Audit / Refactoring Mode** — **absent.** No directive covers boundary compliance, dead-code removal or test integrity.
  - [ ] No verification that the classifier actually behaves as instructed; behaviour depends entirely on the model's compliance.

---

## Phase 3: v1.3.0 — Extended Complexity Guard & Pre-Tool Whisperer

*Target: Q1 2027*

### 3.1. Extended Complexity Heuristics (YAGNI)
- [ ] Forwarding wrapper layer detection (classes that merely forward calls across 3+ layers without logic).
- [ ] Single-implementation abstraction warnings for private internal modules.
- [ ] Dependency creep detector (new external dependencies added for single small functions).

### 3.2. Pre-Hook Architecture Whisperer
- [ ] Intercept AI agent tool calls before execution (`pre-tool hook`).
- [ ] Automatically inject active layer boundaries and architectural rules into the agent's prompt context to prevent violations before code is generated.

### 3.3. `run_command` Mutation Detection (P3-02)
- [ ] Narrow pre-filter for obvious filesystem mutation commands (`Remove-Item`, `del`, `rmdir`, `rm`, `move`, `Move-Item`, `Set-Content`, `Out-File`, `Add-Content`).
- [ ] **Do NOT** deep-analyze every terminal command. Fast-path allow ordinary work: `git status/diff/log/show`, `python -c`, `blender --background --python`, `npm`, `pytest`.
- [ ] Explicitly document that bypass remains possible (`python x.py` calling `os.remove`, `blender --python` scripts) — this closes obvious paths only, not all paths.
- [ ] Performance must be measured on a **real coding session** — not on this conversation's transcript, which is polluted with diagnostic commands.
- [ ] Known measured baseline (this repo's log): ~30.7% git, ~28.5% arbitrary Python/Blender code exec, ~2% file mutation commands.

### 3.4. Controlled Test Maintenance Mode (P3-01)
- [ ] User can consciously authorize test cleanup; only **G2** relaxes while the mode is active.
- [ ] **AI must not be able to grant this permission to itself** — otherwise the guard stops being a boundary.
- [ ] No broad bypass without explicit user approval.
- [ ] Authorization mechanism intentionally undecided: `.gravityguard.json` is technically easy but is AI-modifiable (so not a security boundary); an environment variable is impractical for an already-running Antigravity process (env vars are read at process start).
- [ ] Note: G2 currently blocks test deletion, renaming, `.skip`, and moving a test to `archive/`, with no escape hatch equivalent to `# srp: bypass`.

### 3.5. Git Secret Safety Net — commit-time hook (P3-03)
> This is a **local machine layer**, separate from GravityGuard's engine. It lives in `.git/hooks`, which is not version-controlled.

- [x] Replaced the dead `lefthook` trigger with a **portable** `loss-guard.py` call (no hardcoded user paths).
- [x] Applied to `~/.git-template` + 12 repositories (8 previously dead, 4 previously alive).
- [x] Extended secret-scan scope from `{.tsx,.jsx,.ts,.js,.vue,.svelte}` to include `.py`, `.pyw`, `.pyi`.
- [x] Verified: synthetic `.ts` / `.js` / `.py` / `.pyw` commits are blocked; a clean file passes.
- [x] **Fixed:** the interactive confirmation prompt (`CONIN$`) used to hang forever when no console was attached, so the commit never completed. The prompt was removed entirely; warnings are now informational and never block. Verified: warning-producing commit completes in 0.7s.
- [x] **Fixed:** reverted the `pre-push` hook to a no-op in 9 repositories (it inspected staged files, which is meaningless at push time).
- [x] **Expanded scan coverage (measured):** the guard previously scanned only 9 file types. A 16-type probe showed `.env`, `.json`, `.yaml`, `.toml`, `.ipynb`, `.sh`, `.ps1`, `.bat`, `.gd`, `.godot` all passed through unscanned. Fixed with a **two-list design**: `SECRET_EXTENSIONS` (wide, ~30 types, secret scan only) and `STRUCTURAL_EXTENSIONS` (narrow, code files only, the four structural checks). This widens detection without adding a single warning to non-code files.
- [x] **Hardened `secret_checker.py`:** added AWS (`AKIA`), HuggingFace (`hf_`), GitLab (`glpat-`), Stripe (`sk_live_`/`rk_live_`), Telegram bot, npm, and PyPI patterns, plus PEM private-key block headers. Added placeholder skipping (so `.env.example` and documentation examples do not false-block) and value masking + line numbers in the block message.
- [x] **Template-diff verification:** all 12 repository copies verified byte-identical to `~/.git-template/hooks`.
- [x] **Global gitignore:** `core.excludesFile` was unset (no global protection at all). Created `~/.gitignore_global` covering `.env*`, `*.key`, `*.pem`, `credentials.json`, `secrets.*`, `id_rsa`, etc. This prevents secrets from being staged in the first place across all 55 repositories; the hook remains the detection layer for `git add -f` overrides.
- [x] **Backup consolidation:** 105 scattered `.bak-before-*` files (161.5 KB) moved from hidden `.git/hooks` directories into `~/.git-hook-backups/`, tagged with their originating repository. Nothing deleted.
- [ ] Scope note: of the 5 checks in `loss-guard`, only the secret check is relevant to Python projects; the other 4 (visual tags, React hooks, lazy placeholders, `components/` line balance) target web/React code.

### 3.6. Repo ↔ Live Plugin Synchronization (P3-04)
> The guard engine exists as **two copies**: the repo source (`engine/gravity-validator.py`) and the live plugin copy (`~/.gemini/config/plugins/srp-swarm-guardian/scripts/srp-validator.py`). The plugin copy is renamed because `hooks.json` invokes `python scripts/srp-validator.py`. The two directories are separate deployment targets, so the duplicate cannot be eliminated — only kept in check.

- [x] **Risk identified and closed with tooling.** No sync mechanism existed. This is the same failure mode as the earlier `lefthook` incident: one copy is edited, the other silently rots, and live protection degrades without any signal.
- [x] **Added `tools/sync_plugin.py`** — copies repo engine → live plugin:
  - `--check` reports drift only and exits `1` when copies differ (safe for pre-commit / CI).
  - `--dry-run` prints the plan without touching anything.
  - Default mode backs the old target up into `~/.git-hook-backups/plugin-sync/` before copying.
  - Validates the source with `ast.parse` **before** copying, so a broken file can never be pushed into the live hook.
  - Verifies the copy with MD5 **after** copying; a mismatch is reported as failure (exit `2`).
  - Files tracked: `engine/gravity-validator.py` → `scripts/srp-validator.py`, and `engine/async_runner.py` → `scripts/async_runner.py`.
- [x] **Verified by deliberate drift injection:** a synthetic 21-byte line was appended to the live plugin copy. `--check` correctly reported `FARKLI / drift` and exited `1`; the default mode restored the file and confirmed it by MD5 (`f1bbb2af…`). Test residue was removed afterwards.
- [x] **Now automated — `tools/autosync_plugin.py`**, wired into `.git/hooks/pre-commit` right after the secret scan. On every commit the repo engine is pushed to the live plugin, so the repo is the single source of truth at commit time.
  - **Design boundary (deliberate):** this is a convenience, not a security boundary. It never blocks the commit when the plugin directory is absent or a copy fails. It stops the commit **only** when a source file fails `ast.parse`, so a broken file can never reach the live hook.
  - Silent when there is no drift, so ordinary commits stay quiet.
  - Backs the previous plugin copy up into `~/.git-hook-backups/plugin-sync/` before overwriting.
- [x] **Verified end-to-end (three tests):** (1) no drift → silent, exit `0`; (2) injected drift → copied and MD5-confirmed, exit `0`; (3) deliberately broken source → exit `1` **and the live plugin remained intact** (`f1bbb2af…`). Also confirmed via a real `git commit`, where the hook fired and repaired the drift. All test residue and the temporary commit were reverted.
- [ ] **Open naming debt:** the same file is `gravity-validator.py` in the repo and `srp-validator.py` in the plugin. A search finds no cross-reference between the two names, so the relationship is invisible to anyone reading either side.

### 3.7. Repository Hygiene (local cleanup, 2026-09-20)
- [x] Removed the `.kilo/worktrees/magnificent-earth` git worktree via `git worktree remove --force`. It was **not** a stale copy — it sat on the same commit (`2377035`) with identical line counts; the byte delta (1526 B) exactly matched the line count, i.e. a pure CRLF-vs-LF difference under `core.autocrlf=true`.
- [x] Removed `srp-validator.py.bak-v123` (63,454 B). Confirmed as a manual snapshot of `v1.2.3`: its size matches `git cat-file -s 8ad8bef:engine/gravity-validator.py` exactly, so it remains recoverable from history. (Its exact original location was not conclusively re-verified before deletion; the size match is the evidence that matters.)
- [x] **Found and archived:** the plugin's `skills/srp-modularizer/` folder contained five unrelated files — `SKILL (1).md` (SOLID Principles), `SKILL (2).md` (@json-render/solid), `SKILL(3).md` (Requesting Code Review), `solid.md`, and `solid-skills-main.zip`. Their word-overlap with the real `SKILL.md` was 7–10% (i.e. unrelated content), the `(1)`/`(2)` suffixes indicated browser download duplicates, and none was referenced by any other file. **Moved (not deleted) to `Desktop/GG-artik/`** on user instruction, leaving only `SKILL.md` and `Single-Responsibility-Principle.md` in the skill folder.
- [ ] **Note:** `.gravityguard/runtime/` empty directories regenerate on their own because the engine recreates them; deleting them is pointless.

---

## 4. Explicit Anti-Goals & Out-of-Scope Boundaries

To maintain sub-10ms gatekeeping latency and prevent catastrophic scope creep, GravityGuard explicitly rejects the following product directions:

### ❌ Anti-Goal 1: Becoming a SonarQube / CodeQL Alternative
- **Why**: SonarQube, Semgrep, and CodeQL are heavy, asynchronous, whole-repository static analysis platforms evaluating cognitive complexity, code duplication, CVE vulnerabilities, and deep inter-procedural dataflow taint. Attempting to replicate this inside an AI tool-interception hook introduces massive latency, clutters prompt feedback with low-priority stylistic nits, and duplicates decades of solved compiler engineering.
- **Enforcement**: Deep static governance belongs strictly to Ring 4 (CI/CD Quality Gates), not GravityGuard.

### ❌ Anti-Goal 2: Heavy In-Hook AST & Cross-File Taint Tracking
- **Why**: The synchronous `PreToolUse` fast guard path operates under a strict **< 10ms execution budget** (measured typical: 0.1ms - 2ms). Running full cross-file dependency graph resolution or global symbol tables in Tier 1 would cause noticeable agent stuttering and prompt developers to bypass the gatekeeper.
- **Enforcement**: Fast guard checks must remain localized to ephemeral tool diffs and lightweight regex/shallow AST checks.

### ❌ Anti-Goal 3: Code Formatting & Stylistic Linting
- **Why**: Line lengths, trailing commas, indentation, and variable naming styles are solved deterministically by existing formatters (`Prettier`, `Ruff format`, `Black`). GravityGuard must not warn or block on superficial formatting matters.

### ❌ Anti-Goal 4: Replacing Behavioral Test Execution
- **Why**: Static code inspection (AST/regex) can verify structural presence (e.g. T1 test file existence, T2 assertion counts, T3 symbol names), but can **never** verify behavioral correctness or runtime contracts. GravityGuard verifies test evidence presence, but defers behavioral proof to native test runners (`vitest`, `pytest`).

### ❌ Anti-Goal 5: Autonomous AI Self-Exemption
- **Why**: An AI agent must never be permitted to weaken or bypass blocking integrity rules (`G0`, `G1`, `G2`, `G4`) autonomously through synthetic escape comments or self-authorizing config flags. A guard that an agent can talk itself out of is not a security boundary.
