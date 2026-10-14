import test from 'node:test';
import assert from 'node:assert/strict';
import { renderObligationsTab } from '../dist/webview/tabs/obligations.js';

function makeMockVM(overrides = {}) {
  return {
    eventsList: [],
    data: null,
    pendingTests: {},
    pendingDocs: {},
    resolutionIntents: [],
    stopRetries: 0,
    skillsList: [],
    projectCfg: null,
    sessionId: 'test-session',
    totalObligations: 0,
    ...overrides
  };
}

test('renderObligationsTab renders clean state when no obligations exist', () => {
  const vm = makeMockVM();
  const html = renderObligationsTab(vm);
  assert.match(html, /clean-state-box/);
});

test('renderObligationsTab renders stop guard and pending test obligations', () => {
  const vm = makeMockVM({
    stopRetries: 1,
    pendingTests: {
      'src/engine.ts': {
        expected_name: 'engine.test.ts',
        reason: 'Test Kanıtı Uyarısı (T1): Test dosyası eksik.'
      }
    }
  });

  const html = renderObligationsTab(vm);
  assert.match(html, /engine\.ts/);
  assert.match(html, /engine\.test\.ts/);
  assert.match(html, /Devre Kesici Sayacı/);
  assert.match(html, /1 \/ 5/);
});

test('renderObligationsTab renders pending doc obligations with reason and CHANGELOG requirement', () => {
  const vm = makeMockVM({
    stopRetries: 0,
    pendingDocs: {
      'src/core.ts': {
        required_docs: ['CHANGELOG.md'],
        reason: 'docs/KNOWLEDGE.md §6 uyarınca CHANGELOG güncellenmeli'
      }
    }
  });

  const html = renderObligationsTab(vm);
  assert.match(html, /src\/core\.ts/);
  assert.match(html, /CHANGELOG\.md/);
  assert.match(html, /docs\/KNOWLEDGE\.md §6/);
});
