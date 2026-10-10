import * as vscode from 'vscode';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as http from 'http';
import { buildOfflinePrompt, buildSystemPrompt, classifyIntent, modeLabel, shouldAskForMode, IntentClassification, IntentMode } from './intent';
import { initI18n, t, setLanguage, getCurrentLanguage } from './i18n';
import { lucide } from './icons';
import { filterEventsAfterSeq, resolveClearedAfterSeq } from './view_filter';

interface LogEvent {
  status?: string;
  timestamp?: string;
  target?: string;
  action?: string;
  reason?: string;
  ruleId?: string;
  outcome?: string;
  resolvedRuleId?: string;
  recoveryAttempts?: number;
  resolutionMs?: number;
  [key: string]: any;
}

interface GuardianData {
  activeGuard?: string;
  status?: string;
  lastCheck?: string;
  events?: LogEvent[];
}

class RouterUnreachableError extends Error {}

interface EnhancementResult {
  text: string;
  offline: boolean;
  mode: IntentMode;
}

function getRouterConfig() {
  const config = vscode.workspace.getConfiguration('gravityguard');
  const host = config.get<string>('routerHost') || process.env.ROUTER_HOST || '127.0.0.1';
  const port = config.get<number>('routerPort') || (process.env.ROUTER_PORT ? parseInt(process.env.ROUTER_PORT, 10) : 20128);
  const token = config.get<string>('routerToken') || process.env.GRAVITYGUARD_ROUTER_TOKEN || process.env.ROUTER_TOKEN || '';
  const timeoutMs = config.get<number>('routerTimeoutMs') || parseInt(process.env.ROUTER_TIMEOUT_MS || '', 10) || 12000;
  const configuredModels = config.get<string[]>('models') || [];
  const envModels = (process.env.ROUTER_MODELS || '').split(',').map(m => m.trim()).filter(Boolean);
  const models = (configuredModels.length ? configuredModels : (envModels.length ? envModels : DEFAULT_MODELS))
    .map(m => m.trim())
    .filter(Boolean);
  return { host, port, token, timeoutMs, models };
}

const DEFAULT_MODELS = [
  'ag/gemini-3.8-flash-low',
  'ag/gemini-3.7-flash-medium',
  'all'
];

const CONNECTION_ERROR_CODES = new Set([
  'ECONNREFUSED', 'ENOTFOUND', 'EHOSTUNREACH', 'ENETUNREACH', 'EAI_AGAIN', 'ECONNRESET', 'EPIPE'
]);

export function activate(context: vscode.ExtensionContext): void {
  const savedLang = context.globalState.get<string>('gravityguard.language');
  const initialLang = savedLang || (vscode.env.language && vscode.env.language.toLowerCase().startsWith('tr') ? 'tr' : 'en');
  initI18n(initialLang);
  console.log(`[GravityGuard] Extension activated successfully! Language: ${initialLang}`);

  // 1. Register Status Bar Item for Prompt Enhancement
  const promptStatusBarItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100
  );
  promptStatusBarItem.command = 'antigravityBridge.enhancePrompt';
  promptStatusBarItem.text = `$(sparkle) ${t('actions.enhancePrompt')}`;
  promptStatusBarItem.tooltip = t('actions.statusBarTooltip');
  promptStatusBarItem.show();
  context.subscriptions.push(promptStatusBarItem);

  // 2. Register Webview Provider for GravityGuard Live Monitor
  const provider = new GuardianViewProvider(
    context.extensionUri,
    context,
    () => {
      promptStatusBarItem.text = `$(sparkle) ${t('actions.enhancePrompt')}`;
      promptStatusBarItem.tooltip = t('actions.statusBarTooltip');
    }
  );
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider('antigravity-guardian-view', provider)
  );

  // 3. Register Commands
  context.subscriptions.push(
    vscode.commands.registerCommand('antigravityBridge.ping', async () => {
      const health = await probeRouter();
      if (health.ok) {
        vscode.window.showInformationMessage(t('actions.pingLive', { detail: health.detail }));
      } else {
        vscode.window.showWarningMessage(t('actions.pingWarning', { detail: health.detail }));
      }
    }),
    vscode.commands.registerCommand('antigravityBridge.refreshLogs', () => {
      provider.updateHtml();
    }),
    vscode.commands.registerCommand('antigravityBridge.clearLogs', () => {
      provider.clearLogs();
    }),
    vscode.commands.registerCommand('antigravityBridge.toggleLanguage', async () => {
      const next = getCurrentLanguage() === 'tr' ? 'en' : 'tr';
      setLanguage(next);
      await context.globalState.update('gravityguard.language', next);
      promptStatusBarItem.text = `$(sparkle) ${t('actions.enhancePrompt')}`;
      promptStatusBarItem.tooltip = t('actions.statusBarTooltip');
      provider.updateHtml();
      vscode.window.showInformationMessage(t('actions.langSwitched', { lang: next.toUpperCase() }));
    }),
    vscode.commands.registerCommand('antigravityBridge.openConfig', async () => {
      await handleOpenConfig();
    }),
    vscode.commands.registerCommand('antigravityBridge.enhancePrompt', async () => {
      await handleEnhancePrompt();
    })
  );
}

async function handleOpenConfig(): Promise<void> {
  const workspaceFolders = vscode.workspace.workspaceFolders;
  let cfgFile = '';
  if (workspaceFolders && workspaceFolders.length > 0) {
    cfgFile = path.join(workspaceFolders[0].uri.fsPath, '.gravityguard.json');
  } else {
    cfgFile = path.join(os.homedir(), '.gravityguard.json');
    vscode.window.showInformationMessage(t('actions.configNoWorkspaceNotice'));
  }

  try {
    if (!fs.existsSync(cfgFile)) {
      fs.writeFileSync(cfgFile, JSON.stringify({
        "governance": { "enforceDocObligations": true },
        "complexity": { "singleWriteLoc": 200, "totalLoc": 500 },
        "guards": {
          "G0_SECRET_LEAK": "block",
          "G1_SILENT_EXCEPTION": "block",
          "G2_TEST_INTEGRITY": "block",
          "G3_COMPILER_BYPASS": "warn",
          "G4_IMPORT_MATRIX": "block",
          "T1_TEST_EVIDENCE": "warn"
        }
      }, null, 2), 'utf8');
    }
    const uri = vscode.Uri.file(cfgFile);
    await vscode.commands.executeCommand('vscode.open', uri);
  } catch (e: any) {
    vscode.window.showErrorMessage(t('actions.configOpenError', { error: e.message }));
  }
}

