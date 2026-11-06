// Webview CSS part 4: verification gate card on the Live tab. Hairline rows, status only in a dot and a word.
export const GATE_STYLES = `\
          .gate-card {
            border: 1px solid var(--border-dim);
            border-radius: 6px;
            padding: 8px 8px 4px;
            margin-bottom: 8px;
          }
          .gate-hdr {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-bottom: 4px;
          }
          .gate-tag {
            font-size: 9px;
            font-weight: 600;
            letter-spacing: .08em;
            color: var(--text-muted);
          }
          .gate-row {
            display: grid;
            grid-template-columns: 8px 12px auto 1fr auto 32px;
            align-items: center;
            column-gap: 8px;
            min-height: 24px;
            border-top: 1px solid var(--border-dim);
          }
          .gate-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
          }
          .gate-pass { background: var(--color-green); }
          .gate-fail { background: var(--color-red); }
          .gate-warn { background: var(--color-amber); }
          .gate-pending { border: 1px solid var(--text-muted); }
          .gate-step { color: var(--text-muted); font-variant-numeric: tabular-nums; }
          .gate-name { white-space: nowrap; }
          .gate-detail {
            color: var(--text-muted);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            min-width: 0;
          }
          .gate-state { font-size: 10px; font-weight: 500; white-space: nowrap; }
          .gate-text-pass { color: var(--color-green); }
          .gate-text-fail { color: var(--color-red); }
          .gate-text-warn { color: var(--color-amber); }
          .gate-text-pending { color: var(--text-muted); }
          .gate-time {
            color: var(--text-muted);
            font-size: 9px;
            text-align: right;
            font-variant-numeric: tabular-nums;
          }
          .gate-hint {
            border-top: 1px solid var(--border-dim);
            padding: 6px 0 2px;
            color: var(--text-muted);
            font-size: 10px;
          }
`;
