import { t } from '../../i18n';
import { lucide } from '../../icons';
import { GuardianViewModel } from '../types';
import { configuredMode } from '../../rule_modes';
import { NON_VIOLATION_RULES, RuleStat } from '../../audit_stats';
import {
  RULE_GROUPS, RuleGroup, RuleInfo, EffectiveMode, getRule, listedRules, ruleTitle, ruleDescription, effectiveMode, NOTE_RULE_IDS
} from '../../rule_catalog';
import { escapeHtml } from '../html_utils';

const GROUP_KEY: Record<RuleGroup, string> = {
  security: 'rules.groupSecurity',
  architecture: 'rules.groupArchitecture',
  quality: 'rules.groupQuality',
  evidence: 'rules.groupEvidence',
  tooling: 'rules.groupTooling'
};
const STAGE_KEY = { write: 'rules.stageWrite', tool: 'rules.stageTool', stop: 'rules.stageStop', any: 'rules.stageAny' };
const MODE_PILL: Record<EffectiveMode, { cls: string; key: string }> = {
  block: { cls: 'mode-block', key: 'rules.badgeBlock' },
  warn: { cls: 'mode-warn', key: 'rules.badgeWarn' },
  shadow: { cls: 'mode-shadow', key: 'rules.badgeShadow' },
  off: { cls: 'mode-inactive', key: 'rules.badgeOff' }
};

const triggers = (s?: RuleStat): number => (s ? s.blocked + s.repeated + s.warned + s.shadow : 0);

/** Relative time such as "3 sa önce"; an em dash when there is no timestamp. */
export function relativeTime(ts: string | undefined, now: number = Date.now()): string {
  const ms = ts ? Date.parse(ts) : NaN;
  if (Number.isNaN(ms)) return '—';
  const min = Math.max(0, Math.floor((now - ms) / 60000));
  if (min < 1) return t('rules.timeNow');
  if (min < 60) return t('rules.timeMin', { n: min });
  if (min < 1440) return t('rules.timeHour', { n: Math.floor(min / 60) });
  return t('rules.timeDay', { n: Math.floor(min / 1440) });
}

function topAgent(s?: RuleStat): string {
  const entries = Object.entries(s?.agents || {}).sort((a, b) => b[1] - a[1]);
  return entries.length ? entries[0][0] : '';
}

function pill(mode: EffectiveMode): string {
  const p = MODE_PILL[mode];
  return `<span class="mode-pill ${p.cls}">${t(p.key)}</span>`;
}

function modeButton(id: string, mode: string, label: string, active: boolean): string {
  return `<button class="rl-mode-btn${active ? ' active' : ''}" data-action="setRuleMode" data-rule="${escapeHtml(id)}" data-mode="${mode}">${label}</button>`;
}

function controls(rule: RuleInfo, cfg: any, mode: EffectiveMode): string {
  if (rule.mandatory) return `<div class="rl-note">${lucide('lock', { size: 11 })} ${t('rules.mandatoryNote')}</div>`;
  if (rule.control === 'none') return `<div class="rl-note">${t('rules.fixedNote')}</div>`;
  const configured = configuredMode(cfg, rule.id);
  if (rule.control === 'shadow') {
    const inShadow = configured === 'shadow';
    return `<div class="rl-modes">${modeButton(rule.id, 'default', t('rules.modeDefault'), !inShadow)}${modeButton(rule.id, 'shadow', t('rules.modeShadow'), inShadow)}</div>`;
  }
  const explicit = configured === 'warn' || configured === 'off' ? configured : 'default';
  void mode;
  return `<div class="rl-modes">${modeButton(rule.id, 'default', t('rules.modeDefault'), explicit === 'default')}${modeButton(rule.id, 'warn', t('rules.modeWarn'), explicit === 'warn')}${modeButton(rule.id, 'off', t('rules.modeOff'), explicit === 'off')}</div>`;
}

interface RowData { id: string; title: string; mode: EffectiveMode | null; stat?: RuleStat; count: number; rule?: RuleInfo; }

