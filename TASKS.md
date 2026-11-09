# Tasks — GravityGuard

Working checklist for the current cycle. Keep it short, keep it honest, and delete rows
the moment they stop being true. Done work belongs in `CHANGELOG.md`, not here.

## In Progress

- [ ] Keep the governance gate green on the current rule set (`npm test` + engine suite).
- [ ] Hold every `src/*.ts` file under the 350-line read budget; split before it grows.
- [ ] Watch for hook stdout leaks after any engine change (stderr only, one JSON verdict).

## Next

- [ ] Measure new complexity heuristics before promoting them from proposal to rule.
- [ ] Finish `run_command` mutation detection (ROADMAP §2.2, P3-02).
- [ ] Ship controlled test-maintenance mode (ROADMAP §2.3, P3-01).
- [ ] Reduce false positives in `ARCH_FILE_GROWTH` by reporting the responsible block, not just the count.

## Blocked

- [ ] Nothing blocked. Add a row only with the blocking cause written next to it.

## Standing Constraints

- [ ] No AST, taint tracking, formatting duties, or model calls inside the hook.
- [ ] No telemetry, cloud storage, or remote rule fetching.
- [ ] No self-exemption path that lets an agent approve its own bypass.
- [ ] Evidence-backed verdicts only: rule ID, file, line, remediation.

## Verification

```bash
npm test                          # build + node:test suite
npm run test:engine               # python -m unittest discover -s engine
npm run verify:package            # packaged extension contents
```
