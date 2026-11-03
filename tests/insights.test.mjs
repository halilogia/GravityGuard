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
  assert.ok(html.indexOf('G4 Kör Üzerine Yazma') < html.indexOf('G1 Sessiz Hata Yutma'), 'higher volume first');
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
  assert.ok(html.includes('n=56') && html.includes('Güvenlik engeli'));
  assert.ok(!html.includes('Çekirdek düzeyi kilit'));
  assert.ok(!html.includes('< 1 ms'));
  assert.ok(html.includes('Ölçüm yok'));
});

// ---- audit-stats driven view -------------------------------------------------
function win(over = {}) {
  return { operations: 0, blocked: 0, warned: 0, recovered: 0, evasion: 0, falseAlarms: 0, rules: {}, agents: {}, ...over };
}
function ev(i, over = {}) {
  return { eventId: `evt_${i}`, timestamp: new Date(Date.now() - i * 3600e3).toISOString(), status: 'BLOCKED', ruleId: 'G1_SILENT_EXCEPTION',
    target: 'C:\\proj\\src\\app.py', agent: 'Claude Code', conversationId: 'claude:abcdef123456', reason: 'Boom <b>x</b>', evasionSuspect: false, falseAlarm: false, ...over };
}
function stats() {
  const w7 = win({
    operations: 100, blocked: 14, warned: 3, recovered: 10, evasion: 2, falseAlarms: 1,
    rules: {
      G1_SILENT_EXCEPTION: { blocked: 12, repeated: 0, warned: 0, shadow: 0, recovered: 10, evasion: 2, falseAlarms: 1, agents: {} },
      OE_SPIKE: { blocked: 2, repeated: 0, warned: 3, shadow: 0, recovered: 0, evasion: 0, falseAlarms: 0, agents: {} }
    },
    agents: {
      'Claude Code': { agent: 'Claude Code', operations: 80, conversations: 4, blocked: 10, warned: 2, recovered: 8, cleanFirstTry: 60 },
      Codex: { agent: 'Codex', operations: 0, conversations: 2, blocked: 0, warned: 1, recovered: 0, cleanFirstTry: 0 }
    }
  });
  const daily = Array.from({ length: 14 }, (_, i) => ({ day: `2026-10-${String(i + 10).padStart(2, '0')}`, operations: i, blocked: i % 5, warned: i % 3, recovered: 0 }));
  return {
    available: true, totalRecords: 120, firstTs: '2026-10-10T00:00:00Z', lastTs: '2026-11-03T00:00:00Z',
    windows: { '24h': win({ operations: 5 }), '7d': w7, '30d': w7, all: w7 }, daily, sessions: [],
    recentByRule: {
      G1_SILENT_EXCEPTION: [ev(1, { evasionSuspect: true }), ev(2, { falseAlarm: true, eventId: 'evt_fa' }), ev(3, { status: 'RECOVERED', eventId: 'evt_rec' })],
      OE_SPIKE: []
    }
  };
}
function vmStats(s) { return { ...vm({ events: [] }), auditStats: s }; }

test('all four windows are rendered, identical ones share a block', () => {
  initI18n('tr');
  const html = renderInsightsTab(vmStats(stats()));
  for (const k of ['24h', '7d', '30d', 'all']) assert.ok(html.includes(`data-value="${k}"`), k);
  assert.ok(html.includes('ins-win-24h'));
  assert.ok(html.includes('ins-win ins-win-7d ins-win-30d ins-win-all'), 'equal windows share one block');
  assert.ok(html.includes('24 sa') && html.includes('30 gün') && html.includes('Tümü'));
});

test('agent table: first-try clean rate, dash for zero operations, sorted by issues', () => {
  initI18n('tr');
  const html = renderInsightsTab(vmStats(stats()));
  assert.ok(html.includes('%75'), '60/80');
  assert.ok(html.indexOf('title="Claude Code"') < html.indexOf('title="Codex"'));
  const codex = html.slice(html.indexOf('title="Codex"'));
  assert.ok(codex.slice(0, codex.indexOf('</tr>')).includes('>—<'), 'zero operations shows a dash');
  assert.ok(html.includes('3,0'), 'issues per session = 12/4');
});

test('low-data rules collapse into one closed group', () => {
  initI18n('tr');
  const html = renderInsightsTab(vmStats(stats()));
  assert.ok(html.includes('1 kural, az veri'));
  const item = id => html.indexOf(`<div class="rule-stat-item ins-rule" data-rk="${id}"`);
  assert.ok(item('G1_SILENT_EXCEPTION') < html.indexOf('<div class="ins-low-body">'));
  assert.ok(html.indexOf('<div class="ins-low-body">') < item('OE_SPIKE'));
  assert.ok(html.includes('data-group="lowdata" data-value="open"'), 'closed by default, opens via lowdata segment');
});

test('drill-down shows events, escaped reason, false-alarm button and undo', () => {
  initI18n('tr');
  const html = renderInsightsTab(vmStats(stats()));
  assert.ok(html.includes('data-action="markFalseAlarm" data-id="evt_1" data-rule="G1_SILENT_EXCEPTION"'));
  assert.ok(html.includes('data-id="evt_fa" data-rule="G1_SILENT_EXCEPTION" data-undo="1"'));
  assert.ok(html.includes('Geri al'));
  assert.ok(html.includes('#abcdef') && html.includes('title="claude:abcdef123456"'));
  assert.ok(html.includes('>app.py<') && html.includes('title="C:\\proj\\src\\app.py"'));
  assert.ok(html.includes('atlatma şüphesi'));
  assert.ok(!html.includes('<b>x</b>') && html.includes('&lt;b&gt;x&lt;/b&gt;'));
  assert.ok(!html.includes('data-id="evt_rec"'), 'recovered events cannot be marked');
});

test('evasion and false alarm figures appear per rule and in the summary', () => {
  initI18n('tr');
  const html = renderInsightsTab(vmStats(stats()));
  assert.ok(html.includes('Atlatma 2 · düzeltmelerin %20'));
  assert.ok(html.includes('Hatalı alarm 1 · olayların %8'), 'per rule: 1 of 12');
  assert.ok(html.includes('<span class="text-muted"> · %6</span>'), 'summary: 1 of 17 blocked and warned');
  assert.ok(html.includes('<span class="text-muted"> · %20</span>'), 'summary evasion: 2 of 10 fixes');
  assert.ok(html.includes('Atlatma şüphesi') && html.includes('Atlatma: düzeltme yalnızca'));
});

test('trend svg has a max label; empty trend and unavailable stats fall back honestly', () => {
  initI18n('en');
  const html = renderInsightsTab(vmStats(stats()));
  assert.ok(html.includes('<svg class="ins-trend"') && html.includes('peak 5'));
  const s = stats(); s.daily = s.daily.map(d => ({ ...d, blocked: 0, warned: 0 }));
  assert.ok(renderInsightsTab(vmStats(s)).includes('No events in the last 14 days'));
  const legacy = renderInsightsTab(vmStats({ available: false }));
  assert.ok(!legacy.includes('ins-seg') && legacy.includes('width: 0%') && legacy.includes('>—<'));
  initI18n('tr');
});

test('no parenthetical translations in insight texts', () => {
  for (const l of ['tr', 'en']) {
    initI18n(l);
    const html = renderInsightsTab(vmStats(stats())).replace(/<style>[\s\S]*?<\/style>/g, '');
    assert.ok(!/\((GÖLGE|SHADOW|UYARI|WARN)\)/.test(html), l);
  }
  initI18n('tr');
});
