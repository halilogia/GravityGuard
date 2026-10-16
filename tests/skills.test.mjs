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

test('scanAllSkills discovers global skills under the user home', () => {
  // Hermetic: a throw-away home with one skill, so the test never depends on what the developer (or the CI runner)
  // happens to have installed under ~/.gemini.
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'gg-home-'));
  const saved = { HOME: process.env.HOME, USERPROFILE: process.env.USERPROFILE };
  try {
    write(home, '.gemini/config/skills/core-docs/SKILL.md', '---\nname: core-docs\ndescription: Core docs standard\n---\n');
    process.env.HOME = home;
    process.env.USERPROFILE = home;
    const skills = scanAllSkills();
    assert.ok(Array.isArray(skills), 'Skills should be an array');
    const found = skills.find(s => s.name === 'core-docs');
    assert.ok(found, 'Expected the fixture skill core-docs under the user home');
    assert.equal(found.scope, 'global');
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    fs.rmSync(home, { recursive: true, force: true });
  }
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

// ---------------------------------------------------------------------------
// Rule files (kind: 'rule') vs skills (kind: 'skill'). These tests redirect the
// home directory to a temp folder so they never depend on the real ~/.gemini.
// ---------------------------------------------------------------------------

/** Creates an isolated project root + fake home and runs fn(root, home) with HOME/USERPROFILE redirected. */
function withSandbox(fn) {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'gg-rules-'));
  const root = path.join(base, 'project');
  const home = path.join(base, 'home');
  fs.mkdirSync(root, { recursive: true });
  fs.mkdirSync(home, { recursive: true });
  const saved = { USERPROFILE: process.env.USERPROFILE, HOME: process.env.HOME };
  process.env.USERPROFILE = home;
  process.env.HOME = home;
  try {
    assert.equal(path.resolve(os.homedir()), path.resolve(home), 'home redirection must take effect');
    return fn(root, home);
  } finally {
    for (const [k, v] of Object.entries(saved)) {
      if (v === undefined) {
        delete process.env[k];
      } else {
        process.env[k] = v;
      }
    }
    fs.rmSync(base, { recursive: true, force: true });
  }
}

const findByPath = (items, base, rel) => items.find(i => i.skillFilePath === path.join(base, ...rel.split('/')));

test('scanAllSkills finds user rules in ~/.gemini/config/rules as global gemini rules', () => {
  withSandbox((root, home) => {
    write(home, '.gemini/config/rules/naming.md', '---\nname: Naming Conventions\ndescription: Use kebab-case.\n---\nBody\n');
    write(home, '.gemini/config/rules/security.md', '# Security Rules\n\nNever commit secrets.\n');
    write(home, '.gemini/config/rules/notes.txt', 'not a markdown rule\n');
    write(home, '.gemini/config/rules/nested/deep.md', '# Deep\n\nNon-recursive scan skips this.\n');

    const items = scanAllSkills(root);
    const naming = findByPath(items, home, '.gemini/config/rules/naming.md');
    const security = findByPath(items, home, '.gemini/config/rules/security.md');

    assert.ok(naming, 'frontmatter rule found');
    assert.equal(naming.kind, 'rule');
    assert.equal(naming.scope, 'global');
    assert.equal(naming.agentType, 'gemini');
    assert.equal(naming.name, 'Naming Conventions');
    assert.equal(naming.description, 'Use kebab-case.');
    assert.equal(naming.skillDirPath, path.join(home, '.gemini', 'config', 'rules'));

    assert.ok(security, 'heading-only rule found');
    assert.equal(security.name, 'Security Rules');
    assert.equal(security.description, 'Never commit secrets.');

    assert.equal(findByPath(items, home, '.gemini/config/rules/notes.txt'), undefined, 'non-markdown ignored');
    assert.equal(findByPath(items, home, '.gemini/config/rules/nested/deep.md'), undefined, 'not recursive');
  });
});

