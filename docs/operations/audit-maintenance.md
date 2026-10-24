# Audit maintenance

Run maintenance after deploying the checkpoint-aware engine to every audit writer.
The default archive destination is `~/.gravityguard/maintenance`, outside the
repository. Treat reports and archives as private conversation-derived data.

1. Review `tools/telemetry_dashboard.py --weekly` and `--monthly`. Use
   `--export-md` and `--export-json` with destinations outside the repository.
2. Run `python tools/maintain_audit.py --log-dir <active-log-directory>`.
3. Verify the returned archive manifest, sequence high-water mark and empty
   live event list. Concurrent real activity may append new events immediately.

Maintenance acquires the audit writer lock, validates every JSON record and
verifies SHA-256 backups before replacing the active journal with one checkpoint.
The checkpoint preserves cumulative effectiveness counters and unresolved audit
violations. Governance obligations, review receipts, session deltas and fallback
spools are not reset. Corruption or lock acquisition failure aborts cleanup.

The journal checkpoint is the commit point. If the live projection write fails,
the next writer rebuilds from the checkpoint. Never manually erase the journal
or reset its sequence. `telemetry_dashboard.py --all` discovers private archives
and excludes checkpoint records from event metrics.

Security blocks establish that an operation was denied. They do not establish
agent abandonment. The insights tab reports these barriers separately from
engine-correlated code corrections. Historical legacy records and test traffic
can affect aggregates; retain provenance rather than deleting suspected samples.
