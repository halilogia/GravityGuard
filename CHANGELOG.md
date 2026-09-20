# Changelog — GravityGuard

All notable changes to **GravityGuard** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- **Phase 2 — Test Evidence Analyzer (T1, T2, T3)**:
  - `T1_MISSING_RELATED_TEST (WARN)`: Warns when production code changes without a candidate test file on disk or when candidate test was untouched during the active session. Exemption allowlist for `types`, `constants`, `migrations`, `*.d.ts`.
  - `T2_NO_OBSERVABLE_ASSERTION (WARN)`: Verifies newly added test cases contain observable assertions (`assert`, `self.assert*`, `pytest.raises`, `expect()`, `.toBe()`, `.toEqual()`).
  - `T3_SYMBOL_TO_TEST_LINK (WARN)`: Verifies that newly added top-level/exported functions or classes appear by name in the candidate test file.
- **Automated Test Suite Expansion**:
  - Expanded test suite from 13 to **52 automated unit tests** (`engine/test_gravity_validator.py`).
  - Measured core evaluator in-memory execution latency at `~0.031 ms` and Phase 2 evaluator at `~0.007 ms`.

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
