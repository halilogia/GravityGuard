import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HOOK = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'plugin', 'opencode', 'gravityguard_opencode_hook.py');
const PY = process.platform === 'win32' ? 'python' : 'python3';

const PROBE = `
import json, sys, importlib.util
spec = importlib.util.spec_from_file_location("hook", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
value = getattr(module, sys.argv[2])(*json.loads(sys.argv[3]))
print(json.dumps(value))
`;

function call(fn, ...args) {
  const r = spawnSync(PY, ['-I', '-c', PROBE, HOOK, fn, JSON.stringify(args)], { encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
  return JSON.parse(r.stdout);
}

function runHook(event, extraArgs = [], env = {}) {
  return spawnSync(PY, ['-I', HOOK, ...extraArgs], {
    input: JSON.stringify(event),
    encoding: 'utf8',
    env: { ...process.env, ...env },
  });
}

const ABS = process.platform === 'win32' ? 'C:\\proj\\src\\a.ts' : '/proj/src/a.ts';

test('write maps to write_to_file with an absolute target', () => {
  const out = call('to_engine_pretool', { tool: 'write', session_id: 's1', cwd: path.dirname(ABS), args: { filePath: ABS, content: 'x' } });
  assert.equal(out.toolCall.name, 'write_to_file');
  assert.equal(out.toolCall.args.TargetFile, ABS);
  assert.equal(out.toolCall.args.CodeContent, 'x');
});

test('edit maps camelCase oldString/newString to replace_file_content', () => {
  const out = call('to_engine_pretool', {
    tool: 'edit',
    cwd: path.dirname(ABS),
    args: { filePath: ABS, oldString: 'a', newString: 'b', replaceAll: true },
  });
  assert.equal(out.toolCall.name, 'replace_file_content');
  assert.equal(out.toolCall.args.TargetContent, 'a');
  assert.equal(out.toolCall.args.ReplacementContent, 'b');
  assert.equal(out.toolCall.args.AllowMultiple, true);
});

test('multiedit maps to multi_replace_file_content', () => {
  const out = call('to_engine_pretool', {
    tool: 'multiedit',
    cwd: path.dirname(ABS),
    args: { filePath: ABS, edits: [{ oldString: 'a', newString: 'b' }, { oldString: 'c', newString: 'd' }] },
  });
  assert.equal(out.toolCall.name, 'multi_replace_file_content');
  assert.equal(out.toolCall.args.ReplacementChunks.length, 2);
  assert.equal(out.toolCall.args.ReplacementChunks[1].TargetContent, 'c');
});

test('read only reaches the engine for .env files', () => {
  assert.equal(call('to_engine_pretool', { tool: 'read', args: { filePath: ABS } }), null);
  const env = call('to_engine_pretool', { tool: 'read', cwd: path.dirname(ABS), args: { filePath: '.env' } });
  assert.equal(env.toolCall.name, 'read_file');
  assert.equal(path.basename(env.toolCall.args.TargetFile), '.env');
  assert.ok(path.isAbsolute(env.toolCall.args.TargetFile));
});

test('bash is forwarded for the shared shell and token guards', () => {
  assert.equal(call('to_engine_pretool', { tool: 'bash', args: { command: 'ls' } }).toolCall.args.command, 'ls');
});

test('patch text is forwarded as an uncheckable diff so the engine denies it', () => {
  const out = call('to_engine_pretool', { tool: 'patch', cwd: path.dirname(ABS), args: { filePath: ABS, patchText: 'diff --git a/x b/x' } });
  assert.equal(out.toolCall.name, 'apply_diff');
});

test('conversationId is opencode-prefixed with default fallback', () => {
  assert.equal(call('to_engine_pretool', { tool: 'write', session_id: 'abc', args: { filePath: ABS, content: 'x' } }).conversationId, 'opencode:abc');
  assert.equal(call('to_engine_pretool', { tool: 'write', args: { filePath: ABS, content: 'x' } }).conversationId, 'opencode:default');
  assert.equal(call('to_engine_stop', { session_id: 'z' }).conversationId, 'opencode:z');
});

test('to_engine_stop sends a completed termination', () => {
  assert.equal(call('to_engine_stop', { session_id: 'z', cwd: '/w' }).terminationReason, 'completed');
});

test('from_engine_pretool: deny blocks, warning rides along, silent allow says nothing', () => {
  const deny = call('from_engine_pretool', { decision: 'deny', reason: 'nope' });
  assert.deepEqual(deny, { block: true, reason: 'nope' });
  const warn = call('from_engine_pretool', { decision: 'allow', reason: 'careful' });
  assert.deepEqual(warn, { block: false, reason: 'careful' });
  assert.equal(call('from_engine_pretool', { decision: 'allow' }), null);
});

test('from_engine_stop blocks only on continue', () => {
  assert.deepEqual(call('from_engine_stop', { decision: 'continue', reason: 'finish the tests' }), { block: true, reason: 'finish the tests' });
  assert.equal(call('from_engine_stop', { decision: 'allow' }), null);
});

test('silent engine allow produces no verdict at all (no false GUARD_UNAVAILABLE)', () => {
  const stub = path.join(os.tmpdir(), 'gg-allow-engine.py');
  fs.writeFileSync(stub, 'import json; print(json.dumps({"decision": "allow"}))\n', 'utf8');
  const env = { GRAVITYGUARD_ENGINE: stub };
  const allow = runHook({ tool: 'write', args: { filePath: ABS, content: 'x' }, session_id: 's' }, [], env);
  assert.equal(allow.status, 0);
  assert.equal(allow.stdout.trim(), '');
  const stopAllow = runHook({ session_id: 's' }, ['--stop'], env);
  assert.equal(stopAllow.status, 0);
  assert.equal(stopAllow.stdout.trim(), '');
});

test('fail-open: missing engine yields a GUARD_UNAVAILABLE block, exit 0 and a stderr note', () => {
  const env = { GRAVITYGUARD_ENGINE: path.join(path.dirname(HOOK), 'does-not-exist.py') };
  const pre = runHook({ tool: 'write', args: { filePath: ABS, content: 'x' }, session_id: 's' }, [], env);
  assert.equal(pre.status, 0);
  const preAnswer = JSON.parse(pre.stdout);
  assert.equal(preAnswer.block, true);
  assert.match(preAnswer.reason, /GUARD_UNAVAILABLE/);
  assert.match(pre.stderr, /engine not found/);
  const stop = runHook({ session_id: 's' }, ['--stop'], env);
  assert.equal(stop.status, 0);
  assert.equal(JSON.parse(stop.stdout).block, true);
});

test('--briefing-file writes the OpenCode briefing, an empty file when the journal is empty', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gg-oc-brief-'));
  const out = path.join(dir, 'briefing.md');
  const r = runHook({}, ['--briefing-file', out], { GRAVITYGUARD_LOG_DIR: dir });
  assert.equal(r.status, 0);
  assert.equal(fs.readFileSync(out, 'utf8'), '');
  fs.rmSync(dir, { recursive: true, force: true });
});
