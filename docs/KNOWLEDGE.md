# Project Engineering Knowledge Base — GravityGuard

This document serves as the persistent engineering knowledge repository for **GravityGuard**. Any developer or AI agent modifying this codebase must adhere strictly to the invariants, patterns, and lessons documented here.

---

## 1. Architectural Invariants (Non-Negotiable)

### 1.1. The Lightweight Gatekeeper Philosophy (Anti-Bloat Invariant)
- **GravityGuard is NOT a compiler or an AST-heavy SonarQube replacement.**
- The primary directive is: **"Act as a deterministic airbag that prevents AI Coding Agents (Antigravity, Cursor, Claude Engineer) from degrading code architecture."**
- **Latency Invariant**:
  - Core in-memory rule evaluations (`check_g1`, `check_g2`, `check_g4`, `difflib.SequenceMatcher`) must finish in **< 10 milliseconds** (typically ~0.05–1.5 ms).
  - When invoked as an external process hook on Windows via CLI / tool hook, process spawn overhead (`python.exe`) adds real time and is **host- and load-dependent**: measured on this machine at a median of **~340–370 ms** (observed range 294–558 ms across runs), well above the 100–220 ms figure quoted in earlier notes. The spawn cost is unavoidable and is *not* what the guard is optimised for; nothing else in the loop may block.
  - Sub-50ms claims apply strictly to internal rule logic, not full Windows subprocess spawn cycles.
  - **Parity is claimed against `git HEAD`, not against an absolute number.** Measure interleaved, in the same time slice; an absolute "0.11 ms" does not survive a change of host or load. See §4.3.
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
  - Handles VS Code / Antigravity lifecycle, webview message passing, Status Bar items, and clipboard synchronization.
  - `src/intent.ts` is the **local intent classifier**: deterministic, no network, `<1ms`. It is the reason the prompt pipeline has no runtime dependency on an AI gateway.
  - `src/extension.ts` owns the optional local-gateway client (any OpenAI-compatible `/v1` endpoint) and the deterministic offline composer that answers when no gateway is reachable.
- **Python Guard Engine (`engine/`)**:
  - Operates as a standalone CLI / hook runner (`gravity-validator.py`).
  - Executed either via IDE pre/post tool hooks, pre-commit Git hooks, or CLI commands.
  - Communicates with the TypeScript UI via the event stream file at `~/.gemini/logs/srp_guardian_live.json`.

### 1.4. Context-Aware Prompt Enhancement
- The Prompt Enhancer must NEVER assume all user prompts are implementation tasks. The intent is decided **in the extension**, before the request leaves the machine, and the model is told which mode it is in. The three directives are mutually exclusive and only the selected one is sent:
  1. **Inquiry / Consulting ("Fikirlerin nelerdir?", "Nasıl yapmalıyım?")** — directive A: options with trade-offs, over-engineering risks, decision criteria. No build orders, no tool calls.
  2. **Implementation / Coding ("Şunu yaz", "Modül ekle")** — directive B: defensive specification (purpose, scope, module and SRP boundaries, error handling, tests).
  3. **Audit / Refactoring ("Denetle", "ölü kodları incele")** — directive C: no new production code, findings with `dosya:satır` evidence plus an impact rating, unverifiable suspicions in a separate list, refactor advice split into small revertible steps with a verification method each.
