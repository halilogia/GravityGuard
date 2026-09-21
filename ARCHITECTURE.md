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
   └── Yes ──> Output { decision: "allow", reason?: "[RULE_ID] ..." } -> Exit 0
               (schema: decision | reason | permissionOverrides | overwrite, protojson camelCase)
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

### 3.3. Hook stdout Contract (v1.2.5)

A `PreToolUse` hook response accepts **only** these keys:

| Key | Type | Required |
|---|---|---|
| `decision` | string (`allow` / `deny` / `ask` / `force_ask`) | yes |
| `reason` | string | no |
| `permissionOverrides` | array of strings | no |
| `overwrite` | object (shallow top-level merge into tool args) | no |

Payloads are **protojson-encoded**, and protojson **rejects unknown fields**. Emitting
any other key makes the harness discard the *entire* response, so an intended WARN
becomes a hard tool failure.

- **v1.2.5 fix**: warnings were previously emitted as a `warnings` / `warning_rule_ids`
  array. That silently blocked every write tool whenever a warning fired — the safer the
  guard (WARN rather than DENY), the worse the outcome. Warnings now travel inside
  `reason` formatted as `[RULE_ID] message`, joined with `" ⚠ "`, so rule IDs stay
  machine-readable through their prefix.
- **Regression protection**: `TestHookStdoutContract` asserts the warn path emits no
  schema-invalid key and still delivers its warning, and `run_validator()` in the test
  harness gates every response against the allowed key set. A plain `json.loads` accepts
  any key — which is why the suite stayed green while production writes were blocked.

### 3.4. Hidden Background Orchestration & Debounce Worker
1. **Fire-and-Forget Trigger (`trigger_background_validation`)**:
   - Executed on `ALLOW` decisions in `engine/gravity-validator.py`.
   - Spawns `async_runner.py` with `CREATE_NO_WINDOW` + `STARTUPINFO(SW_HIDE)` on Windows, or `start_new_session` on POSIX, with all streams sent to `DEVNULL`.
   - `DETACHED_PROCESS` is intentionally **not** used: a detached process owns no console, so every console child it launches (`cmd.exe` via `npx`, `ruff.exe`, `godot.exe`) allocates a fresh **visible** console window. `CREATE_NO_WINDOW` instead grants a hidden console that all descendants inherit.
   - The pre-tool hook exits immediately (`~1ms` spawn overhead); AI tool-call continues with zero wait.
2. **Silent Linter Invocation (`run_hidden`)**:
   - All Tier 2/3 tool invocations (`ruff`, `eslint` via `npx`, `godot`, `tsc` via `npx`) route through a single `run_hidden()` policy so no linter can ever flash a terminal window.
   - On timeout, `_kill_process_tree()` uses `taskkill /F /T` to terminate the whole process tree, preventing orphaned `cmd.exe`/`node.exe` grandchildren from accumulating.
3. **State-Based Debounce Worker (`debounce_state.json`)**:
   - Records `last_edit_time = time.time()`.
   - Spawns a background worker process that sleeps in 3.0s idle intervals.
   - If an AI agent performs 5 edits in 2.5 seconds, the worker continually resets until a full 3.0s quiet window elapses, then fires `tsc --noEmit` once.
   - **Claim-release invariant (v1.2.3)**: every exit path that leaves a state file behind must clear `worker_running` before returning. The `max_lifetime` guard previously exited without doing so, leaving a stale `True` that blocked all future spawns — the safety mechanism locked the feature it protected.
4. **Per-File Lint Coalescing (`run_coalesced_file_lint_worker`)**:
   - Single-file linters (`ruff`, `eslint`, `godot`) use a 300ms quiet window. The first trigger claims the file in `debounce_state.json`; subsequent triggers inside the window only refresh the timestamp. This is **state-based duplicate suppression**, not a formally atomic mutex — concurrent `load → claim → save` sequences are not guarded by a lock.
   - **New-File Grace Period (v1.2.2)**: because GravityGuard is a `PreToolUse` hook, the worker spawns *before* the AI writes the file. After the quiet window, the worker polls for a **bounded 2.0s** grace period. If the file appears it is linted once; if it never appears the claim is released and the worker exits silently. `execute_single_file_lint()` keeps its own existence check as the final safety net.

---

## 4. Key Engineering Invariants

1. **Sub-10ms Fast Guard Execution**: The synchronous pre-tool interceptor must never stall the AI agent. Heavy external CLI tools (linters, compilers, package managers) are strictly forbidden in Tier 1.
2. **Deterministic & Offline-First**: Both the guard engine and prompt enhancer function fully offline against local AI models (9Router, Ollama, LM Studio).
3. **Lossless Failure Handling**: If 9Router or diagnostic files are temporarily unavailable, the extension displays friendly notifications without crashing or throwing unhandled exceptions.
4. **Zero Host File Patching**: No files in the host IDE installation are modified; all integration is handled through officially supported VS Code extension interfaces.
5. **Architectural Airbag Principle**: GravityGuard acts as a deterministic seatbelt; it prevents secret leaks and silent errors with BLOCK, while guiding architecture and test evidence through informative WARN signals without paralyzing developer velocity.

---

## 5. Architectural Decision Record (ADR-001)

### ADR-001: Pre-Tool Gatekeeper vs. Static Analysis Engine (Why GravityGuard is NOT SonarQube)

