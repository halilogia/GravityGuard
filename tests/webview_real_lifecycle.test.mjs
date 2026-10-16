// End-to-end webview lifecycle test in a REAL Chromium (headless Chrome/Edge driven over the DevTools protocol).
// The production pieces run unmodified: buildHtmlDocument (real HTML + CSP + nonce'd client script) and the
// WebviewLifecycle state machine. Only the VS Code host is emulated: an <iframe> that receives `srcdoc`
// (== webview.html), a hidden/visible slot (== webviewView.visible) and an acquireVsCodeApi shim.
// The emulated host records every destructive document assignment (hidden/detached iframe, previous document
// still loading) -- the exact conditions under which VS Code's ServiceWorker registration throws InvalidStateError.
// Skips (visibly) when no Chromium-based browser is available; set CHROME_PATH to force one.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { spawn, spawnSync } from 'node:child_process';
import { WebviewLifecycle } from '../dist/webview/lifecycle.js';
import { buildHtmlDocument, extractRootInnerHtml } from '../dist/webview/layout.js';

const CANDIDATES = [
  process.env.CHROME_PATH,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
].filter(Boolean);
const browserPath = CANDIDATES.find((p) => fs.existsSync(p));

const HOST_PAGE = `<!DOCTYPE html><html><body>
<div id="slot" style="display:block;width:400px;height:600px"><iframe id="wv" sandbox="allow-scripts allow-same-origin"></iframe></div>
<script>
const wv = document.getElementById('wv'), slot = document.getElementById('slot');
const H = window.__host = { violations: [], assigns: 0, loads: 0, pendingLoad: false, swallowReady: false, naive: false };
H.assign = (html) => {
  if (!wv.isConnected || getComputedStyle(slot).display === 'none') H.violations.push('assigned while hidden/detached');
  if (H.pendingLoad) H.violations.push('assigned while previous document still loading');
  H.pendingLoad = true; H.assigns++;
  const nonce = /nonce="([^"]+)"/.exec(html)[1];
  const shim = '<script nonce="' + nonce + '">window.acquireVsCodeApi=()=>{let s;return{postMessage:m=>parent.postMessage({__gg:m},"*"),getState:()=>s,setState:v=>{s=v}}};</' + 'script>';
  wv.srcdoc = html.replace('<head>', '<head>' + shim);
};
H.setVisible = (v) => { slot.style.display = v ? 'block' : 'none'; };
H.post = (m) => wv.contentWindow.postMessage(m, '*');
wv.addEventListener('load', () => { H.pendingLoad = false; H.loads++; });
window.addEventListener('message', (e) => {
  if (e.source !== wv.contentWindow) return;
  const m = e.data && e.data.__gg;
  if (!m || (m.command === 'ready' && H.swallowReady)) return;
  window.toNode(JSON.stringify(m));
});
</script></body></html>`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(cond, timeoutMs = 5000, what = 'condition') {
  const end = Date.now() + timeoutMs;
  for (;;) {
    const v = await cond();
    if (v) return v;
    if (Date.now() > end) throw new Error(`timeout waiting for ${what}`);
    await sleep(15);
  }
}

class Cdp {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map(); this.listeners = [];
    ws.addEventListener('message', (e) => {
      const m = JSON.parse(e.data);
      if (m.id && this.pending.has(m.id)) {
        const { res, rej } = this.pending.get(m.id); this.pending.delete(m.id);
        m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
      } else if (m.method) this.listeners.forEach((l) => l(m));
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((res, rej) => { this.pending.set(id, { res, rej }); this.ws.send(JSON.stringify({ id, method, params })); });
  }
  on(l) { this.listeners.push(l); }
  async eval(expr) {
    const r = await this.send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  }
}

async function launch() {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'gg-chromium-'));
  const server = http.createServer((q, s) => { s.setHeader('content-type', 'text/html'); s.end(HOST_PAGE); });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const proc = spawn(browserPath, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`,
    '--no-first-run', '--no-default-browser-check', '--disable-gpu', '--disable-extensions', 'about:blank'], { stdio: 'ignore' });
  const portFile = path.join(profile, 'DevToolsActivePort');
  await waitFor(() => fs.existsSync(portFile), 20000, 'DevToolsActivePort');
  const port = fs.readFileSync(portFile, 'utf8').split(/\r?\n/)[0];
  const targets = await waitFor(async () => {
    try { const l = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); return l.find((t) => t.type === 'page'); } catch { return null; }
  }, 20000, 'page target');
  const ws = new WebSocket(targets.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.addEventListener('open', r); ws.addEventListener('error', j); });
  const cdp = new Cdp(ws);
  const messages = [];
  cdp.on((m) => { if (m.method === 'Runtime.bindingCalled' && m.params.name === 'toNode') messages.push(JSON.parse(m.params.payload)); });
  await cdp.send('Runtime.enable');
  await cdp.send('Runtime.addBinding', { name: 'toNode' });
  await cdp.send('Page.enable');
  await cdp.send('Page.navigate', { url: `http://127.0.0.1:${server.address().port}/` });
  await waitFor(() => cdp.eval('typeof window.__host === "object"'), 10000, 'host page');
  return {
    cdp, messages,
    async close() {
      try { ws.close(); } catch { /* ignore */ }
      try { await new Promise((r) => server.close(r)); } catch { /* ignore */ }
      try {
        if (process.platform === 'win32') {
          spawnSync('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { stdio: 'ignore' });
        } else {
          proc.kill();
        }
      } catch {
        proc.kill();
      }
      await sleep(200);
      try { fs.rmSync(profile, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 }); } catch { /* ignore */ }
    }
  };
}

