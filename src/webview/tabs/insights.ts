import { t } from '../../i18n';
import { lucide } from '../../icons';
import { escapeHtml } from '../html_utils';
import { GuardianViewModel } from '../types';

export function renderInsightsTab(vm: GuardianViewModel): string {
  const { data, eventsList, pendingTests, pendingDocs, projectCfg, stopRetries, sessionId } = vm;
  const testKeys = Object.keys(pendingTests);
  const docKeys = Object.keys(pendingDocs);
  const docGovActive = projectCfg?.governance?.enforceDocObligations === true;

  const isSecurityRule = (rule: string) => rule.startsWith('G0_') || ['POLICY_INTEGRITY', 'G2_SECURITY_TAMPERING', 'SHELL_SECURITY'].includes(rule);
  // Only engine-correlated recovery evidence counts; sharing a path is insufficient.
  const totalBlockedAnalyzed = eventsList.filter(e => e.outcome === 'BLOCKED' && !isSecurityRule(e.ruleId || '')).length;
  const recoveredCount = eventsList.filter(e => e.outcome === 'RECOVERED' && e.resolvedRuleId && !isSecurityRule(e.resolvedRuleId)).length;

  // --- TAB 4: INSIGHTS (TELEMETRY, AGENT RECOVERY, EFFECTIVENESS) ---
  const shortSess = sessionId.length > 10 ? sessionId.slice(0, 8) + '…' : sessionId;
  const eff = (data as any)?.effectiveness || {};
  const codeStats = Object.entries(eff.ruleStats || {}).filter(([rule]) => !isSecurityRule(rule)).map(([, stat]) => stat as any);
  const totalBlockedCount = typeof eff.totalCodeBlocked === 'number' ? eff.totalCodeBlocked : (codeStats.length ? codeStats.reduce((sum, s) => sum + (s.blocked || 0), 0) : totalBlockedAnalyzed);
  const totalRecoveredCount = typeof eff.totalCodeRecovered === 'number' ? eff.totalCodeRecovered : (codeStats.length ? codeStats.reduce((sum, s) => sum + Math.min(s.recovered || 0, s.blocked || 0), 0) : recoveredCount);
  const finalRecRate = typeof eff.codeFixRate === 'number' ? eff.codeFixRate
    : (totalBlockedCount > 0 ? Math.min(100, Math.round(totalRecoveredCount / totalBlockedCount * 100)) : 100);

  let recoverySubtext = '';
  if (totalBlockedCount === 0) {
    recoverySubtext = t('insights.subClean');
  } else if (totalBlockedCount < 10) {
    recoverySubtext = t('insights.subSample', { recovered: totalRecoveredCount, blocked: totalBlockedCount });
  } else {
    recoverySubtext = t('insights.subRate', { recovered: totalRecoveredCount, blocked: totalBlockedCount, rate: finalRecRate });
  }

  const ruleStats: Record<string, any> = eff.ruleStats || {};

  function formatRuleStat(ruleKey: string, defaultName: string, isWarning?: boolean) {
    const stat = ruleStats[ruleKey];
    const b = stat?.blocked || 0;
    const r = stat?.recovered || 0;
    const isSecurityBarrier = isSecurityRule(ruleKey);
    const rate = typeof stat?.recoveryRate === 'number' ? stat.recoveryRate : (b > 0 ? Math.round((r / b) * 100) : 100);
    const med = stat?.medianAttempts || 1;
    let badgeText = t('insights.badgeInsufficient', { n: b });
    let badgeClass = 'badge-neutral';
    let badgeIcon = lucide('circleDot', { size: 9 });

    if (isSecurityBarrier && b > 0) {
      badgeText = t('insights.badgeDeterrence', { n: b });
      badgeClass = 'badge-allowed';
      badgeIcon = lucide('shieldCheck', { size: 9 });
    } else if (b === 0) {
      badgeText = t('insights.badgeNoViolations');
      badgeClass = 'badge-allowed';
      badgeIcon = lucide('checkCircle', { size: 9 });
    } else if (b < 10) {
      badgeText = t('insights.badgeInsufficient', { n: b });
      badgeClass = 'badge-neutral';
      badgeIcon = lucide('circleDot', { size: 9 });
    } else if (b < 30) {
      badgeText = t('insights.badgeEarlySignal', { n: b });
      badgeClass = 'badge-warning';
      badgeIcon = lucide('alertTriangle', { size: 9 });
    } else if (rate >= 80) {
      badgeText = t('insights.badgeHighValue', { n: b });
      badgeClass = 'badge-allowed';
      badgeIcon = lucide('trophy', { size: 9 });
    } else if (rate < 50) {
      badgeText = t('insights.badgeFriction', { n: b });
      badgeClass = 'badge-blocked';
      badgeIcon = lucide('zap', { size: 9 });
    } else {
      badgeText = t('insights.badgeBalanced', { n: b });
      badgeClass = 'badge-cyan';
      badgeIcon = lucide('checkCircle', { size: 9 });
    }

    return {
      label: defaultName,
      b,
      r,
      rate,
      med,
      isWarning: !!isWarning,
      isSecurityBarrier,
      badgeText,
      badgeClass,
      badgeIcon
    };
  }

  const rulesToDisplay = [
    formatRuleStat('G0_SECRET_LEAK', t('rules.g0Title')),
    formatRuleStat('G1_SILENT_EXCEPTION', t('rules.g1Title')),
    formatRuleStat('G2_TEST_INTEGRITY', t('rules.g2Title')),
    formatRuleStat('G4_IMPORT_MATRIX', t('rules.g4Title')),
    formatRuleStat('SRP_BOUNDARY', t('rules.srpTitle')),
    formatRuleStat('ARCH_FILE_GROWTH', t('rules.growthTitle'), true),
    formatRuleStat('G3_COMPILER_BYPASS', t('rules.g3Title'), true)
  ];

  const knownKeys = new Set(['G0_SECRET_LEAK', 'G1_SILENT_EXCEPTION', 'G2_TEST_INTEGRITY', 'G4_IMPORT_MATRIX', 'SRP_BOUNDARY', 'ARCH_FILE_GROWTH', 'G3_COMPILER_BYPASS']);
  for (const k of Object.keys(ruleStats)) {
    if (!knownKeys.has(k) && (ruleStats[k]?.blocked > 0 || ruleStats[k]?.recovered > 0)) {
      rulesToDisplay.push(formatRuleStat(k, k));
    }
  }

  const lastEvent = (data.events && data.events.length > 0) ? data.events[0] : null;
  const latencyMatch = lastEvent?.reason?.match(/\((\d+(\.\d+)?ms)\)/);
  const measuredLatency = latencyMatch ? latencyMatch[1] : '< 1 ms';

  const lastSeq = (data as any)?.lastAuditSeq || 0;

  const growthRuleCfg = projectCfg?.rules?.['ARCH_FILE_GROWTH'];
  const isGrowthShadow = (typeof growthRuleCfg === 'object' && growthRuleCfg?.mode === 'shadow') || growthRuleCfg === 'shadow';

  const g3RuleCfg = projectCfg?.rules?.['G3_COMPILER_BYPASS'];
  const isG3Shadow = (typeof g3RuleCfg === 'object' && g3RuleCfg?.mode === 'shadow') || g3RuleCfg === 'shadow';

  const insightsHtml = `
      <div class="insight-card">
        <div class="insight-title"><span class="icon-inline">${lucide('target', { size: 12 })}</span> ${t('insights.recoveryTitle')}</div>
        <div class="recovery-meter">
          <div class="recovery-bar-wrap">
            <div class="recovery-bar" style="width: ${finalRecRate}%;"></div>
          </div>
          <div class="recovery-score">${totalBlockedCount === 0 ? '—' : `${finalRecRate}%`}</div>
        </div>
        <div class="insight-sub">${recoverySubtext}</div>
      </div>

      <div class="insight-card">
        <div class="insight-title"><span class="icon-inline">${lucide('shieldCheck', { size: 12 })}</span> ${t('insights.reportCardTitle')}</div>
        ${rulesToDisplay.map(st => `
          <div class="rule-stat-item">
            <div class="rule-stat-header">
              <span class="rule-stat-name">${escapeHtml(st.label)}</span>
              <span class="status-badge ${st.badgeClass}">${st.badgeIcon} ${st.badgeText}</span>
            </div>
            ${st.b > 0 ? `
              <div class="rule-stat-sub">
                <span>${st.isWarning ? t('insights.ruleWarnings', { count: st.b, rate: st.rate }) : (st.isSecurityBarrier ? t('insights.ruleDeterrence', { blocked: st.b, rate: st.rate }) : t('insights.ruleInterventions', { blocked: st.b, recovered: st.r, rate: st.rate }))}</span>
                ${!st.isWarning && !st.isSecurityBarrier ? `<span>${t('insights.medianAttempts', { attempts: st.med })}</span>` : ''}
              </div>
            ` : `<div class="rule-stat-sub text-muted">${t('insights.ruleClean')}</div>`}
          </div>
        `).join('')}
      </div>

      <div class="insight-card">
        <div class="insight-title"><span class="icon-inline">${lucide('alertTriangle', { size: 12 })}</span> ${t('insights.lifecycleTitle')}</div>
        <div class="metric-row">
          <span class="metric-lbl">${t('insights.t1Label')}</span>
          <span class="metric-val text-cyan">${testKeys.length > 0 ? t('insights.t1Pending', { count: testKeys.length }) : t('insights.t1Verified')}</span>
        </div>
        <div class="metric-row">
          <span class="metric-lbl">${t('insights.docLabel')}</span>
          <span class="metric-val ${docGovActive ? 'text-green' : 'text-muted'}">${docGovActive ? (docKeys.length > 0 ? t('insights.docPending', { count: docKeys.length }) : t('insights.docActive')) : t('insights.docDisabled')}</span>
        </div>
        <div class="metric-row">
          <span class="metric-lbl">${t('insights.growthLabel')}</span>
          <span class="metric-val ${isGrowthShadow ? 'text-purple' : 'text-amber'}">${isGrowthShadow ? t('insights.growthValueShadow') : t('insights.growthValueWarn')}</span>
        </div>
        <div class="metric-row">
          <span class="metric-lbl">${t('insights.g3Label')}</span>
          <span class="metric-val ${isG3Shadow ? 'text-purple' : 'text-amber'}">${isG3Shadow ? t('insights.g3ValueShadow') : t('insights.g3Value')}</span>
        </div>
      </div>

      <details class="diagnostics-details">
        <summary class="diagnostics-summary">
          <span class="summary-left">
            <span class="icon-inline">${lucide('settings', { size: 11, color: 'var(--text-muted)' })}</span>
            <span class="diagnostics-title">${t('insights.diagnosticsTitle')}</span>
          </span>
          <span class="status-badge badge-neutral" style="font-size: 8px; padding: 1px 5px;">
            ${lucide('database', { size: 8 })} ${t('insights.diagnosticsBadge')}
          </span>
        </summary>
        <div class="diagnostics-body">
          <div class="insight-card" style="margin-top: 6px;">
            <div class="insight-title"><span class="icon-inline">${lucide('database', { size: 12 })}</span> ${t('insights.walTitle')}</div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.walJournalLabel')}</span>
              <span class="metric-val text-green"><span class="icon-inline">${lucide('circleDot', { size: 9, color: 'var(--color-green)' })}</span> ${t('insights.walJournalValue')}</span>
            </div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.walLiveLabel')}</span>
              <span class="metric-val text-cyan"><span class="icon-inline">${lucide('circleDot', { size: 9, color: 'var(--color-cyan)' })}</span> ${t('insights.walLiveValue', { seq: lastSeq })}</span>
            </div>
          </div>

          <div class="insight-card">
            <div class="insight-title"><span class="icon-inline">${lucide('cpu', { size: 12 })}</span> ${t('insights.perfTitle')}</div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.latencyFast')}:</span>
              <span class="metric-val text-green">${measuredLatency}</span>
            </div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.latencySpawn')}:</span>
              <span class="metric-val text-muted">${t('insights.spawnBudget')}</span>
            </div>
          </div>

          <div class="insight-card">
            <div class="insight-title"><span class="icon-inline">${lucide('lock', { size: 12 })}</span> ${t('insights.integrityTitle')}</div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.lockStatus')}:</span>
              <span class="metric-val text-green"><span class="icon-inline">${lucide('checkCircle', { size: 10, color: 'var(--color-green)' })}</span> ${t('insights.lockHealthy')}</span>
            </div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.twoPhase')}:</span>
              <span class="metric-val text-green"><span class="icon-inline">${lucide('checkCircle', { size: 10, color: 'var(--color-green)' })}</span> ${t('insights.twoPhaseActive')}</span>
            </div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.sessionLabel')}</span>
              <span class="metric-val text-cyan">${shortSess}</span>
            </div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.circuitLabel')}</span>
              <span class="metric-val text-muted">${t('insights.circuitValue', { retries: stopRetries })}</span>
            </div>
          </div>
        </div>
      </details>
    `;
  return insightsHtml;
}
