import { t } from '../../i18n';
import { lucide } from '../../icons';
import { SkillItem } from '../../skills';
import { escapeHtml } from '../html_utils';

export function renderSkillsTab(skillsList: SkillItem[]): string {
  // --- TAB 5: SKILLS (ACTIVE WORKSPACE, GLOBAL, PLUGIN, BUILT-IN) ---
  let skillsHtml = '';
  if (skillsList.length === 0) {
    skillsHtml = `<div class="empty-state">${t('skills.empty')}</div>`;
  } else {
    skillsHtml = `
        <div style="margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
          <span style="font-size: 10px; font-weight: 800; color: var(--color-cyan);">${t('skills.title')}</span>
          <span class="project-pill">${t('skills.totalCount', { count: skillsList.length })}</span>
        </div>
        <div style="margin-bottom: 8px;">
          <button class="action-btn wide" data-action="findSkills" title="${t('skills.findSkillsTooltip')}">
            ${lucide('sparkles', { size: 12, color: 'var(--color-cyan)' })} ${t('skills.findSkillsBtn')}
          </button>
        </div>
      `;

    for (const sk of skillsList) {
      let badgeCls = 'badge-neutral';
      let scopeLabel = t('skills.builtinScope');
      if (sk.scope === 'workspace') {
        badgeCls = 'badge-allowed';
        scopeLabel = t('skills.workspaceScope');
      } else if (sk.scope === 'global') {
        badgeCls = 'badge-cyan';
        scopeLabel = t('skills.globalScope');
      } else if (sk.scope === 'plugin') {
        badgeCls = 'badge-purple';
        scopeLabel = t('skills.pluginScope');
      }

      const safePath = escapeHtml(sk.skillFilePath);
      skillsHtml += `
          <div class="stream-item" style="padding: 7px 8px; margin-bottom: 6px;">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 4px;">
              <div>
                <span style="font-weight: 700; font-size: 11px; color: var(--text-main);">${escapeHtml(sk.name)}</span>
                <span class="status-badge ${badgeCls}" style="margin-left: 5px; font-size: 8px; padding: 1px 5px;">${scopeLabel}</span>
              </div>
              <button class="mini-icon-btn" data-action="openFile" data-path="${safePath}" title="${t('skills.openSkillMd')}">
                ${lucide('fileText', { size: 12, color: 'var(--text-muted)' })}
              </button>
            </div>
            <div style="font-size: 9px; color: #cbd5e1; line-height: 1.35; margin-bottom: 4px;">
              ${escapeHtml(sk.description)}
            </div>
            <div style="font-size: 8px; color: rgba(255, 255, 255, 0.35); font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(sk.skillFilePath)}">
              ${escapeHtml(sk.skillFilePath)}
            </div>
          </div>
        `;
    }
  }
  return skillsHtml;
}
