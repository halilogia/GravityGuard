# Dual-Speed Security: Fast Hooks + Deep `scan` (Tier 4)

| | Tier 1 - hooks (PreToolUse / PostToolUse) | Tier 4 - `gravityguard scan` |
|---|---|---|
| Speed | <5 ms, deterministic | seconds, on demand |
| Allowed work | local rules on the single edited file | AST taint, cross-line evidence, git calls |
| LLM / network | **never** | never required (agents may add evidence) |
| Output | allow / block | evidence-backed findings, SARIF v2.1.0 |

Invariant: nothing in `security_audit.py` is imported by the hook path, and the git binding in `review_governance.py` runs only at Stop / pre-push evaluation.

## Usage

```bash
python engine/governance_control.py scan                 # changed + staged + untracked files, SARIF
python engine/governance_control.py scan --all           # whole repository
python engine/governance_control.py scan --format text   # sarif | json | text
python engine/governance_control.py scan --output out/scan.json --format json
```

Default output: `.gravityguard/reports/security-scan.sarif`. Exit code is `1` when findings exist, `0` when clean (CI-friendly). Upload the SARIF with `github/codeql-action/upload-sarif`.

Rules: `GGS001` hardcoded secret, `GGS002` unescaped shell execution, `GGS003` insecure deserialization, `GGS004` unsafe eval/exec, `GGS005` path traversal. Python uses AST taint (source -> assignment -> sink, so `os.system('ls ' + request.args['f'])` is CRITICAL with a two-step attack path); other languages use line rules at lower confidence. Findings are deduplicated by (rule, file, line).

## Evidence-backed finding

`finding_id`, `severity` (CRITICAL/HIGH/MEDIUM/LOW), `confidence` (0.0-1.0), `attack_path` (`[{file, line, description}]`), `evidence_payload`, `reproduction_test`, `verification_status` (`UNVERIFIED` / `CONFIRMED_EXPLOITABLE` / `PATCHED_VERIFIED`), `unexamined_scope` (what the scan did NOT prove). JSON reports keep every field; SARIF carries them in `properties` and `codeFlows`.

## Git tree-hash binding and stale invalidation

A JSON/SARIF report stores `binding = {commit, tree (HEAD^{tree}), file_hashes}`. `binding_is_stale()` is true when the tree moved or any bound file hash changed; `invalidate_stale_report()` then marks every finding `stale` and resets it to `UNVERIFIED`. Self-review receipts may add `gitTree` / `gitCommit`; a mismatch with HEAD adds the problem `git-tree-mismatch` / `git-commit-mismatch` at Stop and pre-push. Receipts without these fields behave as before (fingerprint over file hashes).

## Fix verification (fail-before / pass-after)

1. On the unpatched code `record_baseline(finding, root)` runs `reproduction_test`; it must **fail** (otherwise it is rejected as not reproducing) -> `CONFIRMED_EXPLOITABLE`, baseline bound to the current tree/file hashes.
2. After the patch `verify_patched(finding, root)` requires the baseline, changed code since the baseline, and the test now **passing** -> `PATCHED_VERIFIED`.

`reproduction_test` must be an existing file inside the repository.
