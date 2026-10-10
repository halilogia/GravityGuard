import * as vscode from 'vscode';
import * as fs from 'fs';
import { t, setLanguage, getCurrentLanguage } from '../i18n';
import { resolveClearedAfterSeq } from '../view_filter';
import { scanAllSkills } from '../skills';
import { handleOpenConfig } from '../commands';
import { getNonce } from './html_utils';
import { loadGuardianState, getLiveLogPath } from './state';
import { buildHtmlDocument, extractRootInnerHtml } from './layout';

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
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri]
    };

    webviewView.onDidChangeVisibility(() => {
      if (this._view?.visible) {
        this.updateHtml(false);
      }
    });

    webviewView.onDidDispose(() => {
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

    webviewView.webview.onDidReceiveMessage(async (message: { command: string; path?: string; text?: string; tab?: string }) => {
      if (message.command === 'clearLogs' || message.command === 'clearView') {
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
      }
    });

    // Initial render synchronously inside resolveWebviewView (no deferred render)
    this.updateHtml(true);

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
    setTimeout(() => {
      if (this._view && !this._pollInterval) {
        this._pollInterval = setInterval(() => {
          this.updateHtml(false);
        }, 3000);
      }
    }, 2500);
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
    if (!force && !this._view.visible) {
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
      this._view.webview.html = htmlContent;
    } else if (bodyInnerHtml) {
      this._view.webview.postMessage({
        type: 'updateContent',
        bodyHtml: bodyInnerHtml
      });
    }
  }
}
