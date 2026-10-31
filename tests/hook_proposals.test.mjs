import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { hookFilesSignature, splitHookFile, runHookControl } from '../dist/webview/hook_proposals.js';
import { renderHooksTab } from '../dist/webview/tabs/hooks.js';
import { MessagePathPolicy } from '../dist/webview/message_policy.js';

const engineScript = path.resolve('engine', 'hook_proposal_control.py');

function project() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'gg-hooks-'));
  const dir = path.join(root, '.gravityguard', 'proposals', 'hooks');
  fs.mkdirSync(dir, { recursive: true });
  return { root, dir };
}

test('pending proposal shows complaint, diff and buttons; text is escaped', () => {
  const html = renderHooksTab({ pending: [{ id: 'sweep', root: '/p', path: '/p/.gravityguard/proposals/hooks/sweep.json',
    sha256: 'abc', valid: true, target_file: '/p/.claude/settings.json', diff: '@@ -0,0 +1 @@\n+{"hooks": 1}',
    proposal: { event: 'UserPromptSubmit', command: 'cat <x>', complaint: 'unutuyor', rationale: 'r', test: 't' } }],
    installed: [{ id: 'old', root: '/p', status: 'installed', target_file: '/p/.claude/settings.json', proposal: { event: 'Stop' } }] });
  assert.match(html, /data-action="approveHookProposal"[^>]*data-text="abc"/);
  assert.match(html, /data-action="rejectHookProposal"/);
  assert.match(html, /data-action="revertHookProposal" data-path="\/p\/.gravityguard\/runtime\/hook-receipts\/old.json"/);
  assert.match(html, /diff-add/);
  assert.match(html, /cat &lt;x&gt;/);
  assert.doesNotMatch(html, /cat <x>/);
});

test('invalid proposal can be rejected but never approved', () => {
  const html = renderHooksTab({ pending: [{ id: 'bad', root: '/p', path: '/p/x/bad.json', valid: false,
    error: 'PreToolUse önerilemez', proposal: { event: 'PreToolUse' } }], installed: [] });
  assert.doesNotMatch(html, /approveHookProposal/);
  assert.match(html, /rejectHookProposal/);
  assert.match(html, /PreToolUse önerilemez/);
});

test('signature changes when a proposal appears; file paths split into root and id', () => {
  const { root, dir } = project();
  const before = hookFilesSignature([root]);
  fs.writeFileSync(path.join(dir, 'sweep.json'), '{}');
  assert.notEqual(hookFilesSignature([root]), before);
  assert.deepEqual(splitHookFile(path.join(dir, 'sweep.json')), { root, id: 'sweep' });
  assert.deepEqual(splitHookFile(path.join(root, '.gravityguard', 'runtime', 'hook-receipts', 'sweep.json')), { root, id: 'sweep' });
  assert.equal(splitHookFile(path.join(root, 'elsewhere', 'sweep.json')), undefined);
});

test('panel messages only act on listed proposal files', () => {
  const { root, dir } = project();
  const file = path.join(dir, 'sweep.json');
  fs.writeFileSync(file, '{}');
  const policy = new MessagePathPolicy();
  policy.set('hookProposals', [file]);
  assert.equal(policy.permits('hookProposals', file), true);
  assert.equal(policy.permits('hookProposals', path.join(root, '.claude', 'settings.json')), false);
});

test('engine control lists a real proposal for the panel', async () => {
  const { root, dir } = project();
  fs.mkdirSync(path.join(root, 'docs'));
  fs.writeFileSync(path.join(dir, 'sweep.json'), JSON.stringify({ id: 'sweep', target: 'claude', event: 'UserPromptSubmit',
    command: 'cat docs/a.md', test: 'cat docs/a.md', rationale: 'r' }));
  const answer = await runHookControl(engineScript, { action: 'list', roots: [root] });
  assert.equal(answer.pending.length, 1);
  assert.equal(answer.pending[0].valid, true, answer.pending[0].error);
  assert.match(answer.pending[0].diff, /\+\s+"UserPromptSubmit"/);
});
