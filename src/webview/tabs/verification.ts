import { t } from '../../i18n';
import { escapeHtml } from '../html_utils';
import { GateStage, GateStatus, overallGateStatus } from '../../verification_gate';

function shortTime(stamp: string | undefined): string {
  if (!stamp) {
    return '';
  }
  const ms = Date.parse(stamp.includes('T') ? stamp : stamp.replace(' ', 'T'));
  if (!Number.isFinite(ms)) {
    return '';
  }
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function statusLabel(status: GateStatus): string {
  return t(`gate.status.${status}`);
}

/** Live tab card: one row per verification stage, worst status in the header. */
export function renderVerificationGateCard(stages: GateStage[] | undefined): string {
  if (!stages || stages.length === 0) {
    return '';
  }
  const overall = overallGateStatus(stages);
  const allPending = stages.every(s => s.status === 'pending');
  const rows = stages.map((s, idx) => {
    const detail = s.stale ? t('gate.stale') : (s.detail || '');
    return `
          <div class="gate-row" title="${escapeHtml(s.detail || '')}">
            <span class="gate-dot gate-${s.status}"></span>
            <span class="gate-step">${idx + 1}</span>
            <span class="gate-name">${t(`gate.stages.${s.id}`)}</span>
            <span class="gate-detail">${escapeHtml(detail)}</span>
            <span class="gate-state gate-text-${s.status}">${statusLabel(s.status)}</span>
            <span class="gate-time">${shortTime(s.at)}</span>
          </div>`;
  }).join('');
  return `
        <div class="gate-card">
          <div class="gate-hdr">
            <span class="gate-tag">${t('gate.title')}</span>
            <span class="gate-state gate-text-${overall}">${statusLabel(overall)}</span>
          </div>
          ${rows}
          ${allPending ? `<div class="gate-hint">${t('gate.hint')}</div>` : ''}
        </div>
      `;
}
