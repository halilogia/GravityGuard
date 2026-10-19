// Webview CSS part 2/3: stream list, drawer accordion, task and state machine track, rules group.
// Original source: GravityGuard sidebar HTML template <style> block (indentation kept byte-exact).
export const STREAM_STYLES = `\
          /* Stream List */
          .stream-item {
            margin-bottom: 4px;
            background: var(--bg-card);
            border: 1px solid var(--border-dim);
            border-radius: 4px;
            overflow: hidden;
          }
          .stream-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 6px 8px;
            cursor: pointer;
            user-select: none;
          }
          .stream-row:hover { background: var(--bg-hover); }
          .stream-left { display: flex; align-items: center; gap: 6px; overflow: hidden; }
          .stream-file {
            font-weight: 600;
            font-size: 10px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 140px;
          }
          .stream-right { display: flex; align-items: center; gap: 6px; }
          .stream-rule { font-size: 9px; color: var(--text-muted); }
          .stream-time { font-size: 8px; color: var(--text-muted); }
          .agent-pill {
            display: inline-flex;
            align-items: center;
            gap: 3px;
            padding: 1px 6px;
            border-radius: 8px;
            font-size: 8px;
            font-weight: 600;
            white-space: nowrap;
            border: 1px solid transparent;
          }
          .agent-claude {
            background: rgba(217, 119, 87, 0.15);
            border-color: rgba(217, 119, 87, 0.55);
            color: #e8956f;
          }
          .agent-codex {
            background: rgba(148, 163, 184, 0.15);
            border-color: rgba(148, 163, 184, 0.55);
            color: #94a3b8;
          }
          .agent-antigravity,
          .agent-antigravity-ide {
            background: rgba(34, 211, 238, 0.12);
            border-color: rgba(34, 211, 238, 0.5);
            color: #5ccfe6;
          }
          .agent-antigravity-cli {
            background: rgba(168, 85, 247, 0.15);
            border-color: rgba(168, 85, 247, 0.55);
            color: #c084fc;
          }
          .agent-opencode {
            background: #000000;
            border-color: #3f3f46;
            color: #ffffff;
          }
          .agent-aider {
            background: rgba(239, 68, 68, 0.15);
            border-color: rgba(239, 68, 68, 0.55);
            color: #f87171;
          }
          .agent-freebuff {
            background: rgba(6, 182, 212, 0.15);
            border-color: rgba(6, 182, 212, 0.55);
            color: #22d3ee;
          }
          .agent-antigravity-sdk {
            background: rgba(16, 185, 129, 0.15);
            border-color: rgba(16, 185, 129, 0.55);
            color: #34d399;
          }

          /* Drawer Accordion */
          .stream-drawer {
            padding: 8px;
            background: rgba(0, 0, 0, 0.3);
            border-top: 1px solid var(--border-dim);
          }
          .drawer-header { display: flex; justify-content: space-between; margin-bottom: 4px; }
          .drawer-meta-pill {
            margin-bottom: 6px;
            padding: 4px 6px;
            border-radius: 4px;
            font-size: 9px;
            display: flex;
            flex-direction: column;
            gap: 2px;
          }
          .drawer-meta-pill.bg-cyan {
            background: rgba(56, 189, 248, 0.12);
            border: 1px solid rgba(56, 189, 248, 0.25);
            color: #bae6fd;
          }
          .drawer-meta-pill.bg-purple {
            background: rgba(192, 132, 252, 0.12);
            border: 1px solid rgba(192, 132, 252, 0.25);
            color: #e9d5ff;
          }
          .drawer-rule { font-weight: 800; font-size: 10px; color: var(--color-cyan); }
          .drawer-target { font-size: 9px; color: var(--text-muted); word-break: break-all; margin-bottom: 4px; }
          .drawer-reason { font-size: 10px; color: #cbd5e1; line-height: 1.4; margin-bottom: 6px; }
          .drawer-buttons { display: flex; gap: 4px; }
          .action-btn {
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid var(--border-dim);
            color: var(--text-main);
            font-size: 9px;
            font-weight: 600;
            padding: 3px 6px;
            border-radius: 3px;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 4px;
          }
          .action-btn:hover { background: rgba(255, 255, 255, 0.16); }
          .action-btn.wide { width: 100%; padding: 6px; }

          /* Task & State Machine Track */
          .task-card {
            background: var(--bg-card);
            border: 1px solid var(--border-dim);
            border-radius: 6px;
            padding: 8px;
            margin-bottom: 8px;
          }
          .task-card.border-cyan { border-left: 3px solid var(--color-cyan); }
          .task-card.border-amber { border-left: 3px solid var(--color-amber); }
          .task-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
          .task-title { font-weight: 700; font-size: 11px; word-break: break-all; }
          .mini-icon-btn { background: none; border: none; cursor: pointer; font-size: 10px; padding: 2px; }
          .task-meta { font-size: 9px; color: var(--text-muted); margin-bottom: 6px; }
          .state-track {
            display: flex;
            align-items: center;
            gap: 2px;
            background: rgba(0, 0, 0, 0.3);
            padding: 4px;
            border-radius: 4px;
            margin-bottom: 4px;
          }
          .track-step {
            flex: 1;
            font-size: 7px;
            font-weight: 800;
            text-align: center;
            padding: 2px 1px;
            border-radius: 2px;
          }
          .step-done { background: rgba(16, 185, 129, 0.2); color: var(--color-green); }
          .step-active { background: var(--color-cyan); color: #0b1120; font-weight: 900; }
          .step-todo { color: rgba(255, 255, 255, 0.25); }
          .track-arrow { font-size: 7px; color: rgba(255, 255, 255, 0.3); }
          .track-status-hint { font-size: 9px; color: var(--text-muted); }

          /* Rules Group */
          .rules-group {
            background: var(--bg-card);
            border: 1px solid var(--border-dim);
            border-radius: 6px;
            padding: 8px;
            margin-bottom: 8px;
          }
          .group-title { font-weight: 800; font-size: 10px; margin-bottom: 6px; }
          .rule-row { display: flex; justify-content: space-between; align-items: center; margin-top: 6px; }
          .rule-name { font-weight: 700; font-size: 10px; }
          .rule-desc { font-size: 9px; color: var(--text-muted); line-height: 1.3; margin-top: 2px; }
          .mode-pill { font-size: 8px; font-weight: 800; padding: 1px 5px; border-radius: 3px; display: inline-flex; align-items: center; gap: 3px; }
          .mode-block { background: rgba(239, 68, 68, 0.15); color: var(--color-red); }
          .mode-warn { background: rgba(245, 158, 11, 0.15); color: var(--color-amber); }
          .mode-shadow { background: rgba(192, 132, 252, 0.15); color: var(--color-purple); border: 1px solid rgba(192, 132, 252, 0.3); }
          .mode-active { background: rgba(16, 185, 129, 0.15); color: var(--color-green); }
          .mode-inactive { background: rgba(255, 255, 255, 0.05); color: var(--text-muted); }
`;
