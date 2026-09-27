# Roadmap — GravityGuard

> **Bu dosya yalnızca yapılmamış işi tutar.** Tamamlanan her şey `CHANGELOG.md`'dedir;
> teslim edilen sürüm geçmişi, ölçümler ve "bunu neden böyle yaptık" kayıtları orada yaşar.
> Bir maddeyi buradan silmek, onu kaybetmek demek değildir — taşımak demektir.

| Durum | Sürüm | Nerede |
|---|---|---|
| Yayınlandı | **v1.3.0** (2026-09-27) | `CHANGELOG.md` → `## [1.3.0]` |
| Önceki | v1.2.7 (2026-09-21) | `CHANGELOG.md` → `## [1.2.7]` |
| Makine katmanı / repo araçları (`.vsix` içinde değil) | secret safety net, plugin senkronizasyonu, hijyen | `CHANGELOG.md` → `Appendix` |
| Sıradaki hedef | v1.4.0 (aşağıda) |

**Değişmez çerçeve:** 4 katmanlı savunma (ADR-001), `<10ms` hızlı koruma bütçesi ve
aşağıdaki anti-hedefler. Bir fikir bu çerçeveyi ihlal ediyorsa fikir değildir.

---

## 0. Kesim Sonrası Kalan Madde

- [ ] **Sürüm numarası ritmi — karar bekliyor.** v1.3.0 birden fazla commit'i
      biriktirdikten sonra kesildi. İki seçenek: her davranış değişikliği kendi
      sürümünü ister (şeffaf ama pahalı: her değişiklik paketleme, doğrulama ve
      release demek), yoksa değişiklikler birikir (ucuz ama sürüm notu yazmak
      giderek zorlaşır — 1.3.0'ın Upgrade Notes bölümü bu yüzden uzun).
      Şu an ikincisi uygulanıyor. Bu bir ürün kararı, teknik bir engel değil:
      benim varsayımım, kullanıcının isteğidir.

---

## 1. Intent Classifier Follow-Up'ları (v1.4.0 adayı)

- [ ] **4. mod eklenmeli mi?** Aday: `test` (yalnızca test yaz/sar, üretim koduna dokunma)
      ve `explain` (kod oku, hiçbir şey değiştirme). Karar ölçütü: yönlendirme
      direktifi gerçekten farklı davranış üretiyor mu, yoksa sadece isim mi değişiyor?
      Fark üretmiyorsa eklenmemeli — üç moddan fazlası modelin değil prompt'un
      seçeneğidir.
- [ ] **Kapsam genişletme artık veri ister, tahmin değil.** Elle etiketlenmiş korpus
      (`tests/fixtures/intent-corpus.txt`, 32 madde, %100 gate) regresyonu yakalar ama
      gerçek kullanımı temsil etmez — canlı log prompt içermiyor. Sinyal eklerken
      önce korpusa, sonra gerçek bir oturumda gözle doğrulamak gerekiyor; bu yüzden
      her yeni sinyal için "hangi cümle bunu kandırırdı?" sorusu korpusa girmeli.

---

## 2. Pre-Hook Architecture Whisperer (v1.4.0 adayı)

Amaç: agent kodu yazmadan **önce** aktif katman sınırlarını ve mimari kuralları
prompt bağlamına sokmak. Kanal kararı verildi (`ARCHITECTURE` 3.3.1 → `CHANGELOG`
`[Unreleased]`): fısıltı ayrı bir kanal değil, kendi `RULE_ID`'li bir WARN kuralıdır.

- [ ] **Kuralı yaz:** `ARCH_CONTEXT` (WARN). İçerik kaynağı hazır: `.gravityguard.json`
      → `layers`, `testEvidence.sourceRoots`, `complexity` bloğu. Fısıltı bu dosyadan
      okunmalı, hard-code edilmemeli.
- [ ] **Boyut sınırı:** fısıltı her tool-call'de tekrar edilirse prompt şişer. Sadece
      katman ihlali *riski* taşıyan hedefler için (yeni dosya, yeni import, hedef dizin
      `layers` içinde) gönderilmeli.
- [ ] **Kapsam tuzağı:** fısıltı hiçbir zaman bir BLOCK kararının tek taşıyıcısı
      olamaz (Anti-Goal 5). `G4` engellemeye devam ederken `ARCH_CONTEXT` yalnızca
      bağlam verir.

## 2.1 Complexity Heuristics — Yeni Kural Eklemeden Önce Ölçüm (v1.4.0 adayı)

Mevcut adaylar: forwarding wrapper katmanı, tek implementasyonlu soyutlama,
bağımlılık artışı (dependency creep).

- [ ] **Süreç kuralı (artık bağlayıcı):** her yeni heuristik, `CHANGELOG`'daki
      kalibrasyon yöntemiyle önce gerçel korpusta ölçülmek zorunda —
      11 repo, son 400 commit, 6.404 üretim dosya-yazımı — ve **ölçülen fire rate'i
      ile birlikte** sevk edilmeli. Fire rate'i bilinmeyen bir heuristik, tahmin
      değil sitedir. (OE_SPIKE bu yüzden 1,27% ölçümüyle değiştirilmedi.)
- [ ] Her aday için ayrıca: false-positive örneği (gerçek geçmişten) ve
      true-positive örneği (gerçek geçmişten) CHANGELOG'da gösterilmeli.
- [ ] `dependency creep` için sınır: `package.json` / `requirements.txt` farkı
      hook'un `added_text`inde görünür, bu yüzden uygulanabilir; ancak yeni bir
      bağımlılığın "küçük bir fonksiyon için mi" olduğunu bilmek statik olarak
      mümkün değil — bu kural kaçınılmaz olarak spekülatiftir ve **WARN** olmalı.

## 2.2 `run_command` Mutation Detection (P3-02)

- [ ] Dar ön filtre: `Remove-Item`, `del`, `rmdir`, `rm`, `move`, `Move-Item`,
      `Set-Content`, `Out-File`, `Add-Content`.
- [ ] **Her terminal komutunu derin analiz etme.** Fast-path izin listesi:
      `git status/diff/log/show`, `python -c`, `blender --background --python`,
      `npm`, `pytest`.
- [ ] **Bypass'in hâlâ mümkün olduğu açıkça yazılacak**: `python x.py` içinde
      `os.remove`, `blender --python` script'leri. Bu kural gözle görünür yolları
      kapatır, hepsini değil. Vaat edilenden azını vaat et.
- [ ] Performans **gerçek bir kodlama oturumunda** ölçülecek — bu repo'nun log'u
      değil: kayıtlı ölçüm, oturumun kendi tanıklığıyla (`git ~%30,7`,
      keyfi Python/Blender çalıştırma ~%28,5, dosya mutasyonu ~%2`) teşhis
      komutlarıyla kirlenmiş.
- [ ] Karar noktası: `run_command` hook'ta `args.command` olarak mı geliyor, yoksa
      ayrı mı? Doğrulanmadan yazılmamalı — 1.2.5'te hatırlanıldığı gibi hook'un
      payload şeması tahminle değil, ölçümle konuşulmalı.

## 2.3 Controlled Test Maintenance Mode (P3-01)

- [ ] Kullanıcı bilinçli olarak test bakımını yetkilendirebilecek; yalnızca
      **G2** bu mod aktifken gevşeyecek.
- [ ] **Yapay zeka bu yetkiyi kendine verememeli.** Aksi halde koruma değil, tavsiye olur.
- [ ] **Geniş bypass olmayacak** — sadece test dosyalarında, sadece onay süresince.
- [ ] **Yetkilendirme mekanizması hâlâ karar bekliyor** ve seçenekler daralmış:
      - `.gravityguard.json` → teknik olarak kolay ama ajan tarafından yazılabilir
        (**güvenlik sınırı değildir**).
      - Ortam değişkeni → pratikte imkânsız: Antigravity zaten çalışıyor, env
        değişkenleri süreç başında okunuyor.
      - Kalan gerçekçi yol: kullanıcının **kendi terminalinde** çalıştırdığı bir
        komutun tek seferlik bir jeton yazması ve hook'un o jetonu okuması
        (kısa ömürlü, tek kullanımlık, kullanıcı komut isteminde görünür).
        Uygulanabilirliği doğrulanmadan karar verilmeyecek.
- [ ] Not: G2 şu anda test silme, yeniden adlandırma, `.skip` ve testi
      `archive/`'a taşımayı engelliyor ve `# srp: bypass` benzeri bir çıkış yolu yok.

---

## 3. Borç Kaydı — **boş**

Kayıtta borç kalmadı. Yedi maddenin akıbeti:

| # | Borç | Kapanış |
|---|---|---|
| 1 | Classifier heuristiği, düşük güvende tahmin | **düzeltildi** — onay akışı + 32 maddelik korpus |
| 2 | Engine'in iki kopyası, isim ayrışmış, manifestler sürümlenmemiş | **düzeltildi** — tek isim, `plugin/hooks.json` + `plugin.json` depoda, senkron listesi tek yerde |
| 3 | `loss-guard`'ın web'a özgü kontrolleri | **ölçüldü, hata değil** — her kontrol kendi kapısında; Python repo'da `[]` döner, maliyeti mikrosaniye |
| 4 | Boş `.gravityguard/runtime/` dizinleri | **ölçüldü, hata değil** — motorun çalışma zamanı durum dizini; silmek hiçbir şey değiştirmiyor |
| 5 | CI yok | **düzeltildi** — üç platformlu Actions, ilk koşu yeşil |
| 6 | `reason` kanalı belirsizliği | **karara bağlandı** — fısıltı ayrı kanal değil, WARN kuralı |
| 7 | T1'in testsiz projeye sürekli uyarısı | **düzeltildi** — test altyapısı ön koşulu + kapatma anahtarı |

Kanıtlar ve ölçümler: `CHANGELOG.md` → `[Unreleased]`. Yeni borç buraya girmez —
ya düzeltilir ya da (3 ve 4'te olduğu gibi) ölçülüp hata olmadığı kanıtlanır.

---

## 4. Anti-Hedefler (değişmez — bir maddeyi açmak için gerekçe yazılmalı)

To maintain sub-10ms gatekeeping latency and prevent catastrophic scope creep, GravityGuard explicitly rejects the following product directions:

### ❌ Anti-Goal 1: Becoming a SonarQube / CodeQL Alternative
- **Why**: SonarQube, Semgrep, and CodeQL are heavy, asynchronous, whole-repository static analysis platforms evaluating cognitive complexity, code duplication, CVE vulnerabilities, and deep inter-procedural dataflow taint. Attempting to replicate this inside an AI tool-interception hook introduces massive latency, clutters prompt feedback with low-priority stylistic nits, and duplicates decades of solved compiler engineering.
- **Enforcement**: Deep static governance belongs strictly to Ring 4 (CI/CD Quality Gates), not GravityGuard.

### ❌ Anti-Goal 2: Heavy In-Hook AST & Cross-File Taint Tracking
- **Why**: The synchronous `PreToolUse` fast guard path operates under a strict **< 10ms execution budget** (measured typical: 0.1ms - 2ms). Running full cross-file dependency graph resolution or global symbol tables in Tier 1 would cause noticeable agent stuttering and prompt developers to bypass the gatekeeper.
- **Enforcement**: Fast guard checks must remain localized to ephemeral tool diffs and lightweight regex/shallow AST checks.

### ❌ Anti-Goal 3: Code Formatting & Stylistic Linting
- **Why**: Line lengths, trailing commas, indentation, and variable naming styles are solved deterministically by existing formatters (`Prettier`, `Ruff format`, `Black`). GravityGuard must not warn or block on superficial formatting matters.

### ❌ Anti-Goal 4: Replacing Behavioral Test Execution
- **Why**: Static code inspection (AST/regex) can verify structural presence (e.g. T1 test file existence, T2 assertion counts, T3 symbol names), but can **never** verify behavioral correctness or runtime contracts. GravityGuard verifies test evidence presence, but defers behavioral proof to native test runners (`vitest`, `pytest`).

### ❌ Anti-Goal 5: Autonomous AI Self-Exemption
- **Why**: An AI agent must never be permitted to weaken or bypass blocking integrity rules (`G0`, `G1`, `G2`, `G4`) autonomously through synthetic escape comments or self-authorizing config flags. A guard that an agent can talk itself out of is not a security boundary.
- **Consequence for the work in this file**: `srp: allow-monolith` and the `complexity` block are deliberately scoped to **WARN-only** rules. Extending either to a BLOCK rule re-opens this anti-goal and must be argued explicitly, not assumed.

### ❌ Anti-Goal 6: Telemetry, Cloud, or "Just Ask the Model"
- **Why**: A local gatekeeper that phones home stops being a boundary, and a heuristic that is delegated to an LLM stops being deterministic. The intent classifier exists *because* the same prompt instruction was previously the classifier, and the same reasoning applies to every other decision.
- **Enforcement**: No network call on the Tier 1 path. The prompt enhancer's gateway is optional by design and its offline composer is a first-class path, not a degraded one.
