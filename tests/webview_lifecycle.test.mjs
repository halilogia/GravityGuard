import test from 'node:test';
import assert from 'node:assert/strict';
import { WebviewLifecycle } from '../dist/webview/lifecycle.js';

const OPTS = { settleMs: 100, readyTimeoutMs: 1000, backoffMs: [200, 500] };

function harness(visible = true) {
  let now = 0;
  let seq = 0;
  const pending = new Map();
  const timers = {
    setTimeout(fn, ms) { const id = ++seq; pending.set(id, { at: now + ms, fn }); return id; },
    clearTimeout(id) { pending.delete(id); }
  };
  const h = { visible, renders: [], updates: 0, giveUps: [], pending };
  h.advance = (ms) => {
    const end = now + ms;
    for (;;) {
      const due = [...pending.entries()].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      pending.delete(due[0]);
      now = due[1].at;
      due[1].fn();
    }
    now = end;
  };
  let n = 0;
  h.lc = new WebviewLifecycle({
    renderDocument: (nonce) => h.renders.push(nonce),
    postUpdate: () => { h.updates++; },
    onGiveUp: (r) => h.giveUps.push(r),
    isVisible: () => h.visible
  }, OPTS, timers, () => `n${++n}`);
  return h;
}

test('html is never assigned before the settle delay', () => {
  const h = harness(true);
  h.lc.resolve();
  assert.equal(h.renders.length, 0);
  h.advance(99);
  assert.equal(h.renders.length, 0);
  h.advance(1);
  assert.equal(h.renders.length, 1);
  assert.equal(h.lc.phase, 'loading');
});

test('hidden view never receives html; renders once when shown', () => {
  const h = harness(false);
  h.lc.resolve();
  h.advance(5000);
  assert.equal(h.renders.length, 0);
  h.lc.requestRender(true);
  h.advance(5000);
  assert.equal(h.renders.length, 0);
  h.visible = true;
  h.lc.visibilityChanged(true);
  h.advance(100);
  assert.equal(h.renders.length, 1);
});

test('requests during loading are coalesced (no second html assignment)', () => {
  const h = harness(true);
  h.lc.resolve();
  h.advance(100);
  for (let i = 0; i < 10; i++) h.lc.requestRender(true);
  assert.equal(h.renders.length, 1);
  h.lc.ready('n1');
  assert.equal(h.updates, 1, 'dirty flag flushes as a single in-place update');
  assert.equal(h.lc.phase, 'ready');
});

test('stale ready nonce is ignored; matching nonce is idempotent', () => {
  const h = harness(true);
  h.lc.resolve();
  h.advance(100);
  assert.equal(h.lc.ready('old'), false);
  assert.equal(h.lc.phase, 'loading');
  assert.equal(h.lc.ready('n1'), true);
  assert.equal(h.lc.ready('n1'), false);
});

test('ready state updates in place, never reloading the document', () => {
  const h = harness(true);
  h.lc.resolve();
  h.advance(100);
  h.lc.ready('n1');
  h.lc.requestRender(true);
  h.lc.requestRender(false);
  assert.equal(h.renders.length, 1);
  assert.equal(h.updates, 2);
});

test('ready timeout recovers with backoff, fresh nonce, then gives up', () => {
  const h = harness(true);
  h.lc.resolve();
  h.advance(100);            // load #1
  h.advance(1000);           // timeout -> recovering (200ms)
  assert.equal(h.lc.phase, 'recovering');
  h.advance(200);            // load #2
  assert.equal(h.renders.length, 2);
  assert.notEqual(h.renders[0], h.renders[1]);
  h.advance(1000);           // timeout -> recovering (500ms)
  h.advance(500);            // load #3
  assert.equal(h.renders.length, 3);
  h.advance(1000);           // budget exhausted
  assert.equal(h.lc.phase, 'failed');
  assert.deepEqual(h.giveUps, ['ready timeout']);
  h.advance(60000);
  assert.equal(h.renders.length, 3, 'no more attempts after giving up');
});

test('successful ready resets the retry budget', () => {
  const h = harness(true);
  h.lc.resolve();
  h.advance(100);
  h.advance(1000);
  h.advance(200);
  assert.equal(h.lc.attempts, 1);
  h.lc.ready(h.renders[1]);
  assert.equal(h.lc.attempts, 0);
});

test('hiding during loading pauses the watchdog (no false recovery)', () => {
  const h = harness(true);
  h.lc.resolve();
  h.advance(100);
  h.visible = false;
  h.lc.visibilityChanged(false);
  h.advance(60000);
  assert.equal(h.renders.length, 1);
  assert.equal(h.lc.phase, 'loading');
  h.visible = true;
  h.lc.visibilityChanged(true);
  h.lc.ready('n1');
  assert.equal(h.lc.phase, 'ready');
});

test('hiding during settle cancels the pending render', () => {
  const h = harness(true);
  h.lc.resolve();
  h.advance(50);
  h.visible = false;
  h.lc.visibilityChanged(false);
  h.advance(1000);
  assert.equal(h.renders.length, 0);
  assert.equal(h.lc.phase, 'hidden');
});

test('updates while hidden are deferred and flushed on show', () => {
  const h = harness(true);
  h.lc.resolve();
  h.advance(100);
  h.lc.ready('n1');
  h.visible = false;
  h.lc.visibilityChanged(false);
  h.lc.requestRender(false);
  assert.equal(h.updates, 0);
  h.visible = true;
  h.lc.visibilityChanged(true);
  assert.equal(h.updates, 1);
});

test('manual reset rebuilds the document and works after failure', () => {
  const h = harness(true);
  h.lc.resolve();
  h.advance(100);
  h.lc.ready('n1');
  h.lc.reset('manual');
  h.advance(200);
  assert.equal(h.renders.length, 2);
  h.advance(1000); h.advance(500); h.advance(1000); h.advance(1000);
  assert.equal(h.lc.phase, 'failed');
  h.lc.reset('manual');
  h.advance(200);
  assert.equal(h.lc.phase, 'loading');
});

test('re-resolve invalidates the previous generation; dispose silences everything', () => {
  const h = harness(true);
  h.lc.resolve();
  h.advance(50);
  h.lc.resolve();
  h.advance(50);
  assert.equal(h.renders.length, 0, 'old settle timer must not fire');
  h.advance(50);
  assert.equal(h.renders.length, 1);
  h.lc.dispose();
  h.advance(60000);
  assert.equal(h.renders.length, 1);
  assert.equal(h.pending.size, 0);
  h.lc.requestRender(true);
  assert.equal(h.updates, 0);
});
