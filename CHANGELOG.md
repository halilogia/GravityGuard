# Changelog — GravityGuard

All notable changes to **GravityGuard** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.7] - 2026-09-21

### Fixed
- **G0 Secret Leak Fast-Pass Bypass (Critical Security Boundary)**:
  - In v1.2.6 and earlier, `is_vendor_or_cache` and `is_data_or_doc` bypassed the validator prior to running `check_g0_secret_leak()`. This allowed plaintext secrets and tokens to be written without inspection into configuration files (`.json`, `.yaml`, `.yml`, `.toml`, `.ini`), documentation (`.md`, `.txt`), vectors (`.svg`), lockfiles (`.lock`), or vendor/cache paths (`node_modules`, `venv`).
  - Fix: The pipeline order was inverted. Fast-pass is now strictly restricted to non-text pure binary assets (`.png`, `.jpg`, `.blend`, `.exe`, etc.). All text files (code, config, docs, vendor) are unconditionally scanned by G0. Only after G0 passes are non-code/vendor files fast-passed.
  - Added AWS Access Key ID regex (`\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b`) with dummy placeholder tolerance.

- **T1 Premature PreToolUse Warnings (Stateful Test Evidence Airbag)**:
  - In v1.2.6, when an AI agent created a new production file (e.g. `service.ts`), `check_t1_missing_test()` executed during `PreToolUse` before the file was written to disk. Because test files (`service.test.ts`) are typically created in subsequent tool calls, T1 emitted an immediate `T1_MISSING_RELATED_TEST` warning on every new file write, creating false noise.
  - Fix: T1 is now stateful. When production code is written or updated without immediate test evidence, the pending expectation is saved to `.gravityguard/runtime/test_evidence_state.json`.
  - When the corresponding test file is written or updated in subsequent tool calls, the pending entry is automatically resolved.
  - Consolidated unresolved T1 warnings are surfaced during final evaluation (`Stop` / `PostInvocation` hook or `--stop` CLI flag).
  - Backward compatibility: `testEvidence.deferredMode: false` in `.gravityguard.json` restores legacy immediate PreToolUse warnings.
  - Added fnmatch glob pattern support to `testEvidence.exemptPatterns` (e.g. `src/components/*`, `*.config.ts`).

- **Test File Path Classification Refinement**:
  - `is_test_file` previously checked `"test_"` as an arbitrary substring of the full path, causing files within temporary directories containing `test_` in their parent path to be misclassified as test files. Path classification now isolates filename tokens (`test_*`, `*_test.*`, `*.test.*`, `*.spec.*`) from directory segments (`/tests/`, `/test/`, `/__tests__/`).

### Added
- **`TestV127G0ZeroBypassAndStatefulEvidence`** (11 tests):
  - G0 secret scans in `.json`, `.yaml`, `.svg`, `.md`, and vendor paths are blocked.
  - G0 AWS access key detection and placeholder tolerance.
  - G0 clean non-code files pass without false positives.
  - Stateful T1 lifecycle: pending state creation, auto-resolution on test write, clean Stop hook.
  - Glob support in `testEvidence.exemptPatterns`.
  - Backward compatibility test for `deferredMode: false`.

### Changed
- Test Count: **104/104 passing** (was 93/93; +11 new regression and lifecycle tests).
- Anti-bloat invariant intact: in-memory guard logic execution avg **0.029–0.030 ms** (bound < 10 ms).

## [1.2.6] - 2026-09-21

