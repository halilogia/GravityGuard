# GravityGuard Obligation-Driven Governance Context (v1.3.1)

This project enforces deterministic obligation-driven governance:

### 1. Invariants
- Fast deterministic airbag: <10ms evaluation, zero heavy AST overhead.
- P0 rules (`G0_SECRET_LEAK`, `G1_SILENT_EXCEPTION`, `G2_TEST_INTEGRITY`, `G4_IMPORT_MATRIX`) block immediately.
- WARN rules (`TEST_EVIDENCE`, `ARCH_FILE_GROWTH`, `OE_SPIKE`) track obligations rather than spamming premature warnings.

### 2. Obligations
- **Code Changes**: Production code edits register pending test obligations in `.gravityguard/runtime/governance.json`.
- **Engine/Rule Changes**: Edits to `engine/`, `src/`, `plugin/`, or `rules/` register doc obligations requiring `CHANGELOG.md` updates (docs/KNOWLEDGE.md §6).

### 3. Lifecycle & Gates
- **Stop Hook**: Attempting to end the session with unresolved test or doc obligations causes GravityGuard to return `{"decision": "continue", "reason": "..."}` to force completion.
- **Git Pre-Commit**: `tools/verify_doc_governance.py` rejects commits altering engine/rules without a staged `CHANGELOG.md`.
