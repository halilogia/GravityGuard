import * as path from 'path';
import { t } from '../../i18n';
import { lucide } from '../../icons';
import { TaskFile, TaskItem, GOVERNANCE_TASK_SOURCE } from '../../tasks';
import { escapeHtml } from '../html_utils';
import { GuardianViewModel } from '../types';

type TaskSourceKind = 'repo' | 'brain' | 'governance';

/** Antigravity brain task files live under ~/.gemini/antigravity/brain/<id>/task.md. */
function sourceKind(file: TaskFile): TaskSourceKind {
  if (file.source === 'governance' || file.path === GOVERNANCE_TASK_SOURCE) {
    return 'governance';
  }
  return /[\\/]antigravity[\\/]brain[\\/]/i.test(file.path) ? 'brain' : 'repo';
}

const SOURCE_BADGES: Record<TaskSourceKind, { key: string; cls: string }> = {
  repo: { key: 'tasks.sourceRepo', cls: 'badge-allowed' },
  brain: { key: 'tasks.sourceBrain', cls: 'badge-purple' },
  governance: { key: 'tasks.sourceGovernance', cls: 'badge-cyan' }
};

function renderTaskItem(item: TaskItem): string {
  let icon: string;
  let textStyle = 'color: var(--text-main);';
  if (item.status === 'done') {
    icon = lucide('checkCircle', { size: 12, color: 'var(--color-green)' });
    textStyle = 'color: var(--text-muted); text-decoration: line-through; opacity: 0.7;';
  } else if (item.status === 'in_progress') {
    icon = lucide('circleDot', { size: 12, color: 'var(--color-cyan)' });
  } else {
    icon = lucide('circle', { size: 12, color: 'var(--text-muted)' });
  }
  const lineBadge = item.line
    ? `<span class="status-badge badge-neutral" style="margin-left: 5px; font-size: 8px; padding: 1px 5px;">L${item.line}</span>`
    : '';
  return `
          <div style="display: flex; align-items: flex-start; gap: 6px; padding: 3px 0; font-size: 10px;">
            <span class="icon-inline" style="flex-shrink: 0;">${icon}</span>
            <span style="flex: 1; word-break: break-word; ${textStyle}">${escapeHtml(item.title)}</span>
            ${lineBadge}
          </div>`;
}

function renderTaskFile(file: TaskFile): string {
  const kind = sourceKind(file);
  const badge = SOURCE_BADGES[kind];
  const isGovernance = kind === 'governance';
  const name = isGovernance ? t('tasks.governanceTitle') : path.basename(file.path);
  const percent = file.total > 0 ? Math.round((file.done / file.total) * 100) : 0;
  const complete = file.total > 0 && file.done === file.total;
  const openBtn = isGovernance
    ? ''
    : `<button class="mini-icon-btn" data-action="openFile" data-path="${escapeHtml(file.path)}" title="${escapeHtml(t('tasks.openFile'))}">${lucide('fileText', { size: 12 })}</button>`;
  const items = file.items.length > 0
    ? file.items.map(renderTaskItem).join('')
    : `<div class="empty-state">${t('tasks.empty')}</div>`;

  return `
        <div class="task-card ${complete ? 'border-cyan' : 'border-amber'}">
          <div class="task-header">
            <span class="task-title" title="${escapeHtml(file.path)}">${escapeHtml(name)}
              <span class="status-badge ${badge.cls}" style="margin-left: 5px; font-size: 8px; padding: 1px 5px;">${t(badge.key)}</span>
            </span>
            <span style="display: flex; align-items: center; gap: 4px;">
              <span class="badge-counter" style="background: rgba(56, 189, 248, 0.25); color: #38bdf8;">${file.done} / ${file.total}</span>
              ${openBtn}
            </span>
          </div>
          <div style="height: 4px; background: rgba(255, 255, 255, 0.08); border-radius: 2px; overflow: hidden; margin: 4px 0 6px;" title="${percent}%">
            <div style="height: 100%; width: ${percent}%; background: ${complete ? 'var(--color-green)' : 'var(--color-cyan)'};"></div>
          </div>
          ${items}
        </div>`;
}

export function renderTasksTab(vm: GuardianViewModel): string {
  const files = vm.tasks || [];
  if (files.length === 0) {
    return `
        <div class="clean-state-box">
          ${lucide('listChecks', { size: 28, color: '#10b981', strokeWidth: 1.75 })}
          <div class="clean-state-title">${t('tasks.cleanState')}</div>
        </div>
      `;
  }
  const total = files.reduce((sum, f) => sum + f.total, 0);
  return `
        <div style="margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
          <span style="font-size: 10px; font-weight: 800; color: var(--color-cyan);">${t('tasks.title')}</span>
          <span class="project-pill">${t('tasks.total', { count: total })}</span>
        </div>
        ${files.map(renderTaskFile).join('')}
      `;
}