test('scanAllSkills finds project rules.md, agent.md and .gemini/rules/*.md as workspace rules', () => {
  withSandbox((root, home) => {
    write(root, 'rules.md', '# Project Rules\n\nKeep functions small.\n');
    write(root, 'agent.md', '---\nname: Project Agent\ndescription: Agent behaviour for this repo.\n---\n');
    write(root, '.gemini/rules/style.md', '# Style\n\nPrefer const.\n');
    write(root, '.gemini/rules/plain.md', 'Just plain text without heading.\n');
    write(root, '.gemini/rules/ignored.json', '{}\n');

    const items = scanAllSkills(root);

    const rules = findByPath(items, root, 'rules.md');
    assert.ok(rules);
    assert.equal(rules.kind, 'rule');
    assert.equal(rules.scope, 'workspace');
    assert.equal(rules.name, 'Project Rules');
    assert.equal(rules.description, 'Keep functions small.');
    assert.equal(rules.skillDirPath, root);

    const agent = findByPath(items, root, 'agent.md');
    assert.ok(agent);
    assert.equal(agent.kind, 'rule');
    assert.equal(agent.scope, 'workspace');
    assert.equal(agent.agentType, 'gemini');
    assert.equal(agent.name, 'Project Agent');
    assert.equal(agent.description, 'Agent behaviour for this repo.');

    const style = findByPath(items, root, '.gemini/rules/style.md');
    assert.ok(style);
    assert.equal(style.kind, 'rule');
    assert.equal(style.scope, 'workspace');
    assert.equal(style.agentType, 'gemini');
    assert.equal(style.name, 'Style');

    // No frontmatter and no heading: name falls back to the file name, description to the first line.
    const plain = findByPath(items, root, '.gemini/rules/plain.md');
    assert.ok(plain);
    assert.equal(plain.name, 'plain.md');
    assert.equal(plain.description, 'Just plain text without heading.');

    assert.equal(findByPath(items, root, '.gemini/rules/ignored.json'), undefined);
  });
});

test('scanAllSkills matches rules.md / agent.md case-insensitively without double counting', () => {
  withSandbox((root, home) => {
    write(root, 'Rules.md', '# Mixed Case Rules\n\nFirst.\n');
    write(root, 'AGENT.md', '# Upper Agent\n\nSecond.\n');
    // On a case-sensitive filesystem this is a second file; on Windows it overwrites Rules.md.
    write(root, 'rules.md', '# Mixed Case Rules\n\nFirst.\n');

    const items = scanAllSkills(root);
    const rootRules = items.filter(i => i.skillDirPath === root && path.basename(i.skillFilePath).toLowerCase() === 'rules.md');
    const rootAgent = items.filter(i => i.skillDirPath === root && path.basename(i.skillFilePath).toLowerCase() === 'agent.md');

    assert.equal(rootRules.length, 1, 'rules.md counted once regardless of case');
    assert.equal(rootRules[0].kind, 'rule');
    assert.equal(rootAgent.length, 1, 'agent.md counted once regardless of case');
    assert.equal(rootAgent[0].kind, 'rule');
    // The on-disk spelling is preserved so the file can be opened as-is.
    assert.equal(path.basename(rootAgent[0].skillFilePath), 'AGENT.md');
    assert.equal(rootAgent[0].name, 'Upper Agent');
  });
});

test('scanAllSkills tolerates missing rule directories and files', () => {
  withSandbox((root, home) => {
    // Neither the project nor the fake home has any agent files at all.
    let items;
    assert.doesNotThrow(() => {
      items = scanAllSkills(root);
    });
    assert.deepEqual(items, []);

    // A rules path that is a file instead of a directory must not throw either.
    write(root, '.gemini/rules', 'not a directory\n');
    write(home, '.gemini/config/rules', 'not a directory\n');
    assert.doesNotThrow(() => scanAllSkills(root));
    assert.deepEqual(scanAllSkills(root), []);
  });
});

