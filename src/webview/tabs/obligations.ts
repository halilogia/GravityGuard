import * as path from 'path';
import { t } from '../../i18n';
import { lucide } from '../../icons';
import { escapeHtml } from '../html_utils';
import { GuardianViewModel } from '../types';

/** Agent badge + creation timestamp row for an obligation record (empty when neither is recorded). */
function renderObligationMeta(item: any): string {
  const agent = typeof item?.agent === 'string' ? item.agent.trim() : '';
  const rawTime = item?.created_at ?? item?.timestamp;
  const time = typeof rawTime === 'string' || typeof rawTime === 'number' ? String(rawTime).trim() : '';
  if (!agent && !time) {
    return '';
  }
  const agentHtml = agent
    ? `<span class="status-badge badge-cyan" style="font-size: 8px; padding: 1px 5px;" title="${escapeHtml(t('obligations.agentLabel'))}"><span class="icon-inline">${lucide('bot', { size: 9 })}</span> ${escapeHtml(agent)}</span>`
    : '';
  const timeHtml = time
    ? `<span style="font-size: 8px; color: var(--text-muted);"><span class="icon-inline">${lucide('clock', { size: 9 })}</span> ${escapeHtml(time)}</span>`
    : '';
  return `<div class="task-meta" style="display: flex; gap: 8px; align-items: center;">${agentHtml}${timeHtml}</div>`;
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
      obligationsHtml += `<div class="section-title text-cyan"><span class="icon-inline">${lucide('flaskConical', { size: 12 })}</span> ${t('obligations.testTitle')} (${testKeys.length})</div>`;
      for (const tk of testKeys) {
        const item = pendingTests[tk];
        const hasIntent = resolutionIntents.some(intent => intent.target_path && intent.target_path.toLowerCase().includes(path.basename(tk).toLowerCase()));
        const step1Class = !hasIntent ? 'step-active' : 'step-done';
        const step2Class = hasIntent ? 'step-active' : 'step-todo';

        obligationsHtml += `
            <div class="task-card border-cyan">
              <div class="task-header">
                <span class="task-title" title="${escapeHtml(tk)}">${escapeHtml(path.basename(tk))}</span>
                <button class="mini-icon-btn" data-action="openFile" data-path="${escapeHtml(tk)}" title="${t('current.openFile')}">${lucide('fileText', { size: 12 })}</button>
              </div>
              ${renderObligationMeta(item)}
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

        obligationsHtml += `
            <div class="task-card border-amber">
              <div class="task-header">
                <span class="task-title" title="${escapeHtml(dk)}">${escapeHtml(path.basename(dk))}</span>
                <button class="mini-icon-btn" data-action="openFile" data-path="${escapeHtml(dk)}" title="${t('current.openFile')}">${lucide('fileText', { size: 12 })}</button>
              </div>
              ${renderObligationMeta(item)}
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
