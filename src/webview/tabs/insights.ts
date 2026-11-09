import { ruleTitle } from '../../rule_catalog';
import { t, getCurrentLanguage } from '../../i18n';
import { lucide } from '../../icons';
import { escapeHtml } from '../html_utils';
import { GuardianViewModel } from '../types';
import type { AuditEventLite, AuditStats, DayBucket, WindowKey, WindowStats } from '../../audit_stats';

const WINDOWS: WindowKey[] = ['24h', '7d', '30d', 'all'];
const WINDOW_LABEL: Record<WindowKey, string> = { '24h': 'win24h', '7d': 'win7d', '30d': 'win30d', all: 'winAll' };
const LOW_DATA_EVENTS = 10;
const DRILL_EVENTS = 6;

const isSecurityRule = (rule: string) => rule.startsWith('G0_') || ['POLICY_INTEGRITY', 'G2_SECURITY_TAMPERING', 'SHELL_SECURITY'].includes(rule);

/** One rule row, whichever source (audit journal or legacy effectiveness block) it came from. */
interface RuleRow {
  id: string;
  blocked: number;
  repeated: number;
  warned: number;
  shadow: number;
  recovered: number;
  evasion: number;
  falseAlarms: number;
  open: number;
  med: number | null;
}

const pct = (n: number) => t('insights.pct', { n });
const rate = (part: number, whole: number): number | null => (whole > 0 ? Math.round((part / whole) * 100) : null);
const ruleKey = (id: string) => id.replace(/[^A-Za-z0-9_-]/g, '_');

// One name per rule across tabs: the catalog is the only source.
const ruleLabel = (id: string): string => ruleTitle(id);

function events(r: RuleRow): number {
  return r.blocked + r.repeated + r.warned + r.shadow;
}

function badgeFor(r: RuleRow): { text: string; cls: string; icon: string; n: number } {
  const b = r.blocked;
  const fix = rate(Math.min(r.recovered, b), b) ?? 0;
  if (isSecurityRule(r.id) && b > 0) return { text: t('insights.badgeDeterrence'), cls: 'badge-allowed', icon: lucide('shieldCheck', { size: 9 }), n: b };
  if (b === 0 && r.warned > 0) return { text: t('insights.badgeAdvisory'), cls: 'badge-warning', icon: lucide('alertTriangle', { size: 9 }), n: r.warned };
  if (b === 0 && r.shadow > 0) return { text: t('insights.badgeObserved'), cls: 'badge-purple', icon: lucide('eye', { size: 9 }), n: r.shadow };
  if (b === 0) return { text: t('insights.badgeNoViolations'), cls: 'badge-allowed', icon: lucide('checkCircle', { size: 9 }), n: 0 };
  if (b < 10) return { text: t('insights.badgeInsufficient'), cls: 'badge-neutral', icon: lucide('circleDot', { size: 9 }), n: b };
  if (b < 30) return { text: t('insights.badgeEarlySignal'), cls: 'badge-warning', icon: lucide('alertTriangle', { size: 9 }), n: b };
  if (fix >= 80) return { text: t('insights.badgeHighValue'), cls: 'badge-allowed', icon: lucide('trophy', { size: 9 }), n: b };
  if (fix < 50) return { text: t('insights.badgeFriction'), cls: 'badge-blocked', icon: lucide('zap', { size: 9 }), n: b };
  return { text: t('insights.badgeBalanced'), cls: 'badge-cyan', icon: lucide('checkCircle', { size: 9 }), n: b };
}

