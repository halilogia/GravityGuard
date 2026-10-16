import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { buildClientScript } from '../dist/webview/client.js';
import { initI18n, t } from '../dist/i18n/index.js';

const pkg = JSON.parse(fs.readFileSync(new URL('../package.json', import.meta.url), 'utf8'));

test('resetWebview command is contributed and registered', () => {
  const cmds = pkg.contributes.commands.map(c => c.command);
  assert.ok(cmds.includes('antigravityBridge.resetWebview'));
  const ext = fs.readFileSync(new URL('../src/extension.ts', import.meta.url), 'utf8');
  assert.ok(ext.includes("'antigravityBridge.resetWebview'"));
  assert.ok(ext.includes('retainContextWhenHidden: true'));
});

test('client script posts ready handshake', () => {
  const script = buildClientScript('nonce123', 'live');
  assert.ok(script.includes("command: 'ready'"));
  assert.ok(script.includes("nonce: 'nonce123'"), 'ready carries the document nonce');
});

test('recovery failure message exists in both languages', () => {
  for (const lang of ['tr', 'en']) {
    initI18n(lang);
    assert.notEqual(t('actions.webviewRecoveryFailed'), 'actions.webviewRecoveryFailed');
  }
});

test('provider only assigns webview.html through the lifecycle controller', () => {
  const src = fs.readFileSync(new URL('../src/webview/provider.ts', import.meta.url), 'utf8');
  assert.equal((src.match(/\.webview\.html\s*=/g) || []).length, 1);
  assert.ok(src.includes('workbench.action.webview.reloadWebviewAction'));
});

test('reloadWebviews label exists in both languages', () => {
  for (const lang of ['tr', 'en']) {
    initI18n(lang);
    assert.notEqual(t('actions.reloadWebviews'), 'actions.reloadWebviews');
  }
});