const VM = { data: {}, eventsList: [], workspaceRoot: '', projectName: 'e2e', govData: null, pendingTests: {}, pendingDocs: {}, resolutionIntents: [], stopRetries: 0, sessionId: 's', projectCfg: {}, totalObligations: 0, tasks: [] };
const buildDoc = (nonce, projectName = 'e2e') => buildHtmlDocument({ vm: { ...VM, projectName }, skills: [], activeTab: 'live', nonce, cspSource: 'vscode-webview:' });

/** Wires the REAL lifecycle to the emulated host in the browser. */
function mountProvider(browser, { opts, naive = false } = {}) {
  const st = { visible: true, project: 'e2e', giveUps: [], nonces: [] };
  let nonceN = 0;
  const lc = new WebviewLifecycle({
    renderDocument: (nonce) => { st.nonces.push(nonce); void browser.cdp.eval(`window.__host.assign(${JSON.stringify(buildDoc(nonce, st.project))})`); },
    postUpdate: () => {
      const body = extractRootInnerHtml(buildDoc(lc.currentNonce, st.project));
      void browser.cdp.eval(`window.__host.post(${JSON.stringify({ type: 'updateContent', bodyHtml: body })})`);
    },
    onGiveUp: (r) => st.giveUps.push(r),
    isVisible: () => st.visible
  }, opts, undefined, () => `nonce${++nonceN}x${Math.random().toString(36).slice(2, 8)}`);
  const setVisible = async (v) => { st.visible = v; await browser.cdp.eval(`window.__host.setVisible(${v})`); lc.visibilityChanged(v); };
  browser.messages.length = 0;
  const pump = setInterval(() => {
    while (browser.messages.length) {
      const m = browser.messages.shift();
      if (m.command === 'ready') lc.ready(m.nonce);
    }
  }, 5);
  return { lc, st, setVisible, stop: () => { clearInterval(pump); lc.dispose(); } };
}

const host = (browser, expr) => browser.cdp.eval(`window.__host.${expr}`);
const iframeDoc = (browser, expr) => browser.cdp.eval(`(function(){const d=document.getElementById('wv').contentDocument; return ${expr};})()`);
const OPTS = { settleMs: 60, readyTimeoutMs: 2500, backoffMs: [100, 250] };