### Fixed
- **Non-ASCII Paths Were Corrupted, and One Class of Them Crashed the Guard Open (Windows)**:
  - `hooks.json` launches the guard as a bare `python scripts/srp-validator.py`. On Windows that does **not** enable UTF-8: measured on the affected host, `sys.flags.utf8_mode == 0` and `stdin`/`stdout`/`stderr` all default to `cp1252`, while the harness writes its JSON payload as **UTF-8 bytes**. Three distinct harms followed from that single mismatch:
    1. **Lossy decode.** Non-ASCII paths were reinterpreted as mojibake — the live audit log literally contained `PropogandasÄ±nÄ±n sÃ¶ylem` instead of `Propogandasının söylem`. The guard then queried a path that does not exist and silently lost the target file's real content, degrading the T1/T3 evidence checks.
    2. **A bogus directory tree inside the user's project.** Because `get_runtime_dir()` creates its directories with `mkdir(parents=True, exist_ok=True)`, the corrupted path did not merely misread — the guard *created* a mojibake-named folder next to the real one.
    3. **Hard crash → FAIL-OPEN.** Characters absent from cp1252 decode to lone surrogates, so `ast.parse()` raised `UnicodeEncodeError` (`ast.parse` was the only unguarded call site; the other two already used `except Exception`). The process exited 1 with **empty stdout**. A hook that returns no decision does not block the write, so **the guard was bypassed silently** — a security-boundary failure, not a cosmetic logging bug.
  - Measured crashing inputs: `U+201D` (the typographic right double quote that Word inserts automatically) and `ZWJ U+200D`. Twenty-six other tested non-ASCII characters, including every Turkish letter, were safe.
  - **Proof of fail-open:** a probe file containing `U+201D` was written to disk with **zero** audit entries; an ASCII control probe produced 2 entries.
  - Fix: both entry points (`gravity-validator.py`, `async_runner.py`) now force `stdin`/`stdout`/`stderr` to UTF-8 with `errors="replace"` at import time, so the guard is correct regardless of how it is launched instead of depending on a launcher flag that lives outside version control. The sole unguarded `ast.parse` gained a defensive fallback to the regex path, re-raising inside the fallback so the underlying defect stays visible.

- **G0 Denied Legitimate Files Containing Sample Private Key Blocks**:
  - The G0 PEM rule (`check_g0_secret_leak`) matched `-----BEGIN ... PRIVATE KEY-----` and denied immediately, **without ever inspecting the body**. Every neighbouring rule (GitHub, Anthropic, OpenAI, Gemini, Slack) guarded itself with `if not is_placeholder(...)`; the PEM rule alone did not. The inconsistency was the defect.
  - Consequence: any test or documentation file containing a sample key block could not be written at all. Measured occurrence: `engine/test_gravity_validator.py` — GravityGuard's **own G0 test** — caused the commit-time secret scanner to reject a legitimate commit (`[KRITIK GUVENLIK ENGELI] ... engine/test_gravity_validator.py`). The project could not commit its own tests.
  - Fix: PEM matches are now classified as fixtures when the body is provably non-live. A real key body is hundreds of base64 characters and **cannot contain `.`** (not in the base64 alphabet), so an ellipsis or a body under 48 base64 characters is conclusive evidence of sample data. The same check was added to the standalone commit-time scanner (`~/.git-template/hooks/guard/secret_checker.py`) and propagated to all 12 repository hook copies (MD5-verified, zero remaining drift).
  - **This is a deliberate, narrow relaxation of a security control, and the threshold is a judgement call — not a standard.** Justification for the size of risk: an elided key is unusable, because base64 decoding fails and no partial key can be reconstructed from a truncated body. The margin is conservative: a real RSA key body is ~1600 characters and an EC key ~230, while the shortest possible real PEM still exceeds 64. Verified end-to-end against the live hook: **8/8** cases behaved correctly, including full-length RSA, EC, OPENSSH, PGP **and** DSA keys, which are all still denied.
  - `test_g0_block_private_key` was **not** weakened to accommodate this: it was re-pointed at a real-length body so the exemption cannot mask a genuine key. A companion test (`test_g0_allows_elided_pem_fixture`) covers the fixture case. Both the test bodies and headers are assembled at runtime, so the test file contains no literal PEM block that would trip the scanners it is testing.
- **`ROADMAP.md` had 25 corrupted lines**: a botched patch left a literal `+` prefix on every line of §3.6 and §3.7, so the `### 3.6.` heading rendered as `+### 3.6.`. Prefixes stripped; the file went 145 → 144 lines.

