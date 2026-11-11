import { ruleTitle } from '../../rule_catalog';
import { t, getCurrentLanguage } from '../../i18n';
import { lucide } from '../../icons';
import { escapeHtml } from '../html_utils';
import type { AuditEventLite, WindowStats } from '../../audit_stats';

export const DRILL_EVENTS = 6;

export const isSecurityRule = (rule: string) =>
  rule.startsWith('G0_') || ['POLICY_INTEGRITY', 'G2_SECURITY_TAMPERING', 'SHELL_SECURITY'].includes(rule);

/** One rule row, whichever source (audit journal or legacy effectiveness block) it came from. */
export interface RuleRow {
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

export const pct = (n: number) => t('insights.pct', { n });
export const rate = (part: number, whole: number): number | null => (whole > 0 ? Math.round((part / whole) * 100) : null);
export const ruleKey = (id: string) => id.replace(/[^A-Za-z0-9_-]/g, '_');

// One name per rule across tabs: the catalog is the only source.
export const ruleLabel = (id: string): string => ruleTitle(id);

export function events(r: RuleRow): number {
  return r.blocked + r.repeated + r.warned + r.shadow;
}

export function badgeFor(r: RuleRow): { text: string; cls: string; icon: string; n: number } {
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

export function ruleHead(r: RuleRow, open: boolean, clickable: boolean): string {
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

export function relTime(ts: string, now: number): string {
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
export function cleanReason(reason: string): string {
  return reason
    .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]️?/gu, '')
    .replace(/^\s*\[?[A-Z0-9_]{3,}\]?\s*:\s*/, '')
    .replace(/^\s*[^:()]{0,80}\(\s*[A-Z0-9_]{3,}\s*\)\s*:\s*/, '')
    .trim();
}

export function drillEvent(e: AuditEventLite, now: number): string {
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

export function ruleItem(r: RuleRow): string {
  const rk = escapeHtml(ruleKey(r.id));
  return `
        <div class="rule-stat-item ins-rule" data-rk="${rk}">
          ${ruleHead(r, false, true)}
          ${ruleHead(r, true, true)}
          <div class="ins-drill" data-drill-slot="${rk}"></div>
        </div>`;
}

export function drillTemplates(ids: string[], recentByRule: Record<string, AuditEventLite[]>, now: number): string {
  return ids.map(id => {
    const list = (recentByRule[id] || []).slice(0, DRILL_EVENTS);
    return `<template data-drill-src="${escapeHtml(ruleKey(id))}">
            <div class="ins-drill-title">${t('insights.drillTitle')}</div>
            ${list.length ? list.map(e => drillEvent(e, now)).join('') : `<div class="insight-sub">${t('insights.drillEmpty')}</div>`}
          </template>`;
  }).join('');
}

export function rowsFromWindow(w: WindowStats, openByRule: Record<string, number>): RuleRow[] {
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

export function sortRows(rows: RuleRow[]): RuleRow[] {
  return rows.sort((a, b) => (b.blocked + b.warned) - (a.blocked + a.warned) || events(b) - events(a) || a.id.localeCompare(b.id));
}

export function fmtDay(day: string): string {
  const [, m, d] = day.split('-');
  if (!m || !d) return day;
  return getCurrentLanguage() === 'tr' ? `${d}.${m}` : `${m}/${d}`;
}