test('scanAllSkills tags skills as kind skill and rule files as kind rule', () => {
  withSandbox((root, home) => {
    write(root, '.agent/skills/deploy/SKILL.md', '---\nname: deploy\ndescription: Deploy helper.\n---\n');
    write(root, 'skills/lint/SKILL.md', '---\nname: lint\ndescription: Lint helper.\n---\n');
    write(home, '.gemini/config/skills/global-skill/SKILL.md', '---\nname: global-skill\ndescription: Global.\n---\n');
    write(home, '.gemini/config/plugins/p1/skills/plug/SKILL.md', '---\nname: plug\ndescription: Plugin.\n---\n');
    write(root, 'CLAUDE.md', '# Claude Rules\n\nBe careful.\n');
    write(root, 'rules.md', '# Rules\n\nRule body.\n');
    write(home, '.gemini/config/rules/user.md', '# User Rule\n\nUser body.\n');

    const items = scanAllSkills(root);
    const kindOf = (base, rel) => {
      const found = findByPath(items, base, rel);
      return found ? found.kind : undefined;
    };

    assert.equal(kindOf(root, '.agent/skills/deploy/SKILL.md'), 'skill');
    assert.equal(kindOf(root, 'skills/lint/SKILL.md'), 'skill');
    assert.equal(kindOf(home, '.gemini/config/skills/global-skill/SKILL.md'), 'skill');
    assert.equal(kindOf(home, '.gemini/config/plugins/p1/skills/plug/SKILL.md'), 'skill');
    assert.equal(kindOf(root, 'CLAUDE.md'), 'rule');
    assert.equal(kindOf(root, 'rules.md'), 'rule');
    assert.equal(kindOf(home, '.gemini/config/rules/user.md'), 'rule');

    // Every item carries an explicit kind and no rule is ever a SKILL.md capability file.
    for (const item of items) {
      assert.ok(item.kind === 'skill' || item.kind === 'rule', `kind set for ${item.skillFilePath}`);
      assert.equal(item.kind === 'rule', path.basename(item.skillFilePath).toUpperCase() !== 'SKILL.MD');
    }
    // Rule and skill ids never collide.
    const ids = items.map(i => i.id);
    assert.equal(new Set(ids).size, ids.length);
  });
});

test('scanAllSkills never lists the same file twice when several scan routes reach it', () => {
  withSandbox((root, home) => {
    // Scanning the home directory as the workspace reaches ~/.agent/skills and ~/.claude/skills
    // both as workspace and as global sources.
    write(home, '.agent/skills/shared/SKILL.md', '---\nname: shared\ndescription: Shared.\n---\n');
    write(home, '.claude/skills/claude-shared/SKILL.md', '---\nname: claude-shared\ndescription: Shared.\n---\n');
    write(home, '.gemini/rules/project-like.md', '# Project Like\n\nBody.\n');
    write(home, '.gemini/config/rules/user.md', '# User\n\nBody.\n');
    write(home, 'rules.md', '# Home Rules\n\nBody.\n');

    const items = scanAllSkills(home);
    const keys = items.map(i => path.resolve(i.skillFilePath).toLowerCase());
    assert.equal(new Set(keys).size, keys.length, 'no duplicate entries');
    assert.ok(findByPath(items, home, '.agent/skills/shared/SKILL.md'));
    assert.ok(findByPath(items, home, '.claude/skills/claude-shared/SKILL.md'));
    assert.ok(findByPath(items, home, '.gemini/rules/project-like.md'));
    assert.ok(findByPath(items, home, '.gemini/config/rules/user.md'));
    assert.ok(findByPath(items, home, 'rules.md'));
  });
});

test('scanAllSkills de-duplicates a rule file reachable through two linked rule directories', () => {
  withSandbox((root, home) => {
    // .cursor/rules and .gemini/rules both point (junction on Windows, symlink elsewhere) at one real folder.
    write(root, 'shared-rules/common.md', '# Common\n\nShared by several agents.\n');
    fs.mkdirSync(path.join(root, '.cursor'), { recursive: true });
    fs.mkdirSync(path.join(root, '.gemini'), { recursive: true });
    const real = path.join(root, 'shared-rules');
    fs.symlinkSync(real, path.join(root, '.cursor', 'rules'), 'junction');
    fs.symlinkSync(real, path.join(root, '.gemini', 'rules'), 'junction');

    const items = scanAllSkills(root);
    const target = fs.realpathSync(path.join(real, 'common.md')).toLowerCase();
    const same = items.filter(i => {
      try {
        return fs.realpathSync(i.skillFilePath).toLowerCase() === target;
      } catch {
        return false;
      }
    });
    assert.equal(same.length, 1, 'one real file is one entry no matter how many routes reach it');
    assert.equal(same[0].kind, 'rule');
  });
});

test('scanAllSkills reads rule files that start with a UTF-8 BOM', () => {
  withSandbox((root, home) => {
    write(root, 'rules.md', '﻿---\nname: Bom Rules\ndescription: Saved by Notepad.\n---\nBody\n');
    write(root, '.gemini/rules/bom-heading.md', '﻿# Bom Heading\n\nSummary line.\n');

    const items = scanAllSkills(root);
    const fm = findByPath(items, root, 'rules.md');
    const heading = findByPath(items, root, '.gemini/rules/bom-heading.md');
    assert.equal(fm.name, 'Bom Rules');
    assert.equal(fm.description, 'Saved by Notepad.');
    assert.equal(heading.name, 'Bom Heading');
    assert.equal(heading.description, 'Summary line.');
  });
});