### Added
- **`TestWindowsEncodingRegression`** (3 tests): the typographic quote must yield a valid decision rather than kill the process; the guard must leave an audit entry (silence would mean it failed open); and a Turkish path must cross the stdin boundary verbatim.
- **`run_validator_raw_bytes()`** test helper: writes the payload as raw UTF-8 bytes with `ensure_ascii=False` and deliberately does **not** pass `-X utf8`, mirroring `hooks.json` exactly.
- The pre-existing `run_validator()` used `text=True` and `json.dumps`' default `ensure_ascii=True`, so its payload was **pure ASCII** — the one configuration immune to this bug. That is precisely why 89 green tests coexisted with a guard that was broken in production; the suite could not have observed the defect.
- **PEM fixture regression tests** (`guard_test.py`, 3 tests) covering both directions: sample blocks allowed, full-length real keys still blocked, so the control cannot silently weaken.

### Changed
- Test Count: **93/93 passing** (was 89/89; +3 encoding, +1 elided-PEM fixture). The 3 encoding tests were confirmed **non-vacuous**: they fail 3/3 against the pre-fix validator and pass 3/3 after it.
- `guard_test.py` (commit-time scanner suite): 9/9 passing (was 6/6; +3 PEM).
- Anti-bloat invariant intact: in-memory guard logic measured avg **0.051–0.069 ms**, p99 **0.175–0.995 ms** (bound < 10 ms).

### Notes
- **Scope limit:** this fixes encoding and the G0 false positive, not the T1 policy. `T1_MISSING_RELATED_TEST` is `WARN ONLY` (returns `decision: allow`) and still fires on the affected project, because that project genuinely contains zero test files. Silencing it requires either adding tests or a `.gravityguard.json` exemption — a separate, deliberate choice.
- Nothing was deleted from the user's project: the two mojibake folders removed were guard-generated empty shells containing a single `debounce_state.json`, and the real 251-file project folder was verified intact afterwards.

## [1.2.5] - 2026-09-20

### Added
- **Packaging support** — first `.vsix` build:
  - Added `.vscodeignore`. Without it the packager bundles `node_modules/`, the test suite, `brain/` and `tools/` into the artifact. The resulting package carries 10 files (54.69 KB): the compiled extension, both engine modules, `media/shield.svg`, `LICENSE`, `README.md`, `package.json`.
  - Added `repository`, `bugs` and `homepage` to `package.json`; the packager requires the repository field.
  - Verified the packaged engine is byte-identical to the repo engine (`md5 b3eac45e…`), so a release artifact can never ship a stale guard.
  - `*.vsix` is gitignored — build artifacts attach to the GitHub Release, they are not committed.

### Fixed
- **`engines.vscode` and `@types/vscode` were inconsistent**, and `vsce package` refused to build:
  - `@types/vscode` declared `^1.134.0` while `engines.vscode` advertised `^1.80.0`. The packager rejects a type package newer than the declared engine, because the extension could then reference APIs absent from the engine it claims to support.
  - Both are now pinned to `^1.107.0`, matching the Antigravity IDE build actually running on this machine (`product.json` → `1.107.0`, quality `stable`). The previous `^1.80.0` figure was never verified against a real host.
  - All 14 `vscode.*` APIs used by `src/extension.ts` exist in 1.107.0.
- **Wrong GitHub account in install instructions:** `README.md` and `package.json` referenced `halilemre`, while the actual remote is `halilogia/GravityGuard`. The documented `git clone` command would have failed. Both now match the remote.

