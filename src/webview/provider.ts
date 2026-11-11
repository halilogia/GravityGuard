import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { t, setLanguage, getCurrentLanguage } from '../i18n';
import { resolveClearedAfterSeq } from '../view_filter';
import { scanAllSkills } from '../skills';
import { handleOpenConfig } from '../commands';
import { writeFalseAlarm } from '../audit_stats';
import { RuleModeChoice, writeRuleMode } from '../rule_modes';
import { getNonce } from './html_utils';
import { loadGuardianState, getLiveLogPath } from './state';
import { buildHtmlDocument, extractRootInnerHtml } from './layout';
import { updateTaskItemStatus, deleteTaskItem, addTaskItem, archiveCompletedTasks, TaskStatus } from '../tasks';
import { addAdrItem, addChangelogItem } from '../knowledge';
import { WebviewLifecycle } from './lifecycle';
import { MessagePathPolicy } from './message_policy';
import { waiveAdvisory } from './governance_control';
import { HookProposalCache, hookFilesSignature } from './hook_proposals';
import { APPROVAL_ID, ApprovalCache } from './approval_tickets';
import { announceApprovalTicket, executeApprovalDecision, executeHookProposalAction } from './provider_actions';

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
  private _messagePaths = new MessagePathPolicy();
  private _hookCache?: HookProposalCache;
  private _approvalCache?: ApprovalCache;

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
      if (!message || typeof message !== 'object' || typeof message.command !== 'string') return;
      const kinds: Record<string, string> = {
        updateTaskStatus: 'tasks', deleteTaskItem: 'tasks', archiveCompletedTasks: 'tasks', addTaskItem: 'tasks',
        addAdr: 'knowledge', addChangelogItem: 'changelog', dismissObligation: 'obligations',
        approveHookProposal: 'hookProposals', rejectHookProposal: 'hookProposals', revertHookProposal: 'hookReceipts',
        allowApproval: 'approvals', denyApproval: 'approvals'
      };
      if (kinds[message.command] && !this._messagePaths.permits(kinds[message.command], message.command.endsWith('Approval') ? message.text : message.path)) return;
      if (message.line !== undefined && (!Number.isSafeInteger(message.line) || message.line < 1)) return;
      if (message.status !== undefined && !['open', 'in_progress', 'done'].includes(message.status)) return;
      if ([message.text, message.title, message.decision].some(value => value !== undefined && (typeof value !== 'string' || value.length > 100000))) return;
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
      } else if (message.command === 'markFalseAlarm' && typeof message.text === 'string' && /^[\w.-]{1,80}$/.test(message.text)
        && typeof message.title === 'string' && /^[A-Z][A-Z0-9_]{1,63}$/.test(message.title)) {
        writeFalseAlarm(message.text, message.title, message.decision === 'undo');
        this._lastHtml = '';
        this._lastDataSig = '';
        this.updateHtml(true);
      } else if (message.command === 'setRuleMode' && typeof message.title === 'string' && typeof message.decision === 'string') {
        const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        const cfgPath = root ? path.join(root, '.gravityguard.json') : path.join(os.homedir(), '.gravityguard.json');
        try {
          if (!writeRuleMode(cfgPath, message.title, message.decision as RuleModeChoice)) return;
        } catch (e) {
          vscode.window.showErrorMessage(t('actions.ruleModeError', { path: cfgPath }));
          return;
        }
        this._lastHtml = '';
        this._lastDataSig = '';
        this.updateHtml(true);
      } else if (message.command === 'openConfig') {
        await handleOpenConfig();
      } else if (message.command === 'copyReason' && message.text) {
        await vscode.env.clipboard.writeText(message.text);
        vscode.window.showInformationMessage(t('actions.reasonCopied'));
      } else if (message.command === 'dismissObligation' && message.path) {
        await this.dismissObligation(message.path);
      } else if (['approveHookProposal', 'rejectHookProposal', 'revertHookProposal'].includes(message.command) && message.path) {
        await this.hookAction(message.command, message.path, message.text);
      } else if ((message.command === 'allowApproval' || message.command === 'denyApproval') && message.text && APPROVAL_ID.test(message.text)) {
        await this.decideApproval(message.command === 'allowApproval' ? 'allow' : 'deny', message.text);
      } else if (message.command === 'clearAllObligations') {
        await this.clearAllObligations();
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
      } else if (message.command === 'archiveCompletedTasks' && message.path) {
        const res = archiveCompletedTasks(message.path, { force: true });
        if (res.performed) {
          this._lastDataSig = '';
          this.updateHtml(true);
          vscode.window.showInformationMessage(t('tasks.archivedNotice', { count: res.archivedCount }));
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

    lifecycle.resolve();

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

  public resetWebview(): void {
    this._lastHtml = '';
    this._lastDataSig = '';
    this._lifecycle?.reset('manual reset');
  }

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
    if (lifecycle.isReady && view.visible && !force && this.currentSignature() === this._lastDataSig) {
      return;
    }
    lifecycle.requestRender(force);
  }

  private currentSignature(): string {
    const { eventsList, govData, stopRetries, resolutionIntents, totalObligations } = loadGuardianState(this._clearedAfterSeq);
    return `${getCurrentLanguage()}:${this._clearedAfterSeq}:${eventsList.length}:${eventsList[0]?.timestamp || ''}:${eventsList[0]?.seq || 0}:${govData?.seq || 0}:${stopRetries}:${resolutionIntents.length}:${totalObligations}:${hookFilesSignature(this.hookRoots())}`;
  }

  private buildDocument(view: vscode.WebviewView, nonce: string): { html: string; body: string } {
    const vm = loadGuardianState(this._clearedAfterSeq);
    this._messagePaths.set('tasks', [...vm.tasks.map(file => file.path), ...(vm.defaultTaskPath ? [vm.defaultTaskPath] : [])]);
    this._messagePaths.set('knowledge', vm.memory?.knowledge ? [vm.memory.knowledge.path] : []);
    this._messagePaths.set('changelog', vm.memory?.changelog ? [vm.memory.changelog.path] : []);
    this._messagePaths.set('obligations', [...Object.keys(vm.pendingTests), ...Object.keys(vm.pendingDocs)]);
    vm.hookProposals = this.hookCache().current(this.hookRoots());
    vm.approvals = this.approvalCache().current();
    this._messagePaths.set('approvals', vm.approvals.map(ticket => ticket.id));
    this._messagePaths.set('hookProposals', vm.hookProposals.pending.map(view => view.path));
    this._messagePaths.set('hookReceipts', vm.hookProposals.installed.map(r => path.join(r.root, '.gravityguard', 'runtime', 'hook-receipts', `${r.id}.json`)));
    const { eventsList, govData, stopRetries, resolutionIntents, totalObligations } = vm;
    this._lastDataSig = `${getCurrentLanguage()}:${this._clearedAfterSeq}:${eventsList.length}:${eventsList[0]?.timestamp || ''}:${eventsList[0]?.seq || 0}:${govData?.seq || 0}:${stopRetries}:${resolutionIntents.length}:${totalObligations}:${hookFilesSignature(this.hookRoots())}`;
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

  private async changeAdvisoryObligations(target?: string): Promise<void> {
    const roots = [...(vscode.workspace.workspaceFolders || []).map(folder => folder.uri.fsPath),
      os.homedir(), path.join(os.homedir(), '.gemini', 'config', 'plugins', 'gravityguard')];
    try {
      await waiveAdvisory(path.join(this._extensionUri.fsPath, 'engine', 'governance_control.py'), roots, target);
      this._lastHtml = '';
      this._lastDataSig = '';
      this.updateHtml(true);
    } catch (error) {
      console.warn('[GravityGuard] Advisory state update failed:', error);
      vscode.window.showErrorMessage(t('actions.governanceWriteFailed'));
    }
  }

  private async dismissObligation(targetPath: string): Promise<void> {
    await this.changeAdvisoryObligations(targetPath);
  }

  private async clearAllObligations(): Promise<void> {
    await this.changeAdvisoryObligations();
  }

  private hookRoots(): string[] {
    return (vscode.workspace.workspaceFolders || []).map(folder => folder.uri.fsPath);
  }

  private hookScript(): string {
    return path.join(this._extensionUri.fsPath, 'engine', 'hook_proposal_control.py');
  }

  private approvalScript(): string {
    return path.join(this._extensionUri.fsPath, 'engine', 'approval_control.py');
  }

  private approvalCache(): ApprovalCache {
    if (!this._approvalCache) {
      this._approvalCache = new ApprovalCache(this.approvalScript(), fresh => {
        this._lastDataSig = '';
        this.updateHtml(true);
        fresh.forEach(ticket => announceApprovalTicket(ticket, (a, id) => this.decideApproval(a, id)));
      });
    }
    return this._approvalCache;
  }

  watchApprovals(): void {
    this.approvalCache().current();
  }

  private async decideApproval(action: 'allow' | 'deny', id: string): Promise<void> {
    await executeApprovalDecision(this.approvalScript(), action, id);
    this._approvalCache?.invalidate();
    this._lastDataSig = '';
    this.updateHtml(true);
  }

  private hookCache(): HookProposalCache {
    if (!this._hookCache) {
      this._hookCache = new HookProposalCache(this.hookScript(), () => {
        this._lastDataSig = '';
        this.updateHtml(true);
      });
    }
    return this._hookCache;
  }

  private async hookAction(command: string, file: string, sha?: string): Promise<void> {
    const changed = await executeHookProposalAction(this.hookScript(), this.hookCache(), this.hookRoots(), command, file, sha);
    if (!changed) return;
    this._hookCache?.invalidate();
    this._lastDataSig = '';
    this.updateHtml(true);
  }
}
