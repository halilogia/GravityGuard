import * as path from 'path';
import { t } from '../../i18n';
import { lucide } from '../../icons';
import { AdrItem, GotchaItem, MemoryHubData, AdrStatus } from '../../knowledge';
import { escapeHtml } from '../html_utils';
import { GuardianViewModel } from '../types';

function statusBadge(status: AdrStatus): { cls: string; label: string } {
  switch (status) {
    case 'ACCEPTED':
      return { cls: 'badge-allowed', label: t('knowledge.statusAccepted') };
    case 'PROPOSED':
      return { cls: 'badge-amber', label: t('knowledge.statusProposed') };
    case 'SUPERSEDED':
      return { cls: 'badge-purple', label: t('knowledge.statusSuperseded') };
    case 'REJECTED':
      return { cls: 'badge-red', label: t('knowledge.statusRejected') };
    case 'DEPRECATED':
      return { cls: 'badge-neutral', label: t('knowledge.statusDeprecated') };
    default:
      return { cls: 'badge-allowed', label: t('knowledge.statusAccepted') };
  }
}

function renderAdrCard(adr: AdrItem, knowledgePath: string): string {
  const badge = statusBadge(adr.status);
  const openLineBtn = knowledgePath
    ? `<button class="mini-icon-btn" data-action="openFile" data-path="${escapeHtml(knowledgePath)}" data-line="${adr.line}" title="${escapeHtml(t('knowledge.openLine'))}" style="margin-left: auto; flex-shrink: 0;">${lucide('externalLink', { size: 10 })}</button>`
    : '';

  return `
    <div class="adr-card" data-adr-id="${escapeHtml(adr.id)}" style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 6px; margin-bottom: 6px; overflow: hidden;">
      <div class="adr-card-header" style="display: flex; align-items: center; gap: 6px; padding: 6px 8px; cursor: pointer; user-select: none;">
        ${lucide('chevronRight', { size: 11, className: 'adr-chevron', color: 'var(--text-muted)' })}
        <span class="status-badge ${badge.cls}" style="font-size: 8px; padding: 1px 5px;">${escapeHtml(adr.id)}</span>
        <span style="font-weight: 500; font-size: 11px; flex: 1; word-break: break-word;">${escapeHtml(adr.title)}</span>
        <span class="status-badge ${badge.cls}" style="font-size: 8px; padding: 1px 5px;">${escapeHtml(badge.label)}</span>
        ${openLineBtn}
      </div>
      <div class="adr-card-body" style="display: none; padding: 6px 10px 8px 24px; border-top: 1px solid rgba(255, 255, 255, 0.05); font-size: 10px; color: var(--text-muted); line-height: 1.45;">
        ${adr.decision ? `<div style="margin-bottom: 4px;"><strong style="color: var(--color-cyan);">${t('knowledge.decision')}:</strong> <span style="color: var(--text-main);">${escapeHtml(adr.decision)}</span></div>` : ''}
        ${adr.context ? `<div style="margin-bottom: 4px;"><strong style="color: var(--text-main);">${t('knowledge.context')}:</strong> ${escapeHtml(adr.context)}</div>` : ''}
        ${adr.consequences ? `<div><strong style="color: var(--color-amber);">${t('knowledge.consequences')}:</strong> ${escapeHtml(adr.consequences)}</div>` : ''}
      </div>
    </div>`;
}

function renderGotchaChip(gotcha: GotchaItem, knowledgePath: string): string {
  const openLineBtn = knowledgePath
    ? `<button class="mini-icon-btn" data-action="openFile" data-path="${escapeHtml(knowledgePath)}" data-line="${gotcha.line}" title="${escapeHtml(t('knowledge.openLine'))}" style="padding: 0 2px; background: none; border: none; cursor: pointer; opacity: 0.5;">${lucide('externalLink', { size: 9 })}</button>`
    : '';

  return `
    <div class="gotcha-chip" style="display: flex; align-items: flex-start; gap: 6px; background: rgba(245, 158, 11, 0.08); border-left: 2px solid var(--color-amber); padding: 5px 8px; border-radius: 0 4px 4px 0; font-size: 10px; margin-bottom: 4px;">
      <span style="color: var(--color-amber); flex-shrink: 0; margin-top: 1px;">${lucide('alertTriangle', { size: 11 })}</span>
      <span style="flex: 1; color: var(--text-main); word-break: break-word;">${escapeHtml(gotcha.text)}</span>
      ${openLineBtn}
    </div>`;
}

