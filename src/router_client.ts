import * as vscode from 'vscode';
import * as http from 'http';
import * as https from 'https';
import { MAX_ROUTER_RESPONSE_BYTES, routerEndpoint } from './router_security';
import { buildOfflinePrompt, buildSystemPrompt, classifyIntent, IntentMode } from './intent';

export class RouterUnreachableError extends Error {}

let storedRouterToken = '';
export async function initializeRouterSecrets(context: vscode.ExtensionContext): Promise<void> {
  const config = vscode.workspace.getConfiguration('gravityguard');
  storedRouterToken = await context.secrets.get('gravityguard.routerToken') || '';
  const legacy = config.get<string>('routerToken');
  if (!storedRouterToken && legacy) {
    await context.secrets.store('gravityguard.routerToken', legacy);
    storedRouterToken = legacy;
  }
  if (legacy) {
    const inspected = config.inspect<string>('routerToken');
    for (const [value, target] of [[inspected?.globalValue, vscode.ConfigurationTarget.Global],
      [inspected?.workspaceValue, vscode.ConfigurationTarget.Workspace],
      [inspected?.workspaceFolderValue, vscode.ConfigurationTarget.WorkspaceFolder]] as const) {
      if (value) await config.update('routerToken', undefined, target);
    }
  }
  context.subscriptions.push(vscode.commands.registerCommand('antigravityBridge.setRouterToken', async () => {
    const token = await vscode.window.showInputBox({ password: true, prompt: 'GravityGuard router token', ignoreFocusOut: true });
    if (token === undefined) return;
    await context.secrets.store('gravityguard.routerToken', token);
    storedRouterToken = token;
  }));
}

export interface EnhancementResult {
  text: string;
  offline: boolean;
  mode: IntentMode;
}

export function getRouterConfig() {
  const config = vscode.workspace.getConfiguration('gravityguard');
  // Workspace files must not redirect a machine-owned token to another host.
  const host = config.inspect<string>('routerHost')?.globalValue || process.env.ROUTER_HOST || '127.0.0.1';
  const port = config.inspect<number>('routerPort')?.globalValue || (process.env.ROUTER_PORT ? parseInt(process.env.ROUTER_PORT, 10) : 20128);
  const token = storedRouterToken || process.env.GRAVITYGUARD_ROUTER_TOKEN || process.env.ROUTER_TOKEN || '';
  const timeoutMs = config.get<number>('routerTimeoutMs') || parseInt(process.env.ROUTER_TIMEOUT_MS || '', 10) || 12000;
  const configuredModels = config.get<string[]>('models') || [];
  const envModels = (process.env.ROUTER_MODELS || '').split(',').map(m => m.trim()).filter(Boolean);
  const models = (configuredModels.length ? configuredModels : (envModels.length ? envModels : DEFAULT_MODELS))
    .map(m => m.trim())
    .filter(Boolean);
  return { host, port, token, timeoutMs, models };
}

export const DEFAULT_MODELS = [
  'ag/gemini-3.8-flash-low',
  'ag/gemini-3.7-flash-medium',
  'all'
];

export const CONNECTION_ERROR_CODES = new Set([
  'ECONNREFUSED', 'ENOTFOUND', 'EHOSTUNREACH', 'ENETUNREACH', 'EAI_AGAIN', 'ECONNRESET', 'EPIPE'
]);

export async function requestPromptEnhancement(rawPrompt: string, mode: IntentMode): Promise<EnhancementResult> {
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

export function probeRouter(): Promise<{ ok: boolean; detail: string }> {
  return new Promise(resolve => {
    const { host, port, token } = getRouterConfig();
    const headers: Record<string, string> = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    let endpoint: ReturnType<typeof routerEndpoint>;
    try { endpoint = routerEndpoint(host, port); }
    catch { resolve({ ok: false, detail: 'Invalid router endpoint: remote gateways require HTTPS' }); return; }
    const transport = endpoint.protocol === 'https:' ? https : http;
    const req = transport.request(
      { ...endpoint, path: '/v1/models', method: 'GET', headers, timeout: 3000 },
      res => {
        let data = '';
        res.setEncoding('utf8');
        let bytes = 0;
        res.on('data', chunk => {
          bytes += Buffer.byteLength(chunk);
          if (bytes > MAX_ROUTER_RESPONSE_BYTES) { res.destroy(); resolve({ ok: false, detail: 'Router response exceeded limit' }); }
          else data += chunk;
        });
        res.on('error', () => resolve({ ok: false, detail: 'Router response interrupted' }));
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

export function postChatCompletion(model: string, systemPrompt: string, userPrompt: string): Promise<string> {
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

    const endpoint = routerEndpoint(host, port);
    const options: http.RequestOptions = {
      ...endpoint,
      path: '/v1/chat/completions',
      method: 'POST',
      headers: headers,
      timeout: timeoutMs
    };

    const transport = endpoint.protocol === 'https:' ? https : http;
    const req = transport.request(options, (res) => {
      let data = '';
      let bytes = 0;

      res.setEncoding('utf8');
      res.on('data', (chunk) => {
        bytes += Buffer.byteLength(chunk);
        if (bytes > MAX_ROUTER_RESPONSE_BYTES) {
          res.destroy(); reject(new Error('Router response exceeded limit'));
        } else data += chunk;
      });
      res.on('error', () => reject(new Error('Router response interrupted')));

      res.on('end', () => {
        if (res.statusCode && res.statusCode >= 200 && res.statusCode < 300) {
          try {
            const parsed = JSON.parse(data);
            const content = parsed.choices?.[0]?.message?.content;
            if (content) {
              resolve(content);
            } else {
              reject(new Error('Router returned no content'));
            }
          } catch (e: any) {
            reject(new Error(`JSON ayrıştırma hatası: ${e.message}`));
          }
        } else {
          reject(new Error(`Router HTTP ${res.statusCode}`));
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
