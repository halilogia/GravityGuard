# Roadmap — GravityGuard

This document outlines the strategic evolution, architectural milestones, and planned releases for **GravityGuard**.

---

## Current Status: v1.2.0 (Phase 1, Phase 2 & Phase 2.5 Released)

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
- [x] **69/69 Automated Unit Tests Passing** (`engine/test_gravity_validator.py`).

---

## ✅ Phase 2: Test Evidence & Intent-Aware Enhancer (v1.1.0)
- [x] **T1 — Missing Related Test (WARN)**: Verifies that production code changes have an associated candidate test file on disk and recent modification window (`sessionWindowSeconds`, default 300s). Dynamically honors `sourceRoots` and `testRoots` from `.gravityguard.json`. Respects exemption allowlist (`types`, `constants`, `index`, `*.d.ts`, `migrations`, `config`, `schemas`).
- [x] **T2 — Observable Assertion Verification (WARN)**: Case-level verification using AST/line-span tracking that modified/added test cases contain observable assertions (`assert`, `self.assert*`, `pytest.raises`, `expect()`, `.toBe()`, `.toEqual()`, `.toThrow()`). Catches body-only modifications without declarations, prevents assertion masking across multiple tests, and protects fixture/beforeEach/describe setups from false alarms.
- [x] **T3 — Symbol-to-Test Link (WARN)**: Body-aware line-span verification that newly added or modified top-level functions, classes, and exported arrow functions are referenced by name in the candidate test file. Ignores scalar constants (`export const MAX = 3`). Emits grouped warning if any changed symbol is absent. Zero blocking.

---

## ✅ Phase 2.5: Static Validation & Architecture Guidance (v1.2.0)
- [x] **ARCH_FILE_GROWTH Guard (WARN ONLY)**:
  - Detects monolithic file accumulation: (1) Projected LOC >= 1000, (2) Single tool-call addition >= 180 LOC, (3) Creeping growth on 800+ LOC file with >= 80 LOC addition.
  - Zero blocking — prompts AI toward modularity and SRP boundaries.
- [x] **Tier 2 / Tier 3 Async Static Validation Pipeline & Real Orchestration**:
  - Preserved the **< 10 ms Fast Guard Invariant**: Pre-tool path strictly runs zero external compilers or linters.
  - **Detached Background Orchestration**: `trigger_background_validation()` launches `async_runner.py` in ~1ms without waiting for completion.
  - **State-Based TS Debounce Worker**: Persistent `.gravityguard/runtime/debounce_state.json` enforces a real 3.0s idle window after edit bursts before running `tsc --noEmit`.
  - **Diagnostics Bridge**: `.gravityguard/runtime/diagnostics.json` stores linter findings; `STATIC_LINTER_DIAGNOSTIC (WARN)` reads them in sub-millisecond time.
- [x] **Prompt Enhancer Architectural Guidance Preamble**:
  - System prompt directives favoring cohesive modules over monolithic accumulation.


### 2.2. Intent-Aware Prompt Enhancer
- [ ] Automated query classification:
  - **Consulting / Brainstorming Mode**: Produces trade-off analyses, architectural choices, and risk pre-mortems.
  - **Implementation Mode**: Produces strict, defensive, SRP-compliant implementation specifications.
  - **Audit / Refactoring Mode**: Focuses on boundary compliance, dead code removal, and test integrity.

---

## Phase 3: v1.2.0 — Extended Complexity Guard & Pre-Tool Whisperer

*Target: Q1 2027*

### 3.1. Extended Complexity Heuristics (YAGNI)
- [ ] Forwarding wrapper layer detection (classes that merely forward calls across 3+ layers without logic).
- [ ] Single-implementation abstraction warnings for private internal modules.
- [ ] Dependency creep detector (new external dependencies added for single small functions).

### 3.2. Pre-Hook Architecture Whisperer
- [ ] Intercept AI agent tool calls before execution (`pre-tool hook`).
- [ ] Automatically inject active layer boundaries and architectural rules into the agent's prompt context to prevent violations before code is generated.
