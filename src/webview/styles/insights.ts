// Webview CSS part 3/3: diagnostics and system health, insights, and shared helper classes.
// Original source: GravityGuard sidebar HTML template <style> block (indentation kept byte-exact).
export const INSIGHTS_STYLES = `\
          /* Diagnostics & System Health (Collapsible) */
          .diagnostics-details {
            margin-top: 10px;
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid var(--border-dim);
            border-radius: 6px;
            overflow: hidden;
          }
          .diagnostics-summary {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 6px 8px;
            cursor: pointer;
            user-select: none;
            font-size: 9px;
            font-weight: 700;
            color: var(--text-muted);
          }
          .diagnostics-summary:hover {
            background: var(--bg-hover);
            color: var(--text-main);
          }
          .diagnostics-title {
            font-size: 9px;
            font-weight: 800;
            letter-spacing: 0.3px;
          }
          .diagnostics-body {
            padding: 6px 8px 8px 8px;
            border-top: 1px solid var(--border-dim);
          }
          .telemetry-alert-banner {
            background: rgba(245, 158, 11, 0.15);
            border: 1px solid var(--color-amber);
            color: #fbbf24;
            padding: 6px 8px;
            border-radius: 6px;
            margin-bottom: 8px;
            font-size: 10px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 6px;
          }
          .recovery-flow-row {
            display: inline-flex;
            align-items: center;
            gap: 4px;
          }

          /* Insights */
          .insight-card {
            background: var(--bg-card);
            border: 1px solid var(--border-dim);
            border-radius: 6px;
            padding: 8px;
            margin-bottom: 8px;
          }
          .insight-title { font-weight: 800; font-size: 10px; color: var(--color-cyan); margin-bottom: 6px; }
          .recovery-meter { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
          .recovery-bar-wrap { flex: 1; height: 6px; background: rgba(255, 255, 255, 0.1); border-radius: 3px; overflow: hidden; }
          .recovery-bar { height: 100%; background: var(--color-green); border-radius: 3px; }
          .recovery-score { font-size: 12px; font-weight: 900; color: var(--color-green); }
          .insight-sub { font-size: 9px; color: var(--text-muted); }
          .metric-row { display: flex; justify-content: space-between; font-size: 9px; padding: 2px 0; }
          .metric-lbl { color: var(--text-muted); }
          .metric-val { font-weight: 700; }
          .rule-stat-item {
            padding: 6px 0;
            border-bottom: 1px solid var(--border-dim);
          }
          .rule-stat-item:last-child {
            border-bottom: none;
          }
          .rule-stat-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 3px;
          }
          .rule-stat-name {
            font-weight: 700;
            font-size: 10px;
            color: var(--text-main);
          }
          .rule-stat-sub {
            display: flex;
            justify-content: space-between;
            font-size: 9px;
            color: var(--text-muted);
          }

          /* Helpers */
          .text-green { color: var(--color-green); }
          .text-red { color: var(--color-red); }
          .text-amber { color: var(--color-amber); }
          .text-cyan { color: var(--color-cyan); }
          .text-purple { color: var(--color-purple); }
          .text-muted { color: var(--text-muted); }
          .section-title { font-size: 9px; font-weight: 800; text-transform: uppercase; margin-bottom: 6px; letter-spacing: 0.4px; }
          .circuit-box { margin-top: 8px; padding: 6px 8px; background: rgba(0,0,0,0.2); border-radius: 4px; display: flex; justify-content: space-between; font-size: 9px; color: var(--text-muted); }
          .clean-state-box { text-align: center; padding: 20px 8px; border: 1px dashed rgba(16, 185, 129, 0.25); border-radius: 8px; background: rgba(16, 185, 129, 0.04); }
          .clean-state-title { font-weight: 700; font-size: 10px; color: var(--color-green); margin-top: 6px; }
          .empty-state { text-align: center; color: var(--text-muted); padding: 20px; font-size: 10px; }
          .icon-inline {
            display: inline-flex;
            align-items: center;
            vertical-align: middle;
            margin-right: 3px;
          }
          .pill-row {
            display: inline-flex;
            align-items: center;
            gap: 4px;
          }
          .idle-inline {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            justify-content: center;
          }`;
