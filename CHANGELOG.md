# Changelog — GravityGuard

All notable changes to **GravityGuard** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
