export type IntentMode = 'consult' | 'implement' | 'audit';

export type Confidence = 'high' | 'medium' | 'low';

export interface IntentClassification {
  mode: IntentMode;
  confidence: Confidence;
  score: number;
  runnerUpScore: number;
  signals: string[];
  source: 'override' | 'heuristic';
}

interface Signal {
  pattern: RegExp;
  weight: number;
  label: string;
}

/**
 * Turkish is agglutinative, and a `\b`-anchored keyword silently fails on every
 * inflected form: "teknik borç" does not match "teknik borcu", "ölü kod" does not
 * match "ölü kodu". Those failures are invisible — the prompt still comes out,
 * just aimed at the wrong job — so Turkish keywords are matched as stems with a
 * bounded suffix allowance.
 *
 * Two details in the pattern are load-bearing, and both were bugs first:
 *   - `\\p{L}` (not `\p{L}`): this builds a STRING handed to `new RegExp`, where
 *     an unescaped `\p` collapses to the literal letter "p" and the "must follow
 *     a non-letter" guard silently degrades into "must not be p, {, L or }" —
 *     which then matches inside ordinary words ("ölçeklenir" contains "ekle").
 *   - the `u` flag, without which `\p{L}` is not a property escape at all.
 * The cost of the suffix allowance is that a stem can occasionally match a
 * longer unrelated word, which is acceptable for a mode hint the user can
 * override with a prefix or confirm when confidence is low.
 *
 * Stems may contain a character class where Turkish consonant softening makes a
 * literal unreliable ("teknik borç" is "teknik borcu" in the accusative).
 *
 * The suffix allowance deliberately EXCLUDES the Turkish potential suffix
 * *-A-bil-* ("yaz-ebil-iriz" = "we could write"), which turns a verb from an
 * order into a hypothesis. Without that exclusion, "how many ways could we
 * write this?" classified as an implementation request, because it mentions a
 * build verb. The vowel before "bil" is harmonised (yaz**a**biliriz), so the
 * guard skips up to two letters rather than looking for a literal "ebil".
 */
function tr(...stems: string[]): RegExp {
  return new RegExp(`(?:^|[^\\p{L}])(?:${stems.join('|')})(?!\\p{L}{0,2}bil)[a-zçğıöşü]{0,8}`, 'iu');
}

const IMPLEMENT_SIGNALS: Signal[] = [
  // Strong build verbs (4): an imperative is a build order even when it names a
  // code smell. "delete the unused feature flag" is a deletion, not an audit.
  { pattern: tr('ekle', 'ekleyelim', 'ekliyoruz'), weight: 4, label: 'tr-add' },
  { pattern: tr('yaz', 'yazalım', 'yazmam', 'yazdır'), weight: 4, label: 'tr-write' },
  { pattern: tr('oluştur', 'oluşturalım'), weight: 4, label: 'tr-create' },
  { pattern: tr('düzelt', 'fixeden'), weight: 4, label: 'tr-fix' },
  { pattern: tr('güncelle'), weight: 4, label: 'tr-update' },
  { pattern: tr('sil', 'kaldır'), weight: 4, label: 'tr-delete' },
  { pattern: tr('taşı'), weight: 4, label: 'tr-move' },
  { pattern: tr('tanımla', 'tanımlar', 'kurgula', 'kurgulayalım'), weight: 4, label: 'tr-define' },
  { pattern: tr('refaktör et', 'refactor et', 'yeniden yaz'), weight: 4, label: 'tr-refactor-verb' },
  { pattern: /\b(?:implement|write|create|add|generate|scaffold|fix|patch|resolve|delete|remove|move|refactor|clean up|wire up|hook up)\b/i, weight: 4, label: 'en-build-verb' },
  // Weak build nouns (1-2): on their own they only hint at the domain.
  { pattern: tr('kur', 'kuralım'), weight: 2, label: 'tr-setup' },
  { pattern: /\b(?:endpoint|schema|migration)\b/i, weight: 1, label: 'en-code-noun' },
  { pattern: tr('modül', 'modul', 'fonksiyon'), weight: 1, label: 'tr-code-noun' }
];

