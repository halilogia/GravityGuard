// In-webview client script (acquireVsCodeApi, tab state, CSP-compliant event delegation).
import { escapeJs } from './html_utils';

/**
 * Returns the `<script nonce="...">...</script>` block injected into the sidebar webview HTML.
 * Starts with `<script` (no leading indentation); the layout is responsible for indenting the first line.
 */
export function buildClientScript(nonce: string, activeTab: string): string {
  return `<script nonce="${nonce}">
          const vscode = acquireVsCodeApi();
          const savedState = vscode.getState() || {};
          let currentTab = savedState.currentTab || '${escapeJs(activeTab)}';

          // In-place dynamic DOM replacement without iframe reload (eliminates InvalidStateError)
          window.addEventListener('message', (event) => {
            const msg = event.data;
            if (msg && msg.type === 'updateContent' && msg.bodyHtml) {
              const root = document.getElementById('guardian-app-root');
              if (root) {
                root.innerHTML = msg.bodyHtml;
                const state = vscode.getState() || {};
                const active = state.currentTab || currentTab;
                if (active) {
                  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
                  const b = document.getElementById('btn-' + active);
                  const p = document.getElementById('tab-' + active);
                  if (b) b.classList.add('active');
                  if (p) p.classList.add('active');
                }
              }
            }
          });

          function setTab(name) {
            currentTab = name;
            vscode.setState({ ...vscode.getState(), currentTab: name });
            vscode.postMessage({ command: 'setTab', tab: name });
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
            const btn = document.getElementById('btn-' + name);
            const pane = document.getElementById('tab-' + name);
            if (btn) btn.classList.add('active');
            if (pane) pane.classList.add('active');
          }

          if (savedState.currentTab && savedState.currentTab !== '${escapeJs(activeTab)}') {
            setTab(savedState.currentTab);
          }

          window.addEventListener('scroll', () => {
            vscode.setState({ ...vscode.getState(), currentTab, scrollY: window.scrollY });
          }, { passive: true });

          if (typeof savedState.scrollY === 'number' && savedState.scrollY > 0) {
            window.scrollTo(0, savedState.scrollY);
          }

          function toggleDetail(id) {
            const el = document.getElementById(id);
            if (el) {
              el.style.display = el.style.display === 'none' ? 'block' : 'none';
            }
          }

          // Centralized CSP-Compliant Event Delegation (No inline onclick violations)
          document.addEventListener('click', (event) => {
            const target = event.target instanceof Element ? event.target.closest('[data-action]') : null;
            if (!target) return;

            const action = target.getAttribute('data-action');
            if (action === 'setTab') {
              const tab = target.getAttribute('data-tab');
              if (tab) setTab(tab);
            } else if (action === 'openConfig') {
              vscode.postMessage({ command: 'openConfig' });
            } else if (action === 'toggleLanguage') {
              vscode.postMessage({ command: 'toggleLanguage' });
            } else if (action === 'clearLogs') {
              vscode.postMessage({ command: 'clearLogs' });
            } else if (action === 'findSkills') {
              vscode.postMessage({ command: 'findSkills' });
            } else if (action === 'openFile') {
              const filePath = target.getAttribute('data-path');
              if (filePath) vscode.postMessage({ command: 'openFile', path: filePath });
            } else if (action === 'copyReason') {
              const text = target.getAttribute('data-text');
              if (text) vscode.postMessage({ command: 'copyReason', text });
            } else if (action === 'toggleDetail') {
              const elId = target.getAttribute('data-target');
              if (elId) toggleDetail(elId);
            }
          });
        </script>`;
}
