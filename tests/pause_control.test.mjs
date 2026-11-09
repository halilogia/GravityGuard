import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pauseFor, pauseStatus, resumeNow, pauseFlagPath, remainingMinutes } from '../dist/pause_control.js';

function withTmp(fn) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gg-pause-'));
  const prev = process.env.GRAVITYGUARD_PAUSE_FILE;
  process.env.GRAVITYGUARD_PAUSE_FILE = path.join(dir, 'sub', 'pause.json');
  try { fn(process.env.GRAVITYGUARD_PAUSE_FILE); } finally {
    if (prev === undefined) delete process.env.GRAVITYGUARD_PAUSE_FILE; else process.env.GRAVITYGUARD_PAUSE_FILE = prev;
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

test('env override selects flag path', () => withTmp(p => assert.equal(pauseFlagPath(), p)));

test('pause writes engine-compatible schema and status reads it', () => withTmp(p => {
  const s = pauseFor(30, 'x', 1000);
  const disk = JSON.parse(fs.readFileSync(p, 'utf-8'));
  assert.deepEqual(Object.keys(disk).sort(), ['minutes', 'reason', 'since', 'until']);
  assert.equal(disk.until, 1000 + 1800);
  assert.equal(s.minutes, 30);
  const st = pauseStatus(1000 + 600);
  assert.equal(st.remaining, 1200);
  assert.equal(remainingMinutes(st), 20);
}));

test('minutes are clamped to 1..480 and expired/missing flag is inactive', () => withTmp(() => {
  assert.equal(pauseFor(9999, '', 0).minutes, 480);
  assert.equal(pauseFor(0, '', 0).minutes, 120);
  assert.equal(pauseFor(-5, '', 0).minutes, 1);
  assert.equal(pauseStatus(480 * 60 + 1), null);
  resumeNow();
  assert.equal(pauseStatus(), null);
}));

test('resume removes the flag and reports missing file', () => withTmp(p => {
  pauseFor(5);
  assert.ok(pauseStatus());
  assert.equal(resumeNow(), true);
  assert.equal(fs.existsSync(p), false);
  assert.equal(resumeNow(), false);
}));

test('corrupt flag file is treated as not paused', () => withTmp(p => {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, '{nope');
  assert.equal(pauseStatus(), null);
}));
