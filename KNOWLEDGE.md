# Knowledge Base — GravityGuard

Durable decisions and hard-won pitfalls. The Live Monitor **Knowledge** tab parses this
file: `### ADR-NNN:` headings become cards, and bullets under **Kör Noktalar** become
gotchas. Keep the format exact.

## Architecture Decisions

### ADR-001: Pre-Tool Gatekeeper, Not a Static Analyzer

- **Durum:** ACCEPTED
- **Bağlam:** Agents write code faster than a post-hoc linter can teach. SonarQube-style scanning reports after the damage; GravityGuard must intervene before the write lands.
- **Karar:** Block at the pre-tool hook with deterministic, evidence-backed rules. No AST, no cross-file taint tracking, no model calls in the hot path.
- **Sonuçlar:** Sub-100ms decisions and reproducible verdicts, at the cost of shallow (single-file, heuristic) analysis.

### ADR-002: Deterministic Python Engine, Thin TypeScript Shell

- **Durum:** ACCEPTED
- **Bağlam:** Rule logic changes weekly; the editor host must stay stable and cheap to load.
- **Karar:** `engine/` owns every verdict and budget check. TypeScript presents results, routes prompts, and never re-implements a rule.
- **Sonuçlar:** Rules are testable without the editor. The cost is a process boundary and a strict stdout contract.

### ADR-003: stdout Contract Is the Only Engine API

- **Durum:** ACCEPTED
- **Bağlam:** Hooks run across Antigravity, Claude Code and Codex with different launchers.
- **Karar:** The engine prints one JSON verdict per invocation; logs go to stderr and `.gravityguard/runtime/`. Extra stdout is a bug.
- **Sonuçlar:** Any harness can integrate without a client library. Debug output must never be printed to stdout.

### ADR-004: Evidence or Nothing

- **Durum:** ACCEPTED
- **Bağlam:** Vague warnings train agents to ignore warnings.
- **Karar:** Every violation carries rule ID, file, line and a concrete remediation. A rule that cannot produce evidence is not shipped.
- **Sonuçlar:** Trustworthy signal, but noisy heuristics get retired instead of softened.

### ADR-005: Local-Only, Zero Telemetry

- **Durum:** ACCEPTED
- **Bağlam:** Source code is the user's most sensitive asset.
- **Karar:** All state lives under the project's `.gravityguard/`. No network calls, no accounts, no usage reporting.
- **Sonuçlar:** Auditable offline behaviour. Cross-machine analytics are deliberately unavailable.

## Kör Noktalar

- [!] `ARCH_FILE_GROWTH` counts physical lines. Splitting a 600-line file into one 500-line file does not clear it — separate by responsibility.
- [!] A lint error left in place at write time is re-flagged; clear the previous diagnostic before adding new code.
- [!] New application code must be `.ts`. A `.js` file needs a one-line justification comment at the top or `G7_TS_FIRST` fires.
- [!] Edits fail when the target text was never read in its current form — re-read the region before replacing it.
- [!] Test maintenance and source edits must not land in the same change; gate evidence gets ambiguous.
- [!] Bypassing a rule by renaming a file or moving logic is treated as evasion, not compliance.
- [!] Hook stdout pollution breaks the verdict contract silently — the host discards the payload instead of erroring.
- [!] Deleting or weakening a test to satisfy the verification gate is a violation, not a fix.
- [!] Complexity heuristics must be measured before a new rule is added; unmeasured thresholds generate permanent false positives.
