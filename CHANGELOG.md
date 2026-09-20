# Changelog — GravityGuard

All notable changes to **GravityGuard** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-09-20

### Added
- **ARCH_FILE_GROWTH Guard (Fast Guard — WARN ONLY)**:
  - Multi-condition heuristic radar detecting uncontrolled monolithic code accumulation without blocking the AI agent.
  - Triggers on: (1) Projected lines >= 1000, (2) Single tool-call addition >= 180 LOC, or (3) Creeping growth on 800+ LOC files with >= 80 LOC additions.
  - Exemption rules for test files (`test_*.py`, `*.test.ts`, `*.spec.ts`) and configured cohesive modules.
- **Detached Asynchronous Orchestration & Background Trigger**:
  - Implemented `trigger_background_validation(target_file)` in `engine/gravity-validator.py`.
  - Spawns `engine/async_runner.py` via detached OS subprocess (`DETACHED_PROCESS` on Windows, `start_new_session` on POSIX) without waiting for completion (returns in ~1 ms).
  - Evaluates changed code files strictly in the background without adding any synchronous delay to the AI tool-call loop.
- **State-Based TypeScript Debounce Worker**:
  - Implemented `run_debounce_worker` and `trigger_debounce_worker_if_needed` in `engine/async_runner.py`.
  - Persists state in `.gravityguard/runtime/debounce_state.json`.
  - Enforces a real 3.0-second idle window after tool bursts before triggering `tsc --noEmit`, completely eliminating repetitive compiler executions during rapid AI edits.
- **Tier 2 / Tier 3 Diagnostics State Bridge**:
  - Background findings recorded in `.gravityguard/runtime/diagnostics.json`.
  - `STATIC_LINTER_DIAGNOSTIC (WARN)`: Injects recent background linter findings into AI context during subsequent pre-tool calls (< 0.5 ms).
- **Per-File TypeScript Diagnostics Integration**:
  - Implemented `parse_tsc_output` in `engine/async_runner.py` parsing raw compiler output (`file(line,col): error TSxxxx: message`) into normalized per-file diagnostic entries.
  - Resolved the critical feedback loop gap: `read_recent_diagnostics(target_file)` now matches TypeScript compiler errors directly against modified target files (e.g. `auth.ts`) instead of dropping them in an unindexed global bucket.
- **Per-File Lint Burst Coalescing**:
  - Implemented `file_edits` tracking in `debounce_state.json` to prevent rapid duplicate linter executions when an AI agent modifies the same file multiple times within milliseconds.
- **Automated Test Suite Expansion (73/73 Passing)**:
  - Expanded test suite to **73 automated unit tests** (`engine/test_gravity_validator.py`), 73/73 passing.
  - Added deterministic tests for pure debounce idle decisions (`should_run_after_idle`), duplicate worker spawn protection, and detached subprocess invocation via `unittest.mock`.
  - Conducted 1,000-iteration statistical latency distribution benchmark:
    - **Average (Avg):** `0.1135 ms`
    - **95th Percentile (p95):** `0.1866 ms`
    - **99th Percentile (p99):** `0.7426 ms`

---

## [1.1.0] - 2026-09-20

### Added
- **G0 — Secret Leak Guard (BLOCK / WARN)**:
  - High-confidence credential airbag blocking OpenAI, Anthropic/Claude, Google/Gemini, Slack, GitHub tokens, and private keys in diffs.
  - Audit warnings for raw connection URIs and bearer tokens.
  - Strict evidence masking (`sk-ant-****...****890`) preventing secondary leaks in logs or stdout.
- **G1 — Silent Exception Hardening (Diff-Safe)**:
  - Upgraded to `difflib.SequenceMatcher` to prevent false positives when existing handlers are touched.
- **G2 — Test Integrity Hardening**:
  - Implemented `collections.Counter` full-file comparison to block test deletion.
  - Downgraded `.only()` to `WARN` and allowed `@pytest.mark.xfail`.
