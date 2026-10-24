import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HOOK = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'plugin', 'codex', 'gravityguard_codex_hook.py');
const PY = process.platform === 'win32' ? 'python' : 'python3';

const PROBE = `
import json, sys, importlib.util
spec = importlib.util.spec_from_file_location("hook", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(json.dumps(getattr(m, sys.argv[2])(*json.loads(sys.argv[3]))))
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
    env: { ...process.env, ...env }
  });
}

const ABS = process.platform === 'win32' ? 'C:\\proj\\src\\a.ts' : '/proj/src/a.ts';

test('to_engine_pretool maps write_file/Write to write_to_file', () => {
  for (const tool of ['write_file', 'Write']) {
    const out = call('to_engine_pretool', { tool_name: tool, session_id: 's1', cwd: path.dirname(ABS), tool_input: { file_path: ABS, content: 'x' } });
    assert.equal(out.toolCall.name, 'write_to_file');
    assert.equal(out.toolCall.args.TargetFile, ABS);
    assert.equal(out.toolCall.args.CodeContent, 'x');
  }
});

test('to_engine_pretool maps apply_diff/edit_file/Edit to replace_file_content', () => {
  for (const tool of ['apply_diff', 'edit_file', 'Edit']) {
    const out = call('to_engine_pretool', { tool_name: tool, tool_input: { file_path: ABS, old_string: 'a', new_string: 'b' } });
    assert.equal(out.toolCall.name, 'replace_file_content');
    assert.equal(out.toolCall.args.TargetContent, 'a');
    assert.equal(out.toolCall.args.ReplacementContent, 'b');
  }
});

test('to_engine_pretool only runs the engine for .env reads', () => {
  assert.equal(call('to_engine_pretool', { tool_name: 'read_file', tool_input: { file_path: ABS } }), null);
  const env = call('to_engine_pretool', { tool_name: 'Read', cwd: path.dirname(ABS), tool_input: { file_path: '.env' } });
  assert.equal(env.toolCall.name, 'read_file');
  assert.equal(path.basename(env.toolCall.args.TargetFile), '.env');
  assert.ok(path.isAbsolute(env.toolCall.args.TargetFile));
});

test('to_engine_pretool forwards command tools for shared security checks', () => {
  assert.equal(call('to_engine_pretool', { tool_name: 'shell', tool_input: { command: 'ls' } }).toolCall.args.command, 'ls');
});

test('conversationId is codex-prefixed with default fallback', () => {
  assert.equal(call('to_engine_pretool', { tool_name: 'write_file', session_id: 'abc', tool_input: { file_path: ABS } }).conversationId, 'codex:abc');
  assert.equal(call('to_engine_pretool', { tool_name: 'write_file', tool_input: { file_path: ABS } }).conversationId, 'codex:default');
  assert.equal(call('to_engine_stop', { session_id: 'z' }).conversationId, 'codex:z');
});

test('to_engine_stop sends a completed termination', () => {
  assert.equal(call('to_engine_stop', { session_id: 'z', cwd: '/w' }).terminationReason, 'completed');
});

test('from_engine_pretool: deny, warning context, silent allow', () => {
  const deny = call('from_engine_pretool', { decision: 'deny', reason: 'nope' });
  assert.equal(deny.hookSpecificOutput.permissionDecision, 'deny');
  assert.equal(deny.hookSpecificOutput.permissionDecisionReason, 'nope');
  const warn = call('from_engine_pretool', { decision: 'allow', reason: 'careful' });
  assert.equal(warn.hookSpecificOutput.additionalContext, 'careful');
  assert.equal(warn.hookSpecificOutput.permissionDecision, undefined);
  assert.equal(call('from_engine_pretool', { decision: 'allow' }), null);
});

test('from_engine_stop blocks only on continue', () => {
  assert.deepEqual(call('from_engine_stop', { decision: 'continue', reason: 'Hop Hemşerim!' }), { decision: 'block', reason: 'Hop Hemşerim!' });
  assert.equal(call('from_engine_stop', { decision: 'allow' }), null);
});

test('fail-open: missing engine yields no output, exit 0 and a stderr note', () => {
  const env = { GRAVITYGUARD_ENGINE: path.join(path.dirname(HOOK), 'does-not-exist.py') };
  const pre = runHook({ tool_name: 'write_file', tool_input: { file_path: ABS, content: 'x' } }, [], env);
  assert.equal(pre.status, 0);
  assert.equal(JSON.parse(pre.stdout).hookSpecificOutput.permissionDecision, 'deny');
  assert.match(pre.stderr, /engine not found/);
  const stop = runHook({ session_id: 's' }, ['--stop'], env);
  assert.equal(stop.status, 0);
  assert.equal(JSON.parse(stop.stdout).decision, 'block');
});