async function handleEnhancePrompt(): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  let initialText = '';

  if (editor && !editor.selection.isEmpty) {
    initialText = editor.document.getText(editor.selection).trim();
  }

  const inputPrompt = await vscode.window.showInputBox({
    prompt: t('actions.promptInputTitle'),
    placeHolder: t('actions.promptInputPlaceholder'),
    value: initialText,
    ignoreFocusOut: true
  });

  if (!inputPrompt || inputPrompt.trim() === '') {
    return;
  }

  const classification = classifyIntent(inputPrompt.trim());
  const mode = await resolveMode(classification);

  try {
    let result: EnhancementResult | undefined;
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: t('actions.promptPreparing', { mode: modeLabel(mode) }),
        cancellable: false
      },
      async () => {
        result = await requestPromptEnhancement(inputPrompt.trim(), mode);
      }
    );

    if (!result || !result.text) {
      vscode.window.showErrorMessage(t('actions.promptFailed'));
      return;
    }

    const enhancedResult = result.text;

    // 1. Copy directly to clipboard
    await vscode.env.clipboard.writeText(enhancedResult);

    // 2. If editor has selected text, optionally replace it
    if (editor && !editor.selection.isEmpty) {
      await editor.edit(editBuilder => {
        editBuilder.replace(editor.selection, enhancedResult);
      });
    }

    // 3. Inform user with action button
    const originNote = result.offline ? t('actions.promptOfflineNote') : '';
    const action = await vscode.window.showInformationMessage(
      t('actions.promptSuccess', { mode: modeLabel(result.mode), note: originNote }),
      t('actions.openInNewDoc')
    );

    if (action === t('actions.openInNewDoc')) {
      const doc = await vscode.workspace.openTextDocument({
        content: enhancedResult,
        language: 'markdown'
      });
      await vscode.window.showTextDocument(doc);
    }
  } catch (error: any) {
    console.error('[Prompt Enhancer Error]:', error);
    vscode.window.showErrorMessage(
      t('actions.promptError', { error: error?.message || error })
    );
  }
}

async function resolveMode(classification: IntentClassification): Promise<IntentMode> {
  if (!shouldAskForMode(classification)) {
    return classification.mode;
  }

  const MODES: IntentMode[] = ['consult', 'implement', 'audit'];
  const pick = await vscode.window.showQuickPick(
    [
      {
        label: t('actions.modeAuto', { mode: modeLabel(classification.mode) }),
        description: t('actions.modeAutoDesc'),
        mode: classification.mode
      },
      ...MODES.filter(mode => mode !== classification.mode).map(mode => ({
        label: modeLabel(mode),
        description: mode === 'consult'
          ? t('actions.modeConsultDesc')
          : mode === 'implement'
            ? t('actions.modeImplementDesc')
            : t('actions.modeAuditDesc'),
        mode
      }))
    ],
    { placeHolder: t('actions.modePlaceholder') }
  );

  return pick ? pick.mode : classification.mode;
}

async function requestPromptEnhancement(rawPrompt: string, mode: IntentMode): Promise<EnhancementResult> {
  const classification = classifyIntent(rawPrompt);
  const systemPrompt = buildSystemPrompt(mode);
  const { host, port, models } = getRouterConfig();

  let lastError: Error | null = null;

  for (const model of models) {
    try {
      const response = await postChatCompletion(model, systemPrompt, rawPrompt);
      if (response && response.trim().length > 0) {
        return { text: response.trim(), offline: false, mode };
      }
    } catch (err: any) {
      console.warn(`[Prompt Enhancer] Model ${model} failed:`, err?.message);
      lastError = err;
      if (err instanceof RouterUnreachableError) {
        console.warn(`[Prompt Enhancer] ${host}:${port} erişilemiyor, kalan modlar atlanıyor.`);
        break;
      }
    }
  }

  console.warn(
    `[Prompt Enhancer] Yerel model yanıt vermedi (${lastError?.message || 'bilinmiyor'}). Çevrimdışı şablona geçiliyor.`
  );
  return { text: buildOfflinePrompt(rawPrompt, classification), offline: true, mode };
}

function probeRouter(): Promise<{ ok: boolean; detail: string }> {
  return new Promise(resolve => {
    const { host, port, token } = getRouterConfig();
    const headers: Record<string, string> = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    const req = http.request(
      { hostname: host, port: port, path: '/v1/models', method: 'GET', headers, timeout: 3000 },
      res => {
        let data = '';
        res.setEncoding('utf8');
        res.on('data', chunk => (data += chunk));
        res.on('end', () => {
          if (res.statusCode && res.statusCode >= 200 && res.statusCode < 300) {
            let count = 0;
            try {
              count = JSON.parse(data)?.data?.length ?? 0;
            } catch {
              count = 0;
            }
            resolve({ ok: true, detail: `${host}:${port} yanıt verdi${count ? ` (${count} model)` : ''}` });
          } else {
            resolve({
              ok: true,
              detail: `${host}:${port} erişilebilir, /v1 models uç noktası yok (HTTP ${res.statusCode})`
            });
          }
        });
      }
    );
    req.on('error', e => resolve({ ok: false, detail: `${host}:${port} — ${(e as NodeJS.ErrnoException).code || e.message}` }));
    req.on('timeout', () => {
      req.destroy();
      resolve({ ok: false, detail: `${host}:${port} — zaman aşımı` });
    });
    req.end();
  });
}

function postChatCompletion(model: string, systemPrompt: string, userPrompt: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify({
      model: model,
      stream: false,
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: userPrompt }
      ],
      temperature: 0.4
    });

    const { host, port, token, timeoutMs } = getRouterConfig();
    const headers: Record<string, string | number> = {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(payload)
    };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const options: http.RequestOptions = {
      hostname: host,
      port: port,
      path: '/v1/chat/completions',
      method: 'POST',
      headers: headers,
      timeout: timeoutMs
    };

    const req = http.request(options, (res) => {
      let data = '';

      res.setEncoding('utf8');
      res.on('data', (chunk) => {
        data += chunk;
      });

      res.on('end', () => {
        if (res.statusCode && res.statusCode >= 200 && res.statusCode < 300) {
          try {
            const parsed = JSON.parse(data);
            const content = parsed.choices?.[0]?.message?.content;
            if (content) {
              resolve(content);
            } else {
              reject(new Error(`Boş içerik alındı: ${data}`));
            }
          } catch (e: any) {
            reject(new Error(`JSON ayrıştırma hatası: ${e.message}`));
          }
        } else {
          reject(new Error(`HTTP ${res.statusCode}: ${data}`));
        }
      });
    });

    req.on('error', (e) => {
      const code = (e as NodeJS.ErrnoException).code;
      if (code && CONNECTION_ERROR_CODES.has(code)) {
        reject(new RouterUnreachableError(`${code} (${host}:${port})`));
        return;
      }
      reject(e);
    });

    req.on('timeout', () => {
      req.destroy();
      reject(new Error(`Yerel AI yanıt zaman aşımına uğradı (${model}, ${timeoutMs}ms)`));
    });

    req.write(payload);
    req.end();
  });
}