- **The user can override the classifier** with a `#denetle:` / `#danış:` / `#kodla:` prefix; the result is reported as `source: 'override'`. A heuristic the user cannot contradict is a heuristic the user will stop trusting.
- **Why not ask the model?** It was the previous design, and it was unverifiable: the repository could not prove compliance, so a directive was a request rather than a decision. `tests/intent.test.mjs` asserts that exactly one directive is emitted per prompt.

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
6. **`OE_SPIKE` (P2 - WARN ONLY)**: Lightweight heuristic for premature abstraction spikes — a change inside `overEngineeringMaxLoc` (default 50 LOC) introducing `overEngineerAbstractions`+ (default 2) classes/interfaces. **Calibrated and deliberately left alone**: measured fire rate 1.27% (59 of 4,639 eligible writes), of which only 2 are attributable to conventional scaffolding (exceptions, dataclasses, Protocols, Enums). Both numbers are tunable per project (§2.4).
7. **`SRP_BOUNDARY` (P0 - BLOCK)**: Flags multi-responsibility anti-patterns (e.g., mixing raw UI widgets with HTTP/Network requests in a single file).
8. **`ARCH_FILE_GROWTH` (P2 - WARN ONLY)**:
   - **Philosophy**: Prevents the "creeping monolith" anti-pattern without blocking. AI agents tend to append small chunks (+40 LOC, +40 LOC) into a single 900+ LOC file, gradually turning it into an unmaintainable god-file.
   - **It measures growth, not file state.** Criteria, first match wins:
     1. The write **crosses** the monolith line (`old_loc < monolithLoc <= projected_loc`, default 1000).
     2. `old_loc >= creepBaseLoc` (default 800) **and** `added >= creepAddedLoc` (default 80).
     3. One tool call adds `>= singleWriteLoc` (default 180) to an **existing** file.
   - **Creation is not accumulation.** Rules 2 and 3 skip files that do not exist yet: a brand-new cohesive module is the outcome these rules ask for. Rule 1 still applies, so a file *born* over the monolith line is reported.
   - **Escape hatch**: `srp: allow-monolith` (or the rest of the marker vocabulary the SRP rule already honours) silences rules 2 and 3. It deliberately does **not** silence rule 1.
   - **Exemptions**: Test files (`test_*.py`, `*.test.ts`) and configured cohesive modules are exempt.
   - **Measured justification** (6,404 real production file-writes, 11 repositories): 60 writes land on files already past 1,000 lines and only 30 of them carry a material addition, so the previous `projected_loc >= 1000` state check repeated itself on half its fires; 359 of 1,636 real file creations added 180+ lines, so warning on creation penalised modularisation. Method and full numbers in the CHANGELOG.
9. **`TEST_EVIDENCE` (Phase 2 - WARN ONLY)**:
   - **Philosophy**: Not a test coverage or mutation testing tool. Acts as a lightweight pre-tool "evidence airbag" to catch AI agents changing production behavior without test updates or writing empty assertionless stubs.
   - **Zero BLOCK Invariant**: Under no circumstance does T1, T2, or T3 block a tool call. All decisions return `decision: allow` with informative warnings.
   - **`T1_MISSING_RELATED_TEST`**: Triggers when production code changes without a candidate test file on disk or when candidate test file was untouched in the active session window. Exemption allowlist (`types`, `constants`, `index`, `*.d.ts`, `migrations`, `config`, `schemas`) prevents false alarms.
   - **`T2_NO_OBSERVABLE_ASSERTION`**: Triggers when newly added test cases (`def test_...`, `it(...)`, `test(...)`) contain no observable assertion pattern (`assert`, `self.assert*`, `pytest.raises`, `expect()`, `.toBe()`, `.toEqual()`, `.toThrow()`, etc.). Fixtures (`beforeEach`, `describe`, `setUp`) are exempt. Regex specifically avoids false matching on test titles starting with "should".
   - **`T3_SYMBOL_TO_TEST_LINK`**: Triggers when top-level/exported functions or classes added to production code do not appear by name in the candidate test file. Only runs when candidate test file exists (avoids warning spam when T1 already triggered).
10. **`STATIC_LINTER_DIAGNOSTIC` (Tier 2/3 Bridge - WARN ONLY)**:
   - **Philosophy**: The pre-tool fast path must stay `< 10ms`. Running `eslint`, `ruff`, or `tsc` synchronously inside pre-tool interceptors paralyzes the AI agent with 1–3s latency spikes.
   - **Asynchronous Runner (`engine/async_runner.py`)**: Runs post-tool in the background on changed files only (Ruff for Python, ESLint for TS/JS, Godot for GDScript, and debounced `tsc --noEmit` across TS projects).
   - **State Bridge (`.gravityguard/runtime/diagnostics.json`)**: Background tools output findings into this JSON file with timestamps.
   - **Next-Hook Injection**: On the next tool-call, `gravity-validator.py` reads `diagnostics.json` in `< 0.5ms`, checks freshness (<600s and file not modified after diagnostic), and injects actionable warnings into the AI prompt.

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

