# Architecture & Technical Design — GravityGuard

This document details the architectural topology, component boundaries, execution flows, and engineering decisions behind **GravityGuard**.

---

## 1. System Topology Overview

GravityGuard operates as a dual-layer system combining a native IDE extension with an ultra-lightweight execution guard engine:

```mermaid
flowchart TD
    subgraph Host IDE ["Antigravity IDE / VS Code"]
        direction TB
        subgraph UI ["User Interface Layer (TypeScript)"]
            SB["Status Bar Item<br/><code>$(sparkle) Prompt Geliştir</code>"]
            WV["GravityGuard Webview<br/><code>Live Monitor Panel</code>"]
            KB["Keybinding Dispatcher<br/><code>Ctrl+Alt+E</code>"]
        end

        subgraph CoreExt ["Extension Core (src/extension.ts)"]
            RouterClient["9Router AI Client<br/>(Local HTTP: 20128)"]
            LogWatcher["Live Log Watcher<br/>(fs.watch + Heartbeat)"]
            ClipSync["Clipboard & Editor<br/>Synchronizer"]
        end
    end

    subgraph GuardEngine ["Deterministic Guard Engine (Python)"]
        direction TB
        CLI["gravity-validator.py<br/>(CLI & Tool Hook Runner)"]
        Rules["Rule Evaluator Matrix<br/>- SRP Boundary<br/>- Layer Matrix<br/>- Size & Complexity"]
        LogFile[("srp_guardian_live.json<br/>(Shared State Log)")]
    end

    subgraph LLM ["Local AI Layer"]
        NineRouter["9Router Gateway<br/><code>http://127.0.0.1:20128</code>"]
        Models["Models:<br/>- ag/gemini-3.8-flash-low<br/>- ag/gemini-3.7-flash-medium<br/>- all"]
    end

    %% Interactions
    SB -->|Triggers| KB
    KB -->|Input Prompt| RouterClient
    RouterClient -->|POST /v1/chat/completions| NineRouter
    NineRouter -->|Inference| Models
    NineRouter -->|Enhanced Spec| RouterClient
    RouterClient -->|Auto-Copy| ClipSync

    CLI -->|Execute Rules| Rules
    Rules -->|Write Verdict| LogFile
    LogFile -->|File Event & Poll| LogWatcher
    LogWatcher -->|Render HTML & Stats| WV
```

---

## 2. Component Responsibility Breakdown

### 2.1. Presentation Layer (TypeScript)
- **`src/extension.ts`**:
  - Acts as the primary lifecycle manager for the VS Code extension host.
  - Registers the Status Bar Item (`vscode.window.createStatusBarItem`) with priority 100 on the right side of the status bar.
  - Registers the `antigravity-guardian-view` webview provider within the dedicated Activity Bar container.
  - Exposes interactive commands:
    - `antigravityBridge.enhancePrompt`: Main prompt enhancement workflow.
    - `antigravityBridge.refreshLogs`: Force-refreshes the log stream.
    - `antigravityBridge.clearLogs`: Purges the local audit log.
    - `antigravityBridge.ping`: Diagnostic healthcheck.

### 2.2. Prompt Engineering Pipeline
The Prompt Enhancer bypasses cloud latency by communicating directly with the user's local **9Router** proxy:
- **Transport**: Node.js native `http.request` targeting `127.0.0.1:20128`.
- **Payload Invariants**: Always enforces `"stream": false` to receive standardized non-streaming JSON.
- **Model Cascade**:
  1. `ag/gemini-3.8-flash-low` (Fastest, ~2-3s average latency)
  2. `ag/gemini-3.7-flash-medium` (Secondary fallback on network error or timeout)
  3. `all` (Automatic router balancing fallback)
- **Output Routing**:
  - The enhanced text is instantly written to the system clipboard via `vscode.env.clipboard.writeText`.
  - If text was selected in the active text editor, it replaces the selection in-place.
  - A non-blocking notification displays an action button: *"Yeni Belgede Aç"* (Open in New Document).

### 2.3. Live Monitor Webview
- Self-contained, zero-dependency HTML/CSS dashboard rendered inside the extension sidebar.
- Styled with modern dark-mode glassmorphism (`#0f172a` slate background, `#1e293b` cards).
- **Resilient Real-time Sync**:
  - Primary: Asynchronous file watcher on `~/.gemini/logs/srp_guardian_live.json`.
  - Secondary: 1.5-second polling interval to guarantee synchronization even on platforms where filesystem watch events are throttled or dropped.
