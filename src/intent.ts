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

const IMPLEMENT_SIGNALS: Signal[] = [
  { pattern: /\b(?:ekle|ekleyelim|ekliyoruz)\b/, weight: 3, label: 'ekle' },
  { pattern: /\b(?:yaz|yazalım|yazmam|yazdır)\b/, weight: 3, label: 'yaz' },
  { pattern: /\b(?:oluştur|oluşturalım|oluşturulacak|create)\b/, weight: 3, label: 'oluştur' },
  { pattern: /\b(?:kur|kuralım|kurulması)\b/, weight: 2, label: 'kur' },
  { pattern: /\b(?:düzelt|fixeden|bug'ı düzelt)\b/, weight: 3, label: 'düzelt' },
  { pattern: /\b(?:güncelle|update)\b/, weight: 3, label: 'güncelle' },
  { pattern: /\b(?:sil|delete|remove|kaldır)\b/, weight: 2, label: 'sil' },
  { pattern: /\b(?:taşı|move|taşınacak)\b/, weight: 2, label: 'taşı' },
  { pattern: /\b(?:implement|write|create|add|build|generate|scaffold|wire up|hook up)\b/, weight: 2, label: 'en-verb' },
  { pattern: /\b(?:fix|patch|resolve)\b/, weight: 2, label: 'en-fix' },
  { pattern: /\b(?:refactor et|refaktör et|yeniden yaz)\b/, weight: 3, label: 'refactor-impl' },
  { pattern: /\b(?:endpoint|modül|modul|class| fonksiyon|schema|migration|test yaz)\b/, weight: 1, label: 'code-noun' }
];

const CONSULT_SIGNALS: Signal[] = [
  { pattern: /\?|؟/, weight: 2, label: 'soru-isareti' },
  { pattern: /\b(?:ne öner|önerir|nasıl yap|nasıl ol|fikrin|fikirlerin|beyin fırtınası)\b/, weight: 4, label: 'tr-brainstorm' },
  { pattern: /\b(?:seçenek|alternatif|karşılaştır|avantaj|dezavantaj|trade-?off)\b/, weight: 3, label: 'tr-tradeoff' },
  { pattern: /\b(?:tavsiye|daniş|danış|consult|görüşün|strateji|planlama)\b/, weight: 2, label: 'tr-advice' },
  { pattern: /\b(?:mı|mi|mu|mü)\s*\??\s*$/, weight: 2, label: 'tr-soru-sonu' },
  { pattern: /\b(?:what do you think|brainstorm|ideas?|how should|which one|compare|pros and cons|trade-?offs?|advice|recommend|should we|is it worth|strategy)\b/i, weight: 3, label: 'en-brainstorm' },
  { pattern: /\b(?:do you (?:think|prefer|recommend)|any idea)\b/i, weight: 3, label: 'en-question' }
];

const AUDIT_SIGNALS: Signal[] = [
  { pattern: /\b(?:denetle|denetim|denetimi)\b/, weight: 4, label: 'tr-audit' },
  { pattern: /\b(?:gözden geçir|gozden gecir|incele|inceleyelim|review et)\b/, weight: 3, label: 'tr-review' },
  { pattern: /\b(?:ölü kod|olu kod|kullanılmayan|kullanilmayan|dead code|unused|technical debt|teknik borç)\b/, weight: 3, label: 'tr-deadcode' },
  { pattern: /\b(?:sınır|sinir|katman ihlali|layer|boundary|bağımlılık|bağımlilik)\b/, weight: 1, label: 'tr-boundary' },
  { pattern: /\b(?:test bütünlüğü|test butunlugu|testleri sil|skip)\b/, weight: 2, label: 'tr-testintegrity' },
  { pattern: /\b(?:kontrol et|doğrula|dogrula|verify|check)\b/, weight: 1, label: 'tr-verify' },
  { pattern: /\b(?:audit|review|inspect|assess|evaluate)\b/i, weight: 3, label: 'en-audit' },
  { pattern: /\b(?:code smell|code quality|technical debt|dead code|unused|single responsibility|duplication)\b/i, weight: 3, label: 'en-smell' },
  { pattern: /\b(?:what(?:'s| is) wrong|any (?:issues|problems|risks)|smells?)\b/i, weight: 3, label: 'en-review-question' },
  { pattern: /\b(?:simplify|clean up|refactor)\b/i, weight: 2, label: 'en-cleanup' }
];

const OVERRIDE_PREFIXES: Array<{ pattern: RegExp; mode: IntentMode }> = [
  { pattern: /^\s*(?:#|\[|\()?\s*(?:denetle|denetim|audit|review|incele)\s*(?:\]|\))?\s*[:\-–]\s*/i, mode: 'audit' },
  { pattern: /^\s*(?:#|\[|\()?\s*(?:danış|danis|fikir|beyin fırtınası|consult|brainstorm)\s*(?:\]|\))?\s*[:\-–]\s*/i, mode: 'consult' },
  { pattern: /^\s*(?:#|\[|\()?\s*(?:kodla|yap|yaz|implement|build|code)\s*(?:\]|\))?\s*[:\-–]\s*/i, mode: 'implement' }
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

  let mode: IntentMode;
  if (winner.score === 0) {
    mode = 'implement';
  } else if (winner.score === runnerUp.score) {
    mode = consult.score > implement.score ? 'consult' : winner.mode;
  } else {
    mode = winner.mode;
  }

  let confidence: Confidence;
  if (winner.score >= 6 && winner.score >= runnerUp.score * 2) {
    confidence = 'high';
  } else if (winner.score >= 3) {
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
