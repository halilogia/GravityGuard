import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { t, setLanguage, getCurrentLanguage } from '../i18n';
import { resolveClearedAfterSeq } from '../view_filter';
import { scanAllSkills } from '../skills';
import { handleOpenConfig } from '../commands';
import { getNonce } from './html_utils';
import { loadGuardianState, getLiveLogPath } from './state';
import { buildHtmlDocument, extractRootInnerHtml } from './layout';
import { updateTaskItemStatus, deleteTaskItem, addTaskItem, TaskStatus } from '../tasks';
import { addAdrItem, addChangelogItem } from '../knowledge';
import { WebviewLifecycle } from './lifecycle';

export class GuardianViewProvider implements vscode.WebviewViewProvider {
  private _view?: vscode.WebviewView;
  private _pollInterval?: NodeJS.Timeout;
  private _logWatcher?: fs.FSWatcher;
  private _clearedAfterSeq: number | null = null;
  private _activeTab: string = 'live';
  private _lastHtml: string = '';
  private _lastDataSig: string = '';
  private _nonce: string = getNonce();
  private _visibilityListener?: vscode.Disposable;
  private _pollStartTimer?: NodeJS.Timeout;
  private _lifecycle?: WebviewLifecycle;
  private _hostReloadTried: boolean = false;

  constructor(
    private readonly _extensionUri: vscode.Uri,
    private readonly _context?: vscode.ExtensionContext,
    private readonly _onLanguageChanged?: () => void
  ) {}

