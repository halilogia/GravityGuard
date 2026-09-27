import * as vscode from 'vscode';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as http from 'http';
import { buildOfflinePrompt, buildSystemPrompt, classifyIntent, modeLabel, IntentMode } from './intent';

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

  try {
    let result: EnhancementResult | undefined;
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: `GravityGuard: ${modeLabel(classification.mode)} modunda prompt hazırlanıyor...`,
        cancellable: false
      },
      async () => {
        result = await requestPromptEnhancement(inputPrompt.trim(), classification.mode);
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
      } catch (e) {}
    }

    const eventsList = data.events || [];
    const blockedCount = eventsList.filter(e => e.status === 'BLOCKED').length;
    const warningCount = eventsList.filter(e => e.status === 'WARNING').length;
    const approvedCount = eventsList.filter(e => e.status === 'APPROVED').length;

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

    const statBoxBlocked = '<div class="stat-box"><div class="stat-val" style="color: #ef4444;">' + blockedCount + '</div><div class="stat-lbl">Engellenen</div></div>';
    const statBoxWarning = '<div class="stat-box"><div class="stat-val" style="color: #f59e0b;">' + warningCount + '</div><div class="stat-lbl">Uyarılar</div></div>';
    const statBoxApproved = '<div class="stat-box"><div class="stat-val" style="color: #10b981;">' + approvedCount + '</div><div class="stat-lbl">Onaylanan</div></div>';

    this._view.webview.html =
      '<!DOCTYPE html>' +
      '<html lang="en">' +
      '<head>' +
      '<meta charset="UTF-8">' +
      '<style>' +
      'body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 14px; color: #f8fafc; background: #0f172a; margin: 0; }' +
      '.header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 12px; }' +
      '.title-box { display: flex; align-items: center; gap: 8px; }' +
      '.title { font-size: 1rem; font-weight: 900; color: #38bdf8; letter-spacing: 0.5px; }' +
      '.btn-group { display: flex; gap: 6px; }' +
      '.action-btn { display: inline-flex; align-items: center; gap: 4px; background: rgba(255,255,255,0.08); color: #cbd5e1; border: 1px solid rgba(255,255,255,0.12); padding: 4px 10px; border-radius: 6px; font-size: 0.7rem; font-weight: 700; cursor: pointer; transition: all 0.2s; }' +
      '.action-btn:hover { background: rgba(255,255,255,0.18); color: white; }' +
      '.action-btn.danger:hover { background: rgba(239, 68, 68, 0.25); color: #ef4444; border-color: rgba(239, 68, 68, 0.4); }' +
      '.stat-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; margin-bottom: 16px; }' +
      '.stat-box { background: #1e293b; padding: 8px 4px; border-radius: 8px; text-align: center; border: 1px solid rgba(255,255,255,0.05); }' +
      '.stat-val { font-size: 1.25rem; font-weight: 900; }' +
      '.stat-lbl { font-size: 0.6rem; text-transform: uppercase; color: #94a3b8; margin-top: 2px; }' +
      '.log-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }' +
      '.log-title { font-size: 0.75rem; font-weight: 800; text-transform: uppercase; color: #94a3b8; letter-spacing: 0.5px; }' +
      '.pulse-dot { width: 8px; height: 8px; border-radius: 50%; background: #10b981; display: inline-block; box-shadow: 0 0 8px #10b981; }' +
      '</style>' +
      '</head>' +
      '<body>' +
      '<div class="header">' +
      '<div class="title-box">' +
      '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>' +
      '<div class="title">GravityGuard</div>' +
      '</div>' +
      '<div class="btn-group">' +
      '<button class="action-btn" onclick="refresh()">' +
      '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg>' +
      'Yenile' +
      '</button>' +
      '<button class="action-btn danger" onclick="clearLogs()">' +
      '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>' +
      'Temizle' +
      '</button>' +
      '</div>' +
      '</div>' +
      '<div class="stat-grid">' +
      statBoxBlocked +
      statBoxWarning +
      statBoxApproved +
      '</div>' +
      '<div class="log-header">' +
      '<div class="log-title">Canlı Güvenlik Akışı</div>' +
      '<div style="display: flex; align-items: center; gap: 6px; font-size: 0.65rem; color: #10b981; font-weight: 800;"><span class="pulse-dot"></span> LIVE AUTO-SYNC</div>' +
      '</div>' +
      '<div>' + eventsHtml + '</div>' +
      '<script>' +
      'const vscode = acquireVsCodeApi();' +
      'function clearLogs() { vscode.postMessage({ command: "clearLogs" }); }' +
      'function refresh() { vscode.postMessage({ command: "refresh" }); }' +
      '</script>' +
      '</body>' +
      '</html>';
  }
}

export function deactivate(): void {}
