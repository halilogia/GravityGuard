# Roadmap — GravityGuard

This document outlines the strategic evolution, architectural milestones, and planned releases for **GravityGuard**.

---

## Current Status: v1.0.0 (Phase 1 — High-Confidence Guards Released)

### ✅ Phase 1: High-Confidence Integrity & Architecture Guards
- [x] **Universal Rebranding & Setup**: Standalone repository under `GitHub/Public/GravityGuard` with full TypeScript IDE extension + Python Guard Engine.
- [x] **G1 — Silent Exception Guard (BLOCK)**:
  - Detects newly added empty exception handlers (`except: pass`, `except: ...`, `catch {}`).
  - Strict diff-based evaluation (existing unchanged handlers are preserved without false alarms).
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
  - Blocks illegal cross-layer imports deterministically in < 2ms.
- [x] **OE_SPIKE — Over-Engineering Heuristic (WARN ONLY)**:
  - Passive warning when small production changes (<50 LOC) introduce a disproportionate abstraction spike (2+ new classes/interfaces).
- [x] **SRP Boundary Guard (BLOCK)**:
  - Blocks single files mixing UI libraries and Network/HTTP libraries, or accumulating 4+ major business classes.
- [x] **Status Bar Prompt Enhancer (`Ctrl + Alt + E`)**:
  - Integrated 9Router local AI pipeline with sub-3s model failover.
- [x] **Live Security Monitor Webview**:
  - Real-time Activity Bar panel streaming audit events from `~/.gemini/logs/srp_guardian_live.json`.
- [x] **52/52 Automated Unit Tests Passing** (`engine/test_gravity_validator.py`).

---

## Phase 2: v1.1.0 — Test Evidence & Intent-Aware Enhancer

*Status: 2.1 Released | 2.2 Target: Q4 2026*

### 2.1. Test Evidence Analyzer (T1, T2, T3) — Released ✅
- [x] **T1 — Missing Related Test (WARN)**: Verifies that production code changes have an associated candidate test file on disk and active session touch footprint. Respects exemption allowlist (`types`, `constants`, `index`, `*.d.ts`, `migrations`, `config`, `schemas`).
- [x] **T2 — Observable Assertion Verification (WARN)**: Lightweight verification that newly added/modified test cases (`def test_...`, `it(...)`, `test(...)`) contain observable assertions (`assert`, `self.assert*`, `pytest.raises`, `expect()`, `.toBe()`, `.toEqual()`, `.toThrow()`). Protects fixture/beforeEach/describe setups from false alarms.
- [x] **T3 — Symbol-to-Test Link (WARN)**: Verifies that newly added/modified top-level or exported production symbols (functions, classes) are referenced by name in the candidate test file. Never double-warns if test file is absent (T1 precedence). Zero blocking.

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