const CONSULT_SIGNALS: Signal[] = [
  // Syntactic markers (1): a question mark says a request is a question, never
  // WHICH kind. Weighting it above a real semantic signal is how "is the quality
  // of this code ok?" ends up classified as brainstorming.
  { pattern: /\?|؟/, weight: 1, label: 'question-mark' },
  { pattern: tr('mı', 'mi', 'mu', 'mü'), weight: 1, label: 'tr-question-particle' },
  // Semantic consult signals: a request for options, trade-offs, advice.
  { pattern: tr('ne öner', 'önerir', 'fikir', 'beyin fırtınası'), weight: 4, label: 'tr-brainstorm' },
  // "nasıl" is a question word, not a mode: "nasıl yazmalıyım" asks for
  // guidance, "kalitesi nasıl" asks for an assessment. Weight 2 keeps it from
  // outranking the specific signal that answers the second question.
  { pattern: tr('nasıl'), weight: 2, label: 'tr-how' },
  { pattern: tr('seçenek', 'alternatif', 'karşılaştır', 'avantaj', 'dezavantaj', 'artıları', 'eksileri'), weight: 3, label: 'tr-tradeoff' },
  { pattern: tr('tavsiye', 'daniş', 'danış', 'görüş', 'strateji', 'planlama', 'hangi'), weight: 3, label: 'tr-advice' },
  { pattern: /\b(?:brainstorm|ideas?|how should|which one|compare|pros and cons|trade-?offs?|advice|recommend|should we|is it worth|strategy|any idea)\b/i, weight: 3, label: 'en-brainstorm' },
  { pattern: /\b(?:do you think|do you prefer|do you recommend)\b/i, weight: 3, label: 'en-question' }
];

