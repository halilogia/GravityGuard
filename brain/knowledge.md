# Project Engineering Knowledge Base — GravityGuard

This document serves as the persistent engineering knowledge repository for **GravityGuard**. Any developer or AI agent modifying this codebase must adhere strictly to the invariants, patterns, and lessons documented here.

---

## 1. Architectural Invariants (Non-Negotiable)

### 1.1. The Lightweight Gatekeeper Philosophy (Anti-Bloat Invariant)
- **GravityGuard is NOT a compiler or an AST-heavy SonarQube replacement.**
- The primary directive is: **"Act as a deterministic airbag that prevents AI Coding Agents (Antigravity, Cursor, Claude Engineer) from degrading code architecture."**
- **Latency Invariant**:
  - Core in-memory rule evaluations (`check_g1`, `check_g2`, `check_g4`, `difflib.SequenceMatcher`) must finish in **< 10 milliseconds** (typically ~0.05–1.5 ms).
  - When invoked as an external process hook on Windows via CLI / tool hook, process spawn overhead (`python.exe`) adds ~100–220 ms. End-to-end hook round-trip is within ~120–250 ms.
  - Sub-50ms claims apply strictly to internal rule logic, not full Windows subprocess spawn cycles.
- Heavy AST computations, recursive symbol resolutions, and whole-project semantic graphs are strictly prohibited. Prefer regex scanning, shallow AST inspection, file metrics, and import boundaries.

### 1.2. Zero Core IDE Tampering (Integrity Invariant)
- Never inject scripts directly into host IDE HTML files (`workbench.html`, `workbench-jetski-agent.html`).
- Modern VS Code and Antigravity distributions verify SHA-256 base64 checksums on startup via `product.json`. Direct file tampering triggers `"Your installation appears to be corrupt"`.
- All IDE UI elements must be mounted through official VS Code Extension APIs:
  - Status Bar: `vscode.window.createStatusBarItem`
  - Sidebar: `vscode.window.registerWebviewViewProvider`
  - Commands: `vscode.commands.registerCommand`

### 1.3. Dual Engine Coordination
- **TypeScript Layer (`src/`)**:
  - Handles VS Code / Antigravity lifecycle, webview message passing, Status Bar items, clipboard synchronization, and 9Router / local LLM prompt enhancement queries.
- **Python Guard Engine (`engine/`)**:
  - Operates as a standalone CLI / hook runner (`gravity-validator.py`).
  - Executed either via IDE pre/post tool hooks, pre-commit Git hooks, or CLI commands.
  - Communicates with the TypeScript UI via the event stream file at `~/.gemini/logs/srp_guardian_live.json`.

### 1.4. Context-Aware Prompt Enhancement
- The Prompt Enhancer must NEVER assume all user prompts are implementation tasks.
- Prompts must be categorized by intent:
  1. **Inquiry / Consulting ("Fikirlerin nelerdir?", "Nasıl yapmalıyız?")**: Generates trade-off analysis, architectural choices, and risk pre-mortems.
  2. **Implementation / Coding ("Şunu yaz", "Modül ekle")**: Generates strict, defensive, SRP-compliant technical specifications.
  3. **Refactoring / Review ("İncele", "Temizle")**: Focuses on boundary violations, dead code, and test coverage.

---

## 2. Key Component Mechanics

### 2.1. Rule Matrix Pipeline Architecture
The Python engine enforces checks through an ordered, high-to-low priority pipeline:
1. **`G0_SECRET_LEAK` (P0 - BLOCK / WARN)**: Diff-safe secret and credential airbag.
   - **Scope Boundary**: Guarantees that AI tool-calls passing through the validator cannot write exposed credentials to target files. Out-of-band OS edits (direct PowerShell scripts, external text editors) are outside hook scope.
   - **Scanning Scope**: Scans strictly `added_text` using `difflib.SequenceMatcher`.
   - **High-Confidence Patterns (BLOCK)**: Private keys (`BEGIN ... PRIVATE KEY`), GitHub tokens (`ghp_`, `github_pat_`, etc.), Claude/Anthropic keys (`sk-ant-...`), OpenAI modern keys (`sk-proj-...`), Google/Gemini keys (`AIza...`), Slack tokens (`xoxb-`, `xoxp-`, etc.).
   - **Suspicious Credentials (WARN)**: Long Bearer tokens and connection URIs with embedded passwords.
   - **Placeholder Principle**: Placeholder detection (`example`, `your_api_key`, `dummy`) is a convenience heuristic to avoid false positives, not a security boundary. The primary security boundary is strict provider pattern matching.
   - **Redaction Invariant**: All detected secrets are redacted (`sk-ant-****...****890`) before reaching logs (`srp_guardian_live.json`) or stdout to prevent secondary leaks.
2. **`G1_SILENT_EXCEPTION` (P0 - BLOCK)**: Diff-safe exception integrity guard. Rejects newly added empty catch/except blocks (`except: pass`, `catch {}`).
3. **`G2_TEST_INTEGRITY` (P0 - BLOCK / WARN)**: Test suite preservation. Rejects test case deletion across full files (`Counter`) and test disablers (`.skip()`, `xit()`). Allows `pytest.mark.xfail` and treats `.only()` as WARN.
4. **`G3_COMPILER_BYPASS` (P1 - WARN ONLY)**: Flags newly introduced linter/compiler suppression pragmas (`# noqa`, `# type: ignore`, `@ts-ignore`).
5. **`G4_IMPORT_MATRIX` (P0 - BLOCK)**: Enforces architecture boundaries (`.gravityguard.json`). Supports relative Python imports and TS side-effects with exact path-segment matching (no false substring collisions).
6. **`OE_SPIKE` (P2 - WARN ONLY)**: Lightweight heuristic for premature abstraction spikes (< 50 LOC introducing 2+ classes/interfaces).
7. **`SRP_BOUNDARY` (P0 - BLOCK)**: Flags multi-responsibility anti-patterns (e.g., mixing raw UI widgets with HTTP/Network requests in a single file).

### 2.2. Event Stream Protocol (`srp_guardian_live.json`)
- The Python engine records all evaluations to `~/.gemini/logs/srp_guardian_live.json`.
- Structure:
  ```json
  {
    "activeGuard": "GravityGuard",
    "status": "ONLINE",
    "lastCheck": "2026-09-20T14:55:00.000Z",
    "events": [
      {
        "status": "BLOCKED" | "APPROVED",
        "timestamp": "HH:MM:SS",
        "target": "path/to/file.py",
        "action": "CREATE_FILE" | "EDIT_FILE",
        "reason": "Human-readable explanation"
      }
    ]
  }
  ```
- The TypeScript webview watches this file using both `fs.watch` and a 1.5s fallback polling heartbeat.

### 2.3. Local LLM / 9Router Fallback Pipeline
- Prompt enhancement queries `http://127.0.0.1:20128/v1/chat/completions` with `"stream": false`.
- Priority cascade:
  1. `ag/gemini-3.8-flash-low` (latency: ~2.5s)
  2. `ag/gemini-3.7-flash-medium` (fallback)
  3. `all` (router-balanced fallback)
- If the local router is unreachable, gracefully inform the user without crashing the extension host.

---

## 3. Developer Guidelines

- Always run `npm run build` after editing `src/*.ts`.
- Ensure `engine/gravity-validator.py` can be executed independently with `python gravity-validator.py --file <path>`.
- Keep telemetry and network calls strictly opt-in and local-first.
