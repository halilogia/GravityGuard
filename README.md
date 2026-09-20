# GravityGuard — v1.0.0

> Deterministic Architecture Airbag & AI Agent Gatekeeper for Antigravity IDE.

[English](#english) | [Türkçe](#türkçe)

[![Antigravity Compatible](https://img.shields.io/badge/Antigravity%20IDE-Compatible-blue.svg)](https://antigravity.google/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.9%20%7C%20ES2022-blue.svg)](https://www.typescriptlang.org/)
[![Python](https://img.shields.io/badge/Python-3.10%2B%20%7C%20Zero%20Dependencies-brightgreen.svg)](https://www.python.org/)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)
[![Local AI First](https://img.shields.io/badge/Local%20AI-9Router%20%7C%20Ollama-orange.svg)]()

**GravityGuard** is a lightweight, deterministic architectural gatekeeper and prompt engineering companion built specifically for **Antigravity IDE** and modern AI coding agents. It prevents autonomous AI agents from degrading codebase quality, violating architectural layer boundaries, creating massive god-files, and breaking the Single Responsibility Principle (SRP).

It also features an ultra-low-latency **Status Bar Prompt Enhancer** that expands raw developer requests into defensive, architecture-preserving technical specifications using local AI models in seconds.

---

## English

## Key Features

### 🛡️ 1. Deterministic Architectural Gatekeeper
- **Single Responsibility Principle (SRP) Enforcement**: Scans code modifications in `< 50ms` to prevent multi-responsibility anti-patterns (such as mixing raw UI rendering with HTTP/Network requests in a single file).
- **Intelligent Scale Heuristics**: Distinguishes cohesive single-responsibility files from unmaintainable god-files without relying on arbitrary mechanical line-count blocking.
- **Zero Heavy Dependencies**: Pure Python validator operating via shallow AST and regex heuristics. Zero compilation overhead.

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
   git clone https://github.com/halilemre/GravityGuard.git "C:\Users\<User>\.antigravity-ide\extensions\gravityguard"
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

## Temel Özellikler

### 🛡️ 1. Deterministik Mimari Bekçi (Gatekeeper)
- **Tek Sorumluluk Prensibi (SRP) Koruması**: Kod değişikliklerini 50 milisaniyenin altında denetler. Ham arayüz (UI) bileşenleri ile ağ (Network/HTTP) işlemlerinin aynı dosyada karıştırılmasını engeller.
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
