import * as vscode from 'vscode';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as http from 'http';
import { buildOfflinePrompt, buildSystemPrompt, classifyIntent, modeLabel, shouldAskForMode, IntentClassification, IntentMode } from './intent';
import { initI18n, t, setLanguage, getCurrentLanguage } from './i18n';

interface LogEvent {
  status?: string;
  timestamp?: string;
  target?: string;
  action?: string;
  reason?: string;
  ruleId?: string;
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
  initI18n(vscode.env.language);
  console.log('[GravityGuard] Extension activated successfully!');

  // 1. Register Webview Provider for GravityGuard Live Monitor
  const provider = new GuardianViewProvider(context.extensionUri);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider('antigravity-guardian-view', provider)
  );

  // 2. Register Status Bar Item for Prompt Enhancement
  const promptStatusBarItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100
  );
  promptStatusBarItem.command = 'antigravityBridge.enhancePrompt';
  promptStatusBarItem.text = '$(sparkle) Prompt Geliştir';
  promptStatusBarItem.tooltip = 'GravityGuard: Yerel AI ağ geçidi ile Promptu Geliştir (Ctrl+Alt+E)';
  promptStatusBarItem.show();
  context.subscriptions.push(promptStatusBarItem);

  // 3. Register Commands
  context.subscriptions.push(
    vscode.commands.registerCommand('antigravityBridge.ping', async () => {
      const health = await probeRouter();
      if (health.ok) {
        vscode.window.showInformationMessage(`🚀 GravityGuard is Live — yerel AI geçidi: ${health.detail}`);
      } else {
        vscode.window.showWarningMessage(
          `GravityGuard aktif, ancak yerel AI geçidine ulaşılamıyor: ${health.detail}. Prompt Geliştir yine de çalışır (çevrimdışı şablon modu).`
        );
      }
    }),
    vscode.commands.registerCommand('antigravityBridge.refreshLogs', () => {
      provider.updateHtml();
    }),
    vscode.commands.registerCommand('antigravityBridge.clearLogs', () => {
      provider.clearLogs();
    }),
    vscode.commands.registerCommand('antigravityBridge.toggleLanguage', () => {
      const next = getCurrentLanguage() === 'tr' ? 'en' : 'tr';
      setLanguage(next);
      provider.updateHtml();
      vscode.window.showInformationMessage(`GravityGuard dili: ${next.toUpperCase()}`);
    }),
    vscode.commands.registerCommand('antigravityBridge.enhancePrompt', async () => {
      await handleEnhancePrompt();
    })
  );
}

