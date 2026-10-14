import { t, getCurrentLanguage } from '../i18n';
import { lucide } from '../icons';
import { SkillItem } from '../skills';
import { countOpenTasks } from '../tasks';
import { GuardianViewModel } from './types';
import { escapeHtml } from './html_utils';
import { WEBVIEW_STYLES } from './styles';
import { buildClientScript } from './client';
import {
  renderCurrentActionCard,
  renderLiveTab,
  renderObligationsTab,
  renderRulesTab,
  renderInsightsTab,
  renderSkillsTab,
  renderTasksTab
} from './tabs';

export interface LayoutParams {
  vm: GuardianViewModel;
  skills: SkillItem[];
  activeTab: string;
  nonce: string;
  cspSource: string;
}

/**
 * Builds the complete webview HTML document from the view model and tab renderers.
 */
export function buildHtmlDocument(p: LayoutParams): string {
  const { vm, activeTab, nonce, cspSource } = p;
  const skillsList = p.skills;
  const { eventsList, projectName, totalObligations } = vm;

  const blockedCount = eventsList.filter(e => e.status === 'BLOCKED').length;
  const warningCount = eventsList.filter(e => e.status === 'WARNING').length;
  const approvedCount = eventsList.filter(e => e.status === 'APPROVED').length;
  const shadowCount = eventsList.filter(e => e.status === 'SHADOW_TRIGGER').length;

  const currentCardHtml = renderCurrentActionCard(vm);
  const liveHtml = renderLiveTab(vm);
  const obligationsHtml = renderObligationsTab(vm);
  const rulesHtml = renderRulesTab(vm);
  const insightsHtml = renderInsightsTab(vm);
  const skillsHtml = renderSkillsTab(skillsList);
  const tasksHtml = renderTasksTab(vm);
  const openTasks = countOpenTasks(vm.tasks || []);

  // --- RENDER MAIN WEBVIEW HTML ---
  const htmlContent = `
      <!DOCTYPE html>
      <html lang="en">
      <head>
        <meta charset="UTF-8">
        <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}'; img-src ${cspSource} https: data:; font-src ${cspSource};">
        <style>
${WEBVIEW_STYLES}
        </style>
      </head>
      <body>
        <div id="guardian-app-root">
        <!-- Header -->
        <div class="header">
          <div class="header-left">
            ${lucide('shield', { size: 15, color: 'var(--color-cyan)', strokeWidth: 2.2 })}
            <span class="brand-title">${t('appName')}</span>
            <span class="project-pill">${escapeHtml(projectName)}</span>
          </div>
          <div class="header-right">
            <button class="mini-btn" data-action="toggleLanguage" title="${t('actions.switchLang')}">${lucide('globe', { size: 11 })} <span>${getCurrentLanguage().toUpperCase()}</span></button>
            <button class="mini-btn" data-action="openConfig" title="${t('actions.openConfig')}">${lucide('settings', { size: 11 })}</button>
            <button class="mini-btn" data-action="clearLogs" title="${t('actions.clearLogs')}">${lucide('trash2', { size: 11 })}</button>
          </div>
        </div>

        <!-- Current Action Banner -->
        ${currentCardHtml}

        <!-- Quick Summary Bar -->
        <div class="stat-summary-bar">
          <div class="stat-chip" title="${t('stats.blockedTooltip')}"><div class="chip-val text-red">${blockedCount}</div><div class="chip-lbl">${t('stats.blocked')}</div></div>
          <div class="stat-chip" title="${t('stats.warningTooltip')}"><div class="chip-val text-amber">${warningCount}</div><div class="chip-lbl">${t('stats.warning')}</div></div>
          <div class="stat-chip" title="${t('stats.approvedTooltip')}"><div class="chip-val text-green">${approvedCount}</div><div class="chip-lbl">${t('stats.approved')}</div></div>
          ${shadowCount > 0 ? `<div class="stat-chip" title="${t('stats.shadowTooltip')}"><div class="chip-val text-purple">${shadowCount}</div><div class="chip-lbl">${t('current.statusShadow')}</div></div>` : ''}
          <div class="stat-chip" title="${t('stats.pendingTooltip')}"><div class="chip-val ${totalObligations > 0 ? 'text-cyan' : 'text-muted'}">${totalObligations}</div><div class="chip-lbl">${t('stats.pending')}</div></div>
        </div>

        <!-- Tabs -->
        <div class="tabs-bar">
          <button class="tab-btn ${activeTab === 'live' ? 'active' : ''}" id="btn-live" data-action="setTab" data-tab="live">${lucide('zap', { size: 11 })} ${t('tabs.live')}</button>
          <button class="tab-btn ${activeTab === 'obligations' ? 'active' : ''}" id="btn-obligations" data-action="setTab" data-tab="obligations">${lucide('clipboardList', { size: 11 })} ${t('tabs.obligations')}${totalObligations > 0 ? `<span class="badge-counter">${totalObligations}</span>` : ''}</button>
          <button class="tab-btn ${activeTab === 'rules' ? 'active' : ''}" id="btn-rules" data-action="setTab" data-tab="rules">${lucide('sliders', { size: 11 })} ${t('tabs.rules')}</button>
          <button class="tab-btn ${activeTab === 'insights' ? 'active' : ''}" id="btn-insights" data-action="setTab" data-tab="insights">${lucide('barChart', { size: 11 })} ${t('tabs.insights')}</button>
          <button class="tab-btn ${activeTab === 'skills' ? 'active' : ''}" id="btn-skills" data-action="setTab" data-tab="skills">${lucide('sparkles', { size: 11 })} ${t('tabs.skills')}<span class="badge-counter" style="background: rgba(56, 189, 248, 0.25); color: #38bdf8;">${skillsList.length}</span></button>
          <button class="tab-btn ${activeTab === 'tasks' ? 'active' : ''}" id="btn-tasks" data-action="setTab" data-tab="tasks">${lucide('listChecks', { size: 11 })} ${t('tabs.tasks')}${openTasks > 0 ? `<span class="badge-counter" style="background: rgba(16, 185, 129, 0.25); color: #10b981;">${openTasks}</span>` : ''}</button>
        </div>

        <!-- Panes -->
        <div id="tab-live" class="tab-pane ${activeTab === 'live' ? 'active' : ''}">
          ${liveHtml}
        </div>
        <div id="tab-obligations" class="tab-pane ${activeTab === 'obligations' ? 'active' : ''}">
          ${obligationsHtml}
        </div>
        <div id="tab-rules" class="tab-pane ${activeTab === 'rules' ? 'active' : ''}">
          ${rulesHtml}
        </div>
        <div id="tab-insights" class="tab-pane ${activeTab === 'insights' ? 'active' : ''}">
          ${insightsHtml}
        </div>
        <div id="tab-skills" class="tab-pane ${activeTab === 'skills' ? 'active' : ''}">
          ${skillsHtml}
        </div>
        <div id="tab-tasks" class="tab-pane ${activeTab === 'tasks' ? 'active' : ''}">
          ${tasksHtml}
        </div>
        </div>

        ${buildClientScript(nonce, activeTab)}
      </body>
      </html>
    `;

  return htmlContent;
}

/**
 * Extracts the inner HTML of the root container so it can be swapped in-place
 * via postMessage without reloading the webview iframe.
 */
export function extractRootInnerHtml(htmlContent: string): string {
  const rootStart = htmlContent.indexOf('<div id="guardian-app-root">');
  const scriptStart = htmlContent.lastIndexOf('<script nonce=');
  if (rootStart === -1 || scriptStart === -1) {
    return '';
  }
  const afterRoot = rootStart + '<div id="guardian-app-root">'.length;
  const beforeScript = htmlContent.lastIndexOf('</div>', scriptStart);
  if (beforeScript > afterRoot) {
    return htmlContent.substring(afterRoot, beforeScript).trim();
  }
  return '';
}
