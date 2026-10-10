import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { parseSkillMdContent, scanAllSkills } from '../dist/skills.js';

function write(root, rel, content) {
  const p = path.join(root, ...rel.split('/'));
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, content);
}

test('parseSkillMdContent parses YAML frontmatter accurately', () => {
  const content = `---
name: test-skill
description: A mock skill for testing purposes.
---

# Title
Body text.
`;
  const result = parseSkillMdContent(content, 'fallback');
  assert.equal(result.name, 'test-skill');
  assert.equal(result.description, 'A mock skill for testing purposes.');
});

test('parseSkillMdContent falls back to first markdown paragraph when frontmatter missing', () => {
  const content = `# My Skill

This is the primary summary paragraph of the skill.

## Details
More details here.
`;
  const result = parseSkillMdContent(content, 'my-skill-dir');
  assert.equal(result.name, 'my-skill-dir');
  assert.equal(result.description, 'This is the primary summary paragraph of the skill.');
});

test('scanAllSkills discovers global and builtin skills', () => {
  const skills = scanAllSkills();
  assert.ok(Array.isArray(skills), 'Skills should be an array');
  assert.ok(skills.length > 0, 'Should discover at least one skill in global or builtin paths');
  const hasCoreDocsOrOther = skills.some(s => s.name === 'core-docs' || s.name === 'find-skill' || s.name === 'automation');
  assert.ok(hasCoreDocsOrOther, 'Expected to find core-docs, find-skill, or automation');
});

test('scanAllSkills detects universal agent rule files by agent type', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'gg-skills-'));
  try {
    write(root, 'CLAUDE.md', '# Claude Project Rules\n\nAlways run tests first.\n');
    write(root, 'AGENTS.md', '# Agents Guide\n\nShared agent instructions.\n');
    write(root, 'GEMINI.md', 'Gemini context only.\n');
    write(root, '.cursorrules', 'Use tabs.\n');
    write(root, '.cursor/rules/style.mdc', '---\ndescription: Style rules\n---\nBody\n');
    write(root, '.cursor/rules/other.md', '# Other\n\nOther rule.\n');
    write(root, '.github/copilot-instructions.md', '# Copilot\n\nBe concise.\n');
    write(root, '.windsurfrules', 'Windsurf rule.\n');
    write(root, '.claude/skills/my-skill/SKILL.md', '---\nname: my-skill\ndescription: Claude skill\n---\n');

    const items = scanAllSkills(root);
    const byPath = (rel) => items.find(i => i.skillFilePath === path.join(root, ...rel.split('/')));

    assert.equal(byPath('CLAUDE.md').agentType, 'claude');
    assert.equal(byPath('CLAUDE.md').name, 'Claude Project Rules');
    assert.equal(byPath('CLAUDE.md').description, 'Always run tests first.');
    assert.equal(byPath('AGENTS.md').agentType, 'gemini');
    assert.equal(byPath('GEMINI.md').name, 'GEMINI.md');
    assert.equal(byPath('.cursorrules').agentType, 'cursor');
    assert.equal(byPath('.cursor/rules/style.mdc').agentType, 'cursor');
    assert.equal(byPath('.cursor/rules/style.mdc').description, 'Style rules');
    assert.equal(byPath('.cursor/rules/other.md').name, 'Other');
    assert.equal(byPath('.github/copilot-instructions.md').agentType, 'copilot');
    assert.equal(byPath('.windsurfrules').agentType, 'windsurf');
    assert.equal(byPath('.claude/skills/my-skill/SKILL.md').agentType, 'claude');
    assert.equal(byPath('.claude/skills/my-skill/SKILL.md').name, 'my-skill');

    const paths = items.map(i => i.skillFilePath.toLowerCase());
    assert.equal(new Set(paths).size, paths.length, 'no duplicate files');
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('scanAllSkills silently skips missing agent files', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'gg-skills-empty-'));
  try {
    const items = scanAllSkills(root);
    assert.ok(!items.some(i => i.skillFilePath.startsWith(root)));
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