- **G4 — Import Matrix Boundary Hardening**:
  - Added support for Python relative imports (`from .network import ...`) and TypeScript side-effects (`import './network'`).
  - Added strict path-segment matching preventing substring collisions (e.g. `networking` vs `network`).
- **Phase 2 — Test Evidence Analyzer (T1, T2, T3) Hardening**:
  - `T1_MISSING_RELATED_TEST (WARN)`: Candidate test resolution honoring `sourceRoots` and `testRoots` from `.gravityguard.json` with recent modification window tracking (`sessionWindowSeconds`). Exemption allowlist for `types`, `constants`, `migrations`, `*.d.ts`.
  - `T2_NO_OBSERVABLE_ASSERTION (WARN)`: Case-level AST and line-span tracking ensuring every modified/added test case individually contains observable assertions (`assert`, `self.assert*`, `pytest.raises`, `expect()`, `.toBe()`, `.toEqual()`). Prevents assertions in adjacent tests from masking unasserted stubs.
  - `T3_SYMBOL_TO_TEST_LINK (WARN)`: Body-aware line-span verification resolving parent functions/classes even when declarations are unchanged. Ignores scalar constants while tracking exported arrow functions. Emits grouped warning if any changed symbol is absent.
- **Automated Test Suite Expansion**:
  - Expanded test suite from 13 to **59 automated unit tests** (`engine/test_gravity_validator.py`).
  - Measured core evaluator in-memory execution latency at `~0.032 ms` and Phase 2 evaluator at `~0.015 ms`.

---

## [1.0.0] - 2026-09-20

### Added
- **Initial Public Release of GravityGuard**:
  - Evolved and rebranded from the internal *SRP Guardian* project into a universal, open-source architectural gatekeeper for Antigravity IDE and AI Coding Agents.
- **TypeScript Extension Architecture**:
  - Full TypeScript rewrite of the Antigravity extension (`src/extension.ts`).
  - Compiled and bundled with `tsc` to `./dist/extension.js`.
- **Status Bar Prompt Enhancer (`$(sparkle) Prompt Geliştir`)**:
  - Interactive status bar button positioned at the bottom right of the IDE.
  - Global shortcut **`Ctrl + Alt + E`** (`Cmd + Alt + E` on macOS).
  - Automatically captures active editor selection or opens an interactive `InputBox`.
  - Sends raw user instructions to the local 9Router endpoint (`http://127.0.0.1:20128`) with automated model fallbacks (`ag/gemini-3.8-flash-low` -> `ag/gemini-3.7-flash-medium` -> `all`).
  - Automatically writes the enhanced technical specification directly to the system clipboard for instantaneous paste (`Ctrl + V`) into the chat.
  - Provides a *"Yeni Belgede Aç"* (Open in New Document) review action.
- **GravityGuard Live Monitor Webview**:
  - Dedicated Activity Bar sidebar panel with custom shield icon (`media/shield.svg`).
  - Real-time audit log cards showing timestamp, target file, action, and detailed architectural verdict.
  - Live statistics dashboard tracking **Engellenen (Blocked)** vs. **Onaylanan (Approved)** events.
  - Dual-mode synchronization combining OS filesystem watcher (`fs.watch`) with an active 1.5-second heartbeat poll.
  - Interactive "Temizle" (Clear Logs) and "Yenile" (Refresh) buttons.
- **Python Guard Engine (`engine/gravity-validator.py`)**:
  - Deterministic check engine running in < 50ms.
  - Enforces Single Responsibility Principle (SRP) by disallowing the dangerous combination of raw UI components with HTTP/Network requests in the same file.
  - Replaced arbitrary line-count restrictions with intelligent semantic responsibility analysis.
- **Native Antigravity Skill (`skills/enhance`)**:
  - Added native `/enhance` slash command support for direct in-chat prompt expansion without external popups.
- **Comprehensive Project Engineering Documentation ("Kutsal 6'lı")**:
  - `README.md` (Bilingual English & Türkçe), `ARCHITECTURE.md`, `ROADMAP.md`, `CHANGELOG.md`, `brain/knowledge.md`, and `LICENSE` (GNU GPL v3.0).