- **Hook Stdout Violated the PreToolUse Schema — Silently Blocked Every File Write**:
  - On the WARN path the validator printed `{"decision": "allow", "warnings": [...], "warning_rule_ids": [...]}`.
  - The Antigravity hook contract permits only `decision`, `reason`, `permissionOverrides` and `overwrite`; payloads are protojson-encoded and protojson **rejects unknown fields**.
  - The harness therefore discarded the **entire** response (`proto: unknown field "warnings"`). An intended, non-blocking warning became a hard tool failure, so `write_to_file` / `replace_file_content` / `multi_replace_file_content` were blocked outright instead of merely annotated. The failure mode was inverted: the *safer* the guard (WARN, not DENY), the more damaging the outcome.
  - Warnings are now folded into `reason` — the only schema-valid field surfaced to the user/agent — formatted as `[RULE_ID] message` and joined with `" ⚠ "`, so rule IDs stay machine-readable via the prefix.
  - Confirmed occurrence: `antigravity/brain/2e98ccd8-...` (Antigravity 2.0), 10 matches of `failed to unmarshal result from hook`. In that session the agent could not use the file-writing tools at all and fell back to PowerShell.
  - Scope note: the same hook code is shared, so the IDE/CLI were equally exposed. A genuine occurrence in the IDE logs was **not** found (the IDE hits were a different, unrelated payload); this fix is preventive there, not a confirmed reproduction.

### Added
- **Stdout contract regression tests** (`TestHookStdoutContract`): the warn path must emit no schema-invalid key, must still deliver its warning through `reason`, and a clean edit must emit a minimal allow.
- **Schema gate in the test harness**: `run_validator()` now asserts `set(res.keys()) <= {decision, reason, permissionOverrides, overwrite}`. The previous harness used plain `json.loads`, which accepts any key — which is precisely why the suite stayed green while the live guard was blocked. A protocol-level bug was invisible to a protocol-blind test.

### Changed
- Warning assertions migrated from `res.get("warning_rule_ids", [])` to `_warnings_from(res)` (reads `reason`); substring semantics preserved.
- Test Count: 89/89 passing (was 87/87).

### Notes
- No governance guard was altered: no block/warn threshold, no TSC debounce, no hidden-console spawn contract. The `deny` paths already emitted only `decision` + `reason` and were correct.
- Whether `allow` + `reason` is *rendered* to the agent is documented as "shown to the user/agent" but was not empirically verified. The field is schema-valid either way, warnings remain in the audit log, and the previous behaviour is strictly worse regardless of the answer.
- `package.json` had drifted to `1.2.3` while `1.2.4` was already released; corrected to `1.2.5`.

## [1.2.4] - 2026-09-20

### Fixed
- **Test Suite Was Flooding the Real Security Audit Log**:
  - Every `run_validator()` call spawned a real `python.exe` that appended to the *live* audit stream (`~/.gemini/logs/srp_guardian_live.json`) via a hard-coded path in `log_event()`.
  - The stream keeps only the newest 50 events (`events[:50]`), so a single suite run (64 spawns) evicted **every** genuine security event. The Live Security Monitor webview therefore displayed test fixtures (`C:/fake_project/...`, `%TEMP%\tmp...`) as if they were real activity.
  - `log_event()` now resolves its directory through a new `_resolve_log_dir()` helper, which honours a `GRAVITYGUARD_LOG_DIR` environment override and falls back to `~/.gemini/logs`.
  - The test harness points that variable at a per-run temp directory **before** the first spawn, so every child inherits the redirect.
  - Verified: after a full suite run the live log contains 0 fixture targets, and its real events are preserved.
- **Malformed Audit Log Discarded History**: when the JSON log existed but failed to parse, the `except` branch silently kept the pre-built empty structure. It now resets to a valid default explicitly instead of relying on an unstated fall-through.
- **`%TEMP%` Leak**: the harness's isolated audit directory was never deleted, so every suite run left a `gg_audit_*` folder behind. Registered `atexit` cleanup via `shutil.rmtree(..., ignore_errors=True)`.

### Changed
- **De-flaked `test_sub_50ms_performance`**: the test averaged 5 measurements, so one scheduler/antivirus outlier (observed worst case: 329 ms against a 250 ms threshold) failed the suite. It now takes the **median**, prints min/max for diagnosis, and uses a regression-oriented 400 ms bound. The genuine latency invariant is still covered strictly by `test_core_in_memory_latency` (< 10 ms, measured ~0.03 ms) — this test only guards against spawn latency regressions.

### Notes
- No behavioural change to any governance guard (G0-G4, SRP, T1-T3, ARCH, OE), to the TSC debounce, or to the hidden-console spawn contract.
- Test Count: 87/87 passing.

