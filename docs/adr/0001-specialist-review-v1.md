# ADR 0001 — Specialist Review V1

Status: Accepted
Date: 2026-10-04

## Vocabulary (frozen)

| Term | Is |
| --- | --- |
| Lead Agent | Antigravity |
| Specialist Agent | SwarmOrchestrator (API, text-in / structured-out) |
| Coding Agent | Nexus / Claude Code / Codex (out of scope for V1) |
| Governor | GravityGuard |

## Context

GravityGuard already governs the Lead's own edits through the Antigravity
PreToolUse hook (G0–G4, SRP, growth) and forces obligations at Stop. It does not
yet force the Lead to obtain an *independent* review of a code change, and a
rule that lives only as text is a wish, not a mechanism.

The temptation is to give the specialist its own file tools so it can "act".
That would create a second, unmapped write surface that GravityGuard cannot see,
and would rebuild a coding agent (tool loop, permissions, sandbox) that we
deliberately chose not to build.

## Decision

1. **Specialist advises; Lead acts; Governor governs.** Swarm returns text or
   JSON and performs **no filesystem mutation** of production files. The Lead
   performs every production write through the host file tools, so every write
   passes through the PreToolUse hook.
2. **The reviewer is read-only.** The `code_review` tool takes no `target_file`,
   never runs commands, and its only write is a receipt under
   `.gravityguard/runtime/reviews/`. The output is strict JSON (`findings`).
3. **Provenance is correlation, not cryptography.** When the Lead calls the
   reviewer, GravityGuard observes the MCP invocation and records the
   `review_id`, `nonce`, and `source_fingerprint` it carried. A receipt is
   accepted only when it matches an observed invocation and is not stale.
4. **Two complementary guards.**
   - *Pre-write guard (intent):* an approved governed write records a review
     obligation carrying the candidate fingerprint.
   - *Final diff guard (state):* at Stop, `git status` is scanned for governed
     code changed out-of-band (e.g. a shell write). Such files are folded into
     the same obligation.
5. **Risk/path-based trigger.** Review is opt-in (`review.enabled`), fires only
   for production code suffixes, and skips tests and configured exempt globs.

## Invariant

> A specialist result cannot authorize integration.
> GravityGuard verifies process evidence, not semantic correctness.

And the product sentence, in code comments and docs:

> A review receipt proves that a review was performed against a specific
> candidate state. It does not prove that the review was correct or complete.

## Consequences

- GravityGuard can mechanically prove: a receipt exists, an invocation was
  observed, the fingerprint/nonce match, the candidate is not stale, the schema
  is valid.
- GravityGuard cannot prove: the review was complete, or semantically correct.
  This is stated, not hidden.
- Shell writes are caught by the final diff guard rather than by policy text.
- `run_command` is still not inspected for *all* of its side effects; the final
  diff guard is the backstop and is best-effort (it needs a git repository).

## Out of scope for V1

Nexus runtime, an autonomous coding agent, a documenter specialist, a policy
registry (R0–R3), a change-manifest ecosystem, and any new UI.
