import test from 'node:test';
import assert from 'node:assert/strict';
import { renderInsightsTab } from '../dist/webview/tabs/insights.js';
import { initI18n } from '../dist/i18n/index.js';

function vm(data) {
  return { data, eventsList: [], pendingTests: {}, pendingDocs: {}, projectCfg: {}, stopRetries: 0, sessionId: 'sess-1' };
}

test('empty history shows no rate and an empty bar', () => {
  initI18n('tr');
  const html = renderInsightsTab(vm({ events: [], effectiveness: { ruleStats: {} } }));
  assert.ok(html.includes('width: 0%'), 'bar must not be full without data');
  assert.ok(html.includes('>—<'));
});

test('median is hidden when no attempts were recorded', () => {
  initI18n('tr');
  const html = renderInsightsTab(vm({ events: [], effectiveness: { ruleStats: {
    G1_SILENT_EXCEPTION: { blocked: 4, recovered: 2, recoveryRate: 50, medianAttempts: 1, attempts: [] }
  } } }));
  assert.ok(!html.includes('Medyan'));
});

test('extra rules get readable names, recovered-only keys are skipped, active rules sorted', () => {
  initI18n('tr');
  const html = renderInsightsTab(vm({ events: [], effectiveness: { ruleStats: {
    G1_SILENT_EXCEPTION: { blocked: 42, recovered: 35, attempts: [1] },
    G4_NO_BLIND_OVERWRITE: { blocked: 137, recovered: 90, attempts: [1, 2] },
    T1_PENDING: { blocked: 0, recovered: 3 }
  } } }));
  assert.ok(html.includes('G4 Kör Üzerine Yazma'));
  assert.ok(!html.includes('G4_NO_BLIND_OVERWRITE'));
  assert.ok(!html.includes('T1_PENDING'));
  assert.ok(html.indexOf('G4 Kör Üzerine Yazma') < html.indexOf('Sessiz hata yutma'), 'higher volume first');
  assert.ok(html.includes('kuralda ihlal yok'), 'clean rules collapse into one line');
});

test('open violations are surfaced per rule and in total', () => {
  initI18n('tr');
  const html = renderInsightsTab(vm({ events: [], effectiveness: { ruleStats: {
    G1_SILENT_EXCEPTION: { blocked: 2, recovered: 0 }
  } }, activeViolations: {
    'c::a.py::G1_SILENT_EXCEPTION': { ruleId: 'G1_SILENT_EXCEPTION' },
    'c::b.py::G1_SILENT_EXCEPTION': { ruleId: 'G1_SILENT_EXCEPTION' }
  } }));
  assert.ok(html.includes('2 hâlâ açık'));
  assert.ok(html.includes('2 engellenen işlem hâlâ düzeltilmedi'));
});

test('security badge shows its count; no hardcoded health checks or fake latency', () => {
  initI18n('tr');
  const html = renderInsightsTab(vm({ events: [], effectiveness: { ruleStats: {
    G0_ENV_PROTECTION: { blocked: 56, recovered: 0 }
  } } }));
  assert.ok(html.includes('Güvenlik engeli (n=56)'));
  assert.ok(!html.includes('Çekirdek düzeyi kilit'));
  assert.ok(!html.includes('< 1 ms'));
  assert.ok(html.includes('Ölçüm yok'));
});