function renderRow(row: RowData, cfg: any, now: number): string {
  const { rule, stat, count } = row;
  const last = count > 0 ? relativeTime(stat?.lastTs, now) : '';
  const agent = count > 0 ? topAgent(stat) : '';
  const meta = [last, agent ? t('rules.topAgent', { agent: escapeHtml(agent) }) : ''].filter(Boolean).join(' · ');
  const desc = rule ? ruleDescription(rule.id) : t('rules.uncataloguedHint');
  const extra = rule ? `<div class="rl-stage">${t(STAGE_KEY[rule.stage])}</div>${rule.enabledBy && !rule.enabledBy(cfg) ? `<div class="rl-stage">${t('rules.offByConfig')}</div>` : ''}` : '';
  const body = `<div class="rl-body"><div class="rl-desc">${escapeHtml(desc)}</div>${extra}${rule && row.mode ? controls(rule, cfg, row.mode) : ''}</div>`;
  return `
      <details class="rl-item${count === 0 ? ' quiet' : ''}">
        <summary>
          <span class="rl-chev">${lucide('chevronRight', { size: 10 })}</span>
          <span class="rl-main">
            <span class="rl-title">${escapeHtml(row.title)}</span>
            <span class="rl-id">${escapeHtml(row.id)}</span>
          </span>
          <span class="rl-side">
            ${row.mode ? pill(row.mode) : ''}
            <span class="rl-count" title="${escapeHtml(t('rules.countTitle'))}">${count > 0 ? count : '—'}</span>
          </span>
          <span class="rl-meta">${meta}</span>
        </summary>
        ${body}
      </details>`;
}

function group(title: string, rows: string[], hint = ''): string {
  if (!rows.length) return '';
  return `
      <div class="rl-group">
        <div class="rl-group-title">${escapeHtml(title)}</div>${hint ? `<div class="rl-group-hint">${escapeHtml(hint)}</div>` : ''}
        ${rows.join('')}
      </div>`;
}

export function renderRulesTab(vm: GuardianViewModel): string {
  const cfg = vm.projectCfg;
  const now = Date.now();
  const week = vm.auditStats?.windows?.['7d']?.rules || {};
  const all = vm.auditStats?.windows?.all?.rules || {};

  const rows: Array<RowData & { group: RuleGroup }> = listedRules().map(rule => ({
    id: rule.id, title: ruleTitle(rule.id), mode: effectiveMode(rule, cfg), stat: week[rule.id], count: triggers(week[rule.id]), rule, group: rule.group
  }));
  const bySort = (a: RowData, b: RowData) => b.count - a.count;

  let nBlock = 0, nWarn = 0, nShadow = 0, nOff = 0, firedRules = 0, firedTotal = 0;
  for (const r of rows) {
    if (r.mode === 'block') nBlock++; else if (r.mode === 'warn') nWarn++; else if (r.mode === 'shadow') nShadow++; else nOff++;
    if (r.count > 0) { firedRules++; firedTotal += r.count; }
  }
  const noted = new Set([...NOTE_RULE_IDS, ...NON_VIOLATION_RULES]);
  const unknownIds = Object.keys(all).filter(id => !getRule(id) && !noted.has(id));
  const unknown: RowData[] = unknownIds.map(id => ({ id, title: id, mode: null, stat: week[id], count: triggers(week[id]) })).sort(bySort);
  for (const u of unknown) if (u.count > 0) { firedRules++; firedTotal += u.count; }

  const modesLine = t('rules.summaryModes', { block: nBlock, warn: nWarn, shadow: nShadow }) + (nOff > 0 ? ' · ' + t('rules.summaryOff', { off: nOff }) : '');
  const firedLine = !vm.auditStats?.available
    ? t('rules.summaryNoData')
    : firedTotal > 0 ? t('rules.summaryFired', { rules: firedRules, count: firedTotal }) : t('rules.summaryQuiet');

  const groups = RULE_GROUPS.map(g =>
    group(t(GROUP_KEY[g]), rows.filter(r => r.group === g).sort(bySort).map(r => renderRow(r, cfg, now)))
  ).join('');
  const uncatalogued = group(t('rules.groupUncatalogued'), unknown.map(r => renderRow(r, cfg, now)), t('rules.uncataloguedHint'));

  return `
      <div class="rl-summary">
        <div>${escapeHtml(modesLine)}</div>
        <div class="rl-summary-sub">${escapeHtml(firedLine)}</div>
      </div>
      ${groups}${uncatalogued}
      <div class="rl-footer">
        <button class="action-btn wide" data-action="openConfig">${lucide('settings', { size: 12 })} ${t('actions.openConfig')}</button>
      </div>
    `;
}
