// Model checking of WebviewLifecycle: EVERY event sequence up to depth 5 (exhaustive) plus seeded random
// long sequences are replayed against a virtual clock, and the safety invariants that keep the host from
// destroying the iframe document (=> ServiceWorker InvalidStateError) are asserted at every html assignment.
import test from 'node:test';
import assert from 'node:assert/strict';
import { WebviewLifecycle } from '../dist/webview/lifecycle.js';

const OPTS = { settleMs: 100, readyTimeoutMs: 1000, backoffMs: [200, 500] };

const EVENTS = ['show', 'hide', 'render', 'force', 'readyOk', 'readyStale', 'tick100', 'tick1000', 'reset', 'dispose'];

function run(seq, startVisible) {
  let now = 0;
  let timerSeq = 0;
  const pending = new Map();
  const timers = {
    setTimeout(fn, ms) { const id = ++timerSeq; pending.set(id, { at: now + ms, fn }); return id; },
    clearTimeout(id) { pending.delete(id); }
  };
  const advance = (ms) => {
    const end = now + ms;
    for (;;) {
      const due = [...pending.entries()].filter(([, v]) => v.at <= end).sort((a, b) => a[1].at - b[1].at || a[0] - b[0])[0];
      if (!due) break;
      pending.delete(due[0]);
      now = due[1].at;
      due[1].fn();
    }
    now = end;
  };

  const st = { visible: startVisible, visibleSince: 0, disposed: false, lastAssignAt: -Infinity, assignsSinceManual: 0, manualSinceAssign: false, trace: [] };
  let nonceN = 0;
  let lc;
  const fail = (msg) => { throw new Error(`${msg}\n  start visible=${startVisible} seq=${seq.join(',')}`); };

  lc = new WebviewLifecycle({
    renderDocument: (nonce) => {
      if (st.disposed) fail('renderDocument after dispose');
      if (!st.visible) fail('html assigned while the view is hidden');
      if (now - st.visibleSince < OPTS.settleMs) fail(`html assigned ${now - st.visibleSince}ms after becoming visible (< settle)`);
      if (lc.phase !== 'loading') fail(`html assigned in phase ${lc.phase}`);
      // A document may be replaced only by its own failed handshake, or by an explicit manual reset / forced retry
      if (st.lastAssignAt !== -Infinity && !st.manualSinceAssign && now - st.lastAssignAt < OPTS.readyTimeoutMs) {
        fail(`document replaced after ${now - st.lastAssignAt}ms without handshake timeout or manual reset`);
      }
      if (now - st.lastAssignAt < OPTS.settleMs) fail('two assignments closer than the settle window');
      st.assignsSinceManual++;
      if (st.assignsSinceManual > 1 + OPTS.backoffMs.length) fail('automatic recovery exceeded its retry budget');
      st.lastAssignAt = now;
      st.manualSinceAssign = false;
    },
    postUpdate: () => {
      if (st.disposed) fail('postUpdate after dispose');
      if (!st.visible) fail('postUpdate while hidden');
      if (lc.phase !== 'ready') fail(`postUpdate in phase ${lc.phase}`);
    },
    onGiveUp: () => { if (st.disposed) fail('onGiveUp after dispose'); },
    isVisible: () => st.visible
  }, OPTS, timers, () => `n${++nonceN}`);

  lc.resolve();
  if (startVisible) st.visibleSince = now;

  for (const ev of seq) {
    const phaseBefore = lc.phase;
    const nonceBefore = lc.currentNonce;
    switch (ev) {
      case 'show': if (!st.visible) { st.visible = true; st.visibleSince = now; } lc.visibilityChanged(true); break;
      case 'hide': st.visible = false; lc.visibilityChanged(false); break;
      case 'render': lc.requestRender(false); break;
      case 'force':
        if (lc.phase === 'failed' && st.visible) { st.assignsSinceManual = 0; st.manualSinceAssign = true; }
        lc.requestRender(true);
        break;
      case 'readyOk': lc.ready(lc.currentNonce || undefined); break;
      case 'readyStale': {
        const accepted = lc.ready('stale-nonce');
        if (accepted) fail('stale nonce was accepted');
        if (lc.phase !== phaseBefore) fail('stale nonce changed the phase');
        break;
      }
      case 'tick100': advance(100); break;
      case 'tick1000': advance(1000); break;
      case 'reset':
        if (lc.phase !== 'disposed' && lc.phase !== 'unresolved') { st.assignsSinceManual = 0; st.manualSinceAssign = true; }
        lc.reset('model');
        break;
      case 'dispose': lc.dispose(); st.disposed = true; break;
      default: throw new Error(ev);
    }
    if (ev === 'readyOk' && phaseBefore === 'ready' && lc.currentNonce !== nonceBefore) fail('duplicate ready replaced the nonce');
    if (st.disposed && lc.phase !== 'disposed') fail('phase left disposed');
  }
  // drain: a healthy run must settle without throwing, and never schedules work after dispose
  advance(10_000);
  if (st.disposed && pending.size) fail('timers left after dispose');
  if (pending.size) fail(`dangling timers in phase ${lc.phase}`);
}

function* sequences(depth) {
  const idx = new Array(depth).fill(0);
  for (;;) {
    yield idx.map((i) => EVENTS[i]);
    let p = depth - 1;
    while (p >= 0 && ++idx[p] === EVENTS.length) { idx[p] = 0; p--; }
    if (p < 0) return;
  }
}

test('exhaustive: every event sequence of length <= 5 keeps all document-safety invariants', () => {
  let count = 0;
  for (let depth = 1; depth <= 5; depth++) {
    for (const seq of sequences(depth)) {
      run(seq, true);
      run(seq, false);
      count += 2;
    }
  }
  assert.ok(count > 200_000, `explored ${count} sequences`);
});

test('randomized: 20000 seeded long sequences keep all document-safety invariants', () => {
  let s = 0x9e3779b9;
  const rnd = () => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return s / 0x100000000; };
  let done = 0;
  for (let n = 0; n < 20_000; n++) {
    const len = 10 + Math.floor(rnd() * 40);
    const seq = Array.from({ length: len }, () => EVENTS[Math.floor(rnd() * (EVENTS.length - 1))]); // no dispose mid-run
    run(seq, rnd() < 0.5);
    done++;
  }
  assert.equal(done, 20_000);
});

test('late handshake of the current document cancels a pending recovery (no needless reload)', () => {
  let now = 0, id = 0;
  const pending = new Map();
  const timers = { setTimeout(fn, ms) { pending.set(++id, { at: now + ms, fn }); return id; }, clearTimeout(i) { pending.delete(i); } };
  const advance = (ms) => { const end = now + ms; for (;;) { const d = [...pending.entries()].filter(([, v]) => v.at <= end).sort((a, b) => a[1].at - b[1].at)[0]; if (!d) break; pending.delete(d[0]); now = d[1].at; d[1].fn(); } now = end; };
  const renders = [];
  const lc = new WebviewLifecycle({ renderDocument: (n) => renders.push(n), postUpdate() {}, onGiveUp() {}, isVisible: () => true }, OPTS, timers, (() => { let n = 0; return () => `n${++n}`; })());
  lc.resolve();
  advance(100);
  assert.equal(renders.length, 1);
  advance(1000); // watchdog fires -> recovering
  assert.equal(lc.phase, 'recovering');
  assert.equal(lc.ready('n1'), true, 'slow but healthy document is accepted');
  assert.equal(lc.phase, 'ready');
  advance(10_000);
  assert.equal(renders.length, 1, 'no second html assignment');
});
