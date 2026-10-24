# GravityGuard security and architecture review — 2026-10-21

## Scope and conclusion

Reviewed the file-hook ingress, provider adapters, projection and rule pipeline,
configuration, governance/review state, monitor message handlers, router,
deployment tooling, packaging policy and CI. This is a source review with
targeted synthetic reproductions and regression tests, not an exhaustive proof
of security or a live-host compatibility certification. No real credentials or
private conversation archives were used. The initial review did not install or
publish anything; the approved local installation is recorded below. No push or
publication was performed.

GravityGuard is a useful deterministic coding guard. It is not a security
boundary against an agent with the same filesystem permissions as the policy,
state and hook files. Renaming resilience is achievable; arbitrary future tool
schemas and enforcement across hosts are not automatically guaranteed.

## Research and implemented compatibility change

- [Antigravity's official hook reference](https://antigravity.google/docs/hooks?tab=ide)
  documents catch-all matchers and still lists `write_to_file`,
  `replace_file_content`, `multi_replace_file_content` and `view_file`. The
  proposed assertion that these were definitively replaced in version 2.0 was
  not established. The current reference is not a history of every release.
- [Claude Code's official hook reference](https://code.claude.com/docs/en/hooks)
  also documents match-all registration and its own hook input/output contract.
  A common classifier cannot replace these provider-specific protocols.
- `operations.py` now owns deterministic classification and normalization.
  Supported path/content/search/replacement/edit-list aliases work independently
  of tool names. Mutation fields take precedence over read names. Empty strings
  survive; conflicting aliases, malformed chunks and incomplete edits are denied.
- Unknown path-only calls are unsupported, not inferred reads. New read names
  need a trusted read mapping; unknown patch formats need explicit adapters.
- Both provider adapters use the same normalizer. Unsupported file shapes reach
  the engine intact instead of being silently filtered away. Notebook cell
  translation remains a distinct, limited adapter.
- Both Antigravity manifests match every tool once; the Claude example matches
  all tools too. Reviewer observation remains in the dispatcher. G4 covers
  semantic writes, including `write_file`. Paths use provider cwd when supplied;
  environment protection checks supplied and resolved names. Invalid JSON is denied.

Compatibility limits: no arbitrary URI/unified-diff/multi-file support, no shell
interpreter, no guarantee that a host emits the assumed events. Wildcards add
process startup overhead on every subscribed call. A sub-millisecond classifier
does not imply a sub-millisecond external hook.

## Hardening status after approval

Validation: **126/126 Node/Chromium tests** and **388/388 engine tests** passed.
An isolated `npm ci --ignore-scripts` completed from the new lockfile;
the main `node_modules` directory was preserved. The final VSIX passed the
explicit file allowlist and byte-for-byte engine checks.

The existing Antigravity extension was backed up under
`~/.git-hook-backups/gravityguard-extension-*` and the verified local VSIX was
installed through the IDE's own CLI. The plugin sync tool backed up and updated
the installed engine/hooks; its final check reported no drift. Comparison of
54 installed engine/JavaScript files found zero source mismatches. Synthetic
calls through the installed hook command denied binary-suffix secrets, live
environment reads, blind document overwrites and policy weakening; a safe write
was allowed. The installed governance command also loaded successfully.

These are installed-file and direct-command checks. The IDE must reload hooks
and its extension host; a real user-session hook dispatch and visual monitor
interaction were not observed. Git pre-commit was updated only after verifying
the existing hook matched the repository baseline and taking a separate backup.

The findings below preserve the original audit evidence. Subsequent remediation:

| Finding | Implemented treatment | Boundary still requiring host support |
| --- | --- | --- |
| Policy weakening | Mandatory G0 floor; structured writes to installed hooks/guard/runtime blocked | Same-user shell/OS permissions |
| Binary suffix bypass | Text writes pass G0 regardless of suffix | Encoded/binary secrets are outside text-pattern detection |
| Shell bypass | Shared command checks; mandatory Stop scan; independent Git pre-commit/CI secret gate | Arbitrary interpreters and immediate exfiltration need host permissions |
| Projection mismatch | Strict reads, exact matching, ambiguity/range rejection, sequential edit validation | Provider execution semantics and check/use races require host validation |
| Engine failure | Explicit default deny/block, including malformed payloads | Operator may explicitly opt into degraded fail-open |
| Stop retries | Security scan and review debts cannot use advisory escape | Host cancellation/override remains outside this engine |
| Review provenance | HMAC signature, result hash, findings schema, full invocation tuple and TTL | Trusted reviewer must own a key inaccessible to the coding agent |
| State writers | UI waiver CLI uses engine lock and updates aggregate/session state; save errors propagate | Filesystem durability and host permissions |
| Webview paths | Canonical per-command allowlists from rendered resources | Live host UI integration still needs observation |
| Router | Remote HTTPS, bounded responses, SecretStorage, machine-owned destination settings | Operator trust in remote gateway and OS secret storage |
| Deployment | Lockfile, `npm ci`, component version alignment, package allowlist and byte parity checks | Installed host event dispatch requires restart/smoke verification |

Packaging verification additionally found archives, local Claude settings and
nested ruff caches entering a candidate VSIX. This candidate was not installed
or published. Ignore rules and an explicit verifier allowlist now reject them.
The README uses a rendered static PNG linked to its original animated SVG to
comply with VSIX SVG restrictions.

Superseded: the signed-receipt design (`GRAVITYGUARD_REVIEW_KEY_FILE`,
`receipt_auth.sign_receipt`) was removed. Opt-in review governance now uses
unsigned self-review records under `.gravityguard/self-review/<id>.json`, bound
to the candidate fingerprint. No review key or synthetic review approval has
been created for this installation.

## Initial findings, ordered by remediation priority

### P1 — Policy can be weakened by the actor being guarded

Evidence: `dispatcher.is_rule_shadow`, `project_context.load_gravityguard_config`,
`security_rules.check_escape_hatch_tampering`.

A structured write of `.gravityguard.json` that sets
`rules.G0_ENV_PROTECTION` and `rules.G0_SECRET_LEAK` to `shadow` is allowed.
After persisting that synthetic policy in an isolated fixture, a `read_file`
request for `.env` is allowed. The escape-hatch rule protects selected source
comments, not policy integrity. A project policy also replaces the user default
instead of enforcing a protected minimum.

Remedy: separate user-owned mandatory security policy from project preferences;
require an authenticated user action to weaken it. Protect hook/engine/policy
files and state using host permissions outside the guarded agent's write scope.
Protecting only one tool spelling cannot enforce this boundary.

### P1 — Binary extension bypasses text secret scanning

Evidence: `dispatcher.validate_gravityguard`, binary-asset fast pass before G0.

A synthetic `path=asset.png, content=<fake GitHub-shaped token>` is allowed.
The same text sent to `model.py` is denied by `G0_SECRET_LEAK`. The decision is
based on the filename suffix even though the incoming payload is plain text.

Remedy: scan supplied text before binary exemptions; explicitly distinguish
binary transport from text writes. Include renamed tools and asset filenames in
the negative-control tests.

### P1 — Shell and external writes bypass the file-rule pipeline

Evidence: `operations.normalize_operation` non-file return, Claude `shell_deny`,
Codex `handle`, `review_governance.record_final_diff_guard`.

An Antigravity `run_command` payload is allowed without projecting its writes.
Claude has a limited command-text check; Codex does not have its equivalent.
Stop's final diff guard is opt-in review tracking, not a full G0/G1/G2 rescan;
it cannot undo an exposed secret. Commands with variables, interpreter scripts,
remote tools and external writers remain outside structured-file coverage.

Remedy: use host filesystem/command permissions and an independent diff/secret
gate at commit or publication. Extend Stop scanning as defense in depth, with
explicit limits. Do not present command regexes as a complete shell sandbox.

### P1 — Projected edits can differ from the operation that will execute

Evidence: `diffing.get_projected_and_old_content`.

A multi-edit whose search text does not occur in an existing file silently
leaves the projection unchanged. In the synthetic probe, a secret-shaped
replacement in that unmatched chunk is therefore not scanned and is allowed.
This proves missing validation; a real host may reject that edit itself.
Single edits instead append an unmatched replacement to their projected text.
Line bounds are not honored, first-occurrence behavior is assumed, and disk
read failures become empty content. These choices can produce both missed
violations and false alarms. An absent file uses a virtual before/after model.

Remedy: explicit projection failures, strict read errors, per-provider edit
semantics, matching/ambiguity validation and scanning all proposed text even
when a full projection cannot be produced. Retain virtual projection only as
an explicit test or supported-host mode. Account for check/use races separately.

### P2 — Engine failure has inconsistent protection across adapters

Evidence: Claude `run_engine` / `emergency_deny`, Codex `run_engine` / `handle`.

Codex proceeds if the engine is missing or unreadable. Claude preserves a small
secret/env check, but its emergency checks still depend on known tool names.
A renamed write can thus have normal-path protection and weaker failure-path
protection. Both adapters depend on an importable engine package; import-time
failure precedes the subprocess fallback. Stop also fails open without answers.

Remedy: a shared, small ingress/failure policy; explicit health status; deny or
require user mediation for sensitive operations during engine failure. Test
timeouts, broken imports, malformed answers and renamed tools in that state.

### P2 — Stop enforcement deliberately releases unresolved obligations

Evidence: `dispatcher.validate_gravityguard`, `STOP_CIRCUIT_BREAKER` branch.

After five blocked continuations the next Stop is allowed despite pending
test/doc/review obligations. Cancellation also permits stopping. This is an
availability policy, not a guarantee that work was tested or reviewed.

Remedy: distinguish advisory debts from mandatory release gates. Keep a visible
degraded outcome; enforce mandatory conditions at a separate trusted boundary.

### P2 — Review evidence does not authenticate an independent reviewer

Evidence: `review_governance._load_receipt`, `_has_matching_invocation`,
`evaluate_review_obligations`.

Receipts are writable JSON. `resultHash` needs only to be a nonempty string;
`findingsParsed` needs only to exist. Invocation correlation checks review ID,
not the recorded invocation's nonce, fingerprint and conversation. A PreToolUse
observation proves an attempted call, not a successful completed review. Disk
fingerprints detect changes but do not authenticate who reviewed them.

Remedy: validate field types and findings, bind the full invocation tuple and
successful result to a trusted issuer, and restrict receipt/state writers.
This is a provenance limitation from source inspection; no live reviewer attack
was performed.

### P2 — Monitor state writes bypass the engine's transaction protocol

Evidence: `src/webview/provider.ts` methods `dismissObligation` and
`clearAllObligations`; `governance.governance_transaction`.

The engine uses OS locks and atomic replacement. The UI reads and rewrites the
same governance JSON directly with `writeFileSync`. Concurrent hook updates can
be lost; dismiss/clear modifies aggregate fields without consistently clearing
session-owned obligations. The UI and engine can disagree about pending work.
Governance save errors are also swallowed, so callers may report success after
a failed persistence attempt.

Remedy: one transaction owner/API shared by UI and hooks; explicit scoped
waivers and durable error reporting. Add a real concurrent UI/hook test.

### P2 — Webview mutation messages lack a file allowlist

Evidence: `src/webview/provider.ts` receive-message handler.

Task/ADR/changelog handlers accept a supplied `message.path` and call filesystem
writers without verifying membership in the displayed/discovered file set.
This increases impact if the webview is compromised. CSP and escaping exist;
this review did not establish a working script-injection chain.

Remedy: opaque resource IDs resolved by the extension, schema validation and
canonical-path authorization against the files exposed by that view.

### P2 — Router can transmit credentials/prompts over plain HTTP

Evidence: `src/router_client.ts` imports `http`; `getRouterConfig` accepts a
configurable host; requests include bearer authorization and prompt content.

The default is loopback, but a nonlocal configured host still uses HTTP.
Response buffers are unbounded. This is conditional on configuration or an
untrusted gateway; no network interception was attempted.

Remedy: enforce loopback for HTTP, require HTTPS for remote gateways, limit
response sizes, and store tokens through SecretStorage rather than a plain
configuration property.

### P2 — Deployment and reproducibility are separate unresolved contracts

Evidence: `.gitignore`, `.github/workflows/ci.yml`, `.vscodeignore`,
`tools/sync_plugin.py`, `plugin/plugin.json`, `package.json`.

Dependency lockfiles are ignored and CI uses `npm install`; dependency trees
are not pinned. Plugin and extension version fields differ. VSIX excludes the
provider adapters and plugin manifests by design, so updating the extension
alone does not update all hook installations. The sync tool can detect drift,
but source tests do not certify an installed host actually dispatches a deny.

Remedy: a committed lockfile and `npm ci`, explicit component versioning, a
coherent installer/update manifest, and per-host smoke tests that verify real
hook registration, denied execution and log continuity. Run existing package
byte-parity verification for every produced release.

## Validation and recommended sequence

The new operation tests cover renamed writes, read-name camouflage, empty
replacements, sequential edits, alias conflicts, incomplete/malformed payloads,
cwd resolution, preserved unsupported provider calls, G0/G4 routing and
manifest parity. Existing adapter tests now expect explicit denial of nontext
content and catch-all subscription.

Synthetic probes observed: binary-suffix secret `allow`; unmatched multi-edit
`allow`; policy weakening `allow`; `.env` after weakening `allow`; shell call
`allow`; ordinary text-secret control `deny`. These are hook decisions, not
claims that a real provider successfully executed every proposed action.

Remediation order: establish the policy trust boundary; close binary/projection
gaps; add independent publication scanning; unify failure behavior; authenticate
review evidence; consolidate state writers; harden the webview/router; then
release with repeatable installation and cross-host smoke checks.

Final suite counts and local limitations are reported in the accompanying chat.
The full suite needs a functioning Python on PATH and normal Windows temporary
directory, symlink and Chromium permissions. A sandbox-only run produced
environment failures; moving TEMP inside this repository also changed project
discovery and is not a valid substitute for the normal suite environment.
