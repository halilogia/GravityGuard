import test from 'node:test';
import assert from 'node:assert/strict';
import { renderRulesTab, relativeTime } from '../dist/webview/tabs/rules.js';
import { listedRules } from '../dist/rule_catalog.js';
import { initI18n, setLanguage } from '../dist/i18n/index.js';

const ago = ms => new Date(Date.now() - ms).toISOString();
const stat = (o = {}) => ({ blocked: 0, repeated: 0, warned: 0, shadow: 0, recovered: 0, evasion: 0, falseAlarms: 0, agents: {}, ...o });

function vm(projectCfg = {}, rules7 = {}, rulesAll = rules7) {
  const win = r => ({ operations: 0, blocked: 0, warned: 0, recovered: 0, evasion: 0, falseAlarms: 0, rules: r, agents: {} });
  return {
    data: { events: [] }, eventsList: [], projectCfg, pendingTests: {}, pendingDocs: {}, stopRetries: 0, sessionId: 'abc',
    auditStats: { available: true, totalRecords: 9, windows: { '24h': win({}), '7d': win(rules7), '30d': win(rulesAll), all: win(rulesAll) }, daily: [], sessions: [], recentByRule: {} }
  };
}

const text = html => html.replace(/<[^>]+>/g, '\n').split('\n').map(s => s.trim()).filter(Boolean);
const rowOf = (html, id) => html.split('<details').find(r => r.includes(`<span class="rl-id">${id}</span>`)) || '';

test('renders every listed catalog rule with its id', () => {
  initI18n('tr');
  const html = renderRulesTab(vm());
  for (const r of listedRules()) assert.ok(html.includes(`<span class="rl-id">${r.id}</span>`), r.id);
  assert.ok(html.includes('data-action="openConfig"'));
});

test('summary counts modes and 7-day triggers from the audit stats', () => {
  initI18n('tr');
  const html = renderRulesTab(vm({}, { G7_TS_FIRST: stat({ blocked: 3, agents: { Codex: 3 }, lastTs: ago(3 * 3600e3) }), OE_SPIKE: stat({ warned: 2, lastTs: ago(10 * 60e3) }) }));
  assert.match(html, /2 kural 5 kez tetiklendi|2 kural toplam 5 kez tetiklendi/);
  const g7 = rowOf(html, 'G7_TS_FIRST');
  assert.match(g7, /3 sa önce/);
  assert.match(g7, /En sık: Codex/);
  assert.match(g7, /<span class="rl-count"[^>]*>3<\/span>/);
  assert.match(rowOf(html, 'OE_SPIKE'), /10 dk önce/);
  // Sorted by 7-day triggers: the busiest rule of a group comes first.
  assert.ok(html.indexOf('>G7_TS_FIRST<') < html.indexOf('>G1_SILENT_EXCEPTION<'));
});

test('quiet rules show an em dash instead of an invented number', () => {
  initI18n('tr');
  const row = rowOf(renderRulesTab(vm()), 'G1_SILENT_EXCEPTION');
  assert.match(row, /<span class="rl-count"[^>]*>—<\/span>/);
  assert.ok(row.includes('rl-item quiet'));
});

test('effective mode comes from the config; shadowed rule is not shown as blocking', () => {
  initI18n('tr');
  const html = renderRulesTab(vm({ rules: { G1_SILENT_EXCEPTION: { mode: 'shadow' }, OE_SINGLE_IMPL: { mode: 'warn' } } }));
  assert.match(rowOf(html, 'G1_SILENT_EXCEPTION'), /mode-shadow/);
  assert.match(rowOf(html, 'G1_SILENT_EXCEPTION'), /data-mode="default"/);
  assert.match(rowOf(html, 'OE_SINGLE_IMPL'), /mode-warn/);
  assert.match(rowOf(html, 'OE_SINGLE_IMPL'), /data-mode="off"/);
  assert.match(rowOf(html, 'G7_TS_FIRST'), /mode-warn/);
});

test('mandatory rules have a lock and no mode buttons', () => {
  initI18n('tr');
  const row = rowOf(renderRulesTab(vm({ rules: { G0_SECRET_LEAK: { mode: 'shadow' } } })), 'G0_SECRET_LEAK');
  assert.match(row, /mode-block/);
  assert.ok(!row.includes('data-action="setRuleMode"'));
  assert.ok(row.includes('<svg'), 'lock icon');
});

test('ids missing from the catalog get their own group with the raw id', () => {
  initI18n('tr');
  const html = renderRulesTab(vm({}, { BRAND_NEW_RULE: stat({ blocked: 4, lastTs: ago(60e3) }), PASS: stat() }));
  const row = rowOf(html, 'BRAND_NEW_RULE');
  assert.ok(row);
  assert.ok(html.includes('Kataloğa eklenmemiş'));
  assert.ok(!html.includes('<span class="rl-id">PASS</span>'));
  assert.ok(!renderRulesTab(vm()).includes('Kataloğa eklenmemiş'));
});

test('no parentheses in any rule title or mode pill, in both languages', () => {
  for (const lang of ['tr', 'en']) {
    setLanguage(lang);
    const html = renderRulesTab(vm({ rules: { G1_SILENT_EXCEPTION: { mode: 'shadow' } } }, { OE_SPIKE: stat({ warned: 1, lastTs: ago(1e3) }) }));
    const titles = [...html.matchAll(/<span class="rl-title">([^<]*)<\/span>/g)].map(m => m[1]);
    const pills = [...html.matchAll(/<span class="mode-pill [^"]*">([^<]*)<\/span>/g)].map(m => m[1]);
    assert.ok(titles.length > 30 && pills.length > 30);
    for (const s of [...titles, ...pills]) assert.ok(!/[()]/.test(s), `${lang}: "${s}"`);
    const group = [...html.matchAll(/rl-group-title">([^<]*)</g)].map(m => m[1]);
    for (const s of group) assert.ok(!/[()]/.test(s));
  }
  initI18n('tr');
});

test('English render has no Turkish text', () => {
  setLanguage('en');
  const html = renderRulesTab(vm({}, { G7_TS_FIRST: stat({ blocked: 1, lastTs: ago(2 * 3600e3) }) }));
  const visible = text(html.replace(/<span class="rl-id">[^<]*<\/span>/g, '')).join(' ');
  assert.ok(!/[ğüşıöçĞÜŞİÖÇ]/.test(visible), visible.match(/\S*[ğüşıöçĞÜŞİÖÇ]\S*/)?.[0]);
  assert.match(visible, /Blocks|Warns|Observes/);
  assert.match(rowOf(html, 'G7_TS_FIRST'), /2 h ago/);
  initI18n('tr');
});

test('relativeTime handles missing and old timestamps', () => {
  initI18n('tr');
  assert.equal(relativeTime(undefined), '—');
  assert.equal(relativeTime('garbage'), '—');
  assert.equal(relativeTime(ago(3 * 864e5)), '3 gün önce');
  assert.equal(relativeTime(ago(5e3)), 'az önce');
});

test('without audit stats the summary says so and nothing is counted', () => {
  initI18n('tr');
  const v = vm();
  delete v.auditStats;
  const html = renderRulesTab(v);
  assert.ok(html.includes('Henüz denetim kaydı yok'));
});
