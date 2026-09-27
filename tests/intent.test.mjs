import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const {
  classifyIntent,
  buildSystemPrompt,
  buildOfflinePrompt,
  modeLabel,
  shouldAskForMode
} = require('../dist/intent.js');

test('implementation order is classified as implement (Turkish)', () => {
  const c = classifyIntent('SRP kuralına uygun websocket bağlantı yöneticisi oluştur ve testlerini yaz');
  assert.equal(c.mode, 'implement');
  assert.equal(c.confidence, 'high');
  assert.equal(c.source, 'heuristic');
});

test('implementation order is classified as implement (English)', () => {
  const c = classifyIntent('add a retry helper to the http client and update the tests');
  assert.equal(c.mode, 'implement');
});

test('a question about architecture is consult, not implement', () => {
  const c = classifyIntent('Bu modülü nasıl yazmalıyım? Hangi yaklaşım daha sağlıklı?');
  assert.equal(c.mode, 'consult');
});

test('brainstorm phrasing is consult even without a question mark', () => {
  const c = classifyIntent('Fikirlerin neler, websocket için ne önerirsin');
  assert.equal(c.mode, 'consult');
});

test('English brainstorming is consult', () => {
  const c = classifyIntent('brainstorm some approaches for the cache layer, pros and cons please');
  assert.equal(c.mode, 'consult');
});

test('audit wording is audit (Turkish)', () => {
  const c = classifyIntent('src/network klasöründeki ölü kodları denetle ve katman ihlallerini raporla');
  assert.equal(c.mode, 'audit');
});

test('audit wording is audit (English)', () => {
  const c = classifyIntent('review this module for dead code and code smells, do not change anything');
  assert.equal(c.mode, 'audit');
});

test('an explicit prefix overrides the heuristic and reports its source', () => {
  const override = classifyIntent('#denetle: yeni bir modül de ekle');
  assert.equal(override.mode, 'audit');
  assert.equal(override.source, 'override');
  assert.equal(override.confidence, 'high');

  assert.equal(classifyIntent('#kodla: sadece bir isim yeter').mode, 'implement');
  assert.equal(classifyIntent('[audit] refactor this').mode, 'audit');
  assert.equal(classifyIntent('#danış: hangisi iyi?').mode, 'consult');
});

test('an ambiguous noun phrase falls back to implement rather than guessing', () => {
  const c = classifyIntent('websocket manager');
  assert.equal(c.mode, 'implement');
  assert.equal(c.confidence, 'low');
});

test('classification is deterministic', () => {
  const prompt = 'cache katmanını denetle, dead code var mı bak';
  const first = classifyIntent(prompt);
  const second = classifyIntent(prompt);
  assert.deepEqual(first, second);
  assert.ok(first.signals.length > 0, 'the decision must be explainable through its signals');
});

test('the system prompt carries exactly the selected mode and no other mode directive', () => {
  const audit = buildSystemPrompt('audit');
  assert.ok(audit.includes('DENETİM / REFACTOR'));
  assert.ok(/denetle/i.test(audit), 'audit directive must name what to inspect');
  assert.ok(!audit.includes('İSTİŞARE / FİKİR / BEYİN FIRTINASI MODU'));
  assert.ok(!audit.includes('UYGULAMA / KODLAMA MODU'));

  const consult = buildSystemPrompt('consult');
  assert.ok(consult.includes('İSTİŞARE / FİKİR / BEYİN FIRTINASI MODU'));
  assert.ok(!consult.includes('DENETİM / REFACTOR'));

  const implement = buildSystemPrompt('implement');
  assert.ok(implement.includes('UYGULAMA / KODLAMA MODU'));
  assert.ok(!implement.includes('DENETİM / REFACTOR'));
});

test('every mode prompt forbids bypassing the active guards', () => {
  for (const mode of ['consult', 'implement', 'audit']) {
    const prompt = buildSystemPrompt(mode);
    assert.ok(
      /sessiz hata yutma/.test(prompt) && /test/.test(prompt),
      `${mode} prompt must restate the integrity boundary`
    );
  }
});

test('the offline composer degrades to a usable brief, never an error', () => {
  const raw = 'kimlik doğrulama hatasını logla';
  const classification = classifyIntent(raw);
  const brief = buildOfflinePrompt(raw, classification);
  assert.ok(brief.includes(raw), 'the original request must survive verbatim');
  assert.ok(brief.includes(modeLabel(classification.mode)));
  assert.ok(brief.includes('### Beklenen çıktı'));
  assert.ok(brief.includes('### Kısıtlar'));
});

test('the offline composer asks for evidence in audit mode', () => {
  const raw = 'bu dosyadaki hataları incele';
  const brief = buildOfflinePrompt(raw, classifyIntent(raw));
  assert.ok(/kanıt|dosya:satır/.test(brief));
});

test('a low-confidence guess is questioned instead of obeyed', () => {
  // No signal at all: the classifier falls back to `implement` and says so.
  const vague = classifyIntent('websocket manager');
  assert.equal(vague.mode, 'implement');
  assert.equal(vague.confidence, 'low');
  assert.equal(shouldAskForMode(vague), true, 'a guess must be confirmed by the user');
});

test('a high-confidence decision is not questioned', () => {
  const clear = classifyIntent('SRP kuralına uygun websocket bağlantı yöneticisi oluştur ve testlerini yaz');
  assert.equal(clear.confidence, 'high');
  assert.equal(shouldAskForMode(clear), false, 'a confident classification must not add a click');
});

test('an explicit override is never questioned', () => {
  const override = classifyIntent('#denetle: sadece bir isim yeter');
  assert.equal(override.source, 'override');
  assert.equal(shouldAskForMode(override), false, 'the user already decided; do not ask again');
});