function ruleHead(r: RuleRow, open: boolean, clickable: boolean): string {
  const badge = badgeFor(r);
  const parts: string[] = [];
  if (isSecurityRule(r.id) && r.blocked) parts.push(t('insights.ruleDeterrence', { blocked: r.blocked }));
  else if (r.blocked) parts.push(t('insights.partBlocked', { n: r.blocked }));
  if (r.repeated) parts.push(t('insights.partRepeated', { n: r.repeated }));
  if (r.warned) parts.push(t('insights.partWarned', { n: r.warned }));
  if (r.shadow) parts.push(t('insights.partShadow', { n: r.shadow }));
  if (r.recovered && !isSecurityRule(r.id)) parts.push(t('insights.partRecovered', { n: r.recovered }));
  const fix = isSecurityRule(r.id) ? null : rate(Math.min(r.recovered, r.blocked), r.blocked);
  const action = clickable
    ? ` data-action="selectSegment" data-group="rule" data-value="${open ? '-' : escapeHtml(ruleKey(r.id))}" role="button" tabindex="0"`
    : '';
  return `
          <div class="ins-rh ${clickable ? (open ? 'ins-rh-open' : 'ins-rh-closed') : ''}"${action}>
            <div class="rule-stat-header">
              <span class="rule-stat-name">${clickable ? `<span class="ins-chev">${lucide('chevronRight', { size: 10 })}</span>` : ''}${escapeHtml(ruleLabel(r.id))}</span>
              <span class="ins-badge-wrap">${badge.n > 0 ? `<span class="ins-n">n=${badge.n}</span>` : ''}<span class="status-badge ${badge.cls}">${badge.icon} ${badge.text}</span></span>
            </div>
            <div class="rule-stat-sub">
              <span>${parts.join(' · ') || '—'}</span>
              ${fix !== null ? `<span class="ins-fix">${t('insights.ruleFixRate', { rate: fix })}</span>` : ''}
            </div>
            ${r.med !== null ? `<div class="rule-stat-sub"><span>${t('insights.medianAttempts', { attempts: r.med })}</span></div>` : ''}
            ${r.evasion > 0 || r.falseAlarms > 0 ? `<div class="ins-signals">
              ${r.evasion > 0 ? `<span class="ins-sig ins-sig-evasion">${t('insights.ruleEvasion', { n: r.evasion, rate: rate(r.evasion, r.recovered) ?? 0 })}</span>` : ''}
              ${r.falseAlarms > 0 ? `<span class="ins-sig ins-sig-fa">${t('insights.ruleFalseAlarm', { n: r.falseAlarms, rate: rate(r.falseAlarms, r.blocked + r.warned) ?? 0 })}</span>` : ''}
            </div>` : ''}
            ${r.open > 0 && !isSecurityRule(r.id) ? `<div class="rule-stat-sub text-amber">${t('insights.ruleOpen', { count: r.open })}</div>` : ''}
          </div>`;
}

function relTime(ts: string, now: number): string {
  const ms = Date.parse(ts);
  if (Number.isNaN(ms)) return '—';
  const min = Math.max(0, Math.floor((now - ms) / 60000));
  if (min < 1) return t('insights.agoNow');
  if (min < 60) return t('insights.agoMin', { n: min });
  if (min < 48 * 60) return t('insights.agoHour', { n: Math.floor(min / 60) });
  return t('insights.agoDay', { n: Math.floor(min / 1440) });
}

const STATUS_VIEW: Record<string, { key: string; cls: string }> = {
  BLOCKED: { key: 'statusBlocked', cls: 'badge-blocked' },
  WARNING: { key: 'statusWarning', cls: 'badge-warning' },
  RECOVERED: { key: 'statusRecovered', cls: 'badge-allowed' },
  SHADOW_TRIGGER: { key: 'statusShadow', cls: 'badge-purple' }
};

/** Drops the "Label (RULE_ID): " / "[RULE_ID]: " prefix and emoji the engine puts in front of a reason. */
function cleanReason(reason: string): string {
  return reason
    .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]️?/gu, '')
    .replace(/^\s*\[?[A-Z0-9_]{3,}\]?\s*:\s*/, '')
    .replace(/^\s*[^:()]{0,80}\(\s*[A-Z0-9_]{3,}\s*\)\s*:\s*/, '')
    .trim();
}

