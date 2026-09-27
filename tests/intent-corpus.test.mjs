import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const require = createRequire(import.meta.url);
const { classifyIntent } = require('../dist/intent.js');

const here = dirname(fileURLToPath(import.meta.url));
const corpus = readFileSync(join(here, 'fixtures', 'intent-corpus.txt'), 'utf8')
  .split('\n')
  .map(line => line.trim())
  .filter(line => line && !line.startsWith('#'))
  .map(line => {
    const [expected, ...rest] = line.split('\t');
    return { expected, prompt: rest.join('\t') };
  });

// A signal change that flips a mode is silent: the prompt still comes out, just
// aimed at the wrong job. This is the gate for that. The threshold is 100% and
// deliberately unforgiving — the corpus is small and hand-written, so anything
// below perfection means a labelled case regressed. New prompts are added here
// as sentences that fooled the classifier, not as filler.
test('every hand-labelled prompt is classified as labelled', () => {
  const misses = [];
  for (const { expected, prompt } of corpus) {
    const actual = classifyIntent(prompt).mode;
    if (actual !== expected) {
      misses.push(`  ${expected} -> ${actual}   "${prompt}"`);
    }
  }
  assert.equal(misses.length, 0, `intent corpus misses (${misses.length}/${corpus.length}):\n${misses.join('\n')}`);
});

test('the corpus is not trivially small', () => {
  assert.ok(corpus.length >= 30, `corpus has only ${corpus.length} entries; a gate over a handful proves little`);
  const modes = new Set(corpus.map(entry => entry.expected));
  assert.deepEqual([...modes].sort(), ['audit', 'consult', 'implement'], 'all three modes must be represented');
});

test('no labelled prompt resolves to a silent low-confidence guess', () => {
  // A real request should not require the confirmation picker; if one does, the
  // signal set is too narrow for that phrasing and the corpus says so.
  const vague = corpus
    .filter(entry => entry.expected !== 'implement' || entry.prompt.length > 20)
    .map(entry => ({ ...entry, confidence: classifyIntent(entry.prompt).confidence }))
    .filter(entry => entry.confidence === 'low');
  assert.equal(
    vague.length,
    0,
    `these labelled prompts classify with 'low' confidence, so users would be asked to confirm them:\n` +
      vague.map(entry => `  "${entry.prompt}"`).join('\n')
  );
});
