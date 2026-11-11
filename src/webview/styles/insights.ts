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

          /* Insights v2: window selector, trend, agents, drill-down */
          .ins-seg { display: flex; gap: 2px; padding: 2px; margin-bottom: 8px; background: var(--bg-card); border: 1px solid var(--border-dim); border-radius: 6px; }
          .ins-seg-btn { flex: 1; background: transparent; border: 0; color: var(--text-muted); font: inherit; font-size: 10px; font-weight: 700; padding: 4px 6px; border-radius: 4px; cursor: pointer; }
          .ins-seg-btn:hover { background: var(--bg-hover); color: var(--text-main); }
          body:not([data-sel-window]) .ins-seg-btn[data-value="7d"],
          body[data-sel-window="24h"] .ins-seg-btn[data-value="24h"],
          body[data-sel-window="7d"] .ins-seg-btn[data-value="7d"],
          body[data-sel-window="30d"] .ins-seg-btn[data-value="30d"],
          body[data-sel-window="all"] .ins-seg-btn[data-value="all"] { background: var(--bg-hover); color: var(--color-cyan); }
          .ins-win { display: none; }
          body:not([data-sel-window]) .ins-win-7d,
          body[data-sel-window="24h"] .ins-win-24h,
          body[data-sel-window="7d"] .ins-win-7d,
          body[data-sel-window="30d"] .ins-win-30d,
          body[data-sel-window="all"] .ins-win-all { display: block; }
          .metric-row.ins-win { display: none; }
          body:not([data-sel-window]) .metric-row.ins-win-7d,
          body[data-sel-window="24h"] .metric-row.ins-win-24h,
          body[data-sel-window="7d"] .metric-row.ins-win-7d,
          body[data-sel-window="30d"] .metric-row.ins-win-30d,
          body[data-sel-window="all"] .metric-row.ins-win-all { display: flex; }

          .ins-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; margin: 8px 0 6px; }
          .ins-stat { text-align: center; padding: 5px 2px; background: rgba(255,255,255,0.03); border-radius: 4px; }
          .ins-stat-val { font-size: 14px; font-weight: 800; line-height: 1.1; }
          .ins-stat-lbl { font-size: 8.5px; color: var(--text-muted); margin-top: 2px; }
          .ins-sig-val { font-weight: 800; }
          .ins-note { margin-top: 4px; line-height: 1.4; }

          .ins-trend-head { display: flex; align-items: center; gap: 10px; font-size: 9px; color: var(--text-muted); margin-bottom: 4px; flex-wrap: wrap; }
          .ins-legend b { color: var(--text-main); font-weight: 800; }
          .ins-key { display: inline-block; width: 7px; height: 7px; border-radius: 2px; margin-right: 4px; }
          .ins-key-block, .ins-tr-block { background: var(--color-red); fill: var(--color-red); }
          .ins-key-warn, .ins-tr-warn { background: var(--color-amber); fill: var(--color-amber); }
          .ins-tr-warn { fill-opacity: 0.85; }
          .ins-tr-zero { fill: var(--border-dim); }
          .ins-tr-grid { stroke: var(--border-dim); stroke-width: 0.5; stroke-dasharray: 2 2; vector-effect: non-scaling-stroke; }
          .ins-peak { margin-left: auto; }
          .ins-trend { display: block; width: 100%; height: 56px; }
          .ins-trend-axis { display: flex; justify-content: space-between; font-size: 8.5px; color: var(--text-muted); margin-top: 2px; }

          .ins-agents { width: 100%; border-collapse: collapse; font-size: 9.5px; table-layout: fixed; }
          .ins-agents th { text-align: right; font-weight: 700; color: var(--text-muted); font-size: 8.5px; padding: 0 3px 4px; border-bottom: 1px solid var(--border-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
          .ins-agents th:last-child { width: 24%; }
          .ins-agents td { text-align: right; padding: 5px 3px; border-bottom: 1px solid var(--border-dim); font-variant-numeric: tabular-nums; }
          .ins-agents tr:last-child td { border-bottom: 0; }
          .ins-agents th:first-child, .ins-agents td:first-child { text-align: left; width: 34%; padding-left: 0; }
          .ins-agent-name { font-weight: 700; font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
          .ins-agent-sub { font-size: 8.5px; color: var(--text-muted); }
          .ins-strong { font-weight: 800; }

          .ins-rule { padding: 0; }
          .ins-rh { padding: 6px 0; cursor: pointer; border-radius: 4px; }
          .ins-rh:hover { background: var(--bg-hover); }
          .ins-rh-open { display: none; }
          .ins-drill { display: none; padding: 2px 0 8px 12px; border-left: 1px solid var(--border-dim); margin-left: 4px; }
          .ins-drill-title { font-size: 8.5px; font-weight: 800; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.4px; margin: 2px 0 4px 6px; }
          .ins-chev { display: inline-flex; vertical-align: middle; margin-right: 3px; color: var(--text-muted); transition: transform 0.12s; }
          .ins-rh-open .ins-chev { transform: rotate(90deg); }
          .ins-badge-wrap { display: inline-flex; align-items: center; gap: 5px; flex-shrink: 0; }
          .ins-n { font-size: 8.5px; color: var(--text-muted); }
          .ins-fix { white-space: nowrap; }
          .ins-signals { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 3px; }
          .ins-sig { font-size: 8.5px; font-weight: 700; padding: 1px 5px; border-radius: 3px; }
          .ins-sig-evasion { background: rgba(192, 132, 252, 0.15); color: var(--color-purple); }
          .ins-sig-fa { background: rgba(56, 189, 248, 0.15); color: var(--color-cyan); }
          .rule-stat-header { gap: 6px; }
          .rule-stat-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

          .ins-ev { padding: 5px 6px; border-radius: 4px; }
          .ins-ev:nth-child(even) { background: rgba(255,255,255,0.025); }
          .ins-ev-fa { opacity: 0.6; }
          .ins-ev-top { display: flex; justify-content: space-between; align-items: center; gap: 6px; }
          .ins-ev-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; font-size: 9px; color: var(--text-muted); min-width: 0; }
          .ins-ev-status { font-size: 8.5px; padding: 1px 5px; }
          .ins-ev-agent { color: var(--text-main); }
          .ins-sess { font-family: var(--vscode-editor-font-family, monospace); font-size: 8.5px; }
          .ins-fa-btn { flex-shrink: 0; font-size: 8.5px; padding: 2px 5px; }
          .ins-ev-file { font-size: 10px; font-weight: 700; margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
          .ins-ev-reason { font-size: 9px; color: var(--text-muted); margin-top: 1px; line-height: 1.35; word-break: break-word; }

          .ins-low { margin-top: 6px; border-top: 1px solid var(--border-dim); }
          .ins-low-head { padding: 7px 0; font-size: 10px; font-weight: 700; color: var(--text-muted); cursor: pointer; }
          .ins-low-head:hover { color: var(--text-main); }
          .ins-low-open { display: none; }
          .ins-low-open .ins-chev { transform: rotate(90deg); }
          .ins-low-body { display: none; }
          body[data-sel-lowdata="open"] .ins-low-closed { display: none; }
          body[data-sel-lowdata="open"] .ins-low-open { display: block; }
          body[data-sel-lowdata="open"] .ins-low-body { display: block; }

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
          .hook-card { background: rgba(15, 23, 42, 0.72); border: 1px solid rgba(148, 163, 184, 0.18); border-top: 2px solid var(--color-amber); border-radius: 8px; padding: 11px 12px; margin: 8px 0; box-shadow: 0 4px 14px rgba(0, 0, 0, 0.28); }
          .hook-card.hook-invalid { border-color: rgba(239, 68, 68, 0.5); }
          .hook-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
          .hook-id { font-weight: 600; font-size: 11px; }
          .hook-field { display: flex; gap: 6px; font-size: 10px; margin: 3px 0; align-items: baseline; }
          .hook-label { color: var(--text-muted); min-width: 56px; flex-shrink: 0; }
          .hook-value { font-size: 9.5px; word-break: break-all; white-space: pre-wrap; background: rgba(6, 9, 17, 0.78); border: 1px solid rgba(148, 163, 184, 0.14); border-radius: 5px; padding: 4px 7px; color: #e2e8f0; }
          .hook-text { font-size: 10.5px; line-height: 1.4; }
          .hook-error { color: #ef4444; font-size: 10px; margin: 6px 0; }
          .hook-diff { font-size: 9.5px; line-height: 1.45; margin: 6px 0; padding: 6px; border-radius: 4px; background: rgba(0,0,0,0.25); overflow-x: auto; white-space: pre; }
          .hook-diff .diff-add { color: #10b981; }
          .hook-diff .diff-del { color: #ef4444; }
          .hook-diff .diff-hunk { color: #38bdf8; }
          .hook-diff .diff-ctx { color: var(--text-muted); }
          .hook-actions { display: flex; gap: 6px; margin-top: 6px; }
          .hook-approve { background: rgba(16, 185, 129, 0.16); border-color: rgba(16, 185, 129, 0.55); color: #34d399; font-weight: 700; }
          .hook-approve:hover { background: #10b981; color: #042f2e; }
          .hook-installed { display: flex; gap: 6px; align-items: center; font-size: 10px; margin: 4px 0; }
          .hook-installed .hook-value { flex: 1; }
          .hook-hint { color: var(--text-muted); font-size: 9.5px; margin-top: 12px; }
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
