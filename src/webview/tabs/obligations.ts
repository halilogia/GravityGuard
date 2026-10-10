import * as path from 'path';
import { t } from '../../i18n';
import { lucide } from '../../icons';
import { escapeHtml } from '../html_utils';
import { GuardianViewModel } from '../types';

export function renderObligationsTab(vm: GuardianViewModel): string {
  const { pendingTests, pendingDocs, resolutionIntents, stopRetries } = vm;

  // --- TAB 2: OBLIGATIONS (ACTIONABLE TASKS + 4-STEP STATE MACHINE TRACK) ---
  let obligationsHtml = '';
  const testKeys = Object.keys(pendingTests);
  const docKeys = Object.keys(pendingDocs);

  if (testKeys.length === 0 && docKeys.length === 0) {
    obligationsHtml = `
        <div class="clean-state-box">
          ${lucide('sparkles', { size: 28, color: '#10b981', strokeWidth: 1.75 })}
          <div class="clean-state-title">${t('obligations.cleanState')}</div>
        </div>
      `;
  } else {
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
              <div class="task-meta">${t('obligations.expectedTest')}: <code class="text-cyan">${escapeHtml(item.expected_name || 'test')}</code></div>
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
        const hasIntent = resolutionIntents.some(intent => intent.target_path && intent.target_path.toLowerCase().includes('changelog'));
        const step1Class = !hasIntent ? 'step-active' : 'step-done';
        const step2Class = hasIntent ? 'step-active' : 'step-todo';

        obligationsHtml += `
            <div class="task-card border-amber">
              <div class="task-header">
                <span class="task-title" title="${escapeHtml(dk)}">${escapeHtml(path.basename(dk))}</span>
                <button class="mini-icon-btn" data-action="openFile" data-path="${escapeHtml(dk)}" title="${t('current.openFile')}">${lucide('fileText', { size: 12 })}</button>
              </div>
              <div class="task-meta">${t('obligations.requiredDoc')}: <code class="text-amber">${escapeHtml(reqs)}</code></div>
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
