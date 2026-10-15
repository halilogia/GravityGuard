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

          // Handshake: tells the extension host the document booted (disarms recovery watchdog)
          vscode.postMessage({ command: 'ready' });

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
            } else if (action === 'dismissObligation') {
              const filePath = target.getAttribute('data-path');
              if (filePath) vscode.postMessage({ command: 'dismissObligation', path: filePath });
            } else if (action === 'clearAllObligations') {
              vscode.postMessage({ command: 'clearAllObligations' });
            } else if (action === 'toggleDetail') {
              const elId = target.getAttribute('data-target');
              if (elId) toggleDetail(elId);
            } else if (action === 'cycleTaskStatus') {
              const filePath = target.getAttribute('data-path');
              const line = parseInt(target.getAttribute('data-line') || '0', 10);
              const nextStatus = target.getAttribute('data-next');
              if (filePath && line > 0 && nextStatus) {
                vscode.postMessage({ command: 'updateTaskStatus', path: filePath, line, status: nextStatus });
              }
            } else if (action === 'deleteTaskItem') {
              const filePath = target.getAttribute('data-path');
              const line = parseInt(target.getAttribute('data-line') || '0', 10);
              if (filePath && line > 0) {
                vscode.postMessage({ command: 'deleteTaskItem', path: filePath, line });
              }
            } else if (action === 'addTaskItem') {
              const filePath = target.getAttribute('data-path');
              const inputId = target.getAttribute('data-input-id');
              const input = inputId ? document.getElementById(inputId) : null;
              const text = input && input.value ? input.value.trim() : '';
              if (filePath && text) {
                vscode.postMessage({ command: 'addTaskItem', path: filePath, title: text });
                input.value = '';
              }
            }
          });

          // Knowledge Hub Event Handlers (ADR Accordion, Drawer, Quick-add)
          document.addEventListener('click', (event) => {
            const adrHeader = event.target instanceof Element ? event.target.closest('.adr-card-header') : null;
            if (adrHeader && !event.target.closest('button')) {
              const card = adrHeader.closest('.adr-card');
              const body = card ? card.querySelector('.adr-card-body') : null;
              const chevron = card ? card.querySelector('.adr-chevron') : null;
              if (body) {
                const isOpen = body.style.display === 'block';
                body.style.display = isOpen ? 'none' : 'block';
                if (chevron) {
                  chevron.style.transform = isOpen ? 'rotate(0deg)' : 'rotate(90deg)';
                }
              }
              return;
            }

            const target = event.target instanceof Element ? event.target.closest('button') : null;
            if (!target) return;

            if (target.id === 'btn-toggle-add-adr' || target.id === 'btn-cancel-adr') {
              const drawer = document.getElementById('add-adr-drawer');
              if (drawer) {
                drawer.style.display = drawer.style.display === 'none' ? 'block' : 'none';
                if (drawer.style.display === 'block') {
                  const titleInput = document.getElementById('new-adr-title');
                  if (titleInput) titleInput.focus();
                }
              }
            } else if (target.id === 'btn-save-adr') {
              const filePath = target.getAttribute('data-path');
              const titleInput = document.getElementById('new-adr-title');
              const decisionInput = document.getElementById('new-adr-decision');
              const title = titleInput && titleInput.value ? titleInput.value.trim() : '';
              const decision = decisionInput && decisionInput.value ? decisionInput.value.trim() : '';
              if (filePath && title && decision) {
                vscode.postMessage({ command: 'addAdr', path: filePath, title, decision });
                titleInput.value = '';
                decisionInput.value = '';
                const drawer = document.getElementById('add-adr-drawer');
                if (drawer) drawer.style.display = 'none';
              }
            } else if (target.id === 'btn-save-changelog') {
              const filePath = target.getAttribute('data-path');
              const input = document.getElementById('changelog-add-input');
              const text = input && input.value ? input.value.trim() : '';
              if (filePath && text) {
                vscode.postMessage({ command: 'addChangelogItem', path: filePath, text });
                input.value = '';
              }
            }
          });

          document.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
              if (event.target && event.target.classList && event.target.classList.contains('task-add-input')) {
                const input = event.target;
                const text = input.value ? input.value.trim() : '';
                const filePath = input.getAttribute('data-path');
                if (filePath && text) {
                  vscode.postMessage({ command: 'addTaskItem', path: filePath, title: text });
                  input.value = '';
                }
              } else if (event.target && event.target.id === 'changelog-add-input') {
                const input = event.target;
                const text = input.value ? input.value.trim() : '';
                const filePath = input.getAttribute('data-path');
                if (filePath && text) {
                  vscode.postMessage({ command: 'addChangelogItem', path: filePath, text });
                  input.value = '';
                }
              }
            }
          });
        </script>`;
}