- **Bi-directional Webview IPC**:
  - Webview sends `clearLogs` and `refresh` messages back to the extension host via `vscode.postMessage()`.

### 2.4. Python Guard Engine (`engine/gravity-validator.py`)
- Standalone, highly performant CLI tool written in standard Python (zero external dependencies).
- Evaluates code mutations using lightweight AST inspection and regex pattern matching:
  - **SRP Violation Check**: Scans for the simultaneous presence of UI elements (e.g. PyQt, Tkinter, Blender `bpy.types.Panel`, DOM manipulations) and Network operations (e.g. `urllib`, `requests`, `aiohttp`, `websocket`) within the same file.
  - **File Scale Heuristics**: Distinguishes cohesive single-responsibility files from unmaintainable god-files without arbitrary mechanical line-count blocking.

---

## 3. Data Flow & Lifecycles

### 3.1. Prompt Enhancement Lifecycle
```text
User Action (Click Button or Press Ctrl+Alt+E)
       │
       ▼
Check Active Editor Selection?
   ├── Yes ──> Pre-fill InputBox with selection
   └── No  ──> Open InputBox with placeholder
       │
       ▼
User Submits Input (Enter)
       │
       ▼
Show IDE Progress Notification ("Prompt analiz ediliyor...")
       │
       ▼
POST Request to 9Router (/v1/chat/completions)
   ├── Success (HTTP 200) ──> Parse choices[0].message.content
   └── Failure/Timeout    ──> Retry with Fallback Model
       │
       ▼
Write to System Clipboard (Ctrl+V Ready)
       │
       ▼
Display Success Notification with "Yeni Belgede Aç" Action
```

### 3.2. Tiered Guard Gatekeeper & Diagnostics Lifecycle
```text
AI Agent Tool Call Triggered
       │
       ▼
[TIER 1: FAST GUARD (<10ms, In-Memory)]
   ├── Check G0 (Secret Leaks) ─────────────> BLOCK / WARN
   ├── Check G1 (Silent Exceptions) ────────> BLOCK
   ├── Check G2 (Test Silencing & Deletion) ─> BLOCK / WARN
   ├── Check G3 (Compiler Bypass) ──────────> WARN
   ├── Check G4 (Import Matrix) ────────────> BLOCK
   ├── Check OE_SPIKE (Over-Engineering) ───> WARN
   ├── Check ARCH_FILE_GROWTH (Monolith) ───> WARN
   ├── Check SRP Boundaries ────────────────> BLOCK
   ├── Check T1-T3 (Test Evidence) ─────────> WARN
   └── Read diagnostics.json (<0.5ms) ──────> Surface previous Linter findings (WARN)
       │
       ▼
All Blocking Rules Passed?
   ├── No  ──> Output { decision: "deny", reason: "..." } -> Exit 0
   └── Yes ──> Output { decision: "allow", warnings: [...] } -> Exit 0
       │
       ▼
Tool Execution Completes
       │
       ▼
[TIER 2: ASYNC STATIC VALIDATION (Background Runner)]
Changed file triggers engine/async_runner.py in background:
   ├── Python     ──> Ruff check
   ├── TypeScript ──> ESLint check
   └── GDScript   ──> Godot check-only
       │
       ▼
Writes findings to .gravityguard/runtime/diagnostics.json
       │
       ▼
[TIER 3: BATCH COMPILER CHECK (Debounced)]
Tool burst ends (3s idle) ──> tsc --noEmit across project
```

---

## 4. Key Engineering Invariants

1. **Sub-10ms Fast Guard Execution**: The synchronous pre-tool interceptor must never stall the AI agent. Heavy external CLI tools (linters, compilers, package managers) are strictly forbidden in Tier 1.
2. **Deterministic & Offline-First**: Both the guard engine and prompt enhancer function fully offline against local AI models (9Router, Ollama, LM Studio).
3. **Lossless Failure Handling**: If 9Router or diagnostic files are temporarily unavailable, the extension displays friendly notifications without crashing or throwing unhandled exceptions.
4. **Zero Host File Patching**: No files in the host IDE installation are modified; all integration is handled through officially supported VS Code extension interfaces.
5. **Architectural Airbag Principle**: GravityGuard acts as a deterministic seatbelt; it prevents secret leaks and silent errors with BLOCK, while guiding architecture and test evidence through informative WARN signals without paralyzing developer velocity.

