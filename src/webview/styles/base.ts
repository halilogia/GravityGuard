// Webview CSS part 1/3: theme variables, base layout, header, current action card, stat row and tabs.
// Original source: GravityGuard sidebar HTML template <style> block (indentation kept byte-exact).
export const BASE_STYLES = `\
          :root {
            --bg-base: var(--vscode-editor-background, #0b1120);
            --bg-card: rgba(255, 255, 255, 0.04);
            --bg-hover: rgba(255, 255, 255, 0.08);
            --border-dim: rgba(255, 255, 255, 0.08);
            --text-main: var(--vscode-editor-foreground, #f8fafc);
            --text-muted: #94a3b8;
            --color-green: #10b981;
            --color-red: #ef4444;
            --color-amber: #f59e0b;
            --color-cyan: #38bdf8;
            --color-purple: #c084fc;
          }
          * { box-sizing: border-box; }
          body {
            font-family: var(--vscode-font-family, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif);
            font-size: 11px;
            color: var(--text-main);
            background: var(--bg-base);
            margin: 0;
            padding: 8px 10px;
          }

          /* Header */
          .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border-dim);
            margin-bottom: 8px;
          }
          .header-left {
            display: flex;
            align-items: center;
            gap: 6px;
          }
          .brand-title {
            font-size: 12px;
            font-weight: 800;
            color: var(--color-cyan);
            letter-spacing: 0.4px;
          }
          .project-pill {
            font-size: 9px;
            color: var(--text-muted);
            background: rgba(255, 255, 255, 0.05);
            padding: 2px 6px;
            border-radius: 4px;
          }
          .header-right {
            display: flex;
            gap: 4px;
          }
          .mini-btn {
            background: var(--bg-card);
            border: 1px solid var(--border-dim);
            color: var(--text-muted);
            font-size: 9px;
            font-weight: 700;
            padding: 3px 6px;
            border-radius: 4px;
            cursor: pointer;
            transition: all 0.15s;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 4px;
          }
          .mini-btn:hover {
            background: var(--bg-hover);
            color: var(--text-main);
          }

          /* Current Action Card */
          .current-card {
            background: var(--bg-card);
            border: 1px solid var(--border-dim);
            border-radius: 6px;
            padding: 8px;
            margin-bottom: 8px;
          }
          .current-card.border-allowed { border-left: 3px solid var(--color-green); }
          .current-card.border-blocked { border-left: 3px solid var(--color-red); }
          .current-card.border-warning { border-left: 3px solid var(--color-amber); }
          .current-card.border-neutral { border-left: 3px solid var(--text-muted); }
          
          .current-hdr {
            display: flex;
            justify-content: space-between;
            font-size: 9px;
            font-weight: 800;
            color: var(--text-muted);
            margin-bottom: 4px;
          }
          .current-action-line {
            display: flex;
            align-items: center;
            gap: 6px;
            margin-bottom: 6px;
            word-break: break-all;
          }
          .current-tool {
            font-weight: 700;
            color: var(--text-muted);
            font-size: 10px;
          }
          .current-target {
            font-weight: 700;
            color: var(--text-main);
            font-size: 11px;
          }
          .current-badge-row {
            display: flex;
            align-items: center;
            gap: 6px;
          }
          .status-badge {
            font-size: 9px;
            font-weight: 800;
            padding: 2px 6px;
            border-radius: 3px;
            display: inline-flex;
            align-items: center;
            gap: 4px;
          }
          .badge-allowed { background: rgba(16, 185, 129, 0.15); color: var(--color-green); }
          .badge-blocked { background: rgba(239, 68, 68, 0.15); color: var(--color-red); }
          .badge-warning { background: rgba(245, 158, 11, 0.15); color: var(--color-amber); }
          .badge-purple { background: rgba(192, 132, 252, 0.15); color: var(--color-purple); }
          .badge-cyan { background: rgba(56, 189, 248, 0.15); color: var(--color-cyan); }
          .badge-neutral { background: rgba(255, 255, 255, 0.08); color: var(--text-muted); }
          .current-rule-badge {
            font-size: 9px;
            font-weight: 700;
            color: var(--text-muted);
            background: rgba(255, 255, 255, 0.05);
            padding: 2px 5px;
            border-radius: 3px;
          }
          .current-reason-text {
            font-size: 10px;
            color: #cbd5e1;
            margin-top: 5px;
            line-height: 1.35;
            background: rgba(0, 0, 0, 0.2);
            padding: 4px 6px;
            border-radius: 4px;
          }
          .current-idle {
            color: var(--text-muted);
            font-size: 10px;
            padding: 6px 0;
            text-align: center;
          }

          /* Stat Row */
          .stat-summary-bar {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(55px, 1fr));
            gap: 4px;
            margin-bottom: 8px;
          }
          .stat-chip {
            background: var(--bg-card);
            border: 1px solid var(--border-dim);
            padding: 4px 6px;
            border-radius: 4px;
            text-align: center;
          }
          .chip-val { font-size: 12px; font-weight: 800; }
          .chip-lbl { font-size: 8px; color: var(--text-muted); text-transform: uppercase; margin-top: 1px; }

          /* Tabs */
          .tabs-bar {
            display: flex;
            background: rgba(0, 0, 0, 0.25);
            padding: 2px;
            border-radius: 6px;
            margin-bottom: 8px;
            border: 1px solid var(--border-dim);
          }
          .tab-btn {
            flex: 1;
            padding: 5px 2px;
            background: transparent;
            border: none;
            color: var(--text-muted);
            font-size: 10px;
            font-weight: 700;
            border-radius: 4px;
            cursor: pointer;
            text-align: center;
            transition: all 0.15s;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 4px;
          }
          .tab-btn.active {
            background: var(--color-cyan);
            color: #0b1120;
            font-weight: 800;
          }
          .tab-pane { display: none; }
          .tab-pane.active { display: block; }
          .badge-counter {
            background: rgba(239, 68, 68, 0.3);
            color: #f87171;
            font-size: 8px;
            padding: 1px 4px;
            border-radius: 6px;
            margin-left: 2px;
          }
`;