test('real Chromium: webview lifecycle never produces a destructive document assignment', { skip: browserPath ? false : 'no Chromium-based browser found (set CHROME_PATH)', timeout: 120000 }, async (t) => {
  const browser = await launch();
  try {
    await t.test('boot: settle -> exactly one assignment -> nonce handshake accepted by the real client script', async () => {
      const p = mountProvider(browser, { opts: OPTS });
      p.lc.resolve();
      assert.equal(await host(browser, 'assigns'), 0, 'nothing assigned before settle elapsed');
      await waitFor(() => p.lc.isReady, 5000, 'ready phase');
      assert.equal(await host(browser, 'assigns'), 1);
      assert.equal(await iframeDoc(browser, '!!d.getElementById("guardian-app-root")'), true, 'real document rendered');
      assert.match(await iframeDoc(browser, 'd.body.innerText'), /e2e/);
      assert.deepEqual(await host(browser, 'violations'), []);
      p.stop();
    });

    await t.test('in-place update: DOM changes, iframe document survives (no reload, no new assignment)', async () => {
      const p = mountProvider(browser, { opts: OPTS });
      p.lc.resolve();
      await waitFor(() => p.lc.isReady, 5000, 'ready');
      const before = await host(browser, 'assigns');
      const loadsBefore = await host(browser, 'loads');
      await iframeDoc(browser, 'void (d.defaultView.__survivor = "alive")');
      p.st.project = 'updated-project-name';
      p.lc.requestRender();
      await waitFor(async () => /updated-project-name/.test(await iframeDoc(browser, 'd.body.innerText')), 5000, 'in-place DOM update');
      assert.equal(await iframeDoc(browser, 'd.defaultView.__survivor'), 'alive', 'document object survived the update');
      assert.equal(await host(browser, 'assigns'), before);
      assert.equal(await host(browser, 'loads'), loadsBefore);
      assert.deepEqual(await host(browser, 'violations'), []);
      p.stop();
    });

    await t.test('visibility storm before first render: no html while hidden, at most one assignment', async () => {
      const assignsBefore = await host(browser, 'assigns');
      const p = mountProvider(browser, { opts: OPTS });
      await p.setVisible(false);
      p.lc.resolve();
      for (let i = 0; i < 40; i++) {
        await p.setVisible(i % 2 === 0);
        await sleep(i % 5);
        p.lc.requestRender();
        if (i % 7 === 0) p.lc.requestRender(true);
      }
      await p.setVisible(false);
      await sleep(OPTS.settleMs * 3);
      assert.equal((await host(browser, 'assigns')) - assignsBefore, 0, 'hidden view received no html');
      await p.setVisible(true);
      await waitFor(() => p.lc.isReady, 5000, 'ready after final show');
      assert.equal((await host(browser, 'assigns')) - assignsBefore, 1, 'exactly one document for the whole storm');
      assert.deepEqual(await host(browser, 'violations'), []);
      p.stop();
    });

    await t.test('show/hide/show on a ready view: updates deferred while hidden, flushed once, document survives', async () => {
      const p = mountProvider(browser, { opts: OPTS });
      p.lc.resolve();
      await waitFor(() => p.lc.isReady, 5000, 'ready');
      const before = await host(browser, 'assigns');
      await iframeDoc(browser, 'void (d.defaultView.__survivor = "alive2")');
      for (let i = 0; i < 30; i++) {
        await p.setVisible(false);
        p.st.project = `hidden-update-${i}`;
        p.lc.requestRender();
        await p.setVisible(true);
      }
      await waitFor(async () => /hidden-update-29/.test(await iframeDoc(browser, 'd.body.innerText')), 5000, 'final update visible');
      assert.equal(await iframeDoc(browser, 'd.defaultView.__survivor'), 'alive2');
      assert.equal(await host(browser, 'assigns'), before, 'no html assignment at all during the storm');
      assert.deepEqual(await host(browser, 'violations'), []);
      p.stop();
    });

    await t.test('failed handshake: watchdog re-creates the document with a fresh nonce, stale nonce ignored, budget ends in onGiveUp', async () => {
      const p = mountProvider(browser, { opts: { settleMs: 40, readyTimeoutMs: 400, backoffMs: [80, 120] } });
      const assignsBefore = await host(browser, 'assigns');
      await browser.cdp.eval('window.__host.swallowReady = true');
      p.lc.resolve();
      await waitFor(() => p.st.giveUps.length === 1, 8000, 'give up');
      assert.equal((await host(browser, 'assigns')) - assignsBefore, 3, '1 initial + 2 budgeted recoveries');
      assert.equal(new Set(p.st.nonces).size, 3, 'every recovery used a fresh nonce');
      assert.equal(p.lc.ready(p.st.nonces[0]), false, 'stale nonce rejected');
      assert.equal(p.lc.phase, 'failed');
      // manual retry after the host recovered
      await browser.cdp.eval('window.__host.swallowReady = false');
      p.lc.reset('test manual reset');
      await waitFor(() => p.lc.isReady, 8000, 'manual reset ready');
      assert.deepEqual(await host(browser, 'violations'), [], 'recovery re-created documents only after the previous one had loaded');
      p.stop();
    });

    await t.test('view re-resolved (new webviewView): old generation is dead, new one boots cleanly', async () => {
      const p1 = mountProvider(browser, { opts: OPTS });
      p1.lc.resolve();
      await waitFor(() => p1.lc.isReady, 5000, 'ready 1');
      const oldNonce = p1.lc.currentNonce;
      p1.stop();
      const p2 = mountProvider(browser, { opts: OPTS });
      p2.lc.resolve();
      await waitFor(() => p2.lc.isReady, 5000, 'ready 2');
      assert.equal(p2.lc.ready(oldNonce), false);
      assert.deepEqual(await host(browser, 'violations'), []);
      p2.stop();
    });

    await t.test('negative control: the pre-1.4.16 behaviour (assign html on every event) IS detected by this harness', async () => {
      await browser.cdp.eval('window.__host.violations.length = 0');
      await host(browser, 'setVisible(false)');
      // Both assigns in ONE evaluation (one JS task): the first document cannot fire its `load` event in between, so
      // the second assign deterministically happens "while the previous document is still loading". Two separate CDP
      // round trips raced the load event on fast runners (the violation was then never recorded).
      await browser.cdp.eval(
        `window.__host.assign(${JSON.stringify(buildDoc('naive1'))});` + // hidden assign
        `window.__host.assign(${JSON.stringify(buildDoc('naive2'))})` // while previous loading
      );
      const v = await host(browser, 'violations');
      assert.ok(v.includes('assigned while hidden/detached'), JSON.stringify(v));
      assert.ok(v.includes('assigned while previous document still loading'), JSON.stringify(v));
      await host(browser, 'setVisible(true)');
    });
  } finally {
    await browser.close();
  }
});
