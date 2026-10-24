import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { routerEndpoint } from '../dist/router_security.js';
import { MessagePathPolicy } from '../dist/webview/message_policy.js';
import { renderInsightsTab } from '../dist/webview/tabs/insights.js';

test('insights separates security barriers from proven code corrections', () => {
  const vm = { data: { effectiveness: { totalBlocked: 2, totalRecovered: 1, recoveryRate: 50,
    totalCodeBlocked: 1, totalCodeRecovered: 1, codeFixRate: 100,
    ruleStats: { G0_ENV_PROTECTION: { blocked: 1, recovered: 0, recoveryRate: 0 } } } },
    eventsList: [], pendingTests: {}, pendingDocs: {}, projectCfg: {}, stopRetries: 0, sessionId: 'test' };
  const html = renderInsightsTab(vm);
  assert.match(html, /recovery-score">100%/);
  assert.match(html, /Vazgeçme doğrulanmadı|Abandonment unverified/);
  vm.data = {};
  vm.eventsList = [{ status: 'APPROVED', target: '/x' }, { status: 'BLOCKED', outcome: 'BLOCKED', ruleId: 'G1', target: '/x' }];
  assert.match(renderInsightsTab(vm), /recovery-score">0%/);
});

test('router sends plain HTTP only to loopback and accepts remote HTTPS', () => {
  assert.equal(routerEndpoint('127.0.0.1', 20128).port, 20128);
  assert.equal(routerEndpoint('::1', 9000).protocol, 'http:');
  assert.equal(routerEndpoint('https://gateway.example', 20128).port, 443);
  for (const host of ['http://gateway.example', 'gateway.example', 'https://user:pass@gateway.example', 'https://gateway.example/path']) {
    assert.throws(() => routerEndpoint(host, 20128));
  }
});

test('webview may mutate only the rendered file set for that command kind', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'gg_message_'));
  try {
    const tasks = path.join(root, 'TASKS.md');
    fs.writeFileSync(tasks, '- [ ] task');
    const policy = new MessagePathPolicy(); policy.set('tasks', [tasks]);
    assert.equal(policy.permits('tasks', tasks), true);
    assert.equal(policy.permits('knowledge', tasks), false);
    assert.equal(policy.permits('tasks', path.join(root, 'other.md')), false);
    assert.equal(policy.permits('tasks', '../TASKS.md'), false);
    assert.equal(policy.permits('tasks', null), false);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
