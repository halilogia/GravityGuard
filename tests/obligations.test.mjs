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

test('renderObligationsTab renders agent badge, project badge, and dismiss buttons', () => {
  const vm = makeMockVM({
    pendingTests: {
      'C:/Users/Halil Emre/Desktop/GitHub/Public/AgentObservatory/src/core/event_store.js': {
        expected_name: 'event_store.test.js',
        agent: 'Codex',
        timestamp: 1791612853,
        reason: 'Test eksik'
      }
    }
  });

  const html = renderObligationsTab(vm);
  assert.match(html, /AgentObservatory/, 'Project badge should be rendered');
  assert.match(html, /Codex/, 'Codex agent name should be rendered');
  assert.match(html, /agent-codex/, 'Codex grey badge class should be rendered');
  assert.match(html, /data-action="dismissObligation"/, 'Dismiss button should be rendered');
  assert.match(html, /data-action="clearAllObligations"/, 'Clear All button should be rendered');
});

