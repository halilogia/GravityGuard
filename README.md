# GravityGuard — v1.4.0

> Deterministic Architecture Airbag, Secret Leak Airbag & AI Agent Gatekeeper for Antigravity IDE.

[English](#english) | [Türkçe](#türkçe)

[![Antigravity Compatible](https://img.shields.io/badge/Antigravity%20IDE-Compatible-blue.svg)](https://antigravity.google/)
[![Tests](https://img.shields.io/badge/Engine%20265%20%2B%20TS%2037-Passing-brightgreen.svg)]()
[![Core Evaluator](https://img.shields.io/badge/Core%20Benchmark-Avg%20~0.1ms%20%7C%20p95%20%3C0.5ms-blue.svg)]()
[![TypeScript](https://img.shields.io/badge/TypeScript-5.9%20%7C%20ES2022-blue.svg)](https://www.typescriptlang.org/)
[![Python](https://img.shields.io/badge/Python-3.10%2B%20%7C%20Zero%20Dependencies-brightgreen.svg)](https://www.python.org/)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)
[![Local AI First](https://img.shields.io/badge/Local%20AI%20%7C%20Optional%20Gateway-orange.svg)]()

**GravityGuard** is an ultra-lightweight, deterministic architectural gatekeeper, secret airbag, and prompt engineering companion built specifically for **Antigravity IDE** and modern autonomous AI coding agents. In development benchmarks, it intercepts AI agent tool-calls with an average in-memory logic execution of `~0.1ms` (p95 `< 0.5ms`), preventing codebase degradation, accidental credential leaks, architectural violations, and silent error masking without adding synchronous developer friction. Absolute latency is host- and load-dependent; the number that is held stable is the ratio against the previous release, measured interleaved in the same time slice.

> **Design philosophy — trust the mechanism, not the model.** GravityGuard exists because an AI agent's goodwill cannot be relied upon: *a rule that lives only as prose is a wish.* Every obligation is therefore backed either by an artifact the agent must actually write to disk, or — wherever it can be made deterministic — by an airbag, linter or hook that refuses the operation outright. No initiative, no "trust me"; the gate stays shut until the artifact exists.

---

## English

## Active Rule & Evidence Matrix

GravityGuard operates an ordered, zero-overhead pipeline before any file modification tool call is executed:

| ID | Rule Name | Severity | What It Enforces / Catches |
| :--- | :--- | :--- | :--- |
| **`G0`** | **Secret Leak Guard** | **BLOCK / WARN** | Blocks leaked credentials in diffs (OpenAI — modern and legacy keys, Anthropic/Claude, Gemini, Slack, GitHub tokens, and private keys). Emits audit warnings for raw connection URIs and bearer tokens. Masks all logs. |
| **`G1`** | **Silent Exception Guard** | **BLOCK** | Rejects newly added empty exception blocks (`except: pass`, `except: ...`, `catch {}`). Forces robust error logging or re-raising. |
| **`G2`** | **Test Integrity Guard** | **BLOCK / WARN** | Prevents AI agents from "cheating" tests. Blocks test deletion via frequency counters (`collections.Counter`) and disables trickery (`.skip()`, `xit()`). Emits WARN on `.only()`. |
| **`G3`** | **Compiler Bypass Guard** | **WARN ONLY** | Flags newly introduced linter/compiler suppression pragmas (`# noqa`, `# type: ignore`, `@ts-ignore`, `eslint-disable`). |
| **`G4`** | **Import Matrix Guard** | **BLOCK** | Enforces layer boundaries defined in `.gravityguard.json` (e.g. `ui` forbidden from importing `database`). Supports relative imports and TS side-effects. |
| **`SRP`** | **Single Responsibility** | **BLOCK** | Blocks files mixing raw UI components with HTTP/network calls, or accumulating 4+ major business classes in a god-file. |
| **`OE`** | **Over-Engineering Spike** | **WARN ONLY** | Heuristic warning when small production changes (< 50 LOC, configurable) introduce a disproportionate abstraction spike (2+ classes/interfaces, configurable). |
| **`ARCH`**| **File Growth Radar** | **WARN ONLY** | Early warning against monolithic *accumulation*: fires on the write that crosses 1000 LOC, on additions >= 200 LOC to an existing file, or on creeping growth (800+ LOC file with >= 80 LOC added). A brand-new module, and a file marked `srp: allow-monolith`, are not nagged for their size. Every threshold is tunable per project through the `complexity` block of `.gravityguard.json`. Zero blocking. |
| **`T1`** | **Missing Related Test** | **WARN ONLY** | Warns when production code changes without a candidate test file on disk or when candidate test was untouched during the active session. Exemption allowlist for `types`, `constants`, `migrations`, etc. |
| **`T2`** | **Observable Assertion** | **WARN ONLY** | Verifies newly added test cases (`def test_...`, `it(...)`) contain observable assertions (`assert`, `self.assert*`, `pytest.raises`, `expect()`, `.toBe()`, `.toEqual()`). |
| **`T3`** | **Symbol-to-Test Link** | **WARN ONLY** | Verifies that newly added top-level/exported functions or classes appear by name in the candidate test file. Never double-warns if test is absent. |
| **`LINT`**| **Diagnostic Feedback** | **WARN ONLY** | Non-blocking Tier 2 background linters (Ruff, ESLint, Godot) write findings to `.gravityguard/runtime/diagnostics.json`, surfaced on subsequent pre-tool calls (<0.5ms). |
| **`R1`** | **Independent Review** | **WARN (Stop gate)** | Opt-in. When a governed production file changes, the Stop hook requires process evidence of an independent `code-reviewer` review: an observed MCP invocation, a schema-valid receipt under `.gravityguard/runtime/reviews/`, matching fingerprint + nonce, and a non-stale candidate. A final diff guard also folds in governed code changed out-of-band (e.g. a shell write). It proves a review ran against a specific candidate — not that the review was correct or complete. |

## Key Features

### 🛡️ 1. Deterministic Architectural Gatekeeper
- **High-Confidence Airbags**: Pure in-memory diff evaluation: avg `~0.1ms`, p95 `<0.5ms` (zero subprocess). Running the engine as a Windows subprocess costs a real `python.exe` spawn — measured at a median of ~340–370 ms on this host, and host-dependent — which is why all linting and compiling happens in a hidden background worker (`CREATE_NO_WINDOW` + `SW_HIDE`, so no console window ever flashes on screen) and the synchronous path stays in-memory.
- **Intelligent Scale Heuristics**: Distinguishes cohesive single-responsibility files from unmaintainable god-files without relying on arbitrary mechanical line-count blocking.
- **Zero Heavy Dependencies**: Pure standard-library Python validator operating via shallow AST and regex heuristics. Zero compilation overhead.

### ✨ 2. Status Bar Prompt Enhancer (`Ctrl + Alt + E`)
- **Interactive Status Bar Item**: Click `$(sparkle) Prompt Geliştir` on the bottom right or press **`Ctrl + Alt + E`** (`Cmd + Alt + E` on macOS) anywhere in the IDE.
- **Active Selection Aware**: Automatically detects text highlighted in your active editor or prompts via a clean modal input box.
- **Local Intent Classifier (no LLM)**: Every request is classified locally, in under a millisecond, into **İSTİŞARE** (brainstorm), **UYGULAMA** (build) or **DENETİM / REFACTOR** (audit). Only the selected mode's directive is sent, so the model no longer has to guess what was asked. Override the decision with a `#denetle:`, `#danış:` or `#kodla:` prefix. When the classifier is not confident it *asks* instead of guessing, and a 32-prompt hand-labelled corpus keeps the signals honest across every change.
- **Local AI Accelerated**: Talks to any OpenAI-compatible local gateway (9Router, Ollama, LM Studio, llama.cpp) over `http://127.0.0.1:20128`, with a configurable model cascade and automatic failover. A gateway that is not running is detected immediately instead of being retried per model, and the enhancer then falls back to a deterministic offline brief — the command never fails because a local service is down.
- **Direct Clipboard Integration**: The enhanced prompt is automatically copied to your system clipboard. Simply press **`Ctrl + V`** in the chat panel to instruct the AI with a defensive, production-ready specification.
- **Review in Document**: Includes an optional *"Yeni Belgede Aç"* (Open in New Document) button to inspect or tweak the enhanced prompt before execution.

### 📊 3. Real-Time Live Monitor (Activity Bar Sidebar)
- **Dedicated Sidebar Panel**: Access the GravityGuard dashboard directly from the Activity Bar using the custom shield icon.
- **Live Event Stream**: Real-time visual cards displaying file paths, actions, verdicts, timestamps, and actionable architectural reasons.
- **Live Statistics**: Visual badges tracking **Engellenen (Blocked)** vs. **Onaylanan (Approved)** operations.
- **Dual-Mode Auto Sync**: Seamlessly blends OS filesystem events (`fs.watch`) with a 1.5-second polling heartbeat to ensure zero dropped logs.
- **One-Click Maintenance**: Instant "Yenile" (Refresh) and "Temizle" (Purge Logs) controls.

### 💬 4. Native In-Chat `/enhance` Skill
- Prefer staying in the chat window? Simply type `/enhance <your instruction>` directly into the Antigravity chat box.
- The built-in GravityGuard skill immediately processes your request without opening external windows.


---

## Quick Start

### Installation

1. Clone or copy the repository into your Antigravity / VS Code extensions directory:
   ```bash
   git clone https://github.com/halilogia/GravityGuard.git "C:\Users\<User>\.antigravity-ide\extensions\gravityguard"
   ```
2. Open the directory in a terminal and install build dependencies:
   ```bash
   cd "C:\Users\<User>\.antigravity-ide\extensions\gravityguard"
   npm install
   npm run build
   ```
3. In Antigravity IDE, press `Ctrl + Shift + P` and select **`Developer: Reload Window`**.

### Usage Workflow

```text
1. Press Ctrl + Alt + E (or click ✨ Prompt Geliştir on the Status Bar).
2. Enter your raw instruction (e.g. "Add player inventory websocket sync").
   Prefix it with #denetle: / #danış: / #kodla: to pin the mode yourself.
3. The request is classified locally (no network) and the enhanced defensive
   specification is copied to your clipboard — in seconds with a local gateway,
   instantly in offline template mode.
4. Go to Antigravity Chat, press Ctrl + V, and submit!
```

### Use the guard in Claude Code

The same engine guards Claude Code through a thin adapter in [`plugin/claude-code/`](plugin/claude-code/README.md): `Write` / `Edit` / `MultiEdit` go through the file rules, and the `Stop` hook holds a session until its own test/doc obligations are met. Each session is tracked separately, so parallel sessions never block each other. `Bash` writes are not inspected. Setup is one `settings.json` snippet.

---

## Türkçe

> **Tasarım felsefesi — modele değil, mekanizmaya güven.** GravityGuard, bir yapay zeka ajanının iyi niyetine güvenilemeyeceği için vardır: *yalnızca metin olarak yaşayan bir kural, bir dilektir.* Bu yüzden her yükümlülük ya ajanın gerçekten diske yazmak zorunda olduğu bir artefakta, ya da — deterministik kılınabildiği her yerde — işlemi doğrudan reddeden bir hava yastığına, linter'a veya kancaya (hook) dayanır. İnisiyatif yok, "bana güven" yok; artefakt oluşana kadar kapı kapalı kalır.

## Aktif Kural ve Kanıt Matrisi

GravityGuard, herhangi bir dosya değiştirme aracı çalıştırılmadan önce sıfır gecikmeli sıralı bir denetim hattı işletir:

| Kural | Adı | Seviye | Ne Yapar / Neyi Yakalar? |
| :--- | :--- | :--- | :--- |
| **`G0`** | **Gizli Veri Hava Yastığı (Secret Leak)** | **ENGELLE / UYAR** | Kod farklarında unutulan API anahtarlarını (OpenAI — modern ve eski biçim, Anthropic/Claude, Gemini, Slack, GitHub tokenları, Private Key'ler) engeller. Ham bağlantı adresleri ve Bearer tokenları için uyarı verir. Logları maskeler. |
| **`G1`** | **Sessiz Hata Engelleme (Silent Exception)** | **ENGELLE (BLOCK)** | Yeni eklenen boş `except: pass` ve `catch {}` bloklarını reddeder. Hataların loglanmasını veya fırlatılmasını zorunlu kılar. |
| **`G2`** | **Test Bütünlüğü Koruma (Test Integrity)** | **ENGELLE / UYAR** | Ajanın testleri silmesini (`Counter` ile tam dosya karşılaştırması) ve testleri `.skip()` / `xit()` ile susturmasını engeller. Odaklanmış testlere (`.only()`) karşı uyarır. |
| **`G3`** | **Derleyici Susturma Tespiti (Compiler Bypass)**| **YALNIZCA UYAR** | Yeni eklenen `# noqa`, `# type: ignore`, `@ts-ignore` gibi linter susturmalarını tespit eder ve geliştiriciyi uyarır. |
| **`G4`** | **Katman İthalat Matrisi (Import Matrix)** | **ENGELLE (BLOCK)** | `.gravityguard.json` dosyasında tanımlanan mimari sınırları zorunlu kılar (örn: `ui` doğrudan `database` import edemez). Relative ve side-effect importları destekler. |
| **`SRP`** | **Tek Sorumluluk Koruması (SRP Boundary)** | **ENGELLE (BLOCK)** | Aynı dosyada UI bileşenleri ile Network/HTTP çağrılarının karıştırılmasını veya bir dosyaya 4'ten fazla ana sınıf yığılmasını engeller. |
| **`OE`** | **Aşırı Soyutlama Tespiti (Over-Engineering)** | **YALNIZCA UYAR** | Küçük değişikliklerde (< 50 satır, ayarlanabilir) orantısız biçimde 2 veya daha fazla yeni soyutlama (sınıf/arayüz, ayarlanabilir) eklenmesine karşı YAGNI uyarısı verir. |
| **`ARCH`**| **Dosya Büyüme Radarı (File Growth)** | **YALNIZCA UYAR** | Monolitik *birikime* karşı erken uyarı: 1000 satır sınırını geçiren yazma, mevcut dosyaya tek seferde >= 200 satır ekleme veya 800+ satırlık dosyaya >= 80 satır ekleme. Yeni oluşturulan modül ve `srp: allow-monolith` işaretli dosya boyutlarından dolayı uyarılmaz. Tüm eşikler `.gravityguard.json` içindeki `complexity` bloğuyla projeye özel ayarlanabilir. Asla engellemez. |
| **`T1`** | **Eksik İlişkili Test (Missing Related Test)** | **YALNIZCA UYAR** | Üretim kodu değiştiğinde diskte aday test dosyası yoksa veya bu oturumda teste dokunulmamışsa uyarır (`types`, `constants`, `migrations` muaf). |
| **`T2`** | **Gözlemlenebilir Assertion (Observable Assertion)**| **YALNIZCA UYAR** | Yeni eklenen test case'lerinin (`def test_...`, `it(...)`) en az bir assertion (`assert`, `self.assert*`, `expect()`, `.toBe()`, `pytest.raises`) içerdiğini doğrular. |
| **`T3`** | **Sembol-Test İlişkisi (Symbol-to-Test Link)** | **YALNIZCA UYAR** | Eklenen/değişen fonksiyon veya sınıf isimlerinin ilgili test dosyasında adıyla geçip geçmediğini kontrol eder. Test yoksa T1 önceliklidir. |
| **`LINT`**| **Statik Linter Bildirimi (Diagnostics)** | **YALNIZCA UYAR** | Arka planda çalışan linter'lar (Ruff, ESLint, Godot) bulgularını `.gravityguard/runtime/diagnostics.json` dosyasına yazar; bir sonraki hook çağrısında yapay zekaya bağlamsal uyarı verilir (<0.5ms). |
| **`R1`** | **Bağımsız İnceleme (Independent Review)** | **UYAR (Stop kapısı)** | Opt-in. Yönetilen üretim kodu değiştiğinde Stop kapısı bağımsız bir `code-reviewer` incelemesinin süreç kanıtını ister: gözlenen MCP çağrısı, `.gravityguard/runtime/reviews/` altında şema-geçerli makbuz, eşleşen fingerprint + nonce ve bayat olmayan aday. Ayrıca bir final diff guard, kanca dışı (ör. kabuk yazımı) değişen yönetilen kodu da katar. İncelemenin belirli bir adaya karşı yapıldığını kanıtlar; incelemenin doğru ya da eksiksiz olduğunu kanıtlamaz. |

## Temel Özellikler

### 🛡️ 1. Deterministik Mimari Bekçi (Gatekeeper)
- **Yüksek Güvenilirlikli Hava Yastığı**: Saf bellek içi mantık denetimlerini ortalama `~0.1 ms` (p95 `< 0.5 ms`) sürede tamamlar (alt süreç yok). Motoru Windows alt süreç olarak çalıştırmak gerçek bir `python.exe` doğurma maliyeti demek — bu makinede medyan ~340–370 ms ölçüldü ve makineye bağlıdır — bu yüzden tüm lint/derleme işi gizli bir arka plan işçisinde çalışır (`CREATE_NO_WINDOW` + `SW_HIDE`, ekranda hiç konsol penceresi açılmaz) ve senkron yol bellek içi kalır.
- **Akıllı Ölçek Analizi**: Yapay zekanın tek dosyaya aşırı sorumluluk yığarak devasa "god-file" oluşturmasını önler. Mekanik satır sınırı koymak yerine semantik sorumluluk dağılımına bakar.
- **Sıfır Harici Bağımlılık**: Saf Python ile yazılmış, AST ve regex tabanlı hafif analiz motoru. Ağır kütüphane veya derleme gerektirmez.


### ✨ 2. Status Bar Prompt Geliştirici (`Ctrl + Alt + E`)
- **Status Bar Erişimi**: Sağ alttaki `✨ Prompt Geliştir` butonuna tıklayın veya dilediğiniz an **`Ctrl + Alt + E`** kısayolunu kullanın.
- **Seçili Metin Algılama**: Editörde fareyle seçtiğiniz kodu/yorumu otomatik olarak algılar; seçim yoksa şık bir girdi kutusu açar.
- **Yerel Niyet Sınıflandırıcı (LLM'siz)**: Her istek yerelde, 1 milisaniyenin altında **İSTİŞARE**, **UYGULAMA** veya **DENETİM / REFACTOR** modlarından birine sınıflandırılır. Modele yalnızca seçilen modun direktifi gönderilir; böylece model ne istendiğini kendisi tahmin etmez. Kararı `#denetle:`, `#danış:` veya `#kodla:` önekiyle siz geçersiz kılabilirsiniz. Sınıflandırıcı emin değilse tahmin etmez, **soruyor** (tek tıkla seçim, tahmin varsayılan); 32 maddelik elle etiketlenmiş korpus ise her değişiklikte sinyallerin doğru kaldığını garanti eder.
- **Yerel Yapay Zeka Hızı**: 9Router, Ollama, LM Studio veya llama.cpp gibi herhangi bir OpenAI uyumlu yerel ağ geçidiyle (`127.0.0.1:20128`) çalışır; model kademeleri ayarlanabilir, hata durumunda otomatik yedek modele geçilir. Geçid kapalıysa bu durum model modeline kadar yeniden denemeden anlaşılır ve geliştirici, yerel hizmet kapalıyken de komutun çalışmaya devam etmesini sağlayan belirlenimci (deterministik) çevrimdışı şablon moduna düşer.
- **Doğrudan Panoya Kopyalama**: Geliştirilen mimari şartname doğrudan Windows/macOS panonuza kopyalanır (`Ctrl+C` yapılmış gibi). Chat kutusuna gidip **`Ctrl + V`** yapmanız yeterlidir.
- **Ayrı Belgede İnceleme**: İsterseniz gelen bildirimdeki *"Yeni Belgede Aç"* butonuna basarak oluşturulan promptu ayrı bir sekmede düzenleyebilirsiniz.

### 📊 3. Canlı Güvenlik Paneli (Activity Bar)
- **Özel Kenar Çubuğu Paneli**: Sol Activity Bar üzerindeki kalkan simgesine tıklayarak canlı denetim paneline erişin.
- **Gerçek Zamanlı Günlük Akışı**: Engellenen ve onaylanan tüm dosya hareketleri, gerekçeleri ve zaman damgalarıyla anlık listelenir.
- **Canlı İstatistikler**: Engellenen ve onaylanan işlemleri sayan görsel sayaç kartları.
- **Çift Modlu Canlı Senkronizasyon**: Dosya izleyici (`fs.watch`) ile 1.5 saniyelik aktif heartbeat mekanizmasını birleştirerek hiçbir günlüğü kaçırmaz.
- **Tek Tıkla Temizleme**: "Yenile" ve "Temizle" butonlarıyla günlükleri anında sıfırlayabilme.

### 💬 4. Sohbet İçi Yerel `/enhance` Yeteneği
- Harici kutucuk açmak istemeyenler için: Doğrudan Antigravity Chat kutusuna `/enhance <isteğiniz>` yazarak sohbet penceresi içinden de prompt geliştirebilirsiniz.

### 🤖 5. Claude Code'da Kullanım
- Aynı motor, [`plugin/claude-code/`](plugin/claude-code/README.md) altındaki ince bir adaptörle Claude Code'u da korur: `Write` / `Edit` / `MultiEdit` dosya kurallarından geçer, `Stop` kancası oturumu kendi test/doküman yükümlülükleri bitene kadar tutar. Her oturum ayrı izlenir; paralel oturumlar birbirini engellemez. `Bash` ile yazılan dosyalar denetlenmez. Kurulum tek bir `settings.json` parçasıdır.

---

## Proje Dokümantasyonu (Kutsal 6'lı)

Bu depo, standart mühendislik prensiplerine tam uyumlu dokümantasyon seti içerir:

| Dosya | Açıklama |
| :--- | :--- |
| **`README.md`** | Bu belge (Genel bakış, İngilizce/Türkçe kılavuz, hızlı başlangıç). |
| **[`ARCHITECTURE.md`](ARCHITECTURE.md)** | Sistem topolojisi, Mermaid diyagramları, bileşen sınırları ve yaşam döngüleri. |
| **[`ROADMAP.md`](ROADMAP.md)** | **Yalnızca yapılmamış iş**: sıradaki sürüm kesimi, açık borç ve sınırlar, anti-hedefler. Tamamlanan her şey `CHANGELOG.md`'dedir. |
| **[`CHANGELOG.md`](CHANGELOG.md)** | Semantik versiyonlama kurallarına göre tüm sürüm değişiklik kayıtları, ölçümler ve gerekçeler; sonunda repo/makine katmanı ek'i. |
| **[`docs/KNOWLEDGE.md`](docs/KNOWLEDGE.md)** | Geliştiriciler ve yapay zeka ajanları için kalıcı mühendislik bilgi tabanı, değişmezler ve "yeni heuristik nasıl sevk edilir" kuralları. |
| **[`LICENSE`](LICENSE)** | GNU General Public License v3.0 (GPL-3.0). |

---

## Lisans

Bu proje [GNU General Public License v3.0](LICENSE) kapsamında lisanslanmıştır.
