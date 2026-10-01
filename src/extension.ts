import * as vscode from 'vscode';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as http from 'http';
import { buildOfflinePrompt, buildSystemPrompt, classifyIntent, modeLabel, shouldAskForMode, IntentClassification, IntentMode } from './intent';

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

    webviewView.webview.onDidReceiveMessage((message: { command: string }) => {
      if (message.command === 'clearLogs') {
        this.clearLogs();
      } else if (message.command === 'refresh') {
        this.updateHtml();
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
    if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
      workspaceRoot = vscode.workspace.workspaceFolders[0].uri.fsPath;
    }

    let govData: any = null;
    let pendingTests: Record<string, any> = {};
    let pendingDocs: Record<string, any> = {};
    let stopRetries = 0;

    if (workspaceRoot) {
      const govPath = path.join(workspaceRoot, '.gravityguard', 'runtime', 'governance.json');
      if (fs.existsSync(govPath)) {
        try {
          govData = JSON.parse(fs.readFileSync(govPath, 'utf8'));
          pendingTests = govData.test_obligations?.pending || {};
          pendingDocs = govData.doc_obligations?.pending || {};
          stopRetries = govData.stop_retries || 0;
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

    // --- TAB 1: Events HTML ---
    let eventsHtml = '';
    for (const e of eventsList) {
      const isBlocked = e.status === 'BLOCKED';
      const isWarning = e.status === 'WARNING';
      const color = isBlocked ? '#ef4444' : isWarning ? '#f59e0b' : '#10b981';
      const badgeBg = isBlocked ? 'rgba(239, 68, 68, 0.15)' : isWarning ? 'rgba(245, 158, 11, 0.15)' : 'rgba(16, 185, 129, 0.15)';
      
      const lucideIcon = isBlocked
        ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"></polygon><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>'
        : isWarning
        ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>'
        : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>';

      const rulePill = e.ruleId && e.ruleId !== 'PASS'
        ? '<span style="font-size: 0.65rem; font-weight: 800; color: #94a3b8; background: rgba(255,255,255,0.06); padding: 2px 6px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.08); letter-spacing: 0.3px;">' + e.ruleId + '</span>'
        : '';

      eventsHtml +=
        '<div style="background: #1e293b; border-left: 4px solid ' + color + '; padding: 12px; border-radius: 8px; margin-bottom: 10px; font-family: sans-serif; box-shadow: 0 4px 10px rgba(0,0,0,0.2);">' +
        '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">' +
        '<div style="display: flex; align-items: center; gap: 6px;">' +
        '<span style="display: inline-flex; align-items: center; gap: 4px; font-size: 0.75rem; font-weight: 800; color: ' + color + '; background: ' + badgeBg + '; padding: 2px 8px; border-radius: 4px;">' +
        lucideIcon + ' ' + (e.status || '') +
        '</span>' +
        rulePill +
        '</div>' +
        '<span style="font-size: 0.7rem; color: #94a3b8;">' + (e.timestamp || '') + '</span>' +
        '</div>' +
        '<div style="font-size: 0.8rem; font-weight: 700; color: #f8fafc; word-break: break-all; margin-bottom: 4px;">' +
        (e.target || e.action || 'Unknown Target') +
        '</div>' +
        '<div style="font-size: 0.75rem; color: #cbd5e1; line-height: 1.4;">' +
        (e.reason || '') +
        '</div>' +
        '</div>';
    }

    if (!eventsHtml) {
      eventsHtml =
        '<div style="color: #64748b; font-size: 0.8rem; text-align: center; padding: 30px 10px; border: 1px dashed rgba(255,255,255,0.1); border-radius: 10px; display: flex; flex-direction: column; align-items: center; gap: 8px;">' +
        '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>' +
        '<span>Günlük tertemiz! Henüz bir olay kaydı yok.</span>' +
        '</div>';
    }

    // --- TAB 2: Obligations HTML ---
    let obligationsHtml = '';
    const testKeys = Object.keys(pendingTests);
    const docKeys = Object.keys(pendingDocs);

    if (testKeys.length === 0 && docKeys.length === 0) {
      obligationsHtml =
        '<div style="color: #10b981; font-size: 0.8rem; text-align: center; padding: 25px 10px; border: 1px dashed rgba(16,185,129,0.25); border-radius: 10px; background: rgba(16,185,129,0.05);">' +
        '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" style="margin-bottom: 8px;"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>' +
        '<div style="font-weight: 800; font-size: 0.85rem;">Tüm Yükümlülükler Temiz!</div>' +
        '<div style="color: #94a3b8; font-size: 0.72rem; margin-top: 4px;">Bekleyen test kanıtı veya eksik CHANGELOG kaydı bulunmuyor.</div>' +
        '</div>';
    } else {
      if (testKeys.length > 0) {
        obligationsHtml += '<div style="font-size: 0.7rem; font-weight: 800; color: #38bdf8; text-transform: uppercase; margin-bottom: 6px; letter-spacing: 0.5px;">🧪 Bekleyen Test Kanıtları (' + testKeys.length + ')</div>';
        for (const tk of testKeys) {
          const item = pendingTests[tk];
          obligationsHtml +=
            '<div style="background: #1e293b; border-left: 3px solid #38bdf8; padding: 10px; border-radius: 6px; margin-bottom: 8px; font-size: 0.75rem;">' +
            '<div style="color: #f8fafc; font-weight: 700; word-break: break-all;">' + path.basename(tk) + '</div>' +
            '<div style="color: #94a3b8; font-size: 0.7rem; margin-top: 2px;">Beklenen Test: <span style="color: #38bdf8;">' + (item.expected_name || 'test') + '</span></div>' +
            '</div>';
        }
      }
      if (docKeys.length > 0) {
        obligationsHtml += '<div style="font-size: 0.7rem; font-weight: 800; color: #f59e0b; text-transform: uppercase; margin: 12px 0 6px 0; letter-spacing: 0.5px;">📝 Bekleyen Dokümantasyon (' + docKeys.length + ')</div>';
        for (const dk of docKeys) {
          const item = pendingDocs[dk];
          const reqs = (item.required_docs || ['CHANGELOG.md']).join(', ');
          obligationsHtml +=
            '<div style="background: #1e293b; border-left: 3px solid #f59e0b; padding: 10px; border-radius: 6px; margin-bottom: 8px; font-size: 0.75rem;">' +
            '<div style="color: #f8fafc; font-weight: 700; word-break: break-all;">' + path.basename(dk) + '</div>' +
            '<div style="color: #94a3b8; font-size: 0.7rem; margin-top: 2px;">Gereken Güncelleme: <span style="color: #f59e0b;">' + reqs + '</span> (§6 Same-Commit)</div>' +
            '</div>';
        }
      }
      obligationsHtml +=
        '<div style="margin-top: 10px; padding: 8px; background: rgba(255,255,255,0.04); border-radius: 6px; font-size: 0.7rem; color: #94a3b8; display: flex; justify-content: space-between;">' +
        '<span>Oturum Stop Tekrarı:</span>' +
        '<span style="font-weight: 800; color: ' + (stopRetries >= 4 ? '#ef4444' : '#38bdf8') + ';">' + stopRetries + ' / 5</span>' +
        '</div>';
    }

    // --- TAB 3: Rules & Context HTML ---
    let rulesHtml = '';
    const docGovActive = projectCfg?.governance?.enforceDocObligations === true;
    const layers = projectCfg?.layers || {};
    const layerNames = Object.keys(layers);

    rulesHtml +=
      '<div style="background: #1e293b; padding: 12px; border-radius: 8px; margin-bottom: 12px; border: 1px solid rgba(255,255,255,0.06);">' +
      '<div style="font-size: 0.75rem; font-weight: 800; color: #38bdf8; margin-bottom: 6px;">📐 Proje Yapılandırması (.gravityguard.json)</div>' +
      '<div style="font-size: 0.7rem; color: #cbd5e1; line-height: 1.6;">' +
      '<div>• <b>Dokümantasyon Yükümlülüğü:</b> ' + (docGovActive ? '<span style="color: #10b981; font-weight: bold;">AKTİF (Opt-in)</span>' : '<span style="color: #94a3b8;">Devre Dışı</span>') + '</div>' +
      '<div>• <b>Tek Seferde Satır Sınırı:</b> ' + (projectCfg?.complexity?.singleWriteLoc || 200) + ' satır (ARCH_FILE_GROWTH)</div>' +
      '<div>• <b>Dosya Tavan Sınırı:</b> ' + (projectCfg?.complexity?.totalLoc || 500) + ' satır</div>' +
      '<div>• <b>Test Kanıt Modu:</b> ' + (projectCfg?.testEvidence?.deferredMode !== false ? 'Ertelenebilir (Stop denetimi)' : 'Anında Uyarı') + '</div>' +
      '</div>' +
      '</div>';

    if (layerNames.length > 0) {
      rulesHtml +=
        '<div style="background: #1e293b; padding: 12px; border-radius: 8px; margin-bottom: 12px; border: 1px solid rgba(255,255,255,0.06);">' +
        '<div style="font-size: 0.75rem; font-weight: 800; color: #a78bfa; margin-bottom: 6px;">🧱 Mimari Katman Sınırları (G4)</div>' +
        '<div style="font-size: 0.7rem; color: #cbd5e1; line-height: 1.5;">';
      for (const lyr of layerNames) {
        const allowed = layers[lyr];
        rulesHtml += '<div>• <code style="color: #38bdf8;">' + lyr + '</code> ➜ ' + (Array.isArray(allowed) && allowed.length ? allowed.join(', ') : '<i>yalnızca kendi katmanı</i>') + '</div>';
      }
      rulesHtml += '</div></div>';
    }

    rulesHtml +=
      '<div style="background: #1e293b; padding: 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.06);">' +
      '<div style="font-size: 0.75rem; font-weight: 800; color: #10b981; margin-bottom: 6px;">🛡️ Değişmez Güvenlik Kuralları</div>' +
      '<div style="font-size: 0.7rem; color: #94a3b8; line-height: 1.5;">' +
      '<div><b>G0:</b> Gizli anahtar / token sızıntısı engeli (HER text dosyası)</div>' +
      '<div><b>G1:</b> Sessiz hata yutma yasağı (except pass / boş handler)</div>' +
      '<div><b>G2:</b> Test bütünlüğü koruması (silme / assert zayıflatma engeli)</div>' +
      '<div><b>G4:</b> Katmanlar arası ters import engeli</div>' +
      '<div><b>T1/T2:</b> Test kanıtı ve gözlemlenebilir assertion şartı</div>' +
      '</div>' +
      '</div>';

    const statBoxBlocked = '<div class="stat-box"><div class="stat-val" style="color: #ef4444;">' + blockedCount + '</div><div class="stat-lbl">Engellenen</div></div>';
    const statBoxWarning = '<div class="stat-box"><div class="stat-val" style="color: #f59e0b;">' + warningCount + '</div><div class="stat-lbl">Uyarılar</div></div>';
    const statBoxApproved = '<div class="stat-box"><div class="stat-val" style="color: #10b981;">' + approvedCount + '</div><div class="stat-lbl">Onaylanan</div></div>';

    this._view.webview.html =
      '<!DOCTYPE html>' +
      '<html lang="en">' +
      '<head>' +
      '<meta charset="UTF-8">' +
      '<style>' +
      'body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 12px; color: #f8fafc; background: #0f172a; margin: 0; }' +
      '.header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 10px; }' +
      '.title-box { display: flex; align-items: center; gap: 8px; }' +
      '.title { font-size: 0.95rem; font-weight: 900; color: #38bdf8; letter-spacing: 0.5px; }' +
      '.btn-group { display: flex; gap: 6px; }' +
      '.action-btn { display: inline-flex; align-items: center; gap: 4px; background: rgba(255,255,255,0.08); color: #cbd5e1; border: 1px solid rgba(255,255,255,0.12); padding: 3px 8px; border-radius: 6px; font-size: 0.68rem; font-weight: 700; cursor: pointer; transition: all 0.2s; }' +
      '.action-btn:hover { background: rgba(255,255,255,0.18); color: white; }' +
      '.action-btn.danger:hover { background: rgba(239, 68, 68, 0.25); color: #ef4444; border-color: rgba(239, 68, 68, 0.4); }' +
      '.stat-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; margin-bottom: 12px; }' +
      '.stat-box { background: #1e293b; padding: 6px 4px; border-radius: 6px; text-align: center; border: 1px solid rgba(255,255,255,0.05); }' +
      '.stat-val { font-size: 1.15rem; font-weight: 900; }' +
      '.stat-lbl { font-size: 0.58rem; text-transform: uppercase; color: #94a3b8; margin-top: 1px; }' +
      '.tabs { display: flex; gap: 4px; margin-bottom: 12px; background: rgba(0,0,0,0.25); padding: 3px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.06); }' +
      '.tab-btn { flex: 1; padding: 6px 2px; font-size: 0.65rem; font-weight: 700; background: transparent; border: none; color: #94a3b8; border-radius: 6px; cursor: pointer; transition: all 0.15s; text-align: center; }' +
      '.tab-btn.active { background: #38bdf8; color: #0f172a; font-weight: 800; box-shadow: 0 2px 6px rgba(56,189,248,0.3); }' +
      '.tab-content { display: none; }' +
      '.tab-content.active { display: block; }' +
      '.badge-pill { font-size: 0.6rem; padding: 1px 5px; border-radius: 10px; background: rgba(239,68,68,0.3); color: #f87171; margin-left: 3px; }' +
      '.pulse-dot { width: 7px; height: 7px; border-radius: 50%; background: #10b981; display: inline-block; box-shadow: 0 0 6px #10b981; }' +
      '</style>' +
      '</head>' +
      '<body>' +
      '<div class="header">' +
      '<div class="title-box">' +
      '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>' +
      '<div class="title">GravityGuard</div>' +
      '</div>' +
      '<div class="btn-group">' +
      '<button class="action-btn" onclick="refresh()">' +
      '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg>' +
      'Yenile' +
      '</button>' +
      '<button class="action-btn danger" onclick="clearLogs()">' +
      '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>' +
      'Temizle' +
      '</button>' +
      '</div>' +
      '</div>' +
      '<div class="stat-grid">' +
      statBoxBlocked +
      statBoxWarning +
      statBoxApproved +
      '</div>' +
      '<div class="tabs">' +
      '<button class="tab-btn active" id="btn-events" onclick="setTab(\'events\')">🛡️ Olaylar</button>' +
      '<button class="tab-btn" id="btn-obligations" onclick="setTab(\'obligations\')">📋 Yükümlülükler' + (totalObligations > 0 ? '<span class="badge-pill">' + totalObligations + '</span>' : '') + '</button>' +
      '<button class="tab-btn" id="btn-rules" onclick="setTab(\'rules\')">📐 Kurallar & Context</button>' +
      '</div>' +
      '<div id="tab-events" class="tab-content active">' +
      '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">' +
      '<span style="font-size: 0.7rem; font-weight: 800; color: #94a3b8; text-transform: uppercase;">Canlı Akış</span>' +
      '<span style="display: flex; align-items: center; gap: 4px; font-size: 0.6rem; color: #10b981; font-weight: 800;"><span class="pulse-dot"></span> CANLI AKTİF</span>' +
      '</div>' +
      eventsHtml +
      '</div>' +
      '<div id="tab-obligations" class="tab-content">' +
      obligationsHtml +
      '</div>' +
      '<div id="tab-rules" class="tab-content">' +
      rulesHtml +
      '</div>' +
      '<script>' +
      'const vscode = acquireVsCodeApi();' +
      'let currentTab = window._lastTab || "events";' +
      'function setTab(tabName) {' +
      '  currentTab = tabName;' +
      '  window._lastTab = tabName;' +
      '  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));' +
      '  document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));' +
      '  const btn = document.getElementById("btn-" + tabName);' +
      '  const content = document.getElementById("tab-" + tabName);' +
      '  if (btn) btn.classList.add("active");' +
      '  if (content) content.classList.add("active");' +
      '}' +
      'if (window._lastTab) { setTab(window._lastTab); }' +
      'function clearLogs() { vscode.postMessage({ command: "clearLogs" }); }' +
      'function refresh() { vscode.postMessage({ command: "refresh" }); }' +
      '</script>' +
      '</body>' +
      '</html>';
  }
}

export function deactivate(): void {}
