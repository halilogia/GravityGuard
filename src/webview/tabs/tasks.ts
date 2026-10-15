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

function renderTaskItem(item: TaskItem, file: TaskFile): string {
  let icon: string;
  let textStyle = 'color: var(--text-main);';
  const isGov = file.source === 'governance';
  const nextStatus = item.status === 'open' ? 'in_progress' : item.status === 'in_progress' ? 'done' : 'open';

  if (item.status === 'done') {
    icon = lucide('checkCircle', { size: 13, color: 'var(--color-green)' });
    textStyle = 'color: var(--text-muted); text-decoration: line-through; opacity: 0.7;';
  } else if (item.status === 'in_progress') {
    icon = lucide('circleDot', { size: 13, color: 'var(--color-cyan)' });
  } else {
    icon = lucide('circle', { size: 13, color: 'var(--text-muted)' });
  }

  const lineBadge = item.line
    ? `<span class="status-badge badge-neutral" style="margin-left: 5px; font-size: 8px; padding: 1px 5px;">L${item.line}</span>`
    : '';

  const statusBtn = isGov || !item.line
    ? `<span class="icon-inline" style="flex-shrink: 0;">${icon}</span>`
    : `<button class="mini-icon-btn task-status-btn" data-action="cycleTaskStatus" data-path="${escapeHtml(file.path)}" data-line="${item.line}" data-next="${nextStatus}" title="${escapeHtml(t('tasks.cycleStatus'))}" style="background: none; border: none; cursor: pointer; padding: 0; display: inline-flex; align-items: center; flex-shrink: 0;">${icon}</button>`;

  const deleteBtn = isGov || !item.line
    ? ''
    : `<button class="mini-icon-btn task-delete-btn" data-action="deleteTaskItem" data-path="${escapeHtml(file.path)}" data-line="${item.line}" title="${escapeHtml(t('tasks.deleteTask'))}" style="background: none; border: none; cursor: pointer; padding: 0 3px; opacity: 0.35; transition: opacity 0.15s; flex-shrink: 0;" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.35'">${lucide('trash2', { size: 11, color: 'var(--color-red, #ef4444)' })}</button>`;

  return `
          <div class="task-item-row" style="display: flex; align-items: flex-start; gap: 6px; padding: 3px 0; font-size: 10px;">
            ${statusBtn}
            <span style="flex: 1; word-break: break-word; ${textStyle}">${escapeHtml(item.title)}</span>
            ${lineBadge}
            ${deleteBtn}
          </div>`;
}

function renderTaskFile(file: TaskFile, fileIdx: number): string {
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
    ? file.items.map(item => renderTaskItem(item, file)).join('')
    : `<div class="empty-state">${t('tasks.empty')}</div>`;

  const addRow = isGovernance
    ? ''
    : `
        <div style="display: flex; gap: 4px; margin-top: 6px; padding-top: 5px; border-top: 1px solid rgba(255, 255, 255, 0.06); align-items: center;">
          <input type="text" id="task-add-input-${fileIdx}" class="task-add-input" placeholder="${escapeHtml(t('tasks.addTaskPlaceholder'))}" style="flex: 1; font-size: 10px; background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.1); border-radius: 4px; color: var(--text-main); padding: 3px 6px; outline: none;" data-path="${escapeHtml(file.path)}" />
          <button class="mini-btn btn-cyan" data-action="addTaskItem" data-input-id="task-add-input-${fileIdx}" data-path="${escapeHtml(file.path)}" style="font-size: 9px; padding: 3px 8px; cursor: pointer; white-space: nowrap; display: inline-flex; align-items: center; gap: 3px;">${lucide('plus', { size: 10 })} ${escapeHtml(t('tasks.addTask'))}</button>
        </div>`;

  return `
        <div class="task-card ${complete ? 'border-cyan' : 'border-amber'}" style="margin-bottom: 8px;">
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
          ${addRow}
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
        ${files.map((file, idx) => renderTaskFile(file, idx)).join('')}
      `;
}
