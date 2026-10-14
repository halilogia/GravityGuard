import * as path from 'path';
import { t } from '../../i18n';
import { lucide } from '../../icons';
import { escapeHtml } from '../html_utils';
import { GuardianViewModel } from '../types';

export function renderAgentBadge(agent: string | undefined, short: boolean): string {
  if (agent === 'Claude Code') {
    return `<span class="agent-pill agent-claude">🟠 ${short ? 'Claude' : 'Claude Code'}</span>`;
  }
  if (agent === 'Codex' || agent === 'OpenAI Codex') {
    return `<span class="agent-pill agent-codex">⚪ ${short ? 'Codex' : 'Codex'}</span>`;
  }
  if (agent === 'Antigravity CLI') {
    return `<span class="agent-pill agent-antigravity-cli">🟣 ${short ? 'CLI' : 'Antigravity CLI'}</span>`;
  }
  if (agent === 'Antigravity SDK') {
    return `<span class="agent-pill agent-antigravity-sdk">🟢 ${short ? 'SDK' : 'Antigravity SDK'}</span>`;
  }
  return `<span class="agent-pill agent-antigravity-ide">🔵 ${short ? 'IDE' : 'Antigravity IDE'}</span>`;
}

export function renderCurrentActionCard(vm: GuardianViewModel): string {
  // --- CURRENT ACTION CARD ---
  const latestEvent = vm.eventsList.length > 0 ? vm.eventsList[0] : null;
  let currentCardHtml = '';
  if (latestEvent) {
    const isBlk = latestEvent.status === 'BLOCKED';
    const isWrn = latestEvent.status === 'WARNING';
    const colorCls = isBlk ? 'border-blocked' : isWrn ? 'border-warning' : 'border-allowed';
    const badgeCls = isBlk ? 'badge-blocked' : isWrn ? 'badge-warning' : 'badge-allowed';
    const statusIcon = isBlk
      ? lucide('octagonX', { size: 10, color: 'var(--color-red)' })
      : isWrn
      ? lucide('alertTriangle', { size: 10, color: 'var(--color-amber)' })
      : lucide('checkCircle', { size: 10, color: 'var(--color-green)' });
    const statusText = isBlk
      ? t('current.statusBlocked')
      : isWrn
      ? t('current.statusWarning')
      : t('current.statusAllowed');
    const actionName = latestEvent.action || 'write_file';
    const targetName = latestEvent.target ? path.basename(latestEvent.target) : 'workspace';
    const ruleText = latestEvent.ruleId && latestEvent.ruleId !== 'PASS' ? latestEvent.ruleId : t('current.allGuardsPassed');
    const timeStr = latestEvent.timestamp ? (latestEvent.timestamp.split(' ')[1] || latestEvent.timestamp) : '';

    currentCardHtml = `
        <div class="current-card ${colorCls}">
          <div class="current-hdr">
            <span class="current-tag">${t('current.title')}</span>
            <span class="current-time">${timeStr}</span>
          </div>
          <div class="current-body">
            <div class="current-action-line">
              <span class="current-tool">${escapeHtml(actionName)}</span>
              <span class="current-target" title="${escapeHtml(latestEvent.target || '')}">${escapeHtml(targetName)}</span>
            </div>
            <div class="current-badge-row">
              <span class="status-badge ${badgeCls}">${statusIcon} ${statusText}</span>
              <span class="current-rule-badge">${escapeHtml(ruleText)}</span>
              ${renderAgentBadge(latestEvent.agent, false)}
            </div>
            ${latestEvent.reason ? `<div class="current-reason-text">${escapeHtml(latestEvent.reason)}</div>` : ''}
          </div>
        </div>
      `;
  } else {
    currentCardHtml = `
        <div class="current-card border-neutral">
          <div class="current-hdr">
            <span class="current-tag">${t('current.title')}</span>
          </div>
          <div class="current-idle">
            <span class="idle-inline">${lucide('zap', { size: 12, color: 'var(--text-muted)' })} ${t('current.idle')}</span>
          </div>
        </div>
      `;
  }
  return currentCardHtml;
}