function drillEvent(e: AuditEventLite, now: number): string {
  const st = STATUS_VIEW[e.status] || { key: '', cls: 'badge-neutral' };
  const statusText = st.key ? t(`insights.${st.key}`) : escapeHtml(e.status || '—');
  const sess = e.conversationId && e.conversationId !== 'default' ? e.conversationId.replace(/^[a-z][\w-]*:/i, '').slice(0, 6) : '';
  const base = e.target ? e.target.split(/[\\/]/).filter(Boolean).pop() || e.target : '';
  const reason = cleanReason(e.reason || '');
  const shortReason = reason.length > 110 ? reason.slice(0, 109) + '…' : reason;
  const canMark = !!e.eventId && e.status !== 'RECOVERED';
  const markBtn = !canMark ? '' : e.falseAlarm
    ? `<button class="mini-btn ins-fa-btn" data-action="markFalseAlarm" data-id="${escapeHtml(e.eventId)}" data-rule="${escapeHtml(e.ruleId)}" data-undo="1">${lucide('rotateCcw', { size: 9 })} ${t('insights.undoFalseAlarm')}</button>`
    : `<button class="mini-btn ins-fa-btn" data-action="markFalseAlarm" data-id="${escapeHtml(e.eventId)}" data-rule="${escapeHtml(e.ruleId)}">${lucide('x', { size: 9 })} ${t('insights.markFalseAlarm')}</button>`;
  return `
              <div class="ins-ev${e.falseAlarm ? ' ins-ev-fa' : ''}">
                <div class="ins-ev-top">
                  <span class="ins-ev-meta">
                    <span class="status-badge ${st.cls} ins-ev-status">${statusText}</span>
                    <span title="${escapeHtml(e.timestamp)}">${relTime(e.timestamp, now)}</span>
                    <span class="ins-dot">·</span><span class="ins-ev-agent">${escapeHtml(e.agent || '—')}</span>
                    ${sess ? `<span class="ins-sess" title="${escapeHtml(e.conversationId)}">#${escapeHtml(sess)}</span>` : ''}
                    ${e.evasionSuspect ? `<span class="ins-sig ins-sig-evasion">${t('insights.evasionTag')}</span>` : ''}
                    ${e.falseAlarm ? `<span class="ins-sig ins-sig-fa">${t('insights.falseAlarmLabel')}</span>` : ''}
                  </span>
                  ${markBtn}
                </div>
                ${base ? `<div class="ins-ev-file" title="${escapeHtml(e.target)}">${escapeHtml(base)}</div>` : ''}
                ${shortReason ? `<div class="ins-ev-reason"${shortReason !== reason ? ` title="${escapeHtml(reason)}"` : ''}>${escapeHtml(shortReason)}</div>` : ''}
              </div>`;
}

// The event list does not depend on the window, so it is rendered once per rule as a <template>;
// the client copies it into the open row (data-drill-slot). Inlining it per window made the tab ~0.5 MB.
function ruleItem(r: RuleRow): string {
  const rk = escapeHtml(ruleKey(r.id));
  return `
        <div class="rule-stat-item ins-rule" data-rk="${rk}">
          ${ruleHead(r, false, true)}
          ${ruleHead(r, true, true)}
          <div class="ins-drill" data-drill-slot="${rk}"></div>
        </div>`;
}

function drillTemplates(ids: string[], recentByRule: Record<string, AuditEventLite[]>, now: number): string {
  return ids.map(id => {
    const list = (recentByRule[id] || []).slice(0, DRILL_EVENTS);
    return `<template data-drill-src="${escapeHtml(ruleKey(id))}">
            <div class="ins-drill-title">${t('insights.drillTitle')}</div>
            ${list.length ? list.map(e => drillEvent(e, now)).join('') : `<div class="insight-sub">${t('insights.drillEmpty')}</div>`}
          </template>`;
  }).join('');
}

function rowsFromWindow(w: WindowStats, openByRule: Record<string, number>): RuleRow[] {
  return Object.entries(w.rules).map(([id, s]) => ({
    id,
    blocked: s.blocked,
    repeated: s.repeated,
    warned: s.warned,
    shadow: s.shadow,
    recovered: s.recovered,
    evasion: s.evasion,
    falseAlarms: s.falseAlarms,
    open: openByRule[id] || 0,
    med: null
  })).filter(r => events(r) + r.recovered > 0);
}

function sortRows(rows: RuleRow[]): RuleRow[] {
  return rows.sort((a, b) => (b.blocked + b.warned) - (a.blocked + a.warned) || events(b) - events(a) || a.id.localeCompare(b.id));
}

function fmtDay(day: string): string {
  const [, m, d] = day.split('-');
  if (!m || !d) return day;
  return getCurrentLanguage() === 'tr' ? `${d}.${m}` : `${m}/${d}`;
}

function summaryCard(w: WindowStats, totalOpen: number, stats: AuditStats): string {
  const code = Object.entries(w.rules).filter(([id]) => !isSecurityRule(id));
  const blocked = code.reduce((s, [, r]) => s + r.blocked, 0);
  const fixed = code.reduce((s, [, r]) => s + Math.min(r.recovered, r.blocked), 0);
  const fixRate = rate(fixed, blocked);
  const sub = blocked === 0 ? t('insights.subClean')
    : blocked < LOW_DATA_EVENTS ? t('insights.subSample', { recovered: fixed, blocked })
      : t('insights.subRate', { recovered: fixed, blocked });
  const sig = (n: number, of: number) => `<span class="ins-sig-val">${n}</span>${n > 0 && of > 0 ? `<span class="text-muted"> · ${pct(rate(n, of) ?? 0)}</span>` : ''}`;
  const range = stats.firstTs && stats.lastTs
    ? t('insights.journalRange', { count: stats.totalRecords, from: fmtDay(stats.firstTs.slice(0, 10)), to: fmtDay(stats.lastTs.slice(0, 10)) })
    : '';
  return `
      <div class="insight-card">
        <div class="insight-title"><span class="icon-inline">${lucide('target', { size: 12 })}</span> ${t('insights.recoveryTitle')}</div>
        <div class="recovery-meter">
          <div class="recovery-bar-wrap"><div class="recovery-bar" style="width: ${fixRate ?? 0}%;"></div></div>
          <div class="recovery-score">${fixRate === null ? '—' : `${fixRate}%`}</div>
        </div>
        <div class="insight-sub">${sub}</div>
        <div class="ins-stats">
          <div class="ins-stat"><div class="ins-stat-val">${w.operations}</div><div class="ins-stat-lbl">${t('insights.statOps')}</div></div>
          <div class="ins-stat"><div class="ins-stat-val text-red">${w.blocked}</div><div class="ins-stat-lbl">${t('insights.statBlocked')}</div></div>
          <div class="ins-stat"><div class="ins-stat-val text-amber">${w.warned}</div><div class="ins-stat-lbl">${t('insights.statWarned')}</div></div>
          <div class="ins-stat"><div class="ins-stat-val text-green">${w.recovered}</div><div class="ins-stat-lbl">${t('insights.statRecovered')}</div></div>
        </div>
        <div class="metric-row"><span class="metric-lbl">${t('insights.evasionLabel')}</span><span class="metric-val">${sig(w.evasion, w.recovered)}</span></div>
        <div class="metric-row"><span class="metric-lbl">${t('insights.falseAlarmLabel')}</span><span class="metric-val">${sig(w.falseAlarms, w.blocked + w.warned)}</span></div>
        <div class="insight-sub text-muted ins-note">${t('insights.signalNote')}</div>
        ${totalOpen > 0 ? `<div class="insight-sub text-amber">${t('insights.openViolations', { count: totalOpen })}</div>` : ''}
        ${range ? `<div class="insight-sub text-muted">${range}</div>` : ''}
      </div>`;
}

function trendCard(daily: DayBucket[]): string {
  const days = daily || [];
  const peak = days.reduce((m, d) => Math.max(m, d.blocked + d.warned), 0);
  const totB = days.reduce((s, d) => s + d.blocked, 0);
  const totW = days.reduce((s, d) => s + d.warned, 0);
  let body: string;
  if (!days.length || peak === 0) {
    body = `<div class="insight-sub">${t('insights.trendEmpty')}</div>`;
  } else {
    const H = 40;
    const slot = 10;
    const bw = 7;
    const bars = days.map((d, i) => {
      const x = i * slot + (slot - bw) / 2;
      const hb = (d.blocked / peak) * H;
      const hw = (d.warned / peak) * H;
      const title = `<title>${escapeHtml(t('insights.trendDay', { day: fmtDay(d.day), blocked: d.blocked, warned: d.warned }))}</title>`;
      if (d.blocked + d.warned === 0) return `<g>${title}<rect class="ins-tr-zero" x="${x}" y="${H - 0.8}" width="${bw}" height="0.8"/></g>`;
      return `<g>${title}<rect class="ins-tr-warn" x="${x}" y="${(H - hb - hw).toFixed(2)}" width="${bw}" height="${hw.toFixed(2)}"/><rect class="ins-tr-block" x="${x}" y="${(H - hb).toFixed(2)}" width="${bw}" height="${hb.toFixed(2)}"/></g>`;
    }).join('');
    body = `
        <div class="ins-trend-head">
          <span class="ins-legend"><i class="ins-key ins-key-block"></i>${t('insights.statBlocked')} <b>${totB}</b></span>
          <span class="ins-legend"><i class="ins-key ins-key-warn"></i>${t('insights.statWarned')} <b>${totW}</b></span>
          <span class="ins-peak">${t('insights.trendMax', { n: peak })}</span>
        </div>
        <svg class="ins-trend" viewBox="0 0 ${days.length * slot} ${H}" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(t('insights.trendTitle'))}">
          <line class="ins-tr-grid" x1="0" y1="0.25" x2="${days.length * slot}" y2="0.25"/>
          ${bars}
        </svg>
        <div class="ins-trend-axis"><span>${fmtDay(days[0].day)}</span><span>${t('insights.trendToday')}</span></div>`;
  }
  return `
      <div class="insight-card">
        <div class="insight-title"><span class="icon-inline">${lucide('barChart', { size: 12 })}</span> ${t('insights.trendTitle')}</div>
        ${body}
      </div>`;
}

function agentsCard(w: WindowStats): string {
  const agents = Object.values(w.agents)
    .filter(a => a.operations + a.blocked + a.warned > 0)
    .sort((a, b) => (b.blocked + b.warned) - (a.blocked + a.warned) || b.operations - a.operations);
  if (!agents.length) {
    return `
      <div class="insight-card">
        <div class="insight-title"><span class="icon-inline">${lucide('bot', { size: 12 })}</span> ${t('insights.agentsTitle')}</div>
        <div class="insight-sub">${t('insights.agentsEmpty')}</div>
      </div>`;
  }
  const rows = agents.map(a => {
    const clean = rate(a.cleanFirstTry, a.operations);
    const perSession = a.conversations > 0 ? ((a.blocked + a.warned) / a.conversations).toFixed(1) : null;
    return `
          <tr>
            <td class="ins-agent"><div class="ins-agent-name" title="${escapeHtml(a.agent)}">${escapeHtml(a.agent)}</div><div class="ins-agent-sub">${t('insights.sessions', { count: a.conversations })}</div></td>
            <td>${a.operations}</td>
            <td class="${clean === null ? 'text-muted' : 'text-green'}">${clean === null ? '—' : pct(clean)}</td>
            <td class="${a.blocked ? 'text-red' : 'text-muted'}">${a.blocked}</td>
            <td class="${a.warned ? 'text-amber' : 'text-muted'}">${a.warned}</td>
            <td class="ins-strong">${perSession === null ? '—' : (getCurrentLanguage() === 'tr' ? perSession.replace('.', ',') : perSession)}</td>
          </tr>`;
  }).join('');
  return `
      <div class="insight-card">
        <div class="insight-title"><span class="icon-inline">${lucide('bot', { size: 12 })}</span> ${t('insights.agentsTitle')}</div>
        <table class="ins-agents">
          <thead><tr>
            <th>${t('insights.colAgent')}</th>
            <th>${t('insights.colOps')}</th>
            <th title="${escapeHtml(t('insights.colCleanHint'))}">${t('insights.colClean')}</th>
            <th>${t('insights.colBlocked')}</th>
            <th>${t('insights.colWarned')}</th>
            <th title="${escapeHtml(t('insights.colPerSessionHint'))}">${t('insights.colPerSession')}</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
        ${briefingLine(w)}
      </div>`;
}

function briefingLine(w: WindowStats): string {
  const b = w.briefing;
  if (!b) return '';
  const briefed = rate(b.briefed.clean, b.briefed.writes);
  const unbriefed = rate(b.unbriefed.clean, b.unbriefed.writes);
  if (briefed === null || unbriefed === null) return '';
  const hint = t('insights.briefingCompareHint', { bs: b.briefed.sessions, us: b.unbriefed.sessions });
  return `<div class="insight-sub" title="${escapeHtml(hint)}">${t('insights.briefingCompare', { briefed: pct(briefed), unbriefed: pct(unbriefed) })}</div>`;
}

function rulesCard(rows: RuleRow[]): string {
  const main = rows.filter(r => events(r) >= LOW_DATA_EVENTS);
  const low = rows.filter(r => events(r) < LOW_DATA_EVENTS);
  const lowGroup = low.length === 0 ? '' : `
        <div class="ins-low">
          <div class="ins-low-head ins-low-closed" data-action="selectSegment" data-group="lowdata" data-value="open" role="button" tabindex="0">
            <span class="ins-chev">${lucide('chevronRight', { size: 10 })}</span>${t('insights.lowDataGroup', { count: low.length })}
          </div>
          <div class="ins-low-head ins-low-open" data-action="selectSegment" data-group="lowdata" data-value="closed" role="button" tabindex="0">
            <span class="ins-chev">${lucide('chevronRight', { size: 10 })}</span>${t('insights.lowDataGroup', { count: low.length })}
          </div>
          <div class="ins-low-body">${low.map(r => ruleItem(r)).join('')}</div>
        </div>`;
  return `
      <div class="insight-card">
        <div class="insight-title"><span class="icon-inline">${lucide('shieldCheck', { size: 12 })}</span> ${t('insights.reportCardTitle')}</div>
        ${rows.length === 0 ? `<div class="insight-sub">${t('insights.rulesEmpty')}</div>` : ''}
        ${main.map(r => ruleItem(r)).join('')}
        ${lowGroup}
      </div>`;
}

/** Per-rule selectors that open exactly the rule stored in <body data-sel-rule>; survives innerHTML refreshes. */
function drillStyles(keys: string[]): string {
  if (!keys.length) return '';
  const sel = (suffix: string) => keys.map(k => `body[data-sel-rule="${k}"] .ins-rule[data-rk="${k}"] > ${suffix}`).join(',');
  return `<style>${sel('.ins-rh-closed')}{display:none}${sel('.ins-rh-open')}{display:block}${sel('.ins-drill')}{display:block}</style>`;
}

function windowSelector(): string {
  return `
      <div class="ins-seg" role="tablist" aria-label="${escapeHtml(t('insights.windowAria'))}">
        ${WINDOWS.map(k => `<button class="ins-seg-btn" data-action="selectSegment" data-group="window" data-value="${k}" role="tab">${t(`insights.${WINDOW_LABEL[k]}`)}</button>`).join('')}
      </div>`;
}

/** Windows with identical numbers share one rendered block (e.g. 7d/30d/all on a young journal). */
function groupWindows(stats: AuditStats): { keys: WindowKey[]; w: WindowStats }[] {
  const groups: { keys: WindowKey[]; w: WindowStats; sig: string }[] = [];
  for (const k of WINDOWS) {
    const w = stats.windows[k];
    if (!w) continue;
    const sig = JSON.stringify(w);
    const g = groups.find(x => x.sig === sig);
    if (g) g.keys.push(k); else groups.push({ keys: [k], w, sig });
  }
  return groups;
}

function legacyCards(vm: GuardianViewModel, openByRule: Record<string, number>, totalOpen: number): string {
  const { data, eventsList } = vm;
  const eff = (data as any)?.effectiveness || {};
  const ruleStats: Record<string, any> = eff.ruleStats || {};
  const codeStats = Object.entries(ruleStats).filter(([rule]) => !isSecurityRule(rule)).map(([, stat]) => stat as any);
  // Only engine-correlated recovery evidence counts; sharing a path is insufficient.
  const blockedFromEvents = eventsList.filter(e => e.outcome === 'BLOCKED' && !isSecurityRule(e.ruleId || '')).length;
  const recoveredFromEvents = eventsList.filter(e => e.outcome === 'RECOVERED' && e.resolvedRuleId && !isSecurityRule(e.resolvedRuleId)).length;
  const totalBlocked = typeof eff.totalCodeBlocked === 'number' ? eff.totalCodeBlocked : (codeStats.length ? codeStats.reduce((s, x) => s + (x.blocked || 0), 0) : blockedFromEvents);
  const totalRecovered = typeof eff.totalCodeRecovered === 'number' ? eff.totalCodeRecovered : (codeStats.length ? codeStats.reduce((s, x) => s + Math.min(x.recovered || 0, x.blocked || 0), 0) : recoveredFromEvents);
  // No blocked operations means no rate, not a perfect one.
  const finalRate: number | null = totalBlocked === 0 ? null
    : (typeof eff.codeFixRate === 'number' ? eff.codeFixRate : Math.min(100, Math.round(totalRecovered / totalBlocked * 100)));
  const sub = totalBlocked === 0 ? t('insights.subClean')
    : totalBlocked < LOW_DATA_EVENTS ? t('insights.subSample', { recovered: totalRecovered, blocked: totalBlocked })
      : t('insights.subRate', { recovered: totalRecovered, blocked: totalBlocked });

  const known = ['G0_SECRET_LEAK', 'G1_SILENT_EXCEPTION', 'G2_TEST_INTEGRITY', 'SRP_BOUNDARY', 'ARCH_FILE_GROWTH', 'G3_COMPILER_BYPASS'];
  // Recovered-only keys (e.g. T1_PENDING) have no blocked operation to score.
  const ids = [...known, ...Object.keys(ruleStats).filter(k => !known.includes(k) && ruleStats[k]?.blocked > 0)];
  const rows: RuleRow[] = ids.map(id => {
    const s = ruleStats[id] || {};
    // A median needs recorded attempts; the engine used to default it to 1.
    const med = Array.isArray(s.attempts) && s.attempts.length > 0 && typeof s.medianAttempts === 'number' && !isSecurityRule(id) ? s.medianAttempts : null;
    return { id, blocked: s.blocked || 0, repeated: 0, warned: 0, shadow: 0, recovered: s.recovered || 0, evasion: 0, falseAlarms: 0, open: openByRule[id] || 0, med };
  });
  const active = rows.filter(r => r.blocked > 0).sort((a, b) => b.blocked - a.blocked);
  const clean = rows.filter(r => r.blocked === 0);
  return `
      <div class="insight-card">
        <div class="insight-title"><span class="icon-inline">${lucide('target', { size: 12 })}</span> ${t('insights.recoveryTitle')}</div>
        <div class="recovery-meter">
          <div class="recovery-bar-wrap"><div class="recovery-bar" style="width: ${finalRate ?? 0}%;"></div></div>
          <div class="recovery-score">${finalRate === null ? '—' : `${finalRate}%`}</div>
        </div>
        <div class="insight-sub">${sub}</div>
        ${totalOpen > 0 ? `<div class="insight-sub text-amber">${t('insights.openViolations', { count: totalOpen })}</div>` : ''}
        <div class="insight-sub text-muted">${t('insights.scopeNote')}</div>
      </div>

      <div class="insight-card">
        <div class="insight-title"><span class="icon-inline">${lucide('shieldCheck', { size: 12 })}</span> ${t('insights.reportCardTitle')}</div>
        ${active.map(r => `<div class="rule-stat-item">${ruleHead(r, false, false)}</div>`).join('')}
        ${clean.length > 0 ? `<div class="rule-stat-sub text-muted rule-clean-summary">${t('insights.cleanRules', { count: clean.length, names: clean.map(r => escapeHtml(ruleLabel(r.id))).join(', ') })}</div>` : ''}
      </div>`;
}

// Template-literal indentation is ~20 % of the markup; it is resent on every refresh.
const collapseIndent = (html: string): string => html.replace(/\n[ \t]+/g, '\n');

export function renderInsightsTab(vm: GuardianViewModel): string {
  const { data, pendingTests, pendingDocs, projectCfg, stopRetries, sessionId } = vm;
  const testKeys = Object.keys(pendingTests);
  const docKeys = Object.keys(pendingDocs);
  const docGovActive = projectCfg?.governance?.enforceDocObligations === true;
  const now = Date.now();

  // Blocked operations the agent has not fixed yet, per rule.
  const openByRule: Record<string, number> = {};
  const activeViolations = (data as any)?.activeViolations;
  if (activeViolations && typeof activeViolations === 'object') {
    for (const v of Object.values(activeViolations) as any[]) {
      if (v?.ruleId) openByRule[v.ruleId] = (openByRule[v.ruleId] || 0) + 1;
    }
  }
  const totalOpen = Object.entries(openByRule).filter(([rule]) => !isSecurityRule(rule)).reduce((sum, [, n]) => sum + n, 0);

  const stats = vm.auditStats;
  let mainHtml: string;
  if (stats && stats.available && stats.windows) {
    const groups = groupWindows(stats);
    const allKeys = new Set<string>();
    const allIds = new Set<string>();
    const blocks = groups.map(g => {
      const rows = sortRows(rowsFromWindow(g.w, openByRule));
      rows.forEach(r => { allKeys.add(ruleKey(r.id)); allIds.add(r.id); });
      const cls = g.keys.map(k => `ins-win-${k}`).join(' ');
      return {
        top: `<div class="ins-win ${cls}">${summaryCard(g.w, totalOpen, stats)}</div>`,
        rest: `<div class="ins-win ${cls}">${agentsCard(g.w)}${rulesCard(rows)}</div>`
      };
    });
    mainHtml = `
      ${drillStyles([...allKeys])}
      ${windowSelector()}
      ${blocks.map(b => b.top).join('')}
      ${trendCard(stats.daily)}
      ${blocks.map(b => b.rest).join('')}
      ${drillTemplates([...allIds], stats.recentByRule || {}, now)}`;
  } else {
    mainHtml = legacyCards(vm, openByRule, totalOpen);
  }

  const shortSess = sessionId.length > 10 ? sessionId.slice(0, 8) + '…' : sessionId;
  const lastEvent = (data.events && data.events.length > 0) ? data.events[0] : null;
  const latencyMatch = lastEvent?.reason?.match(/\((\d+(\.\d+)?ms)\)/);
  const measuredLatency = latencyMatch ? latencyMatch[1] : null;
  const lastSeq = (data as any)?.lastAuditSeq || 0;

  const growthRuleCfg = projectCfg?.rules?.['ARCH_FILE_GROWTH'];
  const isGrowthShadow = (typeof growthRuleCfg === 'object' && growthRuleCfg?.mode === 'shadow') || growthRuleCfg === 'shadow';
  const g3RuleCfg = projectCfg?.rules?.['G3_COMPILER_BYPASS'];
  const isG3Shadow = (typeof g3RuleCfg === 'object' && g3RuleCfg?.mode === 'shadow') || g3RuleCfg === 'shadow';

  return collapseIndent(`
      ${mainHtml}

      <div class="insight-card">
        <div class="insight-title"><span class="icon-inline">${lucide('alertTriangle', { size: 12 })}</span> ${t('insights.lifecycleTitle')}</div>
        <div class="metric-row">
          <span class="metric-lbl">${t('insights.t1Label')}</span>
          <span class="metric-val text-cyan">${testKeys.length > 0 ? t('insights.t1Pending', { count: testKeys.length }) : t('insights.t1Verified')}</span>
        </div>
        <div class="metric-row">
          <span class="metric-lbl">${t('insights.docLabel')}</span>
          <span class="metric-val ${docGovActive ? 'text-green' : 'text-muted'}">${docGovActive ? (docKeys.length > 0 ? t('insights.docPending', { count: docKeys.length }) : t('insights.docActive')) : t('insights.docDisabled')}</span>
        </div>
        <div class="metric-row">
          <span class="metric-lbl">${t('insights.growthLabel')}</span>
          <span class="metric-val ${isGrowthShadow ? 'text-purple' : 'text-amber'}">${isGrowthShadow ? t('insights.growthValueShadow') : t('insights.growthValueWarn')}</span>
        </div>
        <div class="metric-row">
          <span class="metric-lbl">${t('insights.g3Label')}</span>
          <span class="metric-val ${isG3Shadow ? 'text-purple' : 'text-amber'}">${isG3Shadow ? t('insights.g3ValueShadow') : t('insights.g3Value')}</span>
        </div>
      </div>

      <details class="diagnostics-details">
        <summary class="diagnostics-summary">
          <span class="summary-left">
            <span class="icon-inline">${lucide('settings', { size: 11, color: 'var(--text-muted)' })}</span>
            <span class="diagnostics-title">${t('insights.diagnosticsTitle')}</span>
          </span>
          <span class="status-badge badge-neutral" style="font-size: 8px; padding: 1px 5px;">
            ${lucide('database', { size: 8 })} ${t('insights.diagnosticsBadge', { seq: lastSeq })}
          </span>
        </summary>
        <div class="diagnostics-body">
          <div class="insight-card" style="margin-top: 6px;">
            <div class="insight-title"><span class="icon-inline">${lucide('database', { size: 12 })}</span> ${t('insights.walTitle')}</div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.walJournalLabel')}</span>
              <span class="metric-val ${stats?.available ? 'text-green' : 'text-muted'}">${stats?.available ? t('insights.walJournalRecords', { count: stats.totalRecords }) : t('insights.walJournalEmpty')}</span>
            </div>
            ${stats?.available ? WINDOWS.map(k => `
            <div class="metric-row ins-win ins-win-${k}">
              <span class="metric-lbl">${t('insights.walWindowLabel')}</span>
              <span class="metric-val">${t('insights.walWindowValue', { ops: stats.windows[k]?.operations ?? 0, agents: Object.keys(stats.windows[k]?.agents || {}).length })}</span>
            </div>`).join('') : ''}
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.walLiveLabel')}</span>
              <span class="metric-val text-cyan">${t('insights.walLiveValue', { seq: lastSeq })}</span>
            </div>
          </div>

          <div class="insight-card">
            <div class="insight-title"><span class="icon-inline">${lucide('cpu', { size: 12 })}</span> ${t('insights.perfTitle')}</div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.latencyFast')}</span>
              <span class="metric-val ${measuredLatency ? 'text-green' : 'text-muted'}">${measuredLatency ? escapeHtml(measuredLatency) : t('insights.latencyUnknown')}</span>
            </div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.latencySpawn')}</span>
              <span class="metric-val text-muted">${t('insights.spawnBudget')}</span>
            </div>
          </div>

          <div class="insight-card">
            <div class="insight-title"><span class="icon-inline">${lucide('lock', { size: 12 })}</span> ${t('insights.integrityTitle')}</div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.sessionLabel')}</span>
              <span class="metric-val text-cyan">${escapeHtml(shortSess)}</span>
            </div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.circuitLabel')}</span>
              <span class="metric-val text-muted">${t('insights.circuitValue', { retries: stopRetries })}</span>
            </div>
          </div>
        </div>
      </details>
    `);
}