## [1.2.3] - 2026-09-20

### Fixed
- **TSC Debounce Worker Lifecycle Deadlock**:
  - `run_debounce_worker()` exited on the `max_lifetime` guard (120s) **without** clearing `worker_running` in `debounce_state.json`.
  - Sequence: worker claims `worker_running = True` → an edit burst exceeds 120s → the guard fires → the process exits → the persisted flag stays `True` → `trigger_debounce_worker_if_needed()` sees an "active" worker forever and never spawns another one.
  - The safety mechanism disabled the feature it was protecting: the TSC debounce silently stopped working with no error surfaced.
  - The guard now clears `worker_running = False` before exiting, but only when the state file still exists — an absent state file is never re-created, so the deleted runtime directory tree is not resurrected.
  - The project-root and state-file-missing exit paths were deliberately left unchanged.

### Added
- **Lifecycle Regression Tests**: `max_lifetime` expiry must release the claim (followed by a `should_spawn_worker()` consequence check proving a new trigger can claim again), plus a companion test asserting an absent state file is not re-created. Both use a mocked clock — no real 120s wait.
- **Test Count**: 87/87 passing (was 85/85).

## [1.2.2] - 2026-09-20

### Fixed
- **Newly Created Files Were Never Linted**:
  - GravityGuard is a `PreToolUse` hook, so it fires **before** the AI writes the file. `async_runner.py`'s `main()` bailed out with `sys.exit(0)` when the target did not exist yet, so a file created *after* the worker spawned was never linted.
  - Removed that early exit. The per-file coalescing worker now waits its 300 ms quiet window, then spends a **bounded** grace period (2.0 s) for the file to appear.
  - If the file lands, the normal linter runs once. If it never lands, the worker releases its claim and exits silently — no infinite wait, no state leak.
  - `execute_single_file_lint()` retains its own existence check as the final safety net.
- **Documentation Accuracy**: replaced absolute concurrency claims ("exactly 1 worker", "never block") with *state-based duplicate suppression*, since the claim is not a mutex and concurrent `load → claim → save` sequences are not formally atomic.

### Added
- **Regression Coverage for the New-File Path**: `target file initially absent → worker waits → file appears → lint called exactly once`, plus a companion test asserting a never-written file exits cleanly. Both use a mocked clock (`time.sleep` / `time.time` patched) — no real sleeps, no subprocesses.
- **Test Count**: 87/87 passing (was 85/85). Added lifecycle regression tests for the `max_lifetime` claim release.

### Changed
- `async_runner.py` pure helpers: added `should_wait_for_target_file()`; added `_await_target_file()` polling helper. No changes to the TS debounce behavior or governance guards (G0-G4, SRP, T1-T3, ARCH, OE).

## [1.2.1] - 2026-09-20

### Fixed
- **Visible Terminal Windows on Windows (Regression Fix)**:
  - Background validation spawned subprocesses with `DETACHED_PROCESS` (`0x00000008`). A detached process owns **no console**, so every console child it launched (`cmd.exe` via `npx`, `ruff.exe`, `godot.exe`, `node.exe`) allocated a brand-new **visible** console window — the source of the flashing terminal windows.
  - Replaced with `CREATE_NO_WINDOW` (`0x08000000`) plus `STARTUPINFO` / `SW_HIDE`, which grants a hidden console that all descendant processes inherit.
  - Routed **all** Tier 2/3 linter invocations through one `run_hidden()` policy in `engine/async_runner.py`; previously `subprocess.run` was called with no window-suppression flags anywhere.
  - Applied the same hidden-spawn policy to the debounce worker in both `engine/gravity-validator.py` and `engine/async_runner.py`.