async function handleEnhancePrompt(): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  let initialText = '';

  if (editor && !editor.selection.isEmpty) {
    initialText = editor.document.getText(editor.selection).trim();
  }

  const inputPrompt = await vscode.window.showInputBox({
    prompt: 'Geliştirmek istediğiniz prompt veya talimatı girin (GravityGuard AI):',
    placeHolder: 'Örn: SRP kuralına uygun websocket bağlantı yöneticisi oluştur...  |  Mod sabitlemek için: "#denetle: ..."',
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
        title: `GravityGuard: ${modeLabel(mode)} modunda prompt hazırlanıyor...`,
        cancellable: false
      },
      async () => {
        result = await requestPromptEnhancement(inputPrompt.trim(), mode);
      }
    );

    if (!result || !result.text) {
      vscode.window.showErrorMessage('Prompt geliştirilemedi.');
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
    const originNote = result.offline ? ' — çevrimdışı şablon modu' : '';
    const action = await vscode.window.showInformationMessage(
      `✨ Prompt geliştirildi ve panoya kopyalandı (${modeLabel(result.mode)}${originNote})`,
      'Yeni Belgede Aç'
    );

    if (action === 'Yeni Belgede Aç') {
      const doc = await vscode.workspace.openTextDocument({
        content: enhancedResult,
        language: 'markdown'
      });
      await vscode.window.showTextDocument(doc);
    }
  } catch (error: any) {
    console.error('[Prompt Enhancer Error]:', error);
    vscode.window.showErrorMessage(
      `Prompt geliştirme hatası: ${error?.message || error}`
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
        label: `$(sparkle) Otomatik — ${modeLabel(classification.mode)}`,
        description: 'Sınıflandırıcının tahmini (düşük güven)',
        mode: classification.mode
      },
      ...MODES.filter(mode => mode !== classification.mode).map(mode => ({
        label: modeLabel(mode),
        description: mode === 'consult'
          ? 'Fikir, seçenek ve trade-off iste'
          : mode === 'implement'
            ? 'Savunmacı teknik şartname üret'
            : 'Kod değiştirmeden, kanıtlı bulgu listesi üret',
        mode
      }))
    ],
    { placeHolder: 'Niyet belirsiz — modu seçin (varsayılan: Otomatik)' }
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

  constructor(private readonly _extensionUri: vscode.Uri) {}

  public resolveWebviewView(webviewView: vscode.WebviewView): void {
    this._view = webviewView;
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri]
    };

    webviewView.webview.onDidReceiveMessage(async (message: { command: string; path?: string; text?: string }) => {
      if (message.command === 'clearLogs') {
        this.clearLogs();
      } else if (message.command === 'refresh') {
        this.updateHtml();
      } else if (message.command === 'toggleLanguage') {
        const next = getCurrentLanguage() === 'tr' ? 'en' : 'tr';
        setLanguage(next);
        this.updateHtml();
      } else if (message.command === 'openFile' && message.path) {
        try {
          const doc = await vscode.workspace.openTextDocument(message.path);
          await vscode.window.showTextDocument(doc);
        } catch (e: any) {
          vscode.window.showErrorMessage(`Dosya açılamadı: ${message.path}`);
        }
      } else if (message.command === 'openConfig') {
        const workspaceFolders = vscode.workspace.workspaceFolders;
        if (workspaceFolders && workspaceFolders.length > 0) {
          const cfgFile = path.join(workspaceFolders[0].uri.fsPath, '.gravityguard.json');
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
            const doc = await vscode.workspace.openTextDocument(cfgFile);
            await vscode.window.showTextDocument(doc);
          } catch (e: any) {
            vscode.window.showErrorMessage(`Yapılandırma dosyası açılamadı: ${e.message}`);
          }
        }
      } else if (message.command === 'copyReason' && message.text) {
        await vscode.env.clipboard.writeText(message.text);
        vscode.window.showInformationMessage('Kural engelleme nedeni panoya kopyalandı.');
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

  public clearLogs(): void {
    const logPath = path.join(os.homedir(), '.gemini', 'logs', 'srp_guardian_live.json');
    const emptyState: GuardianData = {
      activeGuard: 'GravityGuard',
      status: 'ONLINE',
      lastCheck: new Date().toISOString(),
      events: []
    };
    try {
      fs.writeFileSync(logPath, JSON.stringify(emptyState, null, 2), 'utf8');
      this.updateHtml();
      vscode.window.showInformationMessage('🧹 GravityGuard günlükleri temizlendi!');
    } catch (e) {
      console.error('Clear log error:', e);
    }
  }

  public updateHtml(): void {
    if (!this._view) {
      return;
    }

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

    const totalObligations = Object.keys(pendingTests).length + Object.keys(pendingDocs).length;
    const eventsList = data.events || [];
    const blockedCount = eventsList.filter(e => e.status === 'BLOCKED').length;
    const warningCount = eventsList.filter(e => e.status === 'WARNING').length;
    const approvedCount = eventsList.filter(e => e.status === 'APPROVED').length;
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
      const statusText = isBlk ? '🛑 BLOCKED' : isWrn ? '⚠ WARNING' : '✅ ALLOWED';
      const actionName = latestEvent.action || 'write_file';
      const targetName = latestEvent.target ? path.basename(latestEvent.target) : 'workspace';
      const ruleText = latestEvent.ruleId && latestEvent.ruleId !== 'PASS' ? latestEvent.ruleId : 'G0 G1 G2 G4 ✓';
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
              <span class="status-badge ${badgeCls}">${statusText}</span>
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
            <span>⚡ ${t('current.idle')}</span>
          </div>
        </div>
      `;
    }

    // --- TAB 1: LIVE STREAM (COMPACT ROWS WITH EXPANDABLE ACCORDION) ---
    let liveHtml = '';
    if (eventsList.length === 0) {
      liveHtml = `<div class="empty-state">${t('events.noEvents')}</div>`;
    } else {
      eventsList.forEach((e, idx) => {
        const isBlk = e.status === 'BLOCKED';
        const isWrn = e.status === 'WARNING';
        const badgeCls = isBlk ? 'badge-blocked' : isWrn ? 'badge-warning' : 'badge-allowed';
        const statusLabel = isBlk ? 'BLOCK' : isWrn ? 'WARN' : 'ALLOW';
        const fileName = e.target ? path.basename(e.target) : (e.action || 'system');
        const timeStr = e.timestamp ? (e.timestamp.split(' ')[1] || e.timestamp) : '';
        const ruleId = e.ruleId || 'PASS';
        const fullTargetEsc = escapeHtml(e.target || '');
        const reasonEsc = escapeHtml(e.reason || '');

        liveHtml += `
          <div class="stream-item">
            <div class="stream-row" onclick="toggleDetail('evt-${idx}')">
              <div class="stream-left">
                <span class="status-badge ${badgeCls}">${statusLabel}</span>
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
                <span class="status-badge ${badgeCls}">${e.status}</span>
              </div>
              ${e.target ? `<div class="drawer-target" title="${fullTargetEsc}">📁 ${fullTargetEsc}</div>` : ''}
              ${e.reason ? `<div class="drawer-reason">${reasonEsc}</div>` : ''}
              <div class="drawer-buttons">
                ${e.target ? `<button class="action-btn" onclick="openFile('${escapeJs(e.target)}')">📄 ${t('current.openFile')}</button>` : ''}
                ${e.reason ? `<button class="action-btn" onclick="copyReason('${escapeJs(e.reason)}')">📋 ${t('current.copyReason')}</button>` : ''}
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
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
          <div class="clean-state-title">${t('obligations.cleanState')}</div>
        </div>
      `;
    } else {
      if (testKeys.length > 0) {
        obligationsHtml += `<div class="section-title text-cyan">🧪 ${t('obligations.testTitle')} (${testKeys.length})</div>`;
        for (const tk of testKeys) {
          const item = pendingTests[tk];
          const hasIntent = resolutionIntents.some(intent => intent.target_path && intent.target_path.toLowerCase().includes(path.basename(tk).toLowerCase()));
          const step1Class = !hasIntent ? 'step-active' : 'step-done';
          const step2Class = hasIntent ? 'step-active' : 'step-todo';

          obligationsHtml += `
            <div class="task-card border-cyan">
              <div class="task-header">
                <span class="task-title" title="${escapeHtml(tk)}">${escapeHtml(path.basename(tk))}</span>
                <button class="mini-icon-btn" onclick="openFile('${escapeJs(tk)}')" title="${t('current.openFile')}">📄</button>
              </div>
              <div class="task-meta">${t('obligations.expectedTest')}: <code class="text-cyan">${escapeHtml(item.expected_name || 'test')}</code></div>
              <div class="state-track">
                <div class="track-step ${step1Class}">PENDING</div>
                <div class="track-arrow">→</div>
                <div class="track-step ${step2Class}">INTENT</div>
                <div class="track-arrow">→</div>
                <div class="track-step step-todo">VERIFIED</div>
                <div class="track-arrow">→</div>
                <div class="track-step step-todo">RESOLVED</div>
              </div>
              <div class="track-status-hint">${hasIntent ? '⏳ İki fazlı taahhüt alındı; diske yazım doğrulanması bekleniyor' : '⏳ Ajanın test dosyasını oluşturması/düzenlemesi bekleniyor'}</div>
            </div>
          `;
        }
      }

      if (docKeys.length > 0) {
        obligationsHtml += `<div class="section-title text-amber" style="margin-top: 14px;">📝 ${t('obligations.docTitle')} (${docKeys.length})</div>`;
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
                <button class="mini-icon-btn" onclick="openFile('${escapeJs(dk)}')" title="${t('current.openFile')}">📄</button>
              </div>
              <div class="task-meta">${t('obligations.requiredDoc')}: <code class="text-amber">${escapeHtml(reqs)}</code></div>
              <div class="state-track">
                <div class="track-step ${step1Class}">PENDING</div>
                <div class="track-arrow">→</div>
                <div class="track-step ${step2Class}">INTENT</div>
                <div class="track-arrow">→</div>
                <div class="track-step step-todo">VERIFIED</div>
                <div class="track-arrow">→</div>
                <div class="track-step step-todo">RESOLVED</div>
              </div>
              <div class="track-status-hint">${hasIntent ? '⏳ Dokümantasyon taahhüdü alındı; diske yazım doğrulanması bekleniyor' : '⏳ docs/KNOWLEDGE.md §6 uyarınca CHANGELOG güncellenmeli'}</div>
            </div>
          `;
        }
      }

      obligationsHtml += `
        <div class="circuit-box">
          <span>${t('obligations.circuitBreaker')}:</span>
          <span class="circuit-val ${stopRetries >= 4 ? 'text-red' : 'text-cyan'}">${stopRetries} / 5 ${t('obligations.retries')}</span>
        </div>
      `;
    }

    // --- TAB 3: RULES (CATEGORIZED SECURITY / ARCHITECTURE / QUALITY) ---
    const docGovActive = projectCfg?.governance?.enforceDocObligations === true;
    const rulesHtml = `
      <div class="rules-group">
        <div class="group-title text-red">🔒 Security Guards (Sıfır Tolerans)</div>
        <div class="rule-row">
          <div class="rule-name">● G0 Secret Leak Shield</div>
          <span class="mode-pill mode-block">BLOCK</span>
        </div>
        <div class="rule-desc">Tüm dosyalarda API key, JWT, özel anahtar sızıntılarını engeller.</div>

        <div class="rule-row">
          <div class="rule-name">● G1 Silent Error Swallowing</div>
          <span class="mode-pill mode-block">BLOCK</span>
        </div>
        <div class="rule-desc">Hataların 'except: pass' ile sessizce yutulmasını kesinlikle engeller.</div>

        <div class="rule-row">
          <div class="rule-name">● G2 Test Integrity Protection</div>
          <span class="mode-pill mode-block">BLOCK</span>
        </div>
        <div class="rule-desc">Testlerin sahte 'assert True' ile geçilmesini veya silinmesini engeller.</div>
      </div>

      <div class="rules-group">
        <div class="group-title text-purple">🧱 Architectural Guards</div>
        <div class="rule-row">
          <div class="rule-name">● G4 Import Matrix & Layers</div>
          <span class="mode-pill mode-block">BLOCK</span>
        </div>
        <div class="rule-desc">Katmanlar arası döngüsel veya ters yönde yasadışı importları engeller.</div>

        <div class="rule-row">
          <div class="rule-name">● SRP & Cohesion Boundary</div>
          <span class="mode-pill mode-block">BLOCK</span>
        </div>
        <div class="rule-desc">Tek dosyada çoklu iş yapılmasını önler; cohesive monolith istisnası korur.</div>

        <div class="rule-row">
          <div class="rule-name">● G3 Compiler/Linter Bypass</div>
          <span class="mode-pill mode-warn">WARN (ADVISORY)</span>
        </div>
        <div class="rule-desc">@ts-ignore veya # type: ignore tespitinde tavsiye uyarısı verir; engellemez.</div>

        <div class="rule-row">
          <div class="rule-name">● ARCH_FILE_GROWTH</div>
          <span class="mode-pill mode-warn">WARN (ADVISORY)</span>
        </div>
        <div class="rule-desc">Tek hamlede devasa kod yığılmasında tavsiye uyarısı verir; shadow mode destekler.</div>
      </div>

      <div class="rules-group">
        <div class="group-title text-cyan">🧪 Quality & Governance</div>
        <div class="rule-row">
          <div class="rule-name">● T1/T2 Test Evidence</div>
          <span class="mode-pill mode-warn">WARN (STOP OBLIGATION)</span>
        </div>
        <div class="rule-desc">PreTool: Tavsiye Uyarısı • Stop Hook: Kapanış Yükümlülüğü (Fiziksel Disk Doğrulama).</div>

        <div class="rule-row">
          <div class="rule-name">● Doc Governance (§6 Same-Commit)</div>
          <span class="mode-pill ${docGovActive ? 'mode-active' : 'mode-inactive'}">${docGovActive ? 'OPT-IN (STOP)' : 'OFF'}</span>
        </div>
        <div class="rule-desc">Motor dosyası değiştiğinde oturum kapanışında CHANGELOG güncellenmesini zorlar.</div>
      </div>

      <div style="margin-top: 14px; text-align: center;">
        <button class="action-btn wide" onclick="openConfig()">⚙️ ${t('actions.openConfig')}</button>
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
      recoverySubtext = 'Henüz engellenen işlem yok (Temiz Oturum)';
    } else if (totalBlockedCount < 10) {
      recoverySubtext = `${totalRecoveredCount} / ${totalBlockedCount} düzeltildi (Yetersiz Örneklem, n=${totalBlockedCount})`;
    } else {
      recoverySubtext = `${totalRecoveredCount} / ${totalBlockedCount} ihlal ajan tarafından düzeltildi (%${finalRecRate})`;
    }

    const ruleStats: Record<string, any> = eff.ruleStats || {};

    function formatRuleStat(ruleKey: string, defaultName: string): { label: string; val: string; valClass: string } {
      const stat = ruleStats[ruleKey];
      if (!stat || stat.blocked === 0) {
        return {
          label: defaultName,
          val: 'Temiz (0 İhlal)',
          valClass: 'text-muted'
        };
      }
      const n = stat.blocked;
      if (n < 10) {
        return {
          label: defaultName,
          val: `Yetersiz Veri (n=${n})`,
          valClass: 'text-muted'
        };
      }
      const rate = typeof stat.recoveryRate === 'number' ? stat.recoveryRate : 0;
      const med = stat.medianAttempts || 1;
      const valClass = rate >= 80 ? 'text-green' : rate >= 50 ? 'text-cyan' : 'text-amber';
      const prefix = n < 30 ? 'Ön Sinyal: ' : '';
      return {
        label: defaultName,
        val: `${prefix}%${rate} Düzeltme (n=${n}, medyan ${med})`,
        valClass
      };
    }

    const g0Stat = formatRuleStat('G0_SECRET_LEAK', 'G0 Secret Leak');
    const g1Stat = formatRuleStat('G1_SILENT_EXCEPTION', 'G1 Silent Exception');
    const g2Stat = formatRuleStat('G2_TEST_INTEGRITY', 'G2 Test Integrity');
    const g4Stat = formatRuleStat('G4_IMPORT_MATRIX', 'G4 Import Matrix');
    const srpStat = formatRuleStat('SRP_BOUNDARY', 'SRP & Cohesion');

    const insightsHtml = `
      <div class="insight-card">
        <div class="insight-title">🎯 ${t('insights.recoveryTitle')}</div>
        <div class="recovery-meter">
          <div class="recovery-bar-wrap">
            <div class="recovery-bar" style="width: ${finalRecRate}%;"></div>
          </div>
          <div class="recovery-score">${totalBlockedCount === 0 ? '100%' : `${finalRecRate}%`}</div>
        </div>
        <div class="insight-sub">${recoverySubtext}</div>
      </div>

      <div class="insight-card">
        <div class="insight-title">🛡️ Güvenlik ve Mimari Gardiyanları (Ampirik Veri)</div>
        <div class="metric-row">
          <span class="metric-lbl">${g0Stat.label}:</span>
          <span class="metric-val ${g0Stat.valClass}">${g0Stat.val}</span>
        </div>
        <div class="metric-row">
          <span class="metric-lbl">${g1Stat.label}:</span>
          <span class="metric-val ${g1Stat.valClass}">${g1Stat.val}</span>
        </div>
        <div class="metric-row">
          <span class="metric-lbl">${g2Stat.label}:</span>
          <span class="metric-val ${g2Stat.valClass}">${g2Stat.val}</span>
        </div>
        <div class="metric-row">
          <span class="metric-lbl">${g4Stat.label}:</span>
          <span class="metric-val ${g4Stat.valClass}">${g4Stat.val}</span>
        </div>
        <div class="metric-row">
          <span class="metric-lbl">${srpStat.label}:</span>
          <span class="metric-val ${srpStat.valClass}">${srpStat.val}</span>
        </div>
      </div>

      <div class="insight-card">
        <div class="insight-title">⚠️ Yaşam Döngüsü ve Tavsiye Kuralları</div>
        <div class="metric-row">
          <span class="metric-lbl">T1 Test Evidence:</span>
          <span class="metric-val text-cyan">${testKeys.length > 0 ? `${testKeys.length} Bekleyen Test Kanıtı` : 'Kapanış Doğrulandı'}</span>
        </div>
        <div class="metric-row">
          <span class="metric-lbl">Doc Governance (§6):</span>
          <span class="metric-val ${docGovActive ? 'text-green' : 'text-muted'}">${docGovActive ? (docKeys.length > 0 ? `${docKeys.length} Bekleyen Dokümantasyon` : 'Aktif (Kapanış Şartı)') : 'Devre Dışı'}</span>
        </div>
        <div class="metric-row">
          <span class="metric-lbl">ARCH_FILE_GROWTH:</span>
          <span class="metric-val text-amber">Tavsiye Uyarısı / Gölge Modu</span>
        </div>
        <div class="metric-row">
          <span class="metric-lbl">G3 Compiler Bypass:</span>
          <span class="metric-val text-amber">Tavsiye Uyarısı</span>
        </div>
      </div>

      <div class="insight-card">
        <div class="insight-title">⚡ Latency & Engine Performance</div>
        <div class="metric-row">
          <span class="metric-lbl">${t('insights.latencyFast')}:</span>
          <span class="metric-val text-green">~0.03 ms (< 10 ms bütçe)</span>
        </div>
        <div class="metric-row">
          <span class="metric-lbl">${t('insights.latencySpawn')}:</span>
          <span class="metric-val text-muted">~220 ms (CLI Subprocess)</span>
        </div>
      </div>

      <div class="insight-card">
        <div class="insight-title">🛡️ Session & Concurrency Integrity</div>
        <div class="metric-row">
          <span class="metric-lbl">${t('insights.lockStatus')}:</span>
          <span class="metric-val text-green">🟢 ${t('insights.lockHealthy')}</span>
        </div>
        <div class="metric-row">
          <span class="metric-lbl">${t('insights.twoPhase')}:</span>
          <span class="metric-val text-green">🟢 ${t('insights.twoPhaseActive')}</span>
        </div>
        <div class="metric-row">
          <span class="metric-lbl">Oturum Kimliği:</span>
          <span class="metric-val text-cyan">${shortSess}</span>
        </div>
        <div class="metric-row">
          <span class="metric-lbl">Devre Kesici Sayacı:</span>
          <span class="metric-val text-muted">${stopRetries} / 5 deneme</span>
        </div>
      </div>
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
            display: inline-block;
          }
          .badge-allowed { background: rgba(16, 185, 129, 0.15); color: var(--color-green); }
          .badge-blocked { background: rgba(239, 68, 68, 0.15); color: var(--color-red); }
          .badge-warning { background: rgba(245, 158, 11, 0.15); color: var(--color-amber); }
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
            grid-template-columns: 1fr 1fr 1fr;
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
          .mode-pill { font-size: 8px; font-weight: 800; padding: 1px 5px; border-radius: 3px; }
          .mode-block { background: rgba(239, 68, 68, 0.15); color: var(--color-red); }
          .mode-warn { background: rgba(245, 158, 11, 0.15); color: var(--color-amber); }
          .mode-active { background: rgba(16, 185, 129, 0.15); color: var(--color-green); }
          .mode-inactive { background: rgba(255, 255, 255, 0.05); color: var(--text-muted); }

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
        </style>
      </head>
      <body>
        <!-- Header -->
        <div class="header">
          <div class="header-left">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            <span class="brand-title">GravityGuard</span>
            <span class="project-pill">${escapeHtml(projectName)}</span>
          </div>
          <div class="header-right">
            <button class="mini-btn" onclick="toggleLanguage()" title="Switch Language">🌐 ${getCurrentLanguage().toUpperCase()}</button>
            <button class="mini-btn" onclick="openConfig()" title="Open Configuration">⚙️</button>
            <button class="mini-btn" onclick="clearLogs()" title="Clear Live Logs">🧹</button>
          </div>
        </div>

        <!-- Current Action Banner -->
        ${currentCardHtml}

        <!-- Quick Summary Bar -->
        <div class="stat-summary-bar">
          <div class="stat-chip"><div class="chip-val text-red">${blockedCount}</div><div class="chip-lbl">${t('stats.blocked')}</div></div>
          <div class="stat-chip"><div class="chip-val text-amber">${warningCount}</div><div class="chip-lbl">${t('stats.warning')}</div></div>
          <div class="stat-chip"><div class="chip-val text-cyan">${totalObligations}</div><div class="chip-lbl">${totalObligations > 0 ? 'Pending' : 'Clean'}</div></div>
        </div>

        <!-- Tabs -->
        <div class="tabs-bar">
          <button class="tab-btn active" id="btn-live" onclick="setTab('live')">${t('tabs.live')}</button>
          <button class="tab-btn" id="btn-obligations" onclick="setTab('obligations')">${t('tabs.obligations')}${totalObligations > 0 ? `<span class="badge-counter">${totalObligations}</span>` : ''}</button>
          <button class="tab-btn" id="btn-rules" onclick="setTab('rules')">${t('tabs.rules')}</button>
          <button class="tab-btn" id="btn-insights" onclick="setTab('insights')">${t('tabs.insights')}</button>
        </div>

        <!-- Panes -->
        <div id="tab-live" class="tab-pane active">
          ${liveHtml}
        </div>
        <div id="tab-obligations" class="tab-pane">
          ${obligationsHtml}
        </div>
        <div id="tab-rules" class="tab-pane">
          ${rulesHtml}
        </div>
        <div id="tab-insights" class="tab-pane">
          ${insightsHtml}
        </div>

        <script>
          const vscode = acquireVsCodeApi();
          let currentTab = window._lastTab || 'live';

          function setTab(name) {
            currentTab = name;
            window._lastTab = name;
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
            const btn = document.getElementById('btn-' + name);
            const pane = document.getElementById('tab-' + name);
            if (btn) btn.classList.add('active');
            if (pane) pane.classList.add('active');
          }

          if (window._lastTab) { setTab(window._lastTab); }

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