  public resolveWebviewView(webviewView: vscode.WebviewView): void {
    this._view = webviewView;
    this._lastHtml = '';
    this._lastDataSig = '';
    this._nonce = getNonce();
    this.clearTimers();
    this._lifecycle?.dispose();
    this._visibilityListener?.dispose();
    const lifecycle = new WebviewLifecycle({
      renderDocument: (nonce) => this.renderDocument(webviewView, nonce),
      postUpdate: () => this.postUpdate(webviewView),
      onGiveUp: (reason) => this.escalate(reason),
      isVisible: () => webviewView.visible,
      log: (m) => console.warn(`[GravityGuard] Webview ${m}`)
    }, undefined, undefined, getNonce);
    this._lifecycle = lifecycle;
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri]
    };

    // webview.html is only ever assigned by the lifecycle controller: never while hidden, never while a
    // previous document is still loading (service worker registration fails with InvalidStateError
    // on a hidden / detached / mid-teardown iframe document).
    this._visibilityListener = webviewView.onDidChangeVisibility(() => {
      lifecycle.visibilityChanged(webviewView.visible);
    });

    webviewView.onDidDispose(() => {
      lifecycle.dispose();
      if (this._view !== webviewView) {
        // The host already re-resolved a newer view: its watcher / poller / lifecycle must stay untouched
        return;
      }
      this._lifecycle = undefined;
      this.clearTimers();
      this._visibilityListener?.dispose();
      this._visibilityListener = undefined;
      if (this._pollInterval) {
        clearInterval(this._pollInterval);
        this._pollInterval = undefined;
      }
      if (this._logWatcher) {
        try {
          this._logWatcher.close();
        } catch (err) {
          console.debug('[GravityGuard] Watcher close error:', err);
        }
        this._logWatcher = undefined;
      }
      this._view = undefined;
      this._lastHtml = '';
      this._lastDataSig = '';
    });

    webviewView.webview.onDidReceiveMessage(async (message: { command: string; nonce?: string; path?: string; text?: string; tab?: string; line?: number; status?: string; title?: string; decision?: string }) => {
      if (message.command === 'ready') {
        lifecycle.ready(message.nonce);
      } else if (message.command === 'clearLogs' || message.command === 'clearView') {
        this.clearView();
      } else if (message.command === 'refresh') {
        this._lastHtml = '';
        this._lastDataSig = '';
        this.updateHtml(true);
      } else if (message.command === 'setTab' && message.tab) {
        this._activeTab = message.tab;
      } else if (message.command === 'findSkills') {
        await vscode.commands.executeCommand('antigravityBridge.findSkills');
      } else if (message.command === 'toggleLanguage') {
        const next = getCurrentLanguage() === 'tr' ? 'en' : 'tr';
        setLanguage(next);
        if (this._onLanguageChanged) {
          this._onLanguageChanged();
        }
        this._lastHtml = '';
        this._lastDataSig = '';
        this.updateHtml(true);
        if (this._context) {
          this._context.globalState.update('gravityguard.language', next).then(undefined, (err) => {
            console.debug('Failed to persist language setting:', err);
          });
        }
      } else if (message.command === 'openFile' && message.path) {
        try {
          const doc = await vscode.workspace.openTextDocument(message.path);
          await vscode.window.showTextDocument(doc, { viewColumn: vscode.ViewColumn.One, preview: false });
        } catch (e: any) {
          vscode.window.showErrorMessage(t('actions.fileOpenError', { path: message.path }));
        }
      } else if (message.command === 'openConfig') {
        await handleOpenConfig();
      } else if (message.command === 'copyReason' && message.text) {
        await vscode.env.clipboard.writeText(message.text);
        vscode.window.showInformationMessage(t('actions.reasonCopied'));
      } else if (message.command === 'dismissObligation' && message.path) {
        this.dismissObligation(message.path);
      } else if (message.command === 'clearAllObligations') {
        this.clearAllObligations();
      } else if (message.command === 'updateTaskStatus' && message.path && typeof message.line === 'number' && message.status) {
        if (updateTaskItemStatus(message.path, message.line, message.status as TaskStatus)) {
          this._lastDataSig = '';
          this.updateHtml(true);
        }
      } else if (message.command === 'deleteTaskItem' && message.path && typeof message.line === 'number') {
        if (deleteTaskItem(message.path, message.line)) {
          this._lastDataSig = '';
          this.updateHtml(true);
        }
      } else if (message.command === 'addTaskItem' && message.path && message.title) {
        if (addTaskItem(message.path, message.title)) {
          this._lastDataSig = '';
          this.updateHtml(true);
        }
      } else if (message.command === 'addAdr' && message.path && message.title && message.decision) {
        if (addAdrItem(message.path, { title: message.title, decision: message.decision })) {
          this._lastDataSig = '';
          this.updateHtml(true);
        }
      } else if (message.command === 'addChangelogItem' && message.path && message.text) {
        if (addChangelogItem(message.path, message.text)) {
          this._lastDataSig = '';
          this.updateHtml(true);
        }
      }
    });

    // First render: the lifecycle waits for the iframe document to settle, then assigns html exactly once
    lifecycle.resolve();

    // 1. Live File Watcher (Stored in _logWatcher to prevent leak)
    try {
      this._logWatcher?.close();
    } catch (err) {
      console.debug('[GravityGuard] Watcher close error:', err);
    }
    this._logWatcher = undefined;
    const logPath = getLiveLogPath();
    if (fs.existsSync(logPath)) {
      try {
        this._logWatcher = fs.watch(logPath, () => {
          this.updateHtml(false);
        });
      } catch (e) {
        console.error('Watch log error:', e);
      }
    }

    // 2. Delayed Polling (3s heartbeat) only after webview is stable (prevents Service Worker registration race)
    if (this._pollInterval) {
      clearInterval(this._pollInterval);
      this._pollInterval = undefined;
    }
    this._pollStartTimer = setTimeout(() => {
      this._pollStartTimer = undefined;
      if (this._view && !this._pollInterval) {
        this._pollInterval = setInterval(() => {
          this.updateHtml(false);
        }, 3000);
      }
    }, 2500);
  }

  /**
   * Public reset (antigravityBridge.resetWebview): tears the webview document down and rebuilds it
   * with a fresh nonce. Safe to call at any time, also after an InvalidStateError black screen.
   */
  public resetWebview(): void {
    this._lastHtml = '';
    this._lastDataSig = '';
    this._lifecycle?.reset('manual reset');
  }

  /** Extension deactivation / disable: stop every timer, watcher and lifecycle so nothing touches a dead view. */
  public dispose(): void {
    this._lifecycle?.dispose();
    this._lifecycle = undefined;
    this._visibilityListener?.dispose();
    this._visibilityListener = undefined;
    this.clearTimers();
    if (this._pollInterval) {
      clearInterval(this._pollInterval);
      this._pollInterval = undefined;
    }
    try {
      this._logWatcher?.close();
    } catch (err) {
      console.debug('[GravityGuard] Watcher close error:', err);
    }
    this._logWatcher = undefined;
    this._view = undefined;
  }

  private clearTimers(): void {
    if (this._pollStartTimer) {
      clearTimeout(this._pollStartTimer);
      this._pollStartTimer = undefined;
    }
  }

  /**
   * Recovery budget exhausted (stale / corrupt webview service worker or iframe state in the host).
   * Stage 1 (automatic, once per session): reload every webview iframe through the host's own command,
   * which re-registers the service worker from a clean document. Stage 2: ask the user.
   */
  private escalate(reason: string): void {
    console.warn(`[GravityGuard] Webview recovery gave up (${reason}).`);
    if (!this._hostReloadTried) {
      this._hostReloadTried = true;
      this.reloadHostWebviews();
      return;
    }
    const reloadLabel = t('actions.reloadWebviews');
    vscode.window.showWarningMessage(t('actions.webviewRecoveryFailed'), reloadLabel).then((choice) => {
      if (choice === reloadLabel) {
        this.reloadHostWebviews();
      }
    }, (err) => console.debug('[GravityGuard] escalation prompt error:', err));
  }

  private reloadHostWebviews(): void {
    vscode.commands.executeCommand('workbench.action.webview.reloadWebviewAction').then(() => {
      this._lifecycle?.reset('host webview reload');
    }, (err) => console.warn('[GravityGuard] reloadWebviewAction failed:', err));
  }

  public clearView(): void {
    const logPath = getLiveLogPath();
    try {
      if (fs.existsSync(logPath)) {
        const data = JSON.parse(fs.readFileSync(logPath, 'utf8'));
        this._clearedAfterSeq = resolveClearedAfterSeq(data);
      } else {
        this._clearedAfterSeq = 0;
      }
    } catch (parseErr) {
      console.warn('[GravityGuard] Failed to parse live log on clearView:', parseErr);
      this._clearedAfterSeq = 0;
    }
    this._lastHtml = '';
    this.updateHtml(true);
    vscode.window.showInformationMessage(t('actions.clearedNotice'));
  }

  public clearLogs(): void {
    this.clearView();
  }

  public updateHtml(force: boolean = false): void {
    const view = this._view;
    const lifecycle = this._lifecycle;
    if (!view || !lifecycle) {
      return;
    }
    // Only a ready, visible document is rebuilt eagerly; every other phase just records "dirty" in the
    // lifecycle, which renders the freshest state once the document is safe to touch.
    if (lifecycle.isReady && view.visible && !force && this.currentSignature() === this._lastDataSig) {
      return;
    }
    lifecycle.requestRender(force);
  }

  private currentSignature(): string {
    const { eventsList, govData, stopRetries, resolutionIntents, totalObligations } = loadGuardianState(this._clearedAfterSeq);
    return `${getCurrentLanguage()}:${this._clearedAfterSeq}:${eventsList.length}:${eventsList[0]?.timestamp || ''}:${eventsList[0]?.seq || 0}:${govData?.seq || 0}:${stopRetries}:${resolutionIntents.length}:${totalObligations}`;
  }

  private buildDocument(view: vscode.WebviewView, nonce: string): { html: string; body: string } {
    const vm = loadGuardianState(this._clearedAfterSeq);
    const { eventsList, govData, stopRetries, resolutionIntents, totalObligations } = vm;
    this._lastDataSig = `${getCurrentLanguage()}:${this._clearedAfterSeq}:${eventsList.length}:${eventsList[0]?.timestamp || ''}:${eventsList[0]?.seq || 0}:${govData?.seq || 0}:${stopRetries}:${resolutionIntents.length}:${totalObligations}`;
    const html = buildHtmlDocument({
      vm,
      skills: scanAllSkills(vm.workspaceRoot),
      activeTab: this._activeTab || 'live',
      nonce,
      cspSource: view.webview.cspSource
    });
    this._lastHtml = html;
    return { html, body: extractRootInnerHtml(html) };
  }

  /** Lifecycle callback: hand a brand-new document to the iframe (the only place webview.html is assigned). */
  private renderDocument(view: vscode.WebviewView, nonce: string): void {
    if (this._view !== view) {
      return;
    }
    this._nonce = nonce;
    const { html } = this.buildDocument(view, nonce);
    // Per-render marker busts any html cache so the document is always re-created
    view.webview.html = `${html}
<!-- gg-render:${nonce}:${Date.now()} -->`;
  }

  /** Lifecycle callback: in-place DOM replacement inside the live document (no iframe reload). */
  private postUpdate(view: vscode.WebviewView): void {
    if (this._view !== view) {
      return;
    }
    const { body } = this.buildDocument(view, this._nonce);
    if (body) {
      void view.webview.postMessage({ type: 'updateContent', bodyHtml: body });
    }
  }

  private dismissObligation(targetPath: string): void {
    const candidatePaths: string[] = [];
    const wsFolders = vscode.workspace.workspaceFolders;
    if (wsFolders && wsFolders.length > 0) {
      candidatePaths.push(path.join(wsFolders[0].uri.fsPath, '.gravityguard', 'runtime', 'governance.json'));
    }
    candidatePaths.push(path.join(os.homedir(), '.gravityguard', 'runtime', 'governance.json'));
    candidatePaths.push(path.join(os.homedir(), '.gemini', 'config', 'plugins', 'gravityguard', '.gravityguard', 'runtime', 'governance.json'));

    const normTarget = targetPath.replace(/\\/g, '/').toLowerCase();
    let modified = false;

    for (const govFile of candidatePaths) {
      if (!fs.existsSync(govFile)) {
        continue;
      }
      try {
        const raw = fs.readFileSync(govFile, 'utf8');
        const data = JSON.parse(raw);
        let changed = false;

        if (data.test_obligations?.pending) {
          for (const key of Object.keys(data.test_obligations.pending)) {
            if (key.replace(/\\/g, '/').toLowerCase() === normTarget) {
              delete data.test_obligations.pending[key];
              changed = true;
            }
          }
        }
        if (data.doc_obligations?.pending) {
          for (const key of Object.keys(data.doc_obligations.pending)) {
            if (key.replace(/\\/g, '/').toLowerCase() === normTarget) {
              delete data.doc_obligations.pending[key];
              changed = true;
            }
          }
        }
        if (changed) {
          fs.writeFileSync(govFile, JSON.stringify(data, null, 2), 'utf8');
          modified = true;
        }
      } catch (e) {
        console.warn('[GravityGuard] Failed to dismiss obligation in:', govFile, e);
      }
    }

    if (modified) {
      this._lastHtml = '';
      this._lastDataSig = '';
      this.updateHtml(true);
      vscode.window.showInformationMessage('Yükümlülük kaldırıldı: ' + path.basename(targetPath));
    }
  }

  private clearAllObligations(): void {
    const candidatePaths: string[] = [];
    const wsFolders = vscode.workspace.workspaceFolders;
    if (wsFolders && wsFolders.length > 0) {
      candidatePaths.push(path.join(wsFolders[0].uri.fsPath, '.gravityguard', 'runtime', 'governance.json'));
    }
    candidatePaths.push(path.join(os.homedir(), '.gravityguard', 'runtime', 'governance.json'));
    candidatePaths.push(path.join(os.homedir(), '.gemini', 'config', 'plugins', 'gravityguard', '.gravityguard', 'runtime', 'governance.json'));

    let count = 0;
    for (const govFile of candidatePaths) {
      if (!fs.existsSync(govFile)) {
        continue;
      }
      try {
        const raw = fs.readFileSync(govFile, 'utf8');
        const data = JSON.parse(raw);
        let changed = false;

        if (data.test_obligations?.pending && Object.keys(data.test_obligations.pending).length > 0) {
          count += Object.keys(data.test_obligations.pending).length;
          data.test_obligations.pending = {};
          changed = true;
        }
        if (data.doc_obligations?.pending && Object.keys(data.doc_obligations.pending).length > 0) {
          count += Object.keys(data.doc_obligations.pending).length;
          data.doc_obligations.pending = {};
          changed = true;
        }
        if (data.stop_retries) {
          data.stop_retries = 0;
          changed = true;
        }
        if (changed) {
          fs.writeFileSync(govFile, JSON.stringify(data, null, 2), 'utf8');
        }
      } catch (e) {
        console.warn('[GravityGuard] Failed to clear obligations in:', govFile, e);
      }
    }

    this._lastHtml = '';
    this._lastDataSig = '';
    this.updateHtml(true);
    vscode.window.showInformationMessage(`Tüm bekleyen yükümlülükler temizlendi (${count} adet).`);
  }
}

