import * as vscode from 'vscode';
import * as http from 'http';
import { buildOfflinePrompt, buildSystemPrompt, classifyIntent, IntentMode } from './intent';

export class RouterUnreachableError extends Error {}

export interface EnhancementResult {
  text: string;
  offline: boolean;
  mode: IntentMode;
}

export function getRouterConfig() {
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