export function renderLiveTab(vm: GuardianViewModel): string {
  const { eventsList } = vm;

  // --- TAB 1: LIVE STREAM (COMPACT ROWS WITH EXPANDABLE ACCORDION) ---
  let liveHtml = '';
  if (eventsList.length === 0) {
    liveHtml = `<div class="empty-state">${t('live.empty')}</div>`;
  } else {
    eventsList.forEach((e, idx) => {
      const isBlk = e.status === 'BLOCKED';
      const isWrn = e.status === 'WARNING';
      const isShd = e.status === 'SHADOW_TRIGGER' || e.outcome === 'SHADOW_OBSERVED';
      const isRec = e.outcome === 'RECOVERED';

      let badgeCls = 'badge-allowed';
      let statusLabel = t('current.statusAllowed');
      let statusIcon = lucide('checkCircle', { size: 10, color: 'var(--color-green)' });
      if (isShd) {
        badgeCls = 'badge-purple';
        statusLabel = t('current.statusShadow');
        statusIcon = lucide('eye', { size: 10, color: 'var(--color-purple)' });
      } else if (isRec) {
        badgeCls = 'badge-cyan';
        statusLabel = t('current.statusRecovered');
        statusIcon = lucide('rotateCw', { size: 10, color: 'var(--color-cyan)' });
      } else if (isBlk) {
        badgeCls = 'badge-blocked';
        statusLabel = t('current.statusBlocked');
        statusIcon = lucide('octagonX', { size: 10, color: 'var(--color-red)' });
      } else if (isWrn) {
        badgeCls = 'badge-warning';
        statusLabel = t('current.statusWarning');
        statusIcon = lucide('alertTriangle', { size: 10, color: 'var(--color-amber)' });
      }

      const fileName = e.target ? path.basename(e.target) : (e.action || 'system');
      const timeStr = e.timestamp ? (e.timestamp.split(' ')[1] || e.timestamp) : '';
      const ruleId = e.ruleId || 'PASS';
      const fullTargetEsc = escapeHtml(e.target || '');
      const reasonEsc = escapeHtml(e.reason || '');

      liveHtml += `
          <div class="stream-item">
            <div class="stream-row" data-action="toggleDetail" data-target="evt-${idx}">
              <div class="stream-left">
                <span class="status-badge ${badgeCls}">${statusIcon} ${statusLabel}</span>
                ${renderAgentBadge(e.agent, true)}
                <span class="stream-file" title="${fullTargetEsc}">${escapeHtml(fileName)}</span>
              </div>
              <div class="stream-right">
                <span class="stream-rule">${escapeHtml(ruleId)}</span>
                <span class="stream-time">${timeStr}</span>
              </div>
            </div>
            <div id="evt-${idx}" class="stream-drawer" style="display: none;">
              <div class="drawer-header">
                <span class="drawer-rule">${escapeHtml(ruleId)}</span>
                <span class="status-badge ${badgeCls}">${statusIcon} ${statusLabel}</span>
              </div>
              ${isRec ? `
                <div class="drawer-meta-pill bg-cyan">
                  <div class="recovery-flow-row" style="margin-bottom: 3px;">
                    <span class="status-badge badge-blocked" style="font-size: 8px; padding: 1px 5px;">${t('live.recoveryFlowBlocked')}</span>
                    <span style="color: var(--color-cyan); display: inline-flex; align-items: center;">${lucide('arrowRight', { size: 9 })}</span>
                    <span class="status-badge badge-allowed" style="font-size: 8px; padding: 1px 5px;">${t('live.recoveryFlowRecovered')}</span>
                    <strong style="margin-left: 4px; color: var(--text-main); font-size: 10px;">${escapeHtml(e.resolvedRuleId || e.ruleId || 'Rule')}</strong>
                  </div>
                  <div class="recovery-meta-sub" style="font-size: 9px; color: var(--text-muted);">
                    <span>${t('live.recoveryAttempts', { attempts: e.recoveryAttempts || 1 })}</span>
                    ${e.resolutionMs ? `<span> • ${t('live.recoveryDuration', { duration: (e.resolutionMs / 1000).toFixed(1) })}</span>` : ''}
                  </div>
                </div>
              ` : ''}
              ${isShd ? `
                <div class="drawer-meta-pill bg-purple">
                  <span class="pill-row">${lucide('eye', { size: 11 })} <span>${t('live.shadowDesc')}</span></span>
                </div>
              ` : ''}
              ${e.target ? `<div class="drawer-target" title="${fullTargetEsc}"><span class="icon-inline">${lucide('folder', { size: 11, color: 'var(--text-muted)' })}</span> ${fullTargetEsc}</div>` : ''}
              ${e.reason ? `<div class="drawer-reason">${reasonEsc}</div>` : ''}
              <div class="drawer-buttons">
                ${e.target ? `<button class="action-btn" data-action="openFile" data-path="${fullTargetEsc}">${lucide('fileText', { size: 11 })} ${t('current.openFile')}</button>` : ''}
                ${e.reason ? `<button class="action-btn" data-action="copyReason" data-text="${reasonEsc}">${lucide('copy', { size: 11 })} ${t('current.copyReason')}</button>` : ''}
              </div>
            </div>
          </div>
        `;
    });
  }
  return liveHtml;
}
