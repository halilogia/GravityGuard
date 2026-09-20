# GravityGuard — v1.2.6

> Deterministic Architecture Airbag, Secret Leak Airbag & AI Agent Gatekeeper for Antigravity IDE.

[English](#english) | [Türkçe](#türkçe)

[![Antigravity Compatible](https://img.shields.io/badge/Antigravity%20IDE-Compatible-blue.svg)](https://antigravity.google/)
[![Tests](https://img.shields.io/badge/Tests-92%20Passing-brightgreen.svg)]()
[![Core Evaluator](https://img.shields.io/badge/Core%20Benchmark-Avg%200.11ms%20%7C%20p95%200.24ms-blue.svg)]()
[![TypeScript](https://img.shields.io/badge/TypeScript-5.9%20%7C%20ES2022-blue.svg)](https://www.typescriptlang.org/)
[![Python](https://img.shields.io/badge/Python-3.10%2B%20%7C%20Zero%20Dependencies-brightgreen.svg)](https://www.python.org/)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)
[![Local AI First](https://img.shields.io/badge/Local%20AI-9Router%20%7C%20Ollama-orange.svg)]()

**GravityGuard** is an ultra-lightweight, deterministic architectural gatekeeper, secret airbag, and prompt engineering companion built specifically for **Antigravity IDE** and modern autonomous AI coding agents. In development benchmarks, it intercepts AI agent tool-calls with an average in-memory logic execution of `~0.11ms` (p95 `< 0.25ms`), preventing codebase degradation, accidental credential leaks, architectural violations, and silent error masking without adding synchronous developer friction.

---

## English

## Active Rule & Evidence Matrix

GravityGuard operates an ordered, zero-overhead pipeline before any file modification tool call is executed:

| ID | Rule Name | Severity | What It Enforces / Catches |
| :--- | :--- | :--- | :--- |
| **`G0`** | **Secret Leak Guard** | **BLOCK / WARN** | Blocks leaked credentials in diffs (OpenAI, Anthropic/Claude, Gemini, Slack, GitHub tokens, and private keys). Emits audit warnings for raw connection URIs and bearer tokens. Masks all logs. |
| **`G1`** | **Silent Exception Guard** | **BLOCK** | Rejects newly added empty exception blocks (`except: pass`, `except: ...`, `catch {}`). Forces robust error logging or re-raising. |
| **`G2`** | **Test Integrity Guard** | **BLOCK / WARN** | Prevents AI agents from "cheating" tests. Blocks test deletion via frequency counters (`collections.Counter`) and disables trickery (`.skip()`, `xit()`). Emits WARN on `.only()`. |
| **`G3`** | **Compiler Bypass Guard** | **WARN ONLY** | Flags newly introduced linter/compiler suppression pragmas (`# noqa`, `# type: ignore`, `@ts-ignore`, `eslint-disable`). |
| **`G4`** | **Import Matrix Guard** | **BLOCK** | Enforces layer boundaries defined in `.gravityguard.json` (e.g. `ui` forbidden from importing `database`). Supports relative imports and TS side-effects. |
| **`SRP`** | **Single Responsibility** | **BLOCK** | Blocks files mixing raw UI components with HTTP/network calls, or accumulating 4+ major business classes in a god-file. |
| **`OE`** | **Over-Engineering Spike** | **WARN ONLY** | Heuristic warning when small production changes (< 50 LOC) introduce a disproportionate abstraction spike (2+ classes/interfaces). |
| **`ARCH`**| **File Growth Radar** | **WARN ONLY** | Early warning against monolithic file accumulation: triggers on projected LOC >= 1000, additions >= 180 LOC, or creeping growth on 800+ LOC files. Zero blocking. |
| **`T1`** | **Missing Related Test** | **WARN ONLY** | Warns when production code changes without a candidate test file on disk or when candidate test was untouched during the active session. Exemption allowlist for `types`, `constants`, `migrations`, etc. |
| **`T2`** | **Observable Assertion** | **WARN ONLY** | Verifies newly added test cases (`def test_...`, `it(...)`) contain observable assertions (`assert`, `self.assert*`, `pytest.raises`, `expect()`, `.toBe()`, `.toEqual()`). |
| **`T3`** | **Symbol-to-Test Link** | **WARN ONLY** | Verifies that newly added top-level/exported functions or classes appear by name in the candidate test file. Never double-warns if test is absent. |
| **`LINT`**| **Diagnostic Feedback** | **WARN ONLY** | Non-blocking Tier 2 background linters (Ruff, ESLint, Godot) write findings to `.gravityguard/runtime/diagnostics.json`, surfaced on subsequent pre-tool calls (<0.5ms). |

## Key Features

### 🛡️ 1. Deterministic Architectural Gatekeeper
- **High-Confidence Airbags**: Pure in-memory diff evaluation: avg `~0.11ms`, p95 `<0.25ms` (zero subprocess). Total Windows subprocess spawn overhead is `<230ms` and runs fully hidden from the tool-call loop (`CREATE_NO_WINDOW` + `SW_HIDE`, so no console window ever flashes on screen).
- **Intelligent Scale Heuristics**: Distinguishes cohesive single-responsibility files from unmaintainable god-files without relying on arbitrary mechanical line-count blocking.
- **Zero Heavy Dependencies**: Pure standard-library Python validator operating via shallow AST and regex heuristics. Zero compilation overhead.

### ✨ 2. Status Bar Prompt Enhancer (`Ctrl + Alt + E`)
- **Interactive Status Bar Item**: Click `$(sparkle) Prompt Geliştir` on the bottom right or press **`Ctrl + Alt + E`** (`Cmd + Alt + E` on macOS) anywhere in the IDE.
- **Active Selection Aware**: Automatically detects text highlighted in your active editor or prompts via a clean modal input box.
- **Local AI Accelerated**: Communicates with the local 9Router proxy (`http://127.0.0.1:20128`) using fast sub-3s models (`ag/gemini-3.8-flash-low`) with automatic multi-model failover.
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
3. Within 3 seconds, the enhanced defensive specification is copied to your clipboard.
4. Go to Antigravity Chat, press Ctrl + V, and submit!
```

---

## Türkçe

## Aktif Kural ve Kanıt Matrisi

GravityGuard, herhangi bir dosya değiştirme aracı çalıştırılmadan önce sıfır gecikmeli sıralı bir denetim hattı işletir:

| Kural | Adı | Seviye | Ne Yapar / Neyi Yakalar? |
| :--- | :--- | :--- | :--- |
| **`G0`** | **Gizli Veri Hava Yastığı (Secret Leak)** | **ENGELLE / UYAR** | Kod farklarında unutulan API anahtarlarını (OpenAI, Anthropic/Claude, Gemini, Slack, GitHub tokenları, Private Key'ler) engeller. Ham bağlantı adresleri ve Bearer tokenları için uyarı verir. Logları maskeler. |
| **`G1`** | **Sessiz Hata Engelleme (Silent Exception)** | **ENGELLE (BLOCK)** | Yeni eklenen boş `except: pass` ve `catch {}` bloklarını reddeder. Hataların loglanmasını veya fırlatılmasını zorunlu kılar. |
| **`G2`** | **Test Bütünlüğü Koruma (Test Integrity)** | **ENGELLE / UYAR** | Ajanın testleri silmesini (`Counter` ile tam dosya karşılaştırması) ve testleri `.skip()` / `xit()` ile susturmasını engeller. Odaklanmış testlere (`.only()`) karşı uyarır. |
| **`G3`** | **Derleyici Susturma Tespiti (Compiler Bypass)**| **YALNIZCA UYAR** | Yeni eklenen `# noqa`, `# type: ignore`, `@ts-ignore` gibi linter susturmalarını tespit eder ve geliştiriciyi uyarır. |
| **`G4`** | **Katman İthalat Matrisi (Import Matrix)** | **ENGELLE (BLOCK)** | `.gravityguard.json` dosyasında tanımlanan mimari sınırları zorunlu kılar (örn: `ui` doğrudan `database` import edemez). Relative ve side-effect importları destekler. |
| **`SRP`** | **Tek Sorumluluk Koruması (SRP Boundary)** | **ENGELLE (BLOCK)** | Aynı dosyada UI bileşenleri ile Network/HTTP çağrılarının karıştırılmasını veya bir dosyaya 4'ten fazla ana sınıf yığılmasını engeller. |
| **`OE`** | **Aşırı Soyutlama Tespiti (Over-Engineering)** | **YALNIZCA UYAR** | Küçük değişikliklerde (< 50 satır) orantısız biçimde 2 veya daha fazla yeni soyutlama (sınıf/arayüz) eklenmesine karşı YAGNI uyarısı verir. |
| **`ARCH`**| **Dosya Büyüme Radarı (File Growth)** | **YALNIZCA UYAR** | Monolitik dosya birikimine karşı erken uyarı: dosya >= 1000 satır olduğunda, tek seferde >= 180 satır eklendiğinde veya 800+ satırlık dosyaya >= 80 satır eklendiğinde uyarır. Asla engellemez. |
| **`T1`** | **Eksik İlişkili Test (Missing Related Test)** | **YALNIZCA UYAR** | Üretim kodu değiştiğinde diskte aday test dosyası yoksa veya bu oturumda teste dokunulmamışsa uyarır (`types`, `constants`, `migrations` muaf). |
| **`T2`** | **Gözlemlenebilir Assertion (Observable Assertion)**| **YALNIZCA UYAR** | Yeni eklenen test case'lerinin (`def test_...`, `it(...)`) en az bir assertion (`assert`, `self.assert*`, `expect()`, `.toBe()`, `pytest.raises`) içerdiğini doğrular. |
| **`T3`** | **Sembol-Test İlişkisi (Symbol-to-Test Link)** | **YALNIZCA UYAR** | Eklenen/değişen fonksiyon veya sınıf isimlerinin ilgili test dosyasında adıyla geçip geçmediğini kontrol eder. Test yoksa T1 önceliklidir. |
| **`LINT`**| **Statik Linter Bildirimi (Diagnostics)** | **YALNIZCA UYAR** | Arka planda çalışan linter'lar (Ruff, ESLint, Godot) bulgularını `.gravityguard/runtime/diagnostics.json` dosyasına yazar; bir sonraki hook çağrısında yapay zekaya bağlamsal uyarı verilir (<0.5ms). |

## Temel Özellikler

### 🛡️ 1. Deterministik Mimari Bekçi (Gatekeeper)
- **Yüksek Güvenilirlikli Hava Yastığı**: Saf bellek içi mantık denetimlerini ortalama `~0.11 ms` (p95 `< 0.25 ms`) sürede tamamlar.
- **Akıllı Ölçek Analizi**: Yapay zekanın tek dosyaya aşırı sorumluluk yığarak devasa "god-file" oluşturmasını önler. Mekanik satır sınırı koymak yerine semantik sorumluluk dağılımına bakar.
- **Sıfır Harici Bağımlılık**: Saf Python ile yazılmış, AST ve regex tabanlı hafif analiz motoru. Ağır kütüphane veya derleme gerektirmez.


### ✨ 2. Status Bar Prompt Geliştirici (`Ctrl + Alt + E`)
- **Status Bar Erişimi**: Sağ alttaki `✨ Prompt Geliştir` butonuna tıklayın veya dilediğiniz an **`Ctrl + Alt + E`** kısayolunu kullanın.
- **Seçili Metin Algılama**: Editörde fareyle seçtiğiniz kodu/yorumu otomatik olarak algılar; seçim yoksa şık bir girdi kutusu açar.
- **Yerel Yapay Zeka Hızı**: Yerel 9Router altyapısı (`127.0.0.1:20128`) üzerinden ~2-3 saniyelik ultra hızlı modeller (`ag/gemini-3.8-flash-low`) ve otomatik yedek modeller ile çalışır.
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

---

## Proje Dokümantasyonu (Kutsal 6'lı)

Bu depo, standart mühendislik prensiplerine tam uyumlu dokümantasyon seti içerir:

| Dosya | Açıklama |
| :--- | :--- |
| **`README.md`** | Bu belge (Genel bakış, İngilizce/Türkçe kılavuz, hızlı başlangıç). |
| **[`ARCHITECTURE.md`](ARCHITECTURE.md)** | Sistem topolojisi, Mermaid diyagramları, bileşen sınırları ve yaşam döngüleri. |
| **[`ROADMAP.md`](ROADMAP.md)** | Sürüm kilometre taşları (v1.0 -> v2.0) ve planlanan yetenekler. |
| **[`CHANGELOG.md`](CHANGELOG.md)** | Semantik versiyonlama kurallarına göre tüm sürüm değişiklik kayıtları. |
| **[`brain/knowledge.md`](brain/knowledge.md)** | Geliştiriciler ve yapay zeka ajanları için kalıcı mühendislik bilgi tabanı ve değişmezler. |
| **[`LICENSE`](LICENSE)** | GNU General Public License v3.0 (GPL-3.0). |

---

## Lisans

Bu proje [GNU General Public License v3.0](LICENSE) kapsamında lisanslanmıştır.