### 2.3. Prompt Enhancement Pipeline (optional gateway, deterministic floor)
- Stage 1 — **local intent classification** (`src/intent.ts`): no network, `<1ms`, three mutually exclusive directives (§1.4).
- Stage 2 — **gateway cascade** (optional): `http://<gravityguard.routerHost>:<routerPort>/v1/chat/completions` with `"stream": false`, against any OpenAI-compatible endpoint (9Router, Ollama, LM Studio, llama.cpp). Model ids come from `gravityguard.models` (env: `ROUTER_MODELS`); default cascade is `ag/gemini-3.8-flash-low` → `ag/gemini-3.7-flash-medium` → `all`. Per-model timeout: `gravityguard.routerTimeoutMs` (default 12,000 ms).
- **Two failure classes, two behaviours.** *Model-level* failures (HTTP error, empty content, timeout) fall through to the next model. *Connection-level* failures (`ECONNREFUSED`, `ENOTFOUND`, `EHOSTUNREACH`, `ENETUNREACH`, `EAI_AGAIN`, `ECONNRESET`, `EPIPE`) mean no model behind that host can answer, so the remaining candidates are skipped instead of each burning a full timeout.
- Stage 3 — **offline composer** (always available): `buildOfflinePrompt()` renders a structured, mode-correct brief from the classified intent — the original request verbatim, the expected output for that mode, and the standing constraints. The user is told the result came from the offline path. This is the invariant, not a fallback: offline is the floor.
- `antigravityBridge.ping` performs a real health check (`GET /v1/models`, 3s) and reports the endpoint, the model count, or the exact connection error.

### 2.4. Project Configuration (`.gravityguard.json`)

| Block | Consumed by | Notes |
|---|---|---|
| `layers` | `G4_IMPORT_MATRIX` (BLOCK) | Forbidden import targets per layer. Exact path-segment matching. |
| `testEvidence` | `T1` / `T2` / `T3` (WARN) | `sourceRoots`, `testRoots`, `sessionWindowSeconds` (default 300), `exemptPatterns` (fnmatch globs), `deferredMode`. |
| `complexity` | `OE_SPIKE`, `ARCH_FILE_GROWTH` (WARN only) | `monolithLoc` (1000), `singleWriteLoc` (180), `creepBaseLoc` (800), `creepAddedLoc` (80), `overEngineeringMaxLoc` (50), `overEngineerAbstractions` (2). |

**Configuration is a convenience, never a security boundary.** Every numeric key has a floor (`monolithLoc: 3` would flag every file), non-numeric values, booleans and malformed blocks are ignored, and a bad config degrades to the defaults instead of raising — this code runs inside the pre-tool hook, where an exception means the write proceeds unguarded.

---

## 3. Developer Guidelines

- Run `npm run build` after editing `src/*.ts`, then `npm test` (14 TypeScript tests for the classifier and prompt composer).
- Run `npm run test:engine` (or `python -m unittest discover -s engine -p test_*.py`) after editing the engine. The suite sets `GRAVITYGUARD_LOG_DIR` and `GRAVITYGUARD_DISABLE_ASYNC=1` before importing any module, so it never writes to the live audit log and never spawns a real background worker.
- Keep telemetry and network calls strictly opt-in and local-first.
- `tools/sync_plugin.py --check` reports drift between the repo engine and the live plugin copy; the `pre-commit` hook syncs automatically and reports `[autosync] DRIFT <file> -> <bytes> (dogrulandi)`.

## 4. How A New Heuristic Gets Shipped (lessons that are already paid for)

