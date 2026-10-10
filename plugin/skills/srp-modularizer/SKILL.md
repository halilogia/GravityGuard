---
name: srp-modularizer
description: Use when a GravityGuard SRP_BOUNDARY deny or ARCH_FILE_GROWTH / OE_SPIKE warning appears, or when writing or refactoring a large page, component or module that mixes several sections, tabs, simulations or comparison matrices. Decides whether the file really has more than one change reason, splits it into focused sub-components if so, and keeps cohesive monoliths whole.
---

# SRP Modularizer

## Karar: gerçekten bölünmeli mi?

Ölçüt **değişim nedeni**dir: "bu dosya kaç farklı nedenle değişir?" Bir neden → bırak. Birden fazla → böl.

- **Böl:** sayfa iskeleti + simülasyon mantığı + veri modelleri bir arada; birbirinden bağımsız değişen sekmeler / bölümler; UI ile ağ (network) kodu aynı dosyada.
- **Bölme:** tek akışla değişen state machine / simülasyon; saf fonksiyon + kendi türleri; veri, config, locale, tema dosyaları; sadece yerleşim ve yönlendirme yapan conductor sayfa.
- Satır sayısı yalnız belirtidir. Örnek: iki nedenle değişen 150 satır bölünür, tek nedenle değişen 600 satır bölünmez. "~400+ satır", "~90-150 satırlık conductor" gibi sayılar sezgisel örnektir, kural değildir; hook bunları kullanmaz.

## Hook ne yapar (gravity-validator, birebir)

Kapsam **uzantıya göredir, klasöre göre değil**: `.py`, `.ts`, `.tsx`, `.js`, `.jsx`. Hariç: test dosyaları (`tests/`, `test/`, `__tests__/` altı ya da adında `test_`, `_test`, `.test.`, `.spec.`), vendor / cache yolları (`node_modules`, `venv`, `dist`, `build`, `.git`, `__pycache__`, `runs`, `scratch`, `brain`, `.gemini`), kod olmayan dosyalar (`.json`, `.css`, `.scss`, `.md`, `.txt`, `.yaml`, `.toml` …). `data/`, `locales/`, `i18n/`, `config/` klasörleri **muaf değildir**; oradaki `.ts` / `.py` da denetlenir.

| Kural | Sonuç | Tetikleyen (yazımdan sonraki tam dosya) |
|---|---|---|
| `SRP_BOUNDARY` TS/JS | **DENY** | (`activeTab ===` ≥2 **ve** `glass-card` ≥3) **ya da** (`scrollToSection(` ≥3 **ve** `display: 'grid'` ≥3) |
| `SRP_BOUNDARY` Python | **DENY** | UI kütüphanesi (tkinter, PyQt, PySide, wx, kivy) + ağ kütüphanesi (requests, urllib, http, httpx, aiohttp, websockets, socket) birlikte; ya da ≥4 üst düzey "iş" sınıfı (Exception / Enum / BaseModel / Protocol / ABC tabanlı, `@dataclass`, Blender Panel / Operator sınıfları sayılmaz; `models.py`, `types.py`, `schemas.py`, `constants.py` … dosyaları muaf) |
| `ARCH_FILE_GROWTH` | uyarı (izin verir) | dosya 1000 dolu satırı geçiyor; ya da mevcut dosyada: 800+ satıra ≥80 satır ekleme, tek yazımda ≥200 satır, 15 dakikada toplam ≥200 satır. Yeni dosyanın 1000 altındaki boyu uyarı vermez |
| `OE_SPIKE` | uyarı (izin verir) | ≤50 satırlık eklemede ≥2 yeni `class` / `interface` |

- TS/JS dedektörleri bu projeye özgü yüzey sinyalleridir (bir UI kütüphanesinin sınıf ve fonksiyon adları), gerçek karar değildir. Başka projede SRP ihlali olan dosya bu kelimeleri içermeyince hook susar; o durumda yine yukarıdaki "değişim nedeni" kararını sen verirsin.
- "Cohesive monolith ALLOW" hook'ta bir yargı değildir: sinyaller eşiğin altındaysa geçer. Tek muafiyet, dosyada **zaten bulunan** `// srp: allow-monolith` (ya da `cohesive-monolith`, `bypass`, `noqa`; Python'da `# srp: …` / `# noqa: srp`) işaretidir. Bu işareti ajan yeni eklerse `G2_SECURITY_TAMPERING` ile DENY gelir; işareti yalnız insan ekler.
- Eşikler `.gravityguard.json` → `complexity` (`monolithLoc`, `singleWriteLoc`, `creepBaseLoc`, `creepAddedLoc`, `overEngineeringMaxLoc`, `overEngineerAbstractions`) ile değişir; `rules.SRP_BOUNDARY: "shadow"` kuralı yalnız kayda geçirir.
- DENY gelince sinyali kelime değiştirerek atlatma; dosyayı değişim nedenine göre böl. Bölünmemesi gerektiğine inanıyorsan kullanıcıya söyle, işareti o eklesin.

## Nereye taşınır

1. **Sayfa yanı (co-location)**, basit / orta sayfalar: `src/presentation/pages/<page-name>/<Section>.tsx`. Sayfa silinince bölümler de gider.
2. **Özellik modülü**, multi-tab, simülasyon, ağır iş mantığı: `src/presentation/components/<feature>/<SectionOrTab>.tsx`.
3. **Genel bileşen**, gerçekten yeniden kullanılanlar: `src/presentation/components/<Component>.tsx`.

Yollar örnektir; projenin mevcut klasör düzenine uy.

## Süreç

1. Bileşen sayfaya mı özgü, paylaşılıyor mu? Ona göre yer seç.
2. Değişim nedenlerini say; tek nedense dur, bölme.
3. Her nedeni kendi dosyasına taşı; üst dosya yalnız yerleşimi, sekme / scroll yönlendirmesini ve state bağlantısını tutan conductor kalsın.
4. Doğrula: projenin kendi typecheck / build / test betiklerini çalıştır (`package.json` scripts, `pyproject`, Makefile neyse).
