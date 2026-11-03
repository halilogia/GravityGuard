import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { RULE_CATALOG, NOTE_RULE_IDS, getRule, listedRules, ruleTitle, effectiveMode, RULE_GROUPS } from '../dist/rule_catalog.js';
import { MANDATORY_RULES } from '../dist/rule_modes.js';
import { initI18n, setLanguage, resources } from '../dist/i18n/index.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const engineDirs = [path.join(root, 'engine'), path.join(root, 'engine', 'gravityguard_engine')];

/** Not rule ids: environment variables, audit statuses and similar constants that look like ids. */
const NOT_RULES = new Set([
  'UNVERIFIED_CIRCUIT_BREAKER', 'PENDING_EVIDENCE', 'SHADOW_TRIGGER', 'SHADOW_OBSERVED', 'REPEATED_VIOLATION', 'NO_COLOR',
  'CREATE_NEW_PROCESS_GROUP', 'CREATE_NO_WINDOW', 'DEPRECATED_RULE',
  'MULTI_EDIT' // a tool name in operations.py
]);
const NOT_RULE_PREFIXES = ['GRAVITYGUARD_', 'ANTIGRAVITY_', 'AGY_', 'MODEL_', 'CONVERSATION_'];
const ID = '[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+';

function pythonSources() {
  const files = [];
  for (const dir of engineDirs) {
    for (const f of fs.readdirSync(dir)) if (f.endsWith('.py')) files.push(path.join(dir, f));
  }
  return files;
}

/** Rule ids the engine can emit, found by the patterns it logs and returns them with. */
function emittedIds() {
  const found = new Map();
  const add = (id, file) => { if (!found.has(id)) found.set(id, path.basename(file)); };
  const patterns = [
    new RegExp(`rule_id\\s*=\\s*["'](${ID})["']`, 'g'),            // log_event(..., rule_id="X")
    new RegExp(`\\bRULE_ID\\s*=\\s*["'](${ID})["']`, 'g'),          // token_guard constant
    new RegExp(`\\(\\s*["'](${ID})["']\\s*,`, 'g'),                 // warning tuples ("X", msg) and (rule, msg)
    new RegExp(`return\\s+(?:True|False),\\s*["'](${ID})["']`, 'g'), // return True, "X", ...
    new RegExp(`True,\\s*\\n\\s*["'](${ID})["']`, 'g'),             // multi-line return (web_srp_analyzer)
    new RegExp(`["'](HOOK_PROPOSAL_[A-Z]+)["']`, 'g'),              // hook proposal audit ids
    new RegExp(`["'](GUARD_(?:FALLBACK_LKG|REPAIR_MODE))["']`, 'g') // crash recovery ids
  ];
  for (const file of pythonSources()) {
    const text = fs.readFileSync(file, 'utf8');
    for (const re of patterns) for (const m of text.matchAll(re)) add(m[1], file);
  }
  for (const id of [...found.keys()]) {
    if (NOT_RULES.has(id) || NOT_RULE_PREFIXES.some(p => id.startsWith(p) && !id.startsWith('GUARD_'))) found.delete(id);
  }
  return found;
}

test('every rule id the engine emits has a catalog entry', () => {
  const missing = [...emittedIds()].filter(([id]) => !getRule(id)).map(([id, file]) => `${id} (${file})`);
  assert.deepEqual(missing, [], `Add these ids to src/rule_catalog.ts and the rules.catalog i18n groups: ${missing.join(', ')}`);
});

test('the scan finds the ids it should (guards the scanner itself)', () => {
  const ids = emittedIds();
  for (const id of ['G7_TS_FIRST', 'SHELL_SECURITY', 'ARCH_PMA_DEEP_IMPORT', 'WEB_DOCUMENT_SIZE', 'T2_NO_OBSERVABLE_ASSERTION',
    'T0_COVERAGE_BELOW_THRESHOLD', 'STATIC_LINTER_DIAGNOSTIC', 'TOOL_OUTPUT_BLOAT', 'OE_SINGLE_IMPL', 'HOOK_PROPOSAL_APPROVED']) {
    assert.ok(ids.has(id), `scanner no longer finds ${id}`);
  }
  assert.ok(ids.size > 40);
});

test('catalog entries are well formed', () => {
  const seen = new Set();
  for (const r of RULE_CATALOG) {
    assert.ok(!seen.has(r.id), `duplicate ${r.id}`);
    seen.add(r.id);
    assert.equal(r.mandatory, MANDATORY_RULES.has(r.id));
    assert.ok(['block', 'warn', 'shadow', 'note'].includes(r.defaultEffect));
    if (r.mandatory) assert.equal(r.control, 'none');
  }
  for (const id of MANDATORY_RULES) assert.ok(getRule(id), `mandatory ${id} missing`);
  for (const id of NOTE_RULE_IDS) assert.equal(getRule(id).defaultEffect, 'note');
  for (const r of listedRules()) assert.ok(RULE_GROUPS.includes(r.group));
});

test('every listed rule has a title and description in both languages without parentheses or the raw id', () => {
  for (const lang of ['tr', 'en']) {
    const cat = resources[lang].translation.rules.catalog;
    for (const r of listedRules()) {
      const e = cat[r.id];
      assert.ok(e && e.title && e.desc, `${lang}: missing copy for ${r.id}`);
      assert.ok(!/[()]/.test(e.title), `${lang}: parentheses in title of ${r.id}`);
      assert.ok(!/[()]/.test(e.desc), `${lang}: parentheses in description of ${r.id}`);
    }
  }
  setLanguage('tr');
  assert.equal(ruleTitle('G0_SECRET_LEAK'), 'Gizli anahtar sızıntısı');
  assert.equal(ruleTitle('NOT_IN_CATALOG'), 'NOT_IN_CATALOG');
  initI18n('tr');
});

test('effective mode follows the config only where the engine reads it', () => {
  const shadowCfg = { rules: { G1_SILENT_EXCEPTION: { mode: 'shadow' }, G0_SECRET_LEAK: { mode: 'shadow' }, DESIGN_ICON_RULE: 'shadow' } };
  assert.equal(effectiveMode(getRule('G1_SILENT_EXCEPTION'), {}), 'block');
  assert.equal(effectiveMode(getRule('G1_SILENT_EXCEPTION'), shadowCfg), 'shadow');
  assert.equal(effectiveMode(getRule('G0_SECRET_LEAK'), shadowCfg), 'block', 'mandatory rules ignore shadow');
  assert.equal(effectiveMode(getRule('DESIGN_ICON_RULE'), shadowCfg), 'block', 'engine never reads a mode for this rule');
  assert.equal(effectiveMode(getRule('OE_SINGLE_IMPL'), {}), 'shadow');
  assert.equal(effectiveMode(getRule('OE_SINGLE_IMPL'), { rules: { OE_SINGLE_IMPL: { mode: 'warn' } } }), 'warn');
  assert.equal(effectiveMode(getRule('OE_SINGLE_IMPL'), { rules: { OE_SINGLE_IMPL: { mode: 'off' } } }), 'off');
  assert.equal(effectiveMode(getRule('T0_TEST_RUN_FAILED'), {}), 'off', 'dynamic tests are opt-in');
  assert.equal(effectiveMode(getRule('T0_TEST_RUN_FAILED'), { testEvidence: { dynamicExecution: true } }), 'warn');
  assert.equal(effectiveMode(getRule('DOC_OBLIGATION_UNRESOLVED'), { governance: { enforceDocObligations: false } }), 'off');
});