const AUDIT_SIGNALS: Signal[] = [
  // Audit verbs (4): asking someone to look IS the request.
  { pattern: tr('denetle', 'denetim'), weight: 4, label: 'tr-audit-verb' },
  { pattern: tr('gözden geçir', 'incele', 'kontrol et', 'değerlendir'), weight: 4, label: 'tr-review-verb' },
  { pattern: /\b(?:audit|review|inspect|assess|evaluate)\b/i, weight: 4, label: 'en-audit-verb' },
  // Assessment topics: asking whether existing code is any good IS the audit
  // request, so this outranks a bare question word. "Specific beats generic" is
  // the ordering rule behind the weights here: a build verb or an audit verb (4)
  // outranks a question (1-2), and a named assessment topic (5) outranks both.
  { pattern: tr('kalite', 'riski', 'risk', 'tehlike', 'doğruluk', 'işleyiş'), weight: 5, label: 'tr-assessment' },
  { pattern: tr('teknik bor[çc]', 'ölü kod', 'kullanılmayan', 'kullanilmayan'), weight: 3, label: 'tr-deadcode' },
  { pattern: /\b(?:dead code|unused|technical debt|code smell|code quality|duplication|single responsibility)\b/i, weight: 3, label: 'en-smell' },
  { pattern: /\b(?:what(?:'s| is) wrong|any (?:issues|problems|risks)|smells?)\b/i, weight: 3, label: 'en-review-question' },
  // Weak audit nouns (1-2): a project can legitimately have layers and still be
  // an implementation request.
  { pattern: tr('sınır', 'sinir', 'bağımlılık', 'bağımlilik', 'katman ihlali'), weight: 1, label: 'tr-boundary' },
  { pattern: tr('test bütünlüğü', 'test butunlugu', 'testleri sil'), weight: 2, label: 'tr-test-integrity' }
];

// An override must be marked, never inferred: a leading `#`, `[` or `(` is
// required, and the trailing separator (`:`, `-`, `–`) is optional so that both
// "#denetle: ..." and "[audit] refactor this" work.
const OVERRIDE_PREFIXES: Array<{ pattern: RegExp; mode: IntentMode }> = [
  { pattern: /^\s*[#\[\(]\s*(?:denetle|denetim|audit|review|incele)\s*[\]\)]?\s*[:\-–]?\s*/i, mode: 'audit' },
  { pattern: /^\s*[#\[\(]\s*(?:danış|danis|fikir|beyin fırtınası|consult|brainstorm)\s*[\]\)]?\s*[:\-–]?\s*/i, mode: 'consult' },
  { pattern: /^\s*[#\[\(]\s*(?:kodla|yap|yaz|implement|build|code)\s*[\]\)]?\s*[:\-–]?\s*/i, mode: 'implement' }
];

const SHARED_DIRECTIVE = `2. MİMARİ VE MODÜLERLİK DİREKTİFLERİ (ARCH_FILE_GROWTH & SRP KORUMASI):
   - Tek bir dosyayı kontrolsüzce şişirmek (monolith accumulation) yerine bağımsız sorumlulukları ayrı, cohesive modüllere ayırmayı şart koç.
   - Mevcut büyük bir dosyaya yeni bir ana sorumluluk eklemek yerine yeni modül oluşturmayı tercih ettir.
   - Ancak yapay/gereksiz parçalamadan (over-splitting/over-engineering) kaçın; yalnızca belirgin sorumluluk ve katman sınırlarında ayır.
   - En az dosya sayısıyla en net sorumluluk ayrımını hedefle.`;

const CONSULT_DIRECTIVE = `A) İSTİŞARE / FİKİR / BEYİN FIRTINASI MODU:
   - Kullanıcı danışma ve fikir üretme istiyor. ASLA icraat emri verme; "şunları kodla, şu dosyaları aç" diye yönlendirme yapma.
   - En az 3 gerçek alternatif sun (Seçenek A / B / C); her biri için trade-off, uygulama maliyeti ve hangi durumda seçileceğini yaz.
   - Over-engineering riskini, YAGNI ihlalini ve "şimdi yapılmaması gerekenler" listesini açıkça belirt.
   - Sonunda karar desteği sun: hangi seçeneğin ne zaman seçileceğine dair ölçütler.
   - Hiçbir dosya yazma, hiçbir araç çağırma; yalnızca analiz ve strateji üret.
   - Önerin aktif guard sınırlarını ihlal etmesin: gizli credential, sessiz hata yutma veya test susturma önerisi verme.`;

const IMPLEMENT_DIRECTIVE = `B) UYGULAMA / KODLAMA MODU:
   - Kullanıcı açıkça bir üretim emri verdi. Savunmacı teknik inşaat şartnamesine dönüştür.
   - Şartname şu başlıkları içersin: Amaç, Kapsam (kapsam dışı listesiyle), Mimari ve modül sınırları, SRP sınırları, Hata Yönetimi, Testler (hangi senaryo, hangi dosya), Bağımlılıklar.
   - Her adımda doğrulanabilir bir çıktı tanımla; "yeterince iyi" gibi ölçülemez ifadeler kullanma.
   - Güvenlik sınırı: gizli credential yazma, sessiz hata yutma, test silme veya testi .skip ile susturma yok.`;

const AUDIT_DIRECTIVE = `C) DENETİM / REFACTOR MODU:
   - Bu modda YENİ ÖZELLİK veya üretim kodu yazma. Görevin mevcut kodun durumunu kanıtlı biçimde raporlamak.
   - Çıktıyı bulgu listesi olarak ver: dosya:satır referansı + somut sorun + etkisi (kritik / orta / düşük) + tek satırlık düzeltme önerisi.
   - Denetlenecek alanlar: katman ve bağımlılık sınırı ihlalleri, SRP ihlalleri, ölü kod ve tekrarlanan mantık, sessiz hata yutmaları, gizli credential, yorum ile davranışın uyuşmazlığı, test bütünlüğü (silinmiş / susturulmuş / içi boşaltılmış testler), hata durumunda veri bozulması riski.
   - Her bulguyu kanıtla: iddia ettiğin satırları göster. Kanıtı olmayan şüpheyi bulgu diye yazma; "doğrulanamadı" diye ayrı bir listeye koy.
   - Test bütünlüğü tarafında kullanıcıdan açık izin almadan test silme veya sessizleştirme önerisini uygulama notu olarak yazma; bunlar aktif koruma altındadır.
   - Refactor önerisi veriyorsan davranışı koruyan, küçük ve geri alınabilir adımlara böl; her adım için doğrulama yöntemini (hangi test, hangi komut) belirt.
   - Kapsam genişletme: dokunmadığın modülleri "iyileştirme" gerekçesiyle kapsama alma.`;

const FOOTER_DIRECTIVE = `3. Doğrudan geliştirilmiş prompt metnini ver. Başında veya sonunda gereksiz meta konuşmalar, giriş-çıkış tebrikleri yapma.
4. Dil: Kullanıcının girdiği dille (Türkçe veya İngilizce) aynı dilde cevap ver.`;

const MODE_LABEL: Record<IntentMode, string> = {
  consult: 'İSTİŞARE',
  implement: 'UYGULAMA',
  audit: 'DENETİM / REFACTOR'
};

function scoreSignals(text: string, signals: Signal[]): { score: number; hits: string[] } {
  let score = 0;
  const hits: string[] = [];
  for (const signal of signals) {
    if (signal.pattern.test(text)) {
      score += signal.weight;
      hits.push(signal.label);
    }
  }
  return { score, hits };
}

function detectOverride(raw: string): IntentMode | null {
  for (const entry of OVERRIDE_PREFIXES) {
    if (entry.pattern.test(raw)) {
      return entry.mode;
    }
  }
  return null;
}

export function classifyIntent(rawPrompt: string): IntentClassification {
  const raw = (rawPrompt || '').trim();
  const text = raw.toLowerCase();

  const override = detectOverride(raw);
  if (override) {
    return {
      mode: override,
      confidence: 'high',
      score: Number.POSITIVE_INFINITY,
      runnerUpScore: 0,
      signals: ['override'],
      source: 'override'
    };
  }

  const implement = scoreSignals(text, IMPLEMENT_SIGNALS);
  const consult = scoreSignals(text, CONSULT_SIGNALS);
  const audit = scoreSignals(text, AUDIT_SIGNALS);

  const ranked: Array<{ mode: IntentMode; score: number; hits: string[] }> = [
    { mode: 'implement', ...implement },
    { mode: 'consult', ...consult },
    { mode: 'audit', ...audit }
  ];
  ranked.sort((a, b) => b.score - a.score);

  const winner = ranked[0];
  const runnerUp = ranked[1];

  // Tie-break: equal evidence plus a question mark resolves to `consult`.
  // A user who asked something has not asked for code, and producing code that
  // nobody requested is the more damaging of the two mistakes — so when the
  // classifier cannot tell, it must not assume an order. (Equal evidence without
  // a question mark stays with `implement`, the mode this feature was built
  // around, and the confidence band below sends the ambiguous case to the user.)
  const isQuestion = /\?|؟/.test(raw) || /\b(?:mı|mi|mu|mü)\b/iu.test(raw);
  let mode: IntentMode;
  if (winner.score === 0) {
    mode = 'implement';
  } else if (winner.score === runnerUp.score) {
    mode = isQuestion ? 'consult' : winner.mode;
  } else {
    mode = winner.mode;
  }

  let confidence: Confidence;
  if (winner.score >= 6 && winner.score >= runnerUp.score * 2) {
    confidence = 'high';
  } else if (winner.score >= 3) {
    confidence = 'medium';
  } else if (isQuestion && winner.score > 0) {
    // A question mark is real evidence even when nothing else fires: the user
    // asked something, so "consult" is not a coin flip. Without this floor,
    // "will this scale?" scored 2 and was sent to the user as a guess.
    confidence = 'medium';
  } else {
    confidence = 'low';
  }

  const signals = ranked
    .filter(entry => entry.score > 0)
    .sort((a, b) => b.score - a.score)
    .flatMap(entry => entry.hits.map(hit => `${entry.mode}:${hit}`));

  return {
    mode,
    confidence,
    score: winner.score,
    runnerUpScore: runnerUp.score,
    signals,
    source: 'heuristic'
  };
}

export function modeLabel(mode: IntentMode): string {
  return MODE_LABEL[mode];
}

/**
 * Whether the command should ask instead of guessing.
 *
 * The classifier is a keyword heuristic, so with little evidence it will be
 * wrong sometimes. A silent wrong guess is worse than an extra click: an audit
 * directive sent to an implementation request (or the reverse) actively
 * misleads the model, and the output still looks like a normal answer. So below
 * the high band the user is asked, with the current guess offered as the
 * default. Above it, the guess is trusted and the flow stays one keypress.
 *
 * An explicit override is never questioned: the user already said.
 */
export function shouldAskForMode(classification: IntentClassification): boolean {
  return classification.source === 'heuristic' && classification.confidence !== 'high';
}

export function buildSystemPrompt(mode: IntentMode): string {
  const header = `Sen kıdemli bir yazılım mimarı ve prompt mühendisisin. Kullanıcının verdiği ham/kısa isteği analiz et ve Antigravity IDE içindeki AI asistanına (Agent) verilecek en mükemmel PROMPT'a dönüştür.

ZORUNLU KURALLAR:
1. MOD TESPİTİ: Sistem tarafından "${MODE_LABEL[mode]}" modu olarak belirlendi. Niyeti yeniden yorumlama; bu modun kurallarına uy.

`;
  const body =
    mode === 'consult' ? CONSULT_DIRECTIVE : mode === 'implement' ? IMPLEMENT_DIRECTIVE : AUDIT_DIRECTIVE;
  return header + body + '\n\n' + SHARED_DIRECTIVE + '\n' + FOOTER_DIRECTIVE;
}

export function buildOfflinePrompt(
  rawPrompt: string,
  classification: IntentClassification
): string {
  const request = rawPrompt.trim();
  const mode = classification.mode;

  const objectives: Record<IntentMode, string[]> = {
    consult: [
      'En az 3 alternatif (Seçenek A / B / C) sun; her biri için trade-off ve uygulama maliyetini yaz.',
      'Over-engineering / YAGNI risklerini ve şimdi yapılmaması gerekenleri açıkça listele.',
      'Karar ölçütleriyle sonuç ver: hangi seçenek hangi koşulda seçilmeli.'
    ],
    implement: [
      'Amaç, kapsam ve kapsam dışı listesiyle başla.',
      'Modül ve katman sınırlarını, SRP sınırlarını belirt; yeni sorumluluk için yeni modül tercih et.',
      'Hata yönetimi, bağımlılıklar ve hangi senaryonun hangi test dosyasında doğrulanacağını yaz.',
      'Gizli credential, sessiz hata yutma ve test susturma yasaktır.'
    ],
    audit: [
      'Mevcut kodu değiştirme; bulguları kanıtlı biçimde raporla.',
      'Her bulgu için dosya:satır, somut sorun, etki (kritik/orta/düşük) ve tek satırlık öneri ver.',
      'Şunları denetle: katman sınırı, SRP, ölü kod, tekrar, sessiz hata, gizli credential, test bütünlüğü.',
      'Kanıtı olmayan iddiayı bulgu olarak yazma; doğrulanamayanları ayrı listele.',
      'Refactor önerilerini küçük, geri alınabilir ve doğrulama adımı olan adımlara böl.'
    ]
  };

  return [
    `## Görev — GravityGuard (${MODE_LABEL[mode]} modu)`,
    '',
    '### Kullanıcının isteği',
    '> ' + request.split('\n').join('\n> '),
    '',
    '### Beklenen çıktı',
    ...objectives[mode].map(item => `- ${item}`),
    '',
    '### Kısıtlar',
    '- Tek bir dosyayı şişirme; sorumlulukları cohesive modüllere ayır.',
    '- Yapay parçalamadan (over-engineering) kaçın; sadece belirgin sınırlarda ayır.',
    '- Ölçülemez hedefler ("iyi olsun", "temizleyelim") kullanma; kabul kriteri yaz.',
    '- Gizli credential yazma, sessiz hata yutma, test silme veya .skip ile susturma.',
    '',
    '### Yanıt dili',
    '- Kullanıcının yazdığı dil (Türkçe veya İngilizce).'
  ].join('\n');
}
