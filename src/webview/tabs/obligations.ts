import * as path from 'path';
import { t } from '../../i18n';
import { lucide } from '../../icons';
import { escapeHtml } from '../html_utils';
import { GuardianViewModel } from '../types';
import { renderAgentBadge } from './live';

/** Agent badge + project tag + formatted timestamp row for an obligation record */
function renderObligationMeta(item: any, filePath: string): string {
  // 1. Agent attribution
  let agent = typeof item?.agent === 'string' ? item.agent.trim() : '';
  if (!agent) {
    const rawSession = String(item?.session_id || item?.conversationId || '').toLowerCase();
    if (rawSession.includes('claude')) {
      agent = 'Claude Code';
    } else if (rawSession.includes('codex')) {
      agent = 'Codex';
    } else if (rawSession.includes('opencode')) {
      agent = 'OpenCode';
    } else if (rawSession.includes('aider')) {
      agent = 'Aider';
    } else if (rawSession.includes('freebuff')) {
      agent = 'Freebuff';
    } else if (rawSession.includes('cli') || rawSession.includes('agy-cli')) {
      agent = 'Antigravity CLI';
    } else if (rawSession.includes('sdk') || rawSession.includes('agy-sdk')) {
      agent = 'Antigravity SDK';
    } else {
      agent = 'Antigravity IDE';
    }
  }
  const agentBadgeHtml = renderAgentBadge(agent, true);

  // 2. Project attribution (e.g. AgentObservatory, LifeOS, GravityGuard, AudioCleaner)
  let projectBadgeHtml = '';
  const norm = (filePath || '').replace(/\\/g, '/');
  const projMatch = norm.match(/(?:Desktop\/GitHub\/(?:Public|Private)\/([^/]+)|Desktop\/([^/]+))/i);
  const projName = projMatch ? (projMatch[1] || projMatch[2]) : '';
  if (projName) {
    projectBadgeHtml = `<span class="status-badge" style="background: rgba(99, 102, 241, 0.15); border: 1px solid rgba(99, 102, 241, 0.4); color: #a5b4fc; font-size: 8px; padding: 1px 6px;"><span class="icon-inline">${lucide('folder', { size: 9 })}</span> ${escapeHtml(projName)}</span>`;
  }

  // 3. Human-readable timestamp
  const rawTime = item?.created_at ?? item?.timestamp;
  let formattedTime = '';
  if (typeof rawTime === 'number') {
    const d = new Date(rawTime < 1e11 ? rawTime * 1000 : rawTime);
    const day = String(d.getDate()).padStart(2, '0');
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const hours = String(d.getHours()).padStart(2, '0');
    const minutes = String(d.getMinutes()).padStart(2, '0');
    formattedTime = `${day}.${month} ${hours}:${minutes}`;
  } else if (typeof rawTime === 'string') {
    formattedTime = rawTime.includes('T') ? rawTime.split('T')[1].slice(0, 5) : rawTime;
  }

  const timeHtml = formattedTime
    ? `<span style="font-size: 8px; color: var(--text-muted); margin-left: auto;"><span class="icon-inline">${lucide('clock', { size: 9 })}</span> ${escapeHtml(formattedTime)}</span>`
    : '';

  return `<div class="task-meta" style="display: flex; gap: 6px; align-items: center; margin: 4px 0 6px 0; flex-wrap: wrap;">${agentBadgeHtml}${projectBadgeHtml}${timeHtml}</div>`;
}

