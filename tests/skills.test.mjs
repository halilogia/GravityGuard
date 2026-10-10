import test from 'node:test';
import assert from 'node:assert/strict';
import { parseSkillMdContent, scanAllSkills } from '../dist/skills.js';

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