- **Status**: Accepted & Invariant
- **Context**: As AI-assisted development ("vibecoding") scales, agents produce code at unprecedented velocity. A common temptation is to evolve GravityGuard into an all-encompassing static code analyzer (detecting code smells, cyclomatic complexity, dead code, duplication, or deep taint analysis) similar to **SonarQube**, **CodeQL**, or **Semgrep**.
- **Decision**: GravityGuard **must never** attempt to become a general-purpose static analysis platform or SonarQube clone. GravityGuard is strictly an **AI-Native Pre-Write Gatekeeper / Airbag**, operating synchronously before files touch the disk. Deep static analysis belongs to asynchronous post-write tooling in the developer's defense-in-depth pipeline.

#### 5.1. The 4-Layer Defense-in-Depth Topology

In modern AI agent workflows, software integrity is maintained across four distinct, non-overlapping defense rings:

```mermaid
flowchart TD
    subgraph Ring1 ["Ring 1: Pre-Write Gatekeeper (GravityGuard)"]
        direction TB
        R1A["PreToolUse Hook (<5ms latency)"]
        R1B["Prevents Secret Leaks (G0)"]
        R1C["Prevents Silent Catch / Fallbacks (G1)"]
        R1D["Prevents Test Deletion / Silencing (G2)"]
        R1E["Enforces Layer Boundaries (G4 / SRP)"]
        R1F["Tracks Stateful Test Evidence (T1 Deferred)"]
    end

    subgraph Ring2 ["Ring 2: Post-Write Fast Compilers & Linters"]
        direction TB
        R2A["tsc --noEmit (Type soundness)"]
        R2B["Ruff / ESLint (Syntax & local idioms)"]
        R2C["Triggered asynchronously via Tier 2/3 Runner"]
        R2D["Results surfaced into next prompt via diagnostics.json"]
    end

    subgraph Ring3 ["Ring 3: Behavioral Proof (Test Runners)"]
        direction TB
        R3A["vitest / pytest (Unit & Integration)"]
        R3B["Proves code actually runs and satisfies contracts"]
        R3C["Resolves pending T1 test evidence in GravityGuard"]
    end

    subgraph Ring4 ["Ring 4: Deep Static Analysis & Governance (CI/CD)"]
        direction TB
        R4A["SonarQube / Semgrep / CodeQL"]
        R4B["Cyclomatic & Cognitive Complexity"]
        R4C["Code Duplication & Cross-file Dataflow Taint"]
        R4D["CVE Vulnerability & Security Hotspots"]
        R4E["Runs asynchronously in minutes, not milliseconds"]
    end

    ToolIntent["AI Agent File Write Intent"] --> Ring1
    Ring1 -->|ALLOW| DiskWrite["File Written to Disk"]
    DiskWrite --> Ring2
    DiskWrite --> Ring3
    DiskWrite -.->|Pull Request / Git Push| Ring4
```

#### 5.2. Boundary & Responsibility Matrix

| Dimension | Ring 1: GravityGuard | Ring 2: Linters / Compilers (`tsc`, `ruff`) | Ring 4: SonarQube / Semgrep |
|---|---|---|---|
| **Execution Point** | **Pre-Write** (Tool invocation interception before disk I/O) | **Post-Write** (After file lands on disk) | **Post-Commit / CI/CD** (Entire repo scan) |
| **Latency Budget** | **< 10ms** (Typical: 0.1ms - 2ms) | **300ms - 5s** (Debounced) | **30s - 15 minutes** |
| **Primary Failure Mode Addressed** | Destructive / deceptive AI agent shortcuts (secret commits, empty catches, deleting tests to pass CI, god-file creep) | Syntax errors, type mismatches, unmet compiler contracts | Architecture decay, technical debt, code smells, CVEs, cognitive complexity |
| **Enforcement Style** | Synchronous Gatekeeping (`ALLOW` / `BLOCK` / `WARN`) | Diagnostic feedback | Quality gates, PR blocks, compliance dashboards |
| **State Tracking** | Ephemeral tool diffs + lightweight session evidence (`test_evidence_state.json`) | None (per-run file analysis) | Full persistent database of historic codebase metrics |

#### 5.3. Why Becoming SonarQube Destroys GravityGuard's Core Value

1. **Latency Budget Annihilation**: SonarQube performs cross-file AST traversal, symbol resolution, and dataflow graph generation. Running this in a synchronous `PreToolUse` hook would introduce 5-30 second latencies on every single file write, causing the developer or AI agent to disable the hook immediately.
2. **Reinventing Decades of Mature Tooling**: SonarQube, Semgrep, and CodeQL represent hundreds of engineer-years of rule development for thousands of language edge cases. Duplicating a lightweight, buggy subset of these in a Python script creates maintenance debt without delivering industrial-grade depth.
3. **Misaligned Purpose**: SonarQube answers: *"Is this entire codebase maintainable, secure, and compliant with enterprise standards over time?"* GravityGuard answers: *"Is the AI agent about to commit an irreversible, sloppy, or hazardous act right this millisecond?"*
4. **The Airbag Principle**: GravityGuard is an airbag, not a full annual vehicle inspection. An airbag must deploy in 5 milliseconds when a crash (secret leak, silent error, test destruction) occurs. It does not inspect whether the car's upholstery matches or if the engine oil has 10% wear.