export function renderObligationsTab(vm: GuardianViewModel): string {
  const { pendingTests, pendingDocs, resolutionIntents, stopRetries } = vm;

  // --- TAB 2: OBLIGATIONS (ACTIONABLE TASKS + 4-STEP STATE MACHINE TRACK) ---
  let obligationsHtml = '';
  const testKeys = Object.keys(pendingTests);
  const docKeys = Object.keys(pendingDocs);

  // Stop guard: shown while the agent still has unresolved obligations / retries
  const stopGuardHtml = (stopRetries > 0 || testKeys.length > 0 || docKeys.length > 0)
    ? `
        <div class="task-card border-amber">
          <div class="task-header">
            <span class="task-title text-amber"><span class="icon-inline">${lucide('shield', { size: 12 })}</span> ${t('obligations.stopGuardTitle')}</span>
          </div>
          <div class="task-meta">${t('obligations.stopGuardDesc')}</div>
        </div>
      `
    : '';

  if (testKeys.length === 0 && docKeys.length === 0) {
    obligationsHtml = stopGuardHtml + `
        <div class="clean-state-box">
          ${lucide('sparkles', { size: 28, color: '#10b981', strokeWidth: 1.75 })}
          <div class="clean-state-title">${t('obligations.cleanState')}</div>
        </div>
      `;
  } else {
    obligationsHtml += stopGuardHtml;
    if (testKeys.length > 0) {
      obligationsHtml += `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
          <div class="section-title text-cyan" style="margin: 0;"><span class="icon-inline">${lucide('flaskConical', { size: 12 })}</span> ${t('obligations.testTitle')} (${testKeys.length})</div>
          <button class="mini-btn" data-action="clearAllObligations" style="font-size: 8.5px; padding: 2px 7px;">${lucide('trash2', { size: 9 })} Tümünü Temizle</button>
        </div>
      `;
      for (const tk of testKeys) {
        const item = pendingTests[tk];
        const hasIntent = resolutionIntents.some(intent => intent.target_path && intent.target_path.toLowerCase().includes(path.basename(tk).toLowerCase()));
        const step1Class = !hasIntent ? 'step-active' : 'step-done';
        const step2Class = hasIntent ? 'step-active' : 'step-todo';
        const fileName = path.basename(tk);
        const normPath = tk.replace(/\\/g, '/');
        let relDisplay = normPath;
        const projIdx = normPath.lastIndexOf(fileName);
        if (projIdx > 0) {
          const dir = normPath.substring(0, projIdx);
          const parts = dir.split('/').filter(Boolean);
          relDisplay = parts.slice(-3).join('/') + '/' + fileName;
        }

        obligationsHtml += `
            <div class="task-card border-cyan">
              <div class="task-header" style="align-items: flex-start;">
                <div style="overflow: hidden; flex: 1;">
                  <span class="task-title" title="${escapeHtml(tk)}">${escapeHtml(fileName)}</span>
                  <div style="font-size: 9px; color: var(--text-muted); font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-top: 2px;">${escapeHtml(relDisplay)}</div>
                </div>
                <div style="display: flex; gap: 4px; align-items: center;">
                  <button class="mini-icon-btn" data-action="dismissObligation" data-path="${escapeHtml(tk)}" title="Bu yükümlülüğü kaldır/temizle">${lucide('check', { size: 12, color: 'var(--color-green)' })}</button>
                  <button class="mini-icon-btn" data-action="openFile" data-path="${escapeHtml(tk)}" title="${t('current.openFile')}">${lucide('fileText', { size: 12 })}</button>
                </div>
              </div>
              ${renderObligationMeta(item, tk)}
              <div class="task-meta">${t('obligations.expectedTest')}: <code class="text-cyan">${escapeHtml(item.expected_name || 'test')}</code></div>
              ${item.reason ? `<div class="obligation-reason" style="font-size: 10px; color: var(--text-muted); margin: 6px 0; background: rgba(0,0,0,0.18); padding: 5px 8px; border-radius: 4px; border-left: 2px solid var(--color-cyan); line-height: 1.4;">${escapeHtml(item.reason)}</div>` : ''}
              <div class="state-track">
                <div class="track-step ${step1Class}">${t('obligations.stepPending')}</div>
                <div class="track-arrow">${lucide('arrowRight', { size: 9 })}</div>
                <div class="track-step ${step2Class}">${t('obligations.stepIntent')}</div>
                <div class="track-arrow">${lucide('arrowRight', { size: 9 })}</div>
                <div class="track-step step-todo">${t('obligations.stepVerified')}</div>
                <div class="track-arrow">${lucide('arrowRight', { size: 9 })}</div>
                <div class="track-step step-todo">${t('obligations.stepResolved')}</div>
              </div>
              <div class="track-status-hint"><span class="icon-inline">${lucide('clock', { size: 10 })}</span> ${hasIntent ? t('obligations.hintTestIntent') : t('obligations.hintTestPending')}</div>
            </div>
          `;
      }
    }

    if (docKeys.length > 0) {
      obligationsHtml += `<div class="section-title text-amber" style="margin-top: 14px;"><span class="icon-inline">${lucide('fileText', { size: 12 })}</span> ${t('obligations.docTitle')} (${docKeys.length})</div>`;
      for (const dk of docKeys) {
        const item = pendingDocs[dk];
        const reqs = (item.required_docs || ['CHANGELOG.md']).join(', ');
        const primaryDoc = (item.required_docs && item.required_docs[0]) || 'CHANGELOG.md';
        const hasIntent = resolutionIntents.some(intent => intent.target_path && intent.target_path.toLowerCase().includes('changelog'));
        const step1Class = !hasIntent ? 'step-active' : 'step-done';
        const step2Class = hasIntent ? 'step-active' : 'step-todo';
        const fileName = path.basename(dk);
        const normPath = dk.replace(/\\/g, '/');
        let relDisplay = normPath;
        const projIdx = normPath.lastIndexOf(fileName);
        if (projIdx > 0) {
          const dir = normPath.substring(0, projIdx);
          const parts = dir.split('/').filter(Boolean);
          relDisplay = parts.slice(-3).join('/') + '/' + fileName;
        }

        obligationsHtml += `
            <div class="task-card border-amber">
              <div class="task-header" style="align-items: flex-start;">
                <div style="overflow: hidden; flex: 1;">
                  <span class="task-title" title="${escapeHtml(dk)}">${escapeHtml(fileName)}</span>
                  <div style="font-size: 9px; color: var(--text-muted); font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-top: 2px;">${escapeHtml(relDisplay)}</div>
                </div>
                <div style="display: flex; gap: 4px; align-items: center;">
                  <button class="mini-icon-btn" data-action="dismissObligation" data-path="${escapeHtml(dk)}" title="Bu yükümlülüğü kaldır/temizle">${lucide('check', { size: 12, color: 'var(--color-green)' })}</button>
                  <button class="mini-icon-btn" data-action="openFile" data-path="${escapeHtml(dk)}" title="${t('current.openFile')}">${lucide('fileText', { size: 12 })}</button>
                </div>
              </div>
              ${renderObligationMeta(item, dk)}
              <div class="task-meta" style="display: flex; justify-content: space-between; align-items: center;">
                <span>${t('obligations.requiredDoc')}: <code class="text-amber">${escapeHtml(reqs)}</code></span>
                <button class="mini-btn" data-action="openFile" data-path="${escapeHtml(primaryDoc)}" style="font-size: 9px; padding: 1px 6px;">${lucide('fileText', { size: 9 })} ${escapeHtml(primaryDoc)} Aç</button>
              </div>
              ${item.reason ? `<div class="obligation-reason" style="font-size: 10px; color: var(--text-muted); margin: 6px 0; background: rgba(0,0,0,0.18); padding: 5px 8px; border-radius: 4px; border-left: 2px solid var(--color-amber); line-height: 1.4;">${escapeHtml(item.reason)}</div>` : ''}
              <div class="state-track">
                <div class="track-step ${step1Class}">${t('obligations.stepPending')}</div>
                <div class="track-arrow">${lucide('arrowRight', { size: 9 })}</div>
                <div class="track-step ${step2Class}">${t('obligations.stepIntent')}</div>
                <div class="track-arrow">${lucide('arrowRight', { size: 9 })}</div>
                <div class="track-step step-todo">${t('obligations.stepVerified')}</div>
                <div class="track-arrow">${lucide('arrowRight', { size: 9 })}</div>
                <div class="track-step step-todo">${t('obligations.stepResolved')}</div>
              </div>
              <div class="track-status-hint"><span class="icon-inline">${lucide('clock', { size: 10 })}</span> ${hasIntent ? t('obligations.hintDocIntent') : t('obligations.hintDocPending')}</div>
            </div>
          `;
      }
    }

    obligationsHtml += `
        <div class="circuit-box">
          <span><span class="icon-inline">${lucide('zap', { size: 11 })}</span> ${t('obligations.circuitBreaker')}:</span>
          <span class="circuit-val ${stopRetries >= 4 ? 'text-red' : 'text-cyan'}">${stopRetries} / 5 ${t('obligations.retries')}</span>
        </div>
      `;
  }
  return obligationsHtml;
}