/**
 * Renders the complete [📚 Hafıza] (Knowledge & ADR Hub) tab.
 */
export function renderKnowledgeTab(vm: GuardianViewModel): string {
  const memory: MemoryHubData = (vm as any).memory || {};
  const knowledge = memory.knowledge;
  const changelog = memory.changelog;

  const kPath = knowledge?.path || '';
  const cPath = changelog?.path || '';

  // 1. Dosya Başlık Çubuğu
  const kFileBtn = kPath
    ? `<button class="mini-btn btn-outline" data-action="openFile" data-path="${escapeHtml(kPath)}" style="font-size: 9px; padding: 2px 6px;">${lucide('fileText', { size: 10 })} KNOWLEDGE.md</button>`
    : `<span style="font-size: 9px; color: var(--text-muted);">${t('knowledge.noKnowledgeFile')}</span>`;

  const cFileBtn = cPath
    ? `<button class="mini-btn btn-outline" data-action="openFile" data-path="${escapeHtml(cPath)}" style="font-size: 9px; padding: 2px 6px;">${lucide('fileText', { size: 10 })} CHANGELOG.md</button>`
    : '';

  // 2. ADR Listesi & Ekleme Formu
  const adrCardsHtml = knowledge && knowledge.adrs.length > 0
    ? knowledge.adrs.map(a => renderAdrCard(a, kPath)).join('')
    : `<div class="empty-state" style="padding: 12px; font-size: 10px;">${t('knowledge.emptyAdrs')}</div>`;

  const addAdrForm = kPath
    ? `
    <div id="add-adr-drawer" style="display: none; background: rgba(0,0,0,0.3); border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 6px; padding: 8px; margin-bottom: 8px;">
      <div style="font-size: 10px; font-weight: 600; color: var(--color-cyan); margin-bottom: 6px;">${lucide('plus', { size: 10 })} ${t('knowledge.newAdrTitle')}</div>
      <input type="text" id="new-adr-title" placeholder="${escapeHtml(t('knowledge.adrTitlePlaceholder'))}" style="width: 100%; box-sizing: border-box; font-size: 10px; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 4px; color: var(--text-main); padding: 4px 6px; margin-bottom: 5px; outline: none;" />
      <textarea id="new-adr-decision" placeholder="${escapeHtml(t('knowledge.adrDecisionPlaceholder'))}" rows="2" style="width: 100%; box-sizing: border-box; font-size: 10px; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 4px; color: var(--text-main); padding: 4px 6px; margin-bottom: 5px; outline: none; resize: vertical;"></textarea>
      <div style="display: flex; justify-content: flex-end; gap: 4px;">
        <button class="mini-btn" id="btn-cancel-adr" style="font-size: 9px; padding: 2px 8px;">${t('actions.cancel')}</button>
        <button class="mini-btn btn-cyan" id="btn-save-adr" data-path="${escapeHtml(kPath)}" style="font-size: 9px; padding: 2px 8px;">${lucide('check', { size: 10 })} ${t('actions.save')}</button>
      </div>
    </div>`
    : '';

  // 3. Kör Noktalar Listesi
  const gotchasHtml = knowledge && knowledge.gotchas.length > 0
    ? knowledge.gotchas.map(g => renderGotchaChip(g, kPath)).join('')
    : `<div style="font-size: 10px; color: var(--text-muted); font-style: italic; padding: 4px 0;">${t('knowledge.noGotchas')}</div>`;

  // 4. CHANGELOG [Unreleased] & Son Sürüm
  const hasUnreleased = changelog && changelog.unreleased.length > 0;
  const unreleasedItemsHtml = hasUnreleased
    ? changelog.unreleased.map(u => `
        <div style="display: flex; align-items: flex-start; gap: 6px; padding: 2px 0; font-size: 10px;">
          <span style="color: var(--color-cyan); flex-shrink: 0;">•</span>
          <span style="flex: 1; word-break: break-word;">${escapeHtml(u)}</span>
        </div>`).join('')
    : `<div style="font-size: 10px; color: var(--color-amber); padding: 4px 0;">⚠️ ${t('knowledge.unreleasedEmptyNotice')}</div>`;

  const addChangelogRow = cPath
    ? `
      <div style="display: flex; gap: 4px; margin-top: 6px; padding-top: 5px; border-top: 1px solid rgba(255, 255, 255, 0.06); align-items: center;">
        <input type="text" id="changelog-add-input" placeholder="${escapeHtml(t('knowledge.addChangePlaceholder'))}" style="flex: 1; font-size: 10px; background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.1); border-radius: 4px; color: var(--text-main); padding: 3px 6px; outline: none;" data-path="${escapeHtml(cPath)}" />
        <button class="mini-btn btn-cyan" id="btn-save-changelog" data-path="${escapeHtml(cPath)}" style="font-size: 9px; padding: 3px 8px; cursor: pointer; white-space: nowrap; display: inline-flex; align-items: center; gap: 3px;">${lucide('plus', { size: 10 })} ${t('knowledge.addChange')}</button>
      </div>`
    : '';

  const latestReleaseHtml = changelog?.latestRelease
    ? `
      <div style="background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 6px; padding: 8px; margin-top: 6px;">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;">
          <span style="font-weight: 600; font-size: 11px; color: var(--color-green);">${lucide('tag', { size: 11 })} v${escapeHtml(changelog.latestRelease.version)}</span>
          <span style="font-size: 9px; color: var(--text-muted);">${escapeHtml(changelog.latestRelease.date || '')}</span>
        </div>
        ${changelog.latestRelease.changes.slice(0, 4).map(c => `
          <div style="font-size: 9px; color: var(--text-muted); padding: 1px 0; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">- ${escapeHtml(c)}</div>
        `).join('')}
        ${changelog.totalReleases > 1 ? `<div style="font-size: 8px; color: var(--text-muted); margin-top: 4px; text-align: right;">${changelog.totalReleases} ${t('knowledge.totalReleasesCount')}</div>` : ''}
      </div>`
    : '';

  return `
    <div class="knowledge-tab-content">
      <!-- Hub Header -->
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.08);">
        <div style="display: flex; align-items: center; gap: 6px;">
          <span style="font-size: 11px; font-weight: 600; color: var(--text-main);">${lucide('bookOpen', { size: 12, color: 'var(--color-cyan)' })} ${t('knowledge.hubTitle')}</span>
          ${kFileBtn}
          ${cFileBtn}
        </div>
        ${kPath ? `<button class="mini-btn btn-cyan" id="btn-toggle-add-adr" style="font-size: 9px; padding: 2px 6px;">${lucide('plus', { size: 10 })} ${t('knowledge.newAdr')}</button>` : ''}
      </div>

      <!-- Add ADR Form Drawer -->
      ${addAdrForm}

      <!-- 1. Mimari Kararlar (ADR) Bölümü -->
      <div style="margin-bottom: 10px;">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;">
          <span style="font-size: 10px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">${t('knowledge.adrsHeader')}</span>
          <span class="badge-counter" style="background: rgba(16, 185, 129, 0.2); color: #10b981;">${knowledge?.totalAdrs || 0}</span>
        </div>
        ${adrCardsHtml}
      </div>

      <!-- 2. Kör Noktalar & Gotchas Bölümü -->
      <div style="margin-bottom: 10px;">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;">
          <span style="font-size: 10px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">${t('knowledge.gotchasHeader')}</span>
          <span class="badge-counter" style="background: rgba(245, 158, 11, 0.2); color: #f59e0b;">${knowledge?.totalGotchas || 0}</span>
        </div>
        ${gotchasHtml}
      </div>

      <!-- 3. CHANGELOG & Sürüm Takibi Bölümü -->
      <div>
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;">
          <span style="font-size: 10px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">${t('knowledge.changelogHeader')}</span>
          ${hasUnreleased ? `<span class="status-badge badge-cyan" style="font-size: 8px;">${changelog!.unreleased.length} ${t('knowledge.pendingItems')}</span>` : ''}
        </div>
        
        <div style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 6px; padding: 8px;">
          <div style="font-size: 10px; font-weight: 600; color: var(--text-main); margin-bottom: 4px; display: flex; align-items: center; gap: 4px;">
            ${lucide('clock', { size: 10, color: 'var(--color-cyan)' })} [Unreleased]
          </div>
          ${unreleasedItemsHtml}
          ${addChangelogRow}
        </div>

        ${latestReleaseHtml}
      </div>
    </div>`;
}
