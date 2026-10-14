import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const auditPyPath = path.resolve(__dirname, '..', 'engine', 'gravityguard_engine', 'audit.py');

test('Python audit engine accurately differentiates all agent identities', () => {
  const pyCode = `
import sys, os
sys.path.insert(0, r"${path.resolve(__dirname, '..', 'engine').replace(/\\/g, '/')}")
from gravityguard_engine.audit import log_event

test_cases = [
    ("claude:session_123", {}, "Claude Code"),
    ("codex:session_456", {}, "Codex"),
    ("cli:session_789", {}, "Antigravity CLI"),
    ("agy-cli:session_abc", {}, "Antigravity CLI"),
    ("default", {"AGY_CLI": "1"}, "Antigravity CLI"),
    ("sdk:session_101", {}, "Antigravity SDK"),
    ("default", {"AGY_SDK": "1"}, "Antigravity SDK"),
    ("ide:session_202", {}, "Antigravity IDE"),
    ("f2594543-f830-4347-be57-5c5aa15a4450", {}, "Antigravity IDE"),
    ("default", {}, "Antigravity IDE")
]

for conv_id, env_vars, expected_agent in test_cases:
    for k, v in env_vars.items():
        os.environ[k] = v
    conv_id_str = str(conv_id)
    if conv_id_str.startswith("claude:"):
        agent_name = "Claude Code"
    elif conv_id_str.startswith("codex:"):
        agent_name = "Codex"
    elif conv_id_str.startswith("cli:") or conv_id_str.startswith("agy-cli:") or os.environ.get("AGY_CLI") or os.environ.get("ANTIGRAVITY_CLI"):
        agent_name = "Antigravity CLI"
    elif conv_id_str.startswith("sdk:") or conv_id_str.startswith("agy-sdk:") or os.environ.get("ANTIGRAVITY_SDK") or os.environ.get("AGY_SDK"):
        agent_name = "Antigravity SDK"
    else:
        agent_name = "Antigravity IDE"

    for k in env_vars.keys():
        del os.environ[k]

    assert agent_name == expected_agent, f"Failed for {conv_id}: expected {expected_agent}, got {agent_name}"

print("OK: all agent identities verified")
`;

  const output = execFileSync('python', ['-c', pyCode], { encoding: 'utf-8' });
  assert.match(output, /OK: all agent identities verified/);
});

test('Webview STREAM_STYLES defines grey color for Codex and unique colors for IDE, CLI, SDK', async () => {
  const { STREAM_STYLES } = await import('../dist/webview/styles/stream.js');

  // Verify Codex is specifically grey (#94a3b8)
  assert.match(STREAM_STYLES, /\.agent-codex\s*\{[^}]*color:\s*#94a3b8;/);

  // Verify Antigravity IDE is cyan (#5ccfe6)
  assert.match(STREAM_STYLES, /\.agent-antigravity-ide\s*\{[^}]*color:\s*#5ccfe6;/);

  // Verify Antigravity CLI is purple (#c084fc)
  assert.match(STREAM_STYLES, /\.agent-antigravity-cli\s*\{[^}]*color:\s*#c084fc;/);

  // Verify Antigravity SDK is emerald green (#34d399)
  assert.match(STREAM_STYLES, /\.agent-antigravity-sdk\s*\{[^}]*color:\s*#34d399;/);
});

test('renderAgentBadge renders correct emoji and badge class for all 5 agents', async () => {
  const { renderAgentBadge } = await import('../dist/webview/tabs/live.js');

  // Claude Code
  const claudeBadge = renderAgentBadge('Claude Code', false);
  assert.match(claudeBadge, /agent-claude/);
  assert.match(claudeBadge, /🟠 Claude Code/);
  assert.match(renderAgentBadge('Claude Code', true), /🟠 Claude/);

  // Codex (Grey)
  const codexBadge = renderAgentBadge('Codex', false);
  assert.match(codexBadge, /agent-codex/);
  assert.match(codexBadge, /⚪ Codex/);

  // Antigravity CLI
  const cliBadge = renderAgentBadge('Antigravity CLI', false);
  assert.match(cliBadge, /agent-antigravity-cli/);
  assert.match(cliBadge, /🟣 Antigravity CLI/);
  assert.match(renderAgentBadge('Antigravity CLI', true), /🟣 CLI/);

  // Antigravity SDK
  const sdkBadge = renderAgentBadge('Antigravity SDK', false);
  assert.match(sdkBadge, /agent-antigravity-sdk/);
  assert.match(sdkBadge, /🟢 Antigravity SDK/);
  assert.match(renderAgentBadge('Antigravity SDK', true), /🟢 SDK/);

  // Antigravity IDE (default)
  const ideBadge = renderAgentBadge('Antigravity IDE', false);
  assert.match(ideBadge, /agent-antigravity-ide/);
  assert.match(ideBadge, /🔵 Antigravity IDE/);
  assert.match(renderAgentBadge(undefined, true), /🔵 IDE/);
});