function escapeHtml(str: string): string {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function escapeJs(str: string): string {
  return String(str)
    .replace(/\\/g, '\\\\')
    .replace(/'/g, "\\'")
    .replace(/\n/g, '\\n')
    .replace(/\r/g, '');
}

class GuardianViewProvider implements vscode.WebviewViewProvider {
  private _view?: vscode.WebviewView;
  private _pollInterval?: NodeJS.Timeout;
  private _clearedAfterSeq: number | null = null;
  private _activeTab: string = 'live';

  constructor(
    private readonly _extensionUri: vscode.Uri,
    private readonly _context?: vscode.ExtensionContext,
    private readonly _onLanguageChanged?: () => void
  ) {}

  public resolveWebviewView(webviewView: vscode.WebviewView): void {
    this._view = webviewView;
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri]
    };

    webviewView.webview.onDidReceiveMessage(async (message: { command: string; path?: string; text?: string; tab?: string }) => {
      if (message.command === 'clearLogs' || message.command === 'clearView') {
        this.clearView();
      } else if (message.command === 'refresh') {
        this.updateHtml();
      } else if (message.command === 'setTab' && message.tab) {
        this._activeTab = message.tab;
      } else if (message.command === 'toggleLanguage') {
        const next = getCurrentLanguage() === 'tr' ? 'en' : 'tr';
        setLanguage(next);
        if (this._context) {
          await this._context.globalState.update('gravityguard.language', next);
        }
        if (this._onLanguageChanged) {
          this._onLanguageChanged();
        }
        this.updateHtml();
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

    this.updateHtml();

    // 1. Live File Watcher
    const logPath = path.join(os.homedir(), '.gemini', 'logs', 'srp_guardian_live.json');
    if (fs.existsSync(logPath)) {
      try {
        fs.watch(logPath, () => {
          this.updateHtml();
        });
      } catch (e) {
        console.error('Watch log error:', e);
      }
    }

    // 2. Continuous 1.5s Auto-Refresh (Heartbeat)
    if (this._pollInterval) {
      clearInterval(this._pollInterval);
    }
    this._pollInterval = setInterval(() => {
      this.updateHtml();
    }, 1500);
  }

  public clearView(): void {
    const logPath = path.join(os.homedir(), '.gemini', 'logs', 'srp_guardian_live.json');
    try {
      if (fs.existsSync(logPath)) {
        const data = JSON.parse(fs.readFileSync(logPath, 'utf8'));
        this._clearedAfterSeq = resolveClearedAfterSeq(data);
      } else {
        this._clearedAfterSeq = 0;
      }
    } catch {
      this._clearedAfterSeq = 0;
    }
    this.updateHtml();
    vscode.window.showInformationMessage(t('actions.clearedNotice'));
  }

  public clearLogs(): void {
    this.clearView();
  }

  public updateHtml(): void {
    if (!this._view) {
      return;
    }

    const activeTab = this._activeTab || 'live';

    const logPath = path.join(os.homedir(), '.gemini', 'logs', 'srp_guardian_live.json');
    let data: GuardianData = { activeGuard: 'GravityGuard', status: 'ONLINE', events: [] };

    if (fs.existsSync(logPath)) {
      try {
        data = JSON.parse(fs.readFileSync(logPath, 'utf8'));
      } catch (e) {
        console.warn('Failed to parse live log file:', e);
      }
    }

    // Resolve workspace folder and read governance / project config
    let workspaceRoot = '';
    let projectName = 'Workspace';
    if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
      workspaceRoot = vscode.workspace.workspaceFolders[0].uri.fsPath;
      projectName = path.basename(workspaceRoot);
    }

    let govData: any = null;
    let pendingTests: Record<string, any> = {};
    let pendingDocs: Record<string, any> = {};
    let resolutionIntents: any[] = [];
    let stopRetries = 0;
    let sessionId = 'active';

    if (workspaceRoot) {
      const govPath = path.join(workspaceRoot, '.gravityguard', 'runtime', 'governance.json');
      if (fs.existsSync(govPath)) {
        try {
          govData = JSON.parse(fs.readFileSync(govPath, 'utf8'));
          pendingTests = govData.test_obligations?.pending || {};
          pendingDocs = govData.doc_obligations?.pending || {};
          resolutionIntents = govData.resolution_intents || [];
          stopRetries = govData.stop_retries || 0;
          if (govData.sessions && Object.keys(govData.sessions).length > 0) {
            sessionId = Object.keys(govData.sessions)[0];
          }
        } catch (e) {
          console.warn('Failed to parse governance state:', e);
        }
      }
    }

    let projectCfg: any = null;
    if (workspaceRoot) {
      const cfgPath = path.join(workspaceRoot, '.gravityguard.json');
      if (fs.existsSync(cfgPath)) {
        try {
          projectCfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
        } catch (e) {
          console.warn('Failed to parse .gravityguard.json:', e);
        }
      }
    }
    if (!projectCfg) {
      const userCfgPath = path.join(os.homedir(), '.gravityguard.json');
      if (fs.existsSync(userCfgPath)) {
        try {
          projectCfg = JSON.parse(fs.readFileSync(userCfgPath, 'utf8'));
        } catch (e) {
          console.warn('Failed to parse user .gravityguard.json:', e);
        }
      }
    }

    const totalObligations = Object.keys(pendingTests).length + Object.keys(pendingDocs).length;
    let eventsList = filterEventsAfterSeq(data.events || [], this._clearedAfterSeq);
    const blockedCount = eventsList.filter(e => e.status === 'BLOCKED').length;
    const warningCount = eventsList.filter(e => e.status === 'WARNING').length;
    const approvedCount = eventsList.filter(e => e.status === 'APPROVED').length;
    const shadowCount = eventsList.filter(e => e.status === 'SHADOW_TRIGGER').length;
    const totalEvents = eventsList.length;

    // Agent Recovery Calculation: Did agent fix a blocked event on next turn?
    let recoveredCount = 0;
    let totalBlockedAnalyzed = 0;
    for (let i = 0; i < eventsList.length; i++) {
      if (eventsList[i].status === 'BLOCKED') {
        totalBlockedAnalyzed++;
        const target = eventsList[i].target;
        if (target) {
          const subsequentApproval = eventsList.slice(0, i).some(e => e.target === target && e.status === 'APPROVED');
          if (subsequentApproval) {
            recoveredCount++;
          }
        }
      }
    }
    const recoveryRate = totalBlockedAnalyzed > 0
      ? Math.round((recoveredCount / totalBlockedAnalyzed) * 100)
      : 100;

    // --- CURRENT ACTION CARD ---
    const latestEvent = eventsList.length > 0 ? eventsList[0] : null;
    let currentCardHtml = '';
    if (latestEvent) {
      const isBlk = latestEvent.status === 'BLOCKED';
      const isWrn = latestEvent.status === 'WARNING';
      const colorCls = isBlk ? 'border-blocked' : isWrn ? 'border-warning' : 'border-allowed';
      const badgeCls = isBlk ? 'badge-blocked' : isWrn ? 'badge-warning' : 'badge-allowed';
      const statusIcon = isBlk
        ? lucide('octagonX', { size: 10, color: 'var(--color-red)' })
        : isWrn
        ? lucide('alertTriangle', { size: 10, color: 'var(--color-amber)' })
        : lucide('checkCircle', { size: 10, color: 'var(--color-green)' });
      const statusText = isBlk
        ? t('current.statusBlocked')
        : isWrn
        ? t('current.statusWarning')
        : t('current.statusAllowed');
      const actionName = latestEvent.action || 'write_file';
      const targetName = latestEvent.target ? path.basename(latestEvent.target) : 'workspace';
      const ruleText = latestEvent.ruleId && latestEvent.ruleId !== 'PASS' ? latestEvent.ruleId : t('current.allGuardsPassed');
      const timeStr = latestEvent.timestamp ? (latestEvent.timestamp.split(' ')[1] || latestEvent.timestamp) : '';

      currentCardHtml = `
        <div class="current-card ${colorCls}">
          <div class="current-hdr">
            <span class="current-tag">${t('current.title')}</span>
            <span class="current-time">${timeStr}</span>
          </div>
          <div class="current-body">
            <div class="current-action-line">
              <span class="current-tool">${escapeHtml(actionName)}</span>
              <span class="current-target" title="${escapeHtml(latestEvent.target || '')}">${escapeHtml(targetName)}</span>
            </div>
            <div class="current-badge-row">
              <span class="status-badge ${badgeCls}">${statusIcon} ${statusText}</span>
              <span class="current-rule-badge">${escapeHtml(ruleText)}</span>
            </div>
            ${latestEvent.reason ? `<div class="current-reason-text">${escapeHtml(latestEvent.reason)}</div>` : ''}
          </div>
        </div>
      `;
    } else {
      currentCardHtml = `
        <div class="current-card border-neutral">
          <div class="current-hdr">
            <span class="current-tag">${t('current.title')}</span>
          </div>
          <div class="current-idle">
            <span class="idle-inline">${lucide('zap', { size: 12, color: 'var(--text-muted)' })} ${t('current.idle')}</span>
          </div>
        </div>
      `;
    }

    // --- TAB 1: LIVE STREAM (COMPACT ROWS WITH EXPANDABLE ACCORDION) ---
    let liveHtml = '';
    if (eventsList.length === 0) {
      liveHtml = `<div class="empty-state">${t('live.empty')}</div>`;
    } else {
      eventsList.forEach((e, idx) => {
        const isBlk = e.status === 'BLOCKED';
        const isWrn = e.status === 'WARNING';
        const isShd = e.status === 'SHADOW_TRIGGER' || e.outcome === 'SHADOW_OBSERVED';
        const isRec = e.outcome === 'RECOVERED';

        let badgeCls = 'badge-allowed';
        let statusLabel = t('current.statusAllowed');
        let statusIcon = lucide('checkCircle', { size: 10, color: 'var(--color-green)' });
        if (isShd) {
          badgeCls = 'badge-purple';
          statusLabel = t('current.statusShadow');
          statusIcon = lucide('eye', { size: 10, color: 'var(--color-purple)' });
        } else if (isRec) {
          badgeCls = 'badge-cyan';
          statusLabel = t('current.statusRecovered');
          statusIcon = lucide('rotateCw', { size: 10, color: 'var(--color-cyan)' });
        } else if (isBlk) {
          badgeCls = 'badge-blocked';
          statusLabel = t('current.statusBlocked');
          statusIcon = lucide('octagonX', { size: 10, color: 'var(--color-red)' });
        } else if (isWrn) {
          badgeCls = 'badge-warning';
          statusLabel = t('current.statusWarning');
          statusIcon = lucide('alertTriangle', { size: 10, color: 'var(--color-amber)' });
        }

        const fileName = e.target ? path.basename(e.target) : (e.action || 'system');
        const timeStr = e.timestamp ? (e.timestamp.split(' ')[1] || e.timestamp) : '';
        const ruleId = e.ruleId || 'PASS';
        const fullTargetEsc = escapeHtml(e.target || '');
        const reasonEsc = escapeHtml(e.reason || '');

        liveHtml += `
          <div class="stream-item">
            <div class="stream-row" onclick="toggleDetail('evt-${idx}')">
              <div class="stream-left">
                <span class="status-badge ${badgeCls}">${statusIcon} ${statusLabel}</span>
                <span class="stream-file" title="${fullTargetEsc}">${escapeHtml(fileName)}</span>
              </div>
              <div class="stream-right">
                <span class="stream-rule">${escapeHtml(ruleId)}</span>
                <span class="stream-time">${timeStr}</span>
              </div>
            </div>
            <div id="evt-${idx}" class="stream-drawer" style="display: none;">
              <div class="drawer-header">
                <span class="drawer-rule">${escapeHtml(ruleId)}</span>
                <span class="status-badge ${badgeCls}">${statusIcon} ${statusLabel}</span>
              </div>
              ${isRec ? `
                <div class="drawer-meta-pill bg-cyan">
                  <div class="recovery-flow-row" style="margin-bottom: 3px;">
                    <span class="status-badge badge-blocked" style="font-size: 8px; padding: 1px 5px;">${t('live.recoveryFlowBlocked')}</span>
                    <span style="color: var(--color-cyan); display: inline-flex; align-items: center;">${lucide('arrowRight', { size: 9 })}</span>
                    <span class="status-badge badge-allowed" style="font-size: 8px; padding: 1px 5px;">${t('live.recoveryFlowRecovered')}</span>
                    <strong style="margin-left: 4px; color: var(--text-main); font-size: 10px;">${escapeHtml(e.resolvedRuleId || e.ruleId || 'Rule')}</strong>
                  </div>
                  <div class="recovery-meta-sub" style="font-size: 9px; color: var(--text-muted);">
                    <span>${t('live.recoveryAttempts', { attempts: e.recoveryAttempts || 1 })}</span>
                    ${e.resolutionMs ? `<span> • ${t('live.recoveryDuration', { duration: (e.resolutionMs / 1000).toFixed(1) })}</span>` : ''}
                  </div>
                </div>
              ` : ''}
              ${isShd ? `
                <div class="drawer-meta-pill bg-purple">
                  <span class="pill-row">${lucide('eye', { size: 11 })} <span>${t('live.shadowDesc')}</span></span>
                </div>
              ` : ''}
              ${e.target ? `<div class="drawer-target" title="${fullTargetEsc}"><span class="icon-inline">${lucide('folder', { size: 11, color: 'var(--text-muted)' })}</span> ${fullTargetEsc}</div>` : ''}
              ${e.reason ? `<div class="drawer-reason">${reasonEsc}</div>` : ''}
              <div class="drawer-buttons">
                ${e.target ? `<button class="action-btn" onclick="openFile('${escapeJs(e.target)}')">${lucide('fileText', { size: 11 })} ${t('current.openFile')}</button>` : ''}
                ${e.reason ? `<button class="action-btn" onclick="copyReason('${escapeJs(e.reason)}')">${lucide('copy', { size: 11 })} ${t('current.copyReason')}</button>` : ''}
              </div>
            </div>
          </div>
        `;
      });
    }

    // --- TAB 2: OBLIGATIONS (ACTIONABLE TASKS + 4-STEP STATE MACHINE TRACK) ---
    let obligationsHtml = '';
    const testKeys = Object.keys(pendingTests);
    const docKeys = Object.keys(pendingDocs);

    if (testKeys.length === 0 && docKeys.length === 0) {
      obligationsHtml = `
        <div class="clean-state-box">
          ${lucide('sparkles', { size: 28, color: '#10b981', strokeWidth: 1.75 })}
          <div class="clean-state-title">${t('obligations.cleanState')}</div>
        </div>
      `;
    } else {
      if (testKeys.length > 0) {
        obligationsHtml += `<div class="section-title text-cyan"><span class="icon-inline">${lucide('flaskConical', { size: 12 })}</span> ${t('obligations.testTitle')} (${testKeys.length})</div>`;
        for (const tk of testKeys) {
          const item = pendingTests[tk];
          const hasIntent = resolutionIntents.some(intent => intent.target_path && intent.target_path.toLowerCase().includes(path.basename(tk).toLowerCase()));
          const step1Class = !hasIntent ? 'step-active' : 'step-done';
          const step2Class = hasIntent ? 'step-active' : 'step-todo';

          obligationsHtml += `
            <div class="task-card border-cyan">
              <div class="task-header">
                <span class="task-title" title="${escapeHtml(tk)}">${escapeHtml(path.basename(tk))}</span>
                <button class="mini-icon-btn" onclick="openFile('${escapeJs(tk)}')" title="${t('current.openFile')}">${lucide('fileText', { size: 12 })}</button>
              </div>
              <div class="task-meta">${t('obligations.expectedTest')}: <code class="text-cyan">${escapeHtml(item.expected_name || 'test')}</code></div>
              <div class="state-track">
                <div class="track-step ${step1Class}">${t('obligations.stepPending')}</div>
                <div class="track-arrow">${lucide('arrowRight', { size: 9 })}</div>
                <div class="track-step ${step2Class}">${t('obligations.stepIntent')}</div>
                <div class="track-arrow">${lucide('arrowRight', { size: 9 })}</div>
                <div class="track-step step-todo">${t('obligations.stepVerified')}</div>
                <div class="track-arrow">${lucide('arrowRight', { size: 9 })}</div>
                <div class="track-step step-todo">${t('obligations.stepResolved')}</div>
              </div>
              <div class="track-status-hint"><span class="icon-inline">${lucide('clock', { size: 10 })}</span> ${hasIntent ? t('obligations.hintTestIntent') : t('obligations.hintTestPending')}</div>
            </div>
          `;
        }
      }

      if (docKeys.length > 0) {
        obligationsHtml += `<div class="section-title text-amber" style="margin-top: 14px;"><span class="icon-inline">${lucide('fileText', { size: 12 })}</span> ${t('obligations.docTitle')} (${docKeys.length})</div>`;
        for (const dk of docKeys) {
          const item = pendingDocs[dk];
          const reqs = (item.required_docs || ['CHANGELOG.md']).join(', ');
          const hasIntent = resolutionIntents.some(intent => intent.target_path && intent.target_path.toLowerCase().includes('changelog'));
          const step1Class = !hasIntent ? 'step-active' : 'step-done';
          const step2Class = hasIntent ? 'step-active' : 'step-todo';

          obligationsHtml += `
            <div class="task-card border-amber">
              <div class="task-header">
                <span class="task-title" title="${escapeHtml(dk)}">${escapeHtml(path.basename(dk))}</span>
                <button class="mini-icon-btn" onclick="openFile('${escapeJs(dk)}')" title="${t('current.openFile')}">${lucide('fileText', { size: 12 })}</button>
              </div>
              <div class="task-meta">${t('obligations.requiredDoc')}: <code class="text-amber">${escapeHtml(reqs)}</code></div>
              <div class="state-track">
                <div class="track-step ${step1Class}">${t('obligations.stepPending')}</div>
                <div class="track-arrow">${lucide('arrowRight', { size: 9 })}</div>
                <div class="track-step ${step2Class}">${t('obligations.stepIntent')}</div>
                <div class="track-arrow">${lucide('arrowRight', { size: 9 })}</div>
                <div class="track-step step-todo">${t('obligations.stepVerified')}</div>
                <div class="track-arrow">${lucide('arrowRight', { size: 9 })}</div>
                <div class="track-step step-todo">${t('obligations.stepResolved')}</div>
              </div>
              <div class="track-status-hint"><span class="icon-inline">${lucide('clock', { size: 10 })}</span> ${hasIntent ? t('obligations.hintDocIntent') : t('obligations.hintDocPending')}</div>
            </div>
          `;
        }
      }

      obligationsHtml += `
        <div class="circuit-box">
          <span><span class="icon-inline">${lucide('zap', { size: 11 })}</span> ${t('obligations.circuitBreaker')}:</span>
          <span class="circuit-val ${stopRetries >= 4 ? 'text-red' : 'text-cyan'}">${stopRetries} / 5 ${t('obligations.retries')}</span>
        </div>
      `;
    }

    // --- TAB 3: RULES (CATEGORIZED SECURITY / ARCHITECTURE / QUALITY) ---
    const docGovActive = projectCfg?.governance?.enforceDocObligations === true;

    function getRuleBadge(ruleKey: string, defaultMode: 'block' | 'warn') {
      const rCfg = projectCfg?.rules?.[ruleKey];
      const isShadow = (typeof rCfg === 'object' && rCfg?.mode === 'shadow') || rCfg === 'shadow';
      if (isShadow) {
        return `<span class="mode-pill mode-shadow">${lucide('eye', { size: 9 })} ${t('rules.badgeShadow')}</span>`;
      }
      if (defaultMode === 'block') {
        return `<span class="mode-pill mode-block">${t('rules.badgeBlock')}</span>`;
      }
      return `<span class="mode-pill mode-warn">${t('rules.badgeWarnAdvisory')}</span>`;
    }

    const rulesHtml = `
      <div class="rules-group">
        <div class="group-title text-red"><span class="icon-inline">${lucide('lock', { size: 12 })}</span> ${t('rules.secTitle')}</div>
        <div class="rule-row">
          <div class="rule-name">${t('rules.g0Title')}</div>
          ${getRuleBadge('G0_SECRET_LEAK', 'block')}
        </div>
        <div class="rule-desc">${t('rules.g0Desc')}</div>

        <div class="rule-row">
          <div class="rule-name">${t('rules.g1Title')}</div>
          ${getRuleBadge('G1_SILENT_EXCEPTION', 'block')}
        </div>
        <div class="rule-desc">${t('rules.g1Desc')}</div>

        <div class="rule-row">
          <div class="rule-name">${t('rules.g2Title')}</div>
          ${getRuleBadge('G2_TEST_INTEGRITY', 'block')}
        </div>
        <div class="rule-desc">${t('rules.g2Desc')}</div>
      </div>

      <div class="rules-group">
        <div class="group-title text-purple"><span class="icon-inline">${lucide('layers', { size: 12 })}</span> ${t('rules.archTitle')}</div>
        <div class="rule-row">
          <div class="rule-name">${t('rules.g4Title')}</div>
          ${getRuleBadge('G4_IMPORT_MATRIX', 'block')}
        </div>
        <div class="rule-desc">${t('rules.g4Desc')}</div>

        <div class="rule-row">
          <div class="rule-name">${t('rules.srpTitle')}</div>
          ${getRuleBadge('SRP_BOUNDARY', 'block')}
        </div>
        <div class="rule-desc">${t('rules.srpDesc')}</div>

        <div class="rule-row">
          <div class="rule-name">${t('rules.g3Title')}</div>
          ${getRuleBadge('G3_COMPILER_BYPASS', 'warn')}
        </div>
        <div class="rule-desc">${t('rules.g3Desc')}</div>

        <div class="rule-row">
          <div class="rule-name">${t('rules.growthTitle')}</div>
          ${getRuleBadge('ARCH_FILE_GROWTH', 'warn')}
        </div>
        <div class="rule-desc">${t('rules.growthDesc')}</div>
      </div>

      <div class="rules-group">
        <div class="group-title text-cyan"><span class="icon-inline">${lucide('flaskConical', { size: 12 })}</span> ${t('rules.govTitle')}</div>
        <div class="rule-row">
          <div class="rule-name">${t('rules.t1Title')}</div>
          <span class="mode-pill mode-warn">${t('rules.badgeWarnStop')}</span>
        </div>
        <div class="rule-desc">${t('rules.t1Desc')}</div>

        <div class="rule-row">
          <div class="rule-name">${t('rules.docGovTitle')}</div>
          <span class="mode-pill ${docGovActive ? 'mode-active' : 'mode-inactive'}">${docGovActive ? t('rules.badgeOptInStop') : t('rules.badgeOff')}</span>
        </div>
        <div class="rule-desc">${t('rules.docGovDesc')}</div>
      </div>

      <div style="margin-top: 14px; text-align: center;">
        <button class="action-btn wide" onclick="openConfig()">${lucide('settings', { size: 12 })} ${t('actions.openConfig')}</button>
      </div>
    `;

    // --- TAB 4: INSIGHTS (TELEMETRY, AGENT RECOVERY, EFFECTIVENESS) ---
    const shortSess = sessionId.length > 10 ? sessionId.slice(0, 8) + '…' : sessionId;
    const eff = (data as any)?.effectiveness || {};
    const totalBlockedCount = typeof eff.totalBlocked === 'number' ? eff.totalBlocked : totalBlockedAnalyzed;
    const totalRecoveredCount = typeof eff.totalRecovered === 'number' ? eff.totalRecovered : recoveredCount;
    const finalRecRate = totalBlockedCount > 0 ? Math.round((totalRecoveredCount / totalBlockedCount) * 100) : 100;

    let recoverySubtext = '';
    if (totalBlockedCount === 0) {
      recoverySubtext = t('insights.subClean');
    } else if (totalBlockedCount < 10) {
      recoverySubtext = t('insights.subSample', { recovered: totalRecoveredCount, blocked: totalBlockedCount });
    } else {
      recoverySubtext = t('insights.subRate', { recovered: totalRecoveredCount, blocked: totalBlockedCount, rate: finalRecRate });
    }

    const ruleStats: Record<string, any> = eff.ruleStats || {};

    function formatRuleStat(ruleKey: string, defaultName: string, isWarning?: boolean) {
      const stat = ruleStats[ruleKey];
      const b = stat?.blocked || 0;
      const r = stat?.recovered || 0;
      const rate = typeof stat?.recoveryRate === 'number' ? stat.recoveryRate : (b > 0 ? Math.round((r / b) * 100) : 100);
      const med = stat?.medianAttempts || 1;
      let badgeText = t('insights.badgeInsufficient', { n: b });
      let badgeClass = 'badge-neutral';
      let badgeIcon = lucide('circleDot', { size: 9 });

      if (b === 0) {
        badgeText = t('insights.badgeNoViolations');
        badgeClass = 'badge-allowed';
        badgeIcon = lucide('checkCircle', { size: 9 });
      } else if (b < 10) {
        badgeText = t('insights.badgeInsufficient', { n: b });
        badgeClass = 'badge-neutral';
        badgeIcon = lucide('circleDot', { size: 9 });
      } else if (b < 30) {
        badgeText = t('insights.badgeEarlySignal', { n: b });
        badgeClass = 'badge-warning';
        badgeIcon = lucide('alertTriangle', { size: 9 });
      } else if (rate >= 80) {
        badgeText = t('insights.badgeHighValue', { n: b });
        badgeClass = 'badge-allowed';
        badgeIcon = lucide('trophy', { size: 9 });
      } else if (rate < 50) {
        badgeText = t('insights.badgeFriction', { n: b });
        badgeClass = 'badge-blocked';
        badgeIcon = lucide('zap', { size: 9 });
      } else {
        badgeText = t('insights.badgeBalanced', { n: b });
        badgeClass = 'badge-cyan';
        badgeIcon = lucide('checkCircle', { size: 9 });
      }

      return {
        label: defaultName,
        b,
        r,
        rate,
        med,
        isWarning: !!isWarning,
        badgeText,
        badgeClass,
        badgeIcon
      };
    }

    const rulesToDisplay = [
      formatRuleStat('G0_SECRET_LEAK', t('rules.g0Title')),
      formatRuleStat('G1_SILENT_EXCEPTION', t('rules.g1Title')),
      formatRuleStat('G2_TEST_INTEGRITY', t('rules.g2Title')),
      formatRuleStat('G4_IMPORT_MATRIX', t('rules.g4Title')),
      formatRuleStat('SRP_BOUNDARY', t('rules.srpTitle')),
      formatRuleStat('ARCH_FILE_GROWTH', t('rules.growthTitle'), true),
      formatRuleStat('G3_COMPILER_BYPASS', t('rules.g3Title'), true)
    ];

    const knownKeys = new Set(['G0_SECRET_LEAK', 'G1_SILENT_EXCEPTION', 'G2_TEST_INTEGRITY', 'G4_IMPORT_MATRIX', 'SRP_BOUNDARY', 'ARCH_FILE_GROWTH', 'G3_COMPILER_BYPASS']);
    for (const k of Object.keys(ruleStats)) {
      if (!knownKeys.has(k) && (ruleStats[k]?.blocked > 0 || ruleStats[k]?.recovered > 0)) {
        rulesToDisplay.push(formatRuleStat(k, k));
      }
    }

    const lastEvent = (data.events && data.events.length > 0) ? data.events[0] : null;
    const latencyMatch = lastEvent?.reason?.match(/\((\d+(\.\d+)?ms)\)/);
    const measuredLatency = latencyMatch ? latencyMatch[1] : '< 1 ms';

    const lastSeq = (data as any)?.lastAuditSeq || 0;

    const growthRuleCfg = projectCfg?.rules?.['ARCH_FILE_GROWTH'];
    const isGrowthShadow = (typeof growthRuleCfg === 'object' && growthRuleCfg?.mode === 'shadow') || growthRuleCfg === 'shadow';

    const g3RuleCfg = projectCfg?.rules?.['G3_COMPILER_BYPASS'];
    const isG3Shadow = (typeof g3RuleCfg === 'object' && g3RuleCfg?.mode === 'shadow') || g3RuleCfg === 'shadow';

    const insightsHtml = `
      <div class="insight-card">
        <div class="insight-title"><span class="icon-inline">${lucide('target', { size: 12 })}</span> ${t('insights.recoveryTitle')}</div>
        <div class="recovery-meter">
          <div class="recovery-bar-wrap">
            <div class="recovery-bar" style="width: ${finalRecRate}%;"></div>
          </div>
          <div class="recovery-score">${totalBlockedCount === 0 ? '100%' : `${finalRecRate}%`}</div>
        </div>
        <div class="insight-sub">${recoverySubtext}</div>
      </div>

      <div class="insight-card">
        <div class="insight-title"><span class="icon-inline">${lucide('shieldCheck', { size: 12 })}</span> ${t('insights.reportCardTitle')}</div>
        ${rulesToDisplay.map(st => `
          <div class="rule-stat-item">
            <div class="rule-stat-header">
              <span class="rule-stat-name">${escapeHtml(st.label)}</span>
              <span class="status-badge ${st.badgeClass}">${st.badgeIcon} ${st.badgeText}</span>
            </div>
            ${st.b > 0 ? `
              <div class="rule-stat-sub">
                <span>${st.isWarning ? t('insights.ruleWarnings', { count: st.b, rate: st.rate }) : t('insights.ruleInterventions', { blocked: st.b, recovered: st.r, rate: st.rate })}</span>
                ${!st.isWarning ? `<span>${t('insights.medianAttempts', { attempts: st.med })}</span>` : ''}
              </div>
            ` : `<div class="rule-stat-sub text-muted">${t('insights.ruleClean')}</div>`}
          </div>
        `).join('')}
      </div>

      <div class="insight-card">
        <div class="insight-title"><span class="icon-inline">${lucide('alertTriangle', { size: 12 })}</span> ${t('insights.lifecycleTitle')}</div>
        <div class="metric-row">
          <span class="metric-lbl">${t('insights.t1Label')}</span>
          <span class="metric-val text-cyan">${testKeys.length > 0 ? t('insights.t1Pending', { count: testKeys.length }) : t('insights.t1Verified')}</span>
        </div>
        <div class="metric-row">
          <span class="metric-lbl">${t('insights.docLabel')}</span>
          <span class="metric-val ${docGovActive ? 'text-green' : 'text-muted'}">${docGovActive ? (docKeys.length > 0 ? t('insights.docPending', { count: docKeys.length }) : t('insights.docActive')) : t('insights.docDisabled')}</span>
        </div>
        <div class="metric-row">
          <span class="metric-lbl">${t('insights.growthLabel')}</span>
          <span class="metric-val ${isGrowthShadow ? 'text-purple' : 'text-amber'}">${isGrowthShadow ? t('insights.growthValueShadow') : t('insights.growthValueWarn')}</span>
        </div>
        <div class="metric-row">
          <span class="metric-lbl">${t('insights.g3Label')}</span>
          <span class="metric-val ${isG3Shadow ? 'text-purple' : 'text-amber'}">${isG3Shadow ? t('insights.g3ValueShadow') : t('insights.g3Value')}</span>
        </div>
      </div>

      <details class="diagnostics-details">
        <summary class="diagnostics-summary">
          <span class="summary-left">
            <span class="icon-inline">${lucide('settings', { size: 11, color: 'var(--text-muted)' })}</span>
            <span class="diagnostics-title">${t('insights.diagnosticsTitle')}</span>
          </span>
          <span class="status-badge badge-neutral" style="font-size: 8px; padding: 1px 5px;">
            ${lucide('database', { size: 8 })} ${t('insights.diagnosticsBadge')}
          </span>
        </summary>
        <div class="diagnostics-body">
          <div class="insight-card" style="margin-top: 6px;">
            <div class="insight-title"><span class="icon-inline">${lucide('database', { size: 12 })}</span> ${t('insights.walTitle')}</div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.walJournalLabel')}</span>
              <span class="metric-val text-green"><span class="icon-inline">${lucide('circleDot', { size: 9, color: 'var(--color-green)' })}</span> ${t('insights.walJournalValue')}</span>
            </div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.walLiveLabel')}</span>
              <span class="metric-val text-cyan"><span class="icon-inline">${lucide('circleDot', { size: 9, color: 'var(--color-cyan)' })}</span> ${t('insights.walLiveValue', { seq: lastSeq })}</span>
            </div>
          </div>

          <div class="insight-card">
            <div class="insight-title"><span class="icon-inline">${lucide('cpu', { size: 12 })}</span> ${t('insights.perfTitle')}</div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.latencyFast')}:</span>
              <span class="metric-val text-green">${measuredLatency}</span>
            </div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.latencySpawn')}:</span>
              <span class="metric-val text-muted">${t('insights.spawnBudget')}</span>
            </div>
          </div>

          <div class="insight-card">
            <div class="insight-title"><span class="icon-inline">${lucide('lock', { size: 12 })}</span> ${t('insights.integrityTitle')}</div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.lockStatus')}:</span>
              <span class="metric-val text-green"><span class="icon-inline">${lucide('checkCircle', { size: 10, color: 'var(--color-green)' })}</span> ${t('insights.lockHealthy')}</span>
            </div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.twoPhase')}:</span>
              <span class="metric-val text-green"><span class="icon-inline">${lucide('checkCircle', { size: 10, color: 'var(--color-green)' })}</span> ${t('insights.twoPhaseActive')}</span>
            </div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.sessionLabel')}</span>
              <span class="metric-val text-cyan">${shortSess}</span>
            </div>
            <div class="metric-row">
              <span class="metric-lbl">${t('insights.circuitLabel')}</span>
              <span class="metric-val text-muted">${t('insights.circuitValue', { retries: stopRetries })}</span>
            </div>
          </div>
        </div>
      </details>
    `;

    // --- RENDER MAIN WEBVIEW HTML ---
    this._view.webview.html = `
      <!DOCTYPE html>
      <html lang="en">
      <head>
        <meta charset="UTF-8">
        <style>
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

          /* Diagnostics & System Health (Collapsible) */
          .diagnostics-details {
            margin-top: 10px;
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid var(--border-dim);
            border-radius: 6px;
            overflow: hidden;
          }
          .diagnostics-summary {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 6px 8px;
            cursor: pointer;
            user-select: none;
            font-size: 9px;
            font-weight: 700;
            color: var(--text-muted);
          }
          .diagnostics-summary:hover {
            background: var(--bg-hover);
            color: var(--text-main);
          }
          .diagnostics-title {
            font-size: 9px;
            font-weight: 800;
            letter-spacing: 0.3px;
          }
          .diagnostics-body {
            padding: 6px 8px 8px 8px;
            border-top: 1px solid var(--border-dim);
          }
          .telemetry-alert-banner {
            background: rgba(245, 158, 11, 0.15);
            border: 1px solid var(--color-amber);
            color: #fbbf24;
            padding: 6px 8px;
            border-radius: 6px;
            margin-bottom: 8px;
            font-size: 10px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 6px;
          }
          .recovery-flow-row {
            display: inline-flex;
            align-items: center;
            gap: 4px;
          }

          /* Insights */
          .insight-card {
            background: var(--bg-card);
            border: 1px solid var(--border-dim);
            border-radius: 6px;
            padding: 8px;
            margin-bottom: 8px;
          }
          .insight-title { font-weight: 800; font-size: 10px; color: var(--color-cyan); margin-bottom: 6px; }
          .recovery-meter { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
          .recovery-bar-wrap { flex: 1; height: 6px; background: rgba(255, 255, 255, 0.1); border-radius: 3px; overflow: hidden; }
          .recovery-bar { height: 100%; background: var(--color-green); border-radius: 3px; }
          .recovery-score { font-size: 12px; font-weight: 900; color: var(--color-green); }
          .insight-sub { font-size: 9px; color: var(--text-muted); }
          .metric-row { display: flex; justify-content: space-between; font-size: 9px; padding: 2px 0; }
          .metric-lbl { color: var(--text-muted); }
          .metric-val { font-weight: 700; }
          .rule-stat-item {
            padding: 6px 0;
            border-bottom: 1px solid var(--border-dim);
          }
          .rule-stat-item:last-child {
            border-bottom: none;
          }
          .rule-stat-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 3px;
          }
          .rule-stat-name {
            font-weight: 700;
            font-size: 10px;
            color: var(--text-main);
          }
          .rule-stat-sub {
            display: flex;
            justify-content: space-between;
            font-size: 9px;
            color: var(--text-muted);
          }

          /* Helpers */
          .text-green { color: var(--color-green); }
          .text-red { color: var(--color-red); }
          .text-amber { color: var(--color-amber); }
          .text-cyan { color: var(--color-cyan); }
          .text-purple { color: var(--color-purple); }
          .text-muted { color: var(--text-muted); }
          .section-title { font-size: 9px; font-weight: 800; text-transform: uppercase; margin-bottom: 6px; letter-spacing: 0.4px; }
          .circuit-box { margin-top: 8px; padding: 6px 8px; background: rgba(0,0,0,0.2); border-radius: 4px; display: flex; justify-content: space-between; font-size: 9px; color: var(--text-muted); }
          .clean-state-box { text-align: center; padding: 20px 8px; border: 1px dashed rgba(16, 185, 129, 0.25); border-radius: 8px; background: rgba(16, 185, 129, 0.04); }
          .clean-state-title { font-weight: 700; font-size: 10px; color: var(--color-green); margin-top: 6px; }
          .empty-state { text-align: center; color: var(--text-muted); padding: 20px; font-size: 10px; }
          .icon-inline {
            display: inline-flex;
            align-items: center;
            vertical-align: middle;
            margin-right: 3px;
          }
          .pill-row {
            display: inline-flex;
            align-items: center;
            gap: 4px;
          }
          .idle-inline {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            justify-content: center;
          }
        </style>
      </head>
      <body>
        <!-- Header -->
        <div class="header">
          <div class="header-left">
            ${lucide('shield', { size: 15, color: 'var(--color-cyan)', strokeWidth: 2.2 })}
            <span class="brand-title">${t('appName')}</span>
            <span class="project-pill">${escapeHtml(projectName)}</span>
          </div>
          <div class="header-right">
            <button class="mini-btn" onclick="toggleLanguage()" title="${t('actions.switchLang')}">${lucide('globe', { size: 11 })} <span>${getCurrentLanguage().toUpperCase()}</span></button>
            <button class="mini-btn" onclick="openConfig()" title="${t('actions.openConfig')}">${lucide('settings', { size: 11 })}</button>
            <button class="mini-btn" onclick="clearLogs()" title="${t('actions.clearLogs')}">${lucide('trash2', { size: 11 })}</button>
          </div>
        </div>

        <!-- Current Action Banner -->
        ${currentCardHtml}

        <!-- Quick Summary Bar -->
        <div class="stat-summary-bar">
          <div class="stat-chip"><div class="chip-val text-red">${blockedCount}</div><div class="chip-lbl">${t('stats.blocked')}</div></div>
          <div class="stat-chip"><div class="chip-val text-amber">${warningCount}</div><div class="chip-lbl">${t('stats.warning')}</div></div>
          <div class="stat-chip"><div class="chip-val text-green">${approvedCount}</div><div class="chip-lbl">${t('stats.approved')}</div></div>
          ${shadowCount > 0 ? `<div class="stat-chip"><div class="chip-val text-purple">${shadowCount}</div><div class="chip-lbl">${t('current.statusShadow')}</div></div>` : ''}
          <div class="stat-chip" title="${t('obligations.title')}"><div class="chip-val ${totalObligations > 0 ? 'text-cyan' : 'text-muted'}">${totalObligations}</div><div class="chip-lbl">${t('stats.pending')}</div></div>
        </div>

        <!-- Tabs -->
        <div class="tabs-bar">
          <button class="tab-btn ${activeTab === 'live' ? 'active' : ''}" id="btn-live" onclick="setTab('live')">${lucide('zap', { size: 11 })} ${t('tabs.live')}</button>
          <button class="tab-btn ${activeTab === 'obligations' ? 'active' : ''}" id="btn-obligations" onclick="setTab('obligations')">${lucide('clipboardList', { size: 11 })} ${t('tabs.obligations')}${totalObligations > 0 ? `<span class="badge-counter">${totalObligations}</span>` : ''}</button>
          <button class="tab-btn ${activeTab === 'rules' ? 'active' : ''}" id="btn-rules" onclick="setTab('rules')">${lucide('sliders', { size: 11 })} ${t('tabs.rules')}</button>
          <button class="tab-btn ${activeTab === 'insights' ? 'active' : ''}" id="btn-insights" onclick="setTab('insights')">${lucide('barChart', { size: 11 })} ${t('tabs.insights')}</button>
        </div>

        <!-- Panes -->
        <div id="tab-live" class="tab-pane ${activeTab === 'live' ? 'active' : ''}">
          ${liveHtml}
        </div>
        <div id="tab-obligations" class="tab-pane ${activeTab === 'obligations' ? 'active' : ''}">
          ${obligationsHtml}
        </div>
        <div id="tab-rules" class="tab-pane ${activeTab === 'rules' ? 'active' : ''}">
          ${rulesHtml}
        </div>
        <div id="tab-insights" class="tab-pane ${activeTab === 'insights' ? 'active' : ''}">
          ${insightsHtml}
        </div>

        <script>
          const vscode = acquireVsCodeApi();
          const savedState = vscode.getState() || {};
          let currentTab = savedState.currentTab || '${escapeJs(activeTab)}';

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

          function clearLogs() { vscode.postMessage({ command: 'clearLogs' }); }
          function refresh() { vscode.postMessage({ command: 'refresh' }); }
          function toggleLanguage() { vscode.postMessage({ command: 'toggleLanguage' }); }
          function openFile(path) { vscode.postMessage({ command: 'openFile', path }); }
          function openConfig() { vscode.postMessage({ command: 'openConfig' }); }
          function copyReason(text) { vscode.postMessage({ command: 'copyReason', text }); }
        </script>
      </body>
      </html>
    `;
  }
}

export function deactivate(): void {}
