// Webview CSS for the Rules tab (grouped, collapsible rule rows). Pill colours come from the shared .mode-* classes.
export const RULES_STYLES = `\
          .rl-summary { padding: 2px 2px 8px; font-size: 11px; line-height: 1.45; }
          .rl-summary-sub { color: var(--text-muted); font-size: 10px; margin-top: 1px; }
          .rl-group { margin-bottom: 10px; }
          .rl-group-title { font-size: 9px; font-weight: 800; letter-spacing: 0.5px; text-transform: uppercase; color: var(--text-muted); padding: 0 2px 4px; }
          .rl-group-hint { font-size: 9px; color: var(--text-muted); padding: 0 2px 4px; }
          .rl-item { border-top: 1px solid var(--border-dim); }
          .rl-item:last-child { border-bottom: 1px solid var(--border-dim); }
          .rl-item summary { list-style: none; cursor: pointer; display: grid; grid-template-columns: 12px 1fr auto; column-gap: 4px; align-items: center; padding: 6px 2px; color: var(--text-main); }
          .rl-item summary::-webkit-details-marker { display: none; }
          .rl-item summary:hover { background: var(--bg-hover); }
          .rl-chev { display: inline-flex; color: var(--text-muted); transition: transform 0.15s; }
          .rl-item[open] .rl-chev { transform: rotate(90deg); }
          .rl-main { display: flex; flex-direction: column; min-width: 0; }
          .rl-title { font-size: 11px; font-weight: 700; overflow-wrap: anywhere; }
          .rl-id { font-size: 8px; color: var(--text-muted); opacity: 0.8; font-family: var(--vscode-editor-font-family, monospace); overflow-wrap: anywhere; }
          .rl-side { display: inline-flex; align-items: center; gap: 6px; }
          .rl-count { min-width: 18px; text-align: right; font-size: 12px; font-weight: 800; font-variant-numeric: tabular-nums; }
          .rl-meta { grid-column: 2 / 4; font-size: 9px; color: var(--text-muted); min-height: 0; }
          .rl-meta:empty { display: none; }
          .rl-item.quiet .rl-title { font-weight: 600; color: var(--text-muted); }
          .rl-item.quiet .rl-count { font-weight: 500; color: var(--text-muted); }
          .rl-item.quiet .mode-pill { opacity: 0.65; }
          .rl-body { padding: 2px 4px 10px 16px; }
          .rl-desc { font-size: 10px; color: #cbd5e1; line-height: 1.45; }
          .rl-stage { font-size: 9px; color: var(--text-muted); margin-top: 4px; }
          .rl-modes { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }
          .rl-mode-btn { background: var(--bg-card); border: 1px solid var(--border-dim); color: var(--text-muted); font-size: 9px; font-weight: 600; padding: 3px 8px; border-radius: 3px; cursor: pointer; }
          .rl-mode-btn:hover { background: var(--bg-hover); color: var(--text-main); }
          .rl-mode-btn.active { background: rgba(56, 189, 248, 0.15); border-color: rgba(56, 189, 248, 0.4); color: var(--color-cyan); }
          .rl-note { display: flex; align-items: center; gap: 5px; font-size: 9px; color: var(--text-muted); margin-top: 8px; }
          .rl-footer { margin-top: 12px; }
`;
