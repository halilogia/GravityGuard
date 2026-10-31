import { t } from '../../i18n';
import { lucide } from '../../icons';
import { escapeHtml } from '../html_utils';
import type { HookProposalData, HookProposalView } from '../hook_proposals';

function field(label: string, value: unknown, prose = false): string {
  if (typeof value !== 'string' || !value) return '';
  const body = prose ? `<span class="hook-text">${escapeHtml(value)}</span>` : `<code class="hook-value">${escapeHtml(value)}</code>`;
  return `<div class="hook-field"><span class="hook-label">${label}</span>${body}</div>`;
}

function renderDiff(diff: string): string {
  const lines = diff.split('\n').filter(line => !line.startsWith('---') && !line.startsWith('+++'));
  return `<pre class="hook-diff">${lines.map(line => {
    const kind = line.startsWith('+') ? 'add' : line.startsWith('-') ? 'del' : line.startsWith('@@') ? 'hunk' : 'ctx';
    return `<span class="diff-${kind}">${escapeHtml(line)}</span>`;
  }).join('\n')}</pre>`;
}

function renderPending(view: HookProposalView): string {
  const p = view.proposal || {};
  const actions = view.valid
    ? `<button class="action-btn hook-approve" data-action="approveHookProposal" data-path="${escapeHtml(view.path)}" data-text="${escapeHtml(view.sha256 || '')}">${lucide('check', { size: 11 })} ${t('hooks.approve')}</button>`
    : `<span class="mode-pill mode-block">${t('hooks.invalid')}</span>`;
  return `
    <div class="hook-card ${view.valid ? '' : 'hook-invalid'}">
      <div class="hook-head">
        <span class="hook-id">${escapeHtml(view.id)}</span>
        <span class="mode-pill mode-active">${escapeHtml(String(p.event || '?'))}</span>
      </div>
      ${field(t('hooks.complaint'), p.complaint, true)}
      ${field(t('hooks.rationale'), p.rationale, true)}
      ${field(t('hooks.command'), p.command)}
      ${field(t('hooks.test'), p.test)}
      ${field(t('hooks.target'), view.target_file)}
      ${view.error ? `<div class="hook-error">${lucide('alertTriangle', { size: 11 })} ${escapeHtml(view.error)}</div>` : ''}
      ${view.diff ? renderDiff(view.diff) : ''}
      <div class="hook-actions">
        ${actions}
        <button class="action-btn" data-action="rejectHookProposal" data-path="${escapeHtml(view.path)}">${lucide('x', { size: 11 })} ${t('hooks.reject')}</button>
      </div>
    </div>`;
}

export function renderHooksTab(data: HookProposalData): string {
  const pending = data.pending.length
    ? data.pending.map(renderPending).join('')
    : `<div class="empty-state">${t('hooks.empty')}</div>`;
  const installed = data.installed.map(receipt => {
    const receiptPath = `${receipt.root}/.gravityguard/runtime/hook-receipts/${receipt.id}.json`;
    return `
      <div class="hook-installed">
        <span class="hook-id">${escapeHtml(receipt.id)}</span>
        <span class="hook-value">${escapeHtml(String(receipt.proposal?.event || ''))} → ${escapeHtml(receipt.target_file)}</span>
        <button class="mini-btn" data-action="revertHookProposal" data-path="${escapeHtml(receiptPath)}">${lucide('rotateCcw', { size: 10 })} ${t('hooks.revert')}</button>
      </div>`;
  }).join('');
  return `
    <div class="group-title text-cyan"><span class="icon-inline">${lucide('plug', { size: 12 })}</span> ${t('hooks.title')}</div>
    ${pending}
    ${installed ? `<div class="group-title" style="margin-top: 14px;">${t('hooks.installedTitle')}</div>${installed}` : ''}
    <div class="hook-hint">${t('hooks.cliHint')}</div>`;
}
