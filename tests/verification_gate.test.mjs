import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { computeVerificationGate, overallGateStatus, eventsForProject, loadVerificationGate } from '../dist/verification_gate.js';
import { renderVerificationGateCard } from '../dist/webview/tabs/verification.js';
import { initI18n } from '../dist/i18n/index.js';

// Two-stage gate: shield and tests, both derived from events (compile and preview stages were removed).
const statusOf =(stages, id) => stages.find(s => s.id === id).status;
const write = (target, timestamp, extra = {}) => ({ target, timestamp, status: 'APPROVED', ruleId: 'PASS', ...extra });

test('no evidence leaves every stage pending', () => {
  const stages = computeVerificationGate([], {});
  assert.deepEqual(stages.map(s => s.id), ['shield', 'tests']);
  assert.ok(stages.every(s => s.status === 'pending'));
  assert.equal(overallGateStatus(stages), 'pending');
});

test('recorded passes and a clean shield make the gate pass', () => {
  const events = [write('/p/a.ts', '2026-11-06 10:00:00')];
  const report = { tests: { status: 'pass', at: '2026-11-06T10:05:00' } };
  const stages = computeVerificationGate(events, report);
  assert.equal(overallGateStatus(stages), 'pass');
});

test('a write after a recorded pass makes it stale and pending', () => {
  const events = [write('/p/a.ts', '2026-11-06 10:10:00')];
  const stages = computeVerificationGate(events, { tests: { status: 'pass', at: '2026-11-06T10:05:00' } });
  const tests = stages.find(s => s.id === 'tests');
  assert.equal(tests.status, 'pending');
  assert.equal(tests.stale, true);
});

test('reads and briefings do not age a recorded pass', () => {
  const events = [write('/p/a.ts', '2026-11-06 10:10:00', { ruleId: 'READ_ALLOW' })];
  const stages = computeVerificationGate(events, { tests: { status: 'pass', at: '2026-11-06T10:05:00' } });
  assert.equal(statusOf(stages, 'tests'), 'pass');
});

test('an open linter diagnostic is a shield warning until the file has a later clean event', () => {
  const diag = write('/p/a.ts', '2026-11-06 10:00:00', { status: 'WARNING', ruleId: 'STATIC_LINTER_DIAGNOSTIC' });
  assert.equal(statusOf(computeVerificationGate([diag]), 'shield'), 'warn');
  const cleaned = [write('/p/a.ts', '2026-11-06 10:01:00'), diag];
  assert.equal(statusOf(computeVerificationGate(cleaned), 'shield'), 'pass');
});

test('shield fails on an unrecovered block and passes once the file is written cleanly', () => {
  const block = write('/p/a.py', '2026-11-06 10:00:00', { status: 'BLOCKED', ruleId: 'G1_SILENT_CATCH' });
  const stages = computeVerificationGate([block]);
  assert.equal(statusOf(stages, 'shield'), 'fail');
  assert.equal(stages.find(s => s.id === 'shield').detail, 'G1_SILENT_CATCH');
  assert.equal(statusOf(computeVerificationGate([write('/p/a.py', '2026-11-06 10:02:00'), block]), 'shield'), 'pass');
  const pendingNote = write('/p/b.py', '2026-11-06 10:03:00', { status: 'WARNING', ruleId: 'T1_PENDING' });
  assert.equal(statusOf(computeVerificationGate([pendingNote]), 'shield'), 'pass');
});

test('a test-run failure newer than the recorded pass wins', () => {
  const fail = { timestamp: '2026-11-06 10:10:00', status: 'WARNING', ruleId: 'T0_TEST_RUN_FAILED' };
  const stages = computeVerificationGate([fail], { tests: { status: 'pass', at: '2026-11-06T10:05:00' } });
  assert.equal(statusOf(stages, 'tests'), 'fail');
  assert.equal(overallGateStatus(stages), 'fail');
});

test('the gate has no compile or preview stage any more', () => {
  const ids = computeVerificationGate([], { compile: { status: 'fail' }, preview: { status: 'fail' } }).map(s => s.id);
  assert.deepEqual(ids, ['shield', 'tests']);
});

test('events of other projects are ignored', () => {
  const root = path.resolve('/work/app');
  const events = [{ target: path.join(root, 'a.ts') }, { target: path.resolve('/work/other/b.ts') }, { ruleId: 'T0_TEST_RUN_FAILED' }];
  assert.equal(eventsForProject(events, root).length, 2);
  assert.equal(eventsForProject(events, '').length, 3);
});

test('loadVerificationGate reads the runtime report and survives a corrupt file', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'gg-gate-'));
  const runtime = path.join(root, '.gravityguard', 'runtime');
  fs.mkdirSync(runtime, { recursive: true });
  fs.writeFileSync(path.join(runtime, 'verification.json'), JSON.stringify({ tests: { status: 'fail', detail: '2 failed', at: '2026-11-06T10:00:00Z' } }));
  assert.equal(statusOf(loadVerificationGate(root, []), 'tests'), 'fail');
  fs.writeFileSync(path.join(runtime, 'verification.json'), '{broken');
  assert.equal(statusOf(loadVerificationGate(root, []), 'tests'), 'pending');
  fs.rmSync(root, { recursive: true, force: true });
});

test('the card shows two rows, the worst status and the hint only when nothing is recorded', () => {
  initI18n('en');
  const pending = renderVerificationGateCard(computeVerificationGate([]));
  assert.equal((pending.match(/class="gate-row"/g) || []).length, 2);
  assert.match(pending, /gate-hint/);
  const failed = renderVerificationGateCard(computeVerificationGate([], { tests: { status: 'fail', detail: '<b>3 errors</b>' } }));
  assert.match(failed, /gate-hdr">\s*<span class="gate-tag">VERIFICATION GATE<\/span>\s*<span class="gate-state gate-text-fail">Failed/);
  assert.match(failed, /&lt;b&gt;3 errors&lt;\/b&gt;/);
  assert.doesNotMatch(failed, /gate-hint/);
  assert.equal(renderVerificationGateCard(undefined), '');
});
