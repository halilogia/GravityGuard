import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { renderHooksTab } from '../dist/webview/tabs/hooks.js';
import { APPROVAL_ID, approvalSignature } from '../dist/webview/approval_tickets.js';
import { runHookControl } from '../dist/webview/hook_proposals.js';

const script = path.resolve('engine', 'approval_control.py');
const ticket = { id: '0123456789abcdef', rule: 'G1_X', reason: 'neden <b>', seen: 1, action: { tool: 'Edit', target: 'a.txt', command: 'rm <x>' } };

test('blocked action card has one-click buttons and escaped text', () => {
  const html = renderHooksTab({ pending: [], installed: [] }, [ticket]);
  assert.match(html, /data-action="allowApproval" data-text="0123456789abcdef"/);
  assert.match(html, /data-action="denyApproval" data-text="0123456789abcdef"/);
  assert.match(html, /rm &lt;x&gt;/);
  assert.doesNotMatch(html, /rm <x>/);
});

test('ticket ids are 16 hex characters', () => {
  assert.ok(APPROVAL_ID.test('0123456789abcdef'));
  assert.ok(!APPROVAL_ID.test('../../etc/passwd'));
});

test('one click through the trusted command lifts a real ticket', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gg-tickets-'));
  process.env.GRAVITYGUARD_APPROVAL_DIR = dir;
  const code = 'import sys; sys.path.insert(0, "engine"); from gravityguard_engine import approvals as a; '
    + 'print(a.record_block("G1_X", "[G1_X] r", {"tool": "Edit", "target": "a", "args": {"k": 1}})["id"])';
  const made = spawnSync('python', ['-X', 'utf8', '-c', code], { env: process.env, encoding: 'utf8' });
  const id = made.stdout.trim();
  assert.match(id, APPROVAL_ID);
  assert.notEqual(approvalSignature(), '');
  const listed = await runHookControl(script, { action: 'list' });
  assert.equal(listed.pending[0].id, id);
  const answer = await runHookControl(script, { action: 'allow', id });
  assert.equal(answer.ok, true);
  assert.equal(answer.status, 'approved');
  delete process.env.GRAVITYGUARD_APPROVAL_DIR;
});
