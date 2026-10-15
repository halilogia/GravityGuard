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

export class GuardianViewProvider implements vscode.WebviewViewProvider {
  private _view?: vscode.WebviewView;
  private _pollInterval?: NodeJS.Timeout;
  private _logWatcher?: fs.FSWatcher;
  private _clearedAfterSeq: number | null = null;
  private _activeTab: string = 'live';
  private _lastHtml: string = '';
  private _lastDataSig: string = '';
  private _nonce: string = getNonce();
  private _isHtmlInitialized: boolean = false;
  private _visibilityListener?: vscode.Disposable;
  private _pollStartTimer?: NodeJS.Timeout;
  private _readyTimer?: NodeJS.Timeout;
  private _recoveryTimer?: NodeJS.Timeout;
  private _isWebviewReady: boolean = false;
  private _recoveryAttempts: number = 0;

  // Webview must post 'ready' within this window after html assignment, otherwise recovery kicks in
  private static readonly READY_TIMEOUT_MS = 5000;
  // Gap between clearing html and re-assigning it, lets Chromium tear down the old iframe document
  private static readonly RECOVERY_DELAY_MS = 250;
  private static readonly MAX_RECOVERY_ATTEMPTS = 3;

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
    this._isHtmlInitialized = false;
    this._isWebviewReady = false;
    this._recoveryAttempts = 0;
    this.clearTimers();
    this._visibilityListener?.dispose();
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri]
    };

    // Html is never assigned while the view is hidden: the first render is deferred until visible
    // (service worker registration fails with InvalidStateError on a detached iframe document).
    this._visibilityListener = webviewView.onDidChangeVisibility(() => {
      if (!this._view?.visible) {
        return;
      }
      this.updateHtml(!this._isHtmlInitialized);
    });

    webviewView.onDidDispose(() => {
      this.clearTimers();
      this._visibilityListener?.dispose();
      this._visibilityListener = undefined;
      this._isWebviewReady = false;
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
      this._isHtmlInitialized = false;
    });

    webviewView.webview.onDidReceiveMessage(async (message: { command: string; path?: string; text?: string; tab?: string; line?: number; status?: string; title?: string }) => {
      if (message.command === 'ready') {
        this._isWebviewReady = true;
        this._recoveryAttempts = 0;
        if (this._readyTimer) {
          clearTimeout(this._readyTimer);
          this._readyTimer = undefined;
        }
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
      }
    });

    // Initial render only when visible; otherwise onDidChangeVisibility triggers it (single render)
    if (webviewView.visible) {
      this.updateHtml(true);
    }

    // 1. Live File Watcher (Stored in _logWatcher to prevent leak)
    const logPath = getLiveLogPath();
    if (fs.existsSync(logPath)) {
      try {
        if (this._logWatcher) {
          this._logWatcher.close();
        }
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
    this._recoveryAttempts = 0;
    this.recoverWebview('manual reset');
  }

  private clearTimers(): void {
    for (const timer of [this._pollStartTimer, this._readyTimer, this._recoveryTimer]) {
      if (timer) {
        clearTimeout(timer);
      }
    }
    this._pollStartTimer = undefined;
    this._readyTimer = undefined;
    this._recoveryTimer = undefined;
  }

  private armReadyWatchdog(): void {
    if (this._readyTimer) {
      clearTimeout(this._readyTimer);
    }
    this._isWebviewReady = false;
    this._readyTimer = setTimeout(() => {
      this._readyTimer = undefined;
      if (this._view && !this._isWebviewReady) {
        this.recoverWebview('ready timeout');
      }
    }, GuardianViewProvider.READY_TIMEOUT_MS);
  }

  private recoverWebview(reason: string): void {
    const view = this._view;
    if (!view) {
      return;
    }
    if (this._recoveryAttempts >= GuardianViewProvider.MAX_RECOVERY_ATTEMPTS) {
      console.warn(`[GravityGuard] Webview recovery gave up (${reason}).`);
      vscode.window.showWarningMessage(t('actions.webviewRecoveryFailed'));
      return;
    }
    this._recoveryAttempts++;
    console.warn(`[GravityGuard] Recovering webview (${reason}), attempt ${this._recoveryAttempts}`);

    if (this._readyTimer) {
      clearTimeout(this._readyTimer);
      this._readyTimer = undefined;
    }
    if (this._recoveryTimer) {
      clearTimeout(this._recoveryTimer);
    }
    this._nonce = getNonce();
    this._lastHtml = '';
    this._lastDataSig = '';
    this._isHtmlInitialized = false;
    this._isWebviewReady = false;
    try {
      view.webview.html = '';
    } catch (err) {
      console.debug('[GravityGuard] Webview html reset error:', err);
    }
    this._recoveryTimer = setTimeout(() => {
      this._recoveryTimer = undefined;
      if (this._view === view && view.visible) {
        this.updateHtml(true);
      }
      // If hidden, onDidChangeVisibility renders once the view becomes visible again
    }, GuardianViewProvider.RECOVERY_DELAY_MS);
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
    if (!this._view) {
      return;
    }
    if (!this._view.visible && (!force || !this._isHtmlInitialized)) {
      // Hidden view: never touch webview.html; first render is deferred to onDidChangeVisibility
      return;
    }

    const activeTab = this._activeTab || 'live';

    const vm = loadGuardianState(this._clearedAfterSeq);
    const { eventsList, govData, stopRetries, resolutionIntents, totalObligations } = vm;

    // Skip DOM teardown / re-render if data has not changed
    const currentSig = `${getCurrentLanguage()}:${this._clearedAfterSeq}:${eventsList.length}:${eventsList[0]?.timestamp || ''}:${eventsList[0]?.seq || 0}:${govData?.seq || 0}:${stopRetries}:${resolutionIntents.length}:${totalObligations}`;
    if (!force && this._lastDataSig === currentSig && this._lastHtml) {
      return;
    }
    this._lastDataSig = currentSig;

    // --- TAB 5: SKILLS (ACTIVE WORKSPACE, GLOBAL, PLUGIN, BUILT-IN) ---
    const skillsList = scanAllSkills(vm.workspaceRoot);

    const nonce = this._nonce;

    // --- RENDER MAIN WEBVIEW HTML ---
    const htmlContent = buildHtmlDocument({
      vm,
      skills: skillsList,
      activeTab,
      nonce,
      cspSource: this._view.webview.cspSource
    });

    const bodyInnerHtml = extractRootInnerHtml(htmlContent);

    if (!this._isHtmlInitialized || force) {
      this._isHtmlInitialized = true;
      this._lastHtml = htmlContent;
      // Per-render marker busts any html cache so the document is always re-created
      this._view.webview.html = `${htmlContent}
<!-- gg-render:${nonce}:${Date.now()} -->`;
      this.armReadyWatchdog();
    } else if (bodyInnerHtml) {
      this._view.webview.postMessage({
        type: 'updateContent',
        bodyHtml: bodyInnerHtml
      });
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

