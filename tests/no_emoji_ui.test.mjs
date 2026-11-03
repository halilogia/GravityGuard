import test from 'node:test';
import assert from 'node:assert/strict';
import { renderAgentBadge, renderLiveTab } from '../dist/webview/tabs/live.js';
import { renderSkillsTab } from '../dist/webview/tabs/skills.js';
import { resources, initI18n } from '../dist/i18n/index.js';

// Pictographic emoji, dingbats and variation selector: the UI may only use lucide() icons.
const PICTO = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B50}\u{2B55}\u{FE0F}]/u;

const AGENTS = ['Claude Code', 'claude', 'Codex', 'OpenAI Codex', 'codex', 'OpenCode', 'opencode', 'Aider', 'aider',
  'Freebuff', 'freebuff', 'Antigravity CLI', 'agy', 'Antigravity SDK', 'Antigravity IDE', undefined, 'unknown'];

test('agent badges contain no emoji', () => {
  for (const a of AGENTS) {
    for (const short of [true, false]) {
      const html = renderAgentBadge(a, short);
      assert.ok(!PICTO.test(html), `emoji in badge for ${a}/${short}: ${html}`);
      assert.ok(html.includes('agent-dot'), `badge for ${a} must draw the CSS dot`);
    }
  }
});

test('live tab stream renders no emoji', () => {
  initI18n('tr');
  const eventsList = AGENTS.map((agent, i) => ({
    id: `e${i}`, timestamp: new Date().toISOString(), agent, tool: 'Write', target: `src/f${i}.ts`,
    status: i % 2 ? 'blocked' : 'allowed', ruleId: 'G1_SILENT_EXCEPTION', reason: 'x'
  }));
  const html = renderLiveTab({ data: { events: eventsList }, eventsList, pendingTests: {}, pendingDocs: {}, projectCfg: {}, stopRetries: 0, sessionId: 's' });
  assert.ok(!PICTO.test(html));
});

test('skills tab renders no emoji for every agent type and kind', () => {
  for (const lang of ['tr', 'en']) {
    initI18n(lang);
    const types = ['claude', 'gemini', 'cursor', 'copilot', 'windsurf', 'generic'];
    const list = types.flatMap((agentType) => ['skill', 'rule'].map((kind) => ({
      id: `${agentType}-${kind}`, name: 'n', description: 'd', scope: 'workspace',
      skillFilePath: `/x/${agentType}/${kind}.md`, skillDirPath: '/x', agentType, kind
    })));
    assert.ok(!PICTO.test(renderSkillsTab(list)), `emoji in skills tab (${lang})`);
  }
});

test('i18n strings shown in the UI contain no emoji', () => {
  const bad = [];
  const walk = (o, p) => {
    for (const [k, v] of Object.entries(o)) {
      if (typeof v === 'string') { if (PICTO.test(v)) bad.push(`${p}.${k}`); }
      else if (v && typeof v === 'object') walk(v, `${p}.${k}`);
    }
  };
  walk(resources, 'resources');
  assert.deepEqual(bad, []);
});