- **Orphaned Process Accumulation**: a timed-out linter previously left `cmd.exe`/`node.exe` grandchildren running (the direct child was killed but not its tree). Added `_kill_process_tree()` using `taskkill /F /T` on Windows.
- **Runaway Debounce Worker (Infinite Loop)**:
  - `run_debounce_worker()` used `while True` and could only exit through `should_run_after_idle()`, which **always** returns `False` when `last_edit_time <= 0.0`.
  - If `debounce_state.json` disappeared (temp workspace cleaned up, deleted project), the worker spun forever in 3-second intervals. Worse, `get_runtime_dir()` calls `mkdir` on every pass, so the worker kept **re-creating the deleted directory tree**, making the orphan self-sustaining.
  - Verified live: 4 zombie `--debounce-worker` processes with dead parents but re-created project roots under `%TEMP%`.
  - Added four termination guards (quiet window reached, project root gone, debounce state gone, `last_edit_time <= 0`) plus a hard `max_lifetime` bound (120s). Replaced `break`/`continue` with explicit `return`.
- **Test Harness Hermeticity**: added the `GRAVITYGUARD_DISABLE_ASYNC=1` kill switch, honored by both spawn paths. The suite sets it before importing any module, so no test can launch a real background worker.
- **Test Count**: 83/83 passing (was reported as 81/81). Added regression tests for the hidden-console contract and for the kill switch.
  - Note: the suite sets `GRAVITYGUARD_DISABLE_ASYNC=1`, so it exercises guard/decision logic but does **not** spawn real Windows process trees. The new-file path is covered by a mocked-clock test (see 1.2.2).

### Changed
- Documentation (`ARCHITECTURE.md`, `README.md`) no longer describes `DETACHED_PROCESS` as the spawn mechanism; the hidden-console contract is documented instead.

## [1.2.0] - 2026-09-20

### Added
- **ARCH_FILE_GROWTH Guard (Fast Guard — WARN ONLY)**:
  - Multi-condition heuristic radar detecting uncontrolled monolithic code accumulation without blocking the AI agent.
  - Triggers on: (1) Projected lines >= 1000, (2) Single tool-call addition >= 180 LOC, or (3) Creeping growth on 800+ LOC files with >= 80 LOC additions.
  - Exemption rules for test files (`test_*.py`, `*.test.ts`, `*.spec.ts`) and configured cohesive modules.
- **Detached Asynchronous Orchestration & Background Trigger**:
  - Implemented `trigger_background_validation(target_file)` in `engine/gravity-validator.py`.
  - Spawns `engine/async_runner.py` as a background OS subprocess without waiting for completion (returns in ~1 ms).
  - Superseded in `1.2.1`: originally used `DETACHED_PROCESS`, which caused visible console windows; now uses `CREATE_NO_WINDOW` + `SW_HIDE`.
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
- **Per-File Lint Burst Coalescing & Worker State Cleanup**:
  - Implemented 300 ms quiet-window coalescing (`run_coalesced_file_lint_worker`, `should_spawn_file_worker`, `should_run_file_lint`) in `engine/async_runner.py`.
  - Dedupes rapid consecutive edits (bursts) on the same file via state-based suppression: the first trigger claims the file in `debounce_state.json`, subsequent triggers within the window update the timestamp and exit immediately. For sequential tool calls this yields a single linter run; the claim is best-effort rather than a formally atomic mutex.
  - Once the 300 ms quiet window elapses with no further edits, linter runs once against the final file state.
  - Multi-file isolation: edits across different files (e.g. `auth.ts` vs `calc.py`) maintain separate claims and do not block each other.
  - State cleanup: `clean_file_state` automatically deletes `active_lint_workers` and `file_edits` records upon completion so `debounce_state.json` remains minimal.
  - Floating-point epsilon tolerance (`1e-6`) prevents IEEE 754 precision boundary issues.
- **Automated Test Suite Expansion (81/81 Passing)**:
  - Expanded test suite to **81 automated unit tests** (`engine/test_gravity_validator.py`), 81/81 passing.
  - Added 7 pure deterministic decision tests and 1 integration-style coalescing end-to-end contract test (no sleep, no subprocess).
  - Conducted 1,000-iteration statistical latency distribution benchmark:
    - **Average (Avg):** `0.103 ms`
    - **95th Percentile (p95):** `0.204 ms`
    - **99th Percentile (p99):** `0.454 ms`

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
