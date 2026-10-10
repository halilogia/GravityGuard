import { t } from '../../i18n';
import { lucide } from '../../icons';
import { GuardianViewModel } from '../types';

export function renderRulesTab(vm: GuardianViewModel): string {
  const { projectCfg } = vm;

  // --- TAB 3: RULES (CATEGORIZED SECURITY / ARCHITECTURE / QUALITY) ---
  const docGovActive = projectCfg?.governance?.enforceDocObligations === true;

  function getRuleBadge(ruleKey: string, defaultMode: 'block' | 'warn') {
    const rCfg = projectCfg?.rules?.[ruleKey];
    const isShadow = (typeof rCfg === 'object' && rCfg?.mode === 'shadow') || rCfg === 'shadow';
    if (isShadow) {
      return `<span class="mode-pill mode-shadow">${lucide('eye', { size: 9 })} ${t('rules.badgeShadow')}</span>`;
    }
    if (defaultMode === 'block') {
      return `<span class="mode-pill mode-block">${t('rules.badgeBlock')}</span>`;
    }
    return `<span class="mode-pill mode-warn">${t('rules.badgeWarnAdvisory')}</span>`;
  }

  const rulesHtml = `
      <div class="rules-group">
        <div class="group-title text-red"><span class="icon-inline">${lucide('lock', { size: 12 })}</span> ${t('rules.secTitle')}</div>
        <div class="rule-row">
          <div class="rule-name">${t('rules.g0Title')}</div>
          ${getRuleBadge('G0_SECRET_LEAK', 'block')}
        </div>
        <div class="rule-desc">${t('rules.g0Desc')}</div>

        <div class="rule-row">
          <div class="rule-name">${t('rules.g1Title')}</div>
          ${getRuleBadge('G1_SILENT_EXCEPTION', 'block')}
        </div>
        <div class="rule-desc">${t('rules.g1Desc')}</div>

        <div class="rule-row">
          <div class="rule-name">${t('rules.g2Title')}</div>
          ${getRuleBadge('G2_TEST_INTEGRITY', 'block')}
        </div>
        <div class="rule-desc">${t('rules.g2Desc')}</div>
      </div>

      <div class="rules-group">
        <div class="group-title text-purple"><span class="icon-inline">${lucide('layers', { size: 12 })}</span> ${t('rules.archTitle')}</div>
        <div class="rule-row">
          <div class="rule-name">${t('rules.g4Title')}</div>
          ${getRuleBadge('G4_IMPORT_MATRIX', 'block')}
        </div>
        <div class="rule-desc">${t('rules.g4Desc')}</div>

        <div class="rule-row">
          <div class="rule-name">${t('rules.srpTitle')}</div>
          ${getRuleBadge('SRP_BOUNDARY', 'block')}
        </div>
        <div class="rule-desc">${t('rules.srpDesc')}</div>

        <div class="rule-row">
          <div class="rule-name">${t('rules.g3Title')}</div>
          ${getRuleBadge('G3_COMPILER_BYPASS', 'warn')}
        </div>
        <div class="rule-desc">${t('rules.g3Desc')}</div>

        <div class="rule-row">
          <div class="rule-name">${t('rules.growthTitle')}</div>
          ${getRuleBadge('ARCH_FILE_GROWTH', 'warn')}
        </div>
        <div class="rule-desc">${t('rules.growthDesc')}</div>
      </div>

      <div class="rules-group">
        <div class="group-title text-cyan"><span class="icon-inline">${lucide('flaskConical', { size: 12 })}</span> ${t('rules.govTitle')}</div>
        <div class="rule-row">
          <div class="rule-name">${t('rules.t1Title')}</div>
          <span class="mode-pill mode-warn">${t('rules.badgeWarnStop')}</span>
        </div>
        <div class="rule-desc">${t('rules.t1Desc')}</div>

        <div class="rule-row">
          <div class="rule-name">${t('rules.docGovTitle')}</div>
          <span class="mode-pill ${docGovActive ? 'mode-active' : 'mode-inactive'}">${docGovActive ? t('rules.badgeOptInStop') : t('rules.badgeOff')}</span>
        </div>
        <div class="rule-desc">${t('rules.docGovDesc')}</div>
      </div>

      <div style="margin-top: 14px; text-align: center;">
        <button class="action-btn wide" data-action="openConfig">${lucide('settings', { size: 12 })} ${t('actions.openConfig')}</button>
      </div>
    `;
  return rulesHtml;
}