1. **Measure before you tune.** A heuristic ships with its measured fire rate on the real corpus (11 repositories, last 400 commits, 6,404 production file-writes) and at least one true-positive and one false-positive example from that history. A number nobody measured is a guess. OE_SPIKE shipped *unchanged* because 1.27% measured as already correct.
2. **Test behaviour, not the predicate.** The first cut of the `srp: allow-monolith` exemption reused `is_ts_cohesive_monolith()` — which answers a different question and is true for nearly every TypeScript file — and the mistake was caught by an *existing* behaviour test going silent, not by a unit test of the predicate. Assertions must exercise the rule through the hook.
3. **Claim parity with an A/B, not an absolute.** Latency comparisons run interleaved against `git HEAD` in the same time slice. An absolute "0.11 ms" is host- and load-dependent; the ratio is the claim that survives. A first implementation regressed 1.35x purely by copying a dict per call — invisible without the A/B.
4. **One escape-hatch vocabulary.** A new marker or config key must reuse an existing one (`srp: allow-monolith`) or justify why it cannot.
5. **WARN rules may accept a human exemption; BLOCK rules may not.** Extending `complexity` or the marker to a blocking rule re-opens Anti-Goal 5 and must be argued explicitly.
6. **Schema is a contract.** The hook stdout permits only `decision`, `reason`, `permissionOverrides`, `overwrite`; protojson discards the entire response for an unknown field, and a test harness using plain `json.loads` cannot observe that class of bug. `run_validator()` gates every response against the allowed key set for this reason.

---

## 5. Release Cutting Ritual (repeatable — proven on v1.3.0)

A release is not "bump the version". In order, with the command that proves each step:

1. `npm test` and `npm run test:engine` — both green. If a perf test fails, check whether the machine is loaded before touching any bound: on this host the core evaluator measures 0.10 ms idle and 2.3 ms under three competing builds, and a random failure is not a regression.
2. `python tools/sync_plugin.py --check` — the live plugin must already match the repo engine.
3. `vsce package --no-git-tag-version`, then **`npm run verify:package`**. This is the gate: it compares the packaged engine's md5 against the repo and rejects forbidden content by allowlist. On the 1.3.0 cut it immediately failed — the artifact was 15 files / 80.33 KB instead of 10 / 54.69 KB, because `.vscodeignore` had never been touched since `tests/` and `docs/` came into existence.
4. Update `package.json` version, `README.md` header + badges, and the `ROADMAP` status table **in the same commit**.
5. `CHANGELOG.md`: `[Unreleased]` → `## [x.y.z] - <date>`, with a **separate Upgrade Notes block** for anything a user would notice. The block is not optional: two of 1.3.0's changes altered what warnings appear, and a project with its own thresholds in `.gravityguard.json` is affected by them.
6. Commit, tag, push, then `gh release create v1.3.0 gravityguard-1.3.0.vsix --title "v1.3.0" --notes-file notes.md --verify-tag`.
7. **Download the released asset back and compare its md5** with the local build. "The upload succeeded" is not the same claim as "the artifact on the release page is the one this tree produced".

`gh` is installed user-scope via winget (`winget install --id GitHub.cli -e --scope user`) — no admin required — and is authenticated to `halilogia` with `repo` + `workflow`.

---

## 6. Documentation Discipline

The doc set is six files, and they fail in different ways, so each has a rule:

| File | What it is for | Update rule |
|---|---|---|
| `CHANGELOG.md` | What happened, with the measurement and the reasoning | Every behavioural change. If a rule's *semantics* change, the old meaning must be stated, not just the new one. |
| `ROADMAP.md` | **Unfinished work only** | A completed item moves to the CHANGELOG, not a checkbox. |
| `ARCHITECTURE.md` | How the system is wired right now | Any new module, config key, or pipeline stage. |
| `docs/KNOWLEDGE.md` | Invariants, mechanics, and how work gets done here | Any new standing procedure or lesson (§4, §5, §6). |
| `README.md` | What a user sees and installs | Version header, rule matrix rows, feature descriptions. |
| `.vscodeignore` | What the artifact contains | Any new top-level directory. Verified by `npm run verify:package`, not by reading. |

**Same-commit rule**: a change that alters a rule's behaviour updates `CHANGELOG` + `ARCHITECTURE`/`KNOWLEDGE` in the same commit that changes the code. A rule documented one release later is a rule someone will have already worked around.

`brain/knowledge.md` is an untracked mirror of `docs/KNOWLEDGE.md`; when the tracked copy changes, copy it over (it is not version-controlled, so git will not remind anyone).
