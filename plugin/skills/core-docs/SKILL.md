---
name: core-docs
description: Use when starting, scaffolding, creating, or planning a new project, OR whenever pushing code to Git (git push), publishing to GitHub, or syncing a repo (e.g. "projeye başlayalım", "yeni proje oluştur", "push yap", "gite yükle", "repo güncelle", "core docs kur"). Automatically scaffolds or updates the mandatory 9 core documentation files (README, ARCHITECTURE, DECISIONS, ROADMAP, CHANGELOG, KNOWN_ISSUES, AGENTS, LICENSE, DESIGN) in project root following the 200-line anti-bloat standard. Prohibits brain/ in project root; establishes SecondBrain Obsidian as the single source of truth.
---

# 📜 Core Docs Standardı (Proje Kökü: 9 Temel Dosya | Tek Kaynak: SecondBrain Obsidian)

Bu beceri iki kritik aşamada devreye girer:

1. **Yeni Proje Başlatma:** Kullanıcı yeni bir projeye başlandığını belirttiğinde (*"Yeni bir projeye başlıyoruz"*, *"Yeni proje oluştur"*, *"Projeye başla"* vb.), derin kodlamaya geçmeden önce.
2. **Git Push & Yükleme Kapısı (Pre-Push Documentation Gate):** Git'e herhangi bir `push` yapılacağı veya bir repo GitHub'a yükleneceği zaman (*"push yap"*, *"gite yükle"*, *"commit ve push"* vb.).

---

## 🔄 Pre-Push Dokümantasyon ve Senkronizasyon Kuralı (Mandatory Pre-Push Gate)

Git'e `push` yapılmadan önce **HER PROJEDE** şu kontrol mekanizması işletilir:

- **Eğer Belgeler Yoksa:** Proje kökündeki 9 temel dokümandan eksik olanlar (`README.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `ROADMAP.md`, `CHANGELOG.md`, `KNOWN_ISSUES.md`, `AGENTS.md`, `LICENSE`, `DESIGN.md`) **otomatik ve eksiksiz olarak oluşturulur**. Proje kökünde ASLA `brain/` veya içi boş klasör oluşturulmaz!
- **Kesin Kural (Proje Kökünde Plan & Brain Yasağı):** Kök dizinde asla `PLAN.md`, `TASK.md` veya `brain/` klasörü bulunamaz! Tüm planlar, görevler ve operasyonel zeka için **TEK KAYNAK (Single Source of Truth):** SecondBrain Obsidian kasasındaki ilgili proje dizinidir (`SecondBrain/obsidian/projects/<Proje>/`).
- **Eğer Güncel Değilse:** Yapılan son geliştirmeler, çözülen veya yeni tespit edilen sorunlar ve alınan kararlar doğrultusunda ilgili belgeler (`CHANGELOG.md`'ye sürüm/kayıt, `DECISIONS.md`'ye yeni ADR, `KNOWN_ISSUES.md`'ye açık kısıtlamalar/çözülen bilinen sorunlar, `README.md` ve `ROADMAP.md` durumları) **derhal güncellenir**.
- Güncellenen ve oluşturulan belgeler commite dahil edildikten sonra `git push` yürütülür.

---

## 🏛️ PROJE KÖKÜNDEKİ 9 TEMEL DOSYA

Proje kökü insan geliştiriciye ve kamuoyuna açık temiz vitrindir. Hiçbir doküman dosyası 200 satırı aşamaz (SRP & Anti-Bloat):

1. **`README.md` (Brifing & Vitrin — Max 50 satır)**:
   - Projenin tek cümlelik misyonu, teknoloji rozetleri (Shields.io) ve durum bilgisi.
   - **Görsel Mimari / İş Akışı SVG Zorunluluğu:** Projeyi kristal netlikte anlatan görsel iş akışı diyagramı (`docs/*.svg` veya Mermaid).
   - Hızlı Başlangıç (3 temel komut: install, dev, test) ve dokümantasyon bağlantıları.

2. **`ARCHITECTURE.md` (Mekan, Katman & Tip Güvenliği Mimarisi — Max 80 satır)**:
   - Katmanlar: `presentation/` (UI), `domain/` (iş mantığı), `infrastructure/` (ağ/veri).
   - Katı SRP Kuralı: 1 Dosya = 1 Sorumluluk.
   - **TypeScript-First & Zod:** Tip güvenli kod ve dış veri/ortam değişkeni doğrulaması.

3. **`DECISIONS.md` (Mimari Karar Kayıtları / ADR — Max 150 satır)**:
   - Projede alınan tüm stratejik, kütüphane ve mimari kararların (Architecture Decision Records) değişmez append-only tarihçesi.
   - Format: Karar No, Tarih, Durum (Kabul Edildi / Geçersiz Kılındı), Bağlam, Alınan Karar, Elenen Alternatifler, Sonuçlar.

4. **`ROADMAP.md` (Gelecek & Makro Kilometre Taşları — Max 50 satır)**:
   - Yalnızca makro sürüm aşamaları ve vizyon: `v1.0 (MVP/Tamamlanan)`, `v1.1 (Mevcut Sürüm)`, `v2.0 (Gelecek Vizyon)`.
   - Asla günlük mini sprint görevleriyle şişirilmez.

5. **`CHANGELOG.md` (Geçmiş & Sürüm Tarihçesi)**:
   - **Keep a Changelog** ve **Semantic Versioning (SemVer)** standardı (`Added`, `Changed`, `Fixed`, `Removed`).

6. **`KNOWN_ISSUES.md` (Bilinen Sorunlar, Kısıtlamalar & Geçici Çözümler — Max 100 satır)**:
   - Projede bilinen ancak henüz kalıcı olarak çözülmemiş hatalar, platform/motor kısıtlamaları, teknik borçlar (tech debt) ve uygulanan geçici çözümler (workarounds).
   - Format: Sorun ID (`[ISSUE-01]`), Durum (`Açık` / `Workaround Var` / `Çözüldü`), Etki Alanı, Kök Neden, Geçici Çözüm (Workaround) ve Planlanan Kalıcı Çözüm.
   - Hem geliştiricinin hem de AI ajanlarının aynı tuzağa tekrar düşmesini engeller.

7. **`AGENTS.md` (Ajan Anayasası & Sınırları — Max 100 satır)**:
   - Ajan çalışma kuralları, dokunulmaz sınırlar, mock veri üretme yasağı ve Definition of Done (DoD).

8. **`LICENSE` (GNU General Public License v3.0 - GPL-3.0)**:
   - **ZORUNLU LİSANS:** Varsayılan lisans daima **GNU General Public License v3.0 (GPL-3.0)** tam metnidir.

9. **`DESIGN.md` (Tasarım Sistemi & UI Drift Kalkanı — Arayüz Varsa Zorunlu)**:
   - Web, Mobil, Masaüstü GUI, Godot/Oyun UI olan her projede ZORUNLUDUR (Renk paleti, tipografi, spacing, bileşen kuralları). Saf CLI ve arka plan kütüphanelerinde muaf tutulabilir.

---


## ⚡ OTONOM İNİSİYATİF: Otomatik Karar & Kural Yakalama Protokolü (Autonomous Invariant Capture)

Kullanıcının açıkça *"Bunu kaydet"*, *"Not al"* demesini **BEKLEMEKSİZİN**:
1. Kullanıcı projeyle ilgili bir kural, mimari tercih veya kısıtlama belirttiğinde (Örn: *"Bundan sonra X yerine Y kullanalım"*, *"Z klasörüne dokunma"*, *"Şu hataya dikkat et"*), cevabını tamamlamadan önce **KENDİLİĞİNDEN İNİSİYATİF ALARAK** projenin `KNOWLEDGE.md` dosyasına yeni bir `### [ADR-xx]` veya `### [GOTCHA-xx]` maddesi ekleyin.
2. Bir iş başarıyla tamamlandığında, `TASKS.md` dosyasındaki ilgili maddeyi `[x]` olarak işaretleyin ve gerekiyorsa `CHANGELOG.md`'ye kısa bir kayıt düşün.

---

## 📁 KÖK KLASÖR VE HAFIZA MİMARİSİ

1. **SecondBrain Obsidian (Tek Kaynak — Single Source of Truth)**:
   - Projelerin kök dizininde `brain/` klasörü tutulmaz.
   - Tüm operasyonel hafıza, oturumlar ve artefaktlar `C:\Users\Halil Emre\Desktop\GitHub\SecondBrain\obsidian\projects\<Proje>\` altında yaşar.
2. **Görsel Kanıtlar (`screenshots/`)**:
   - Yalnızca projede somut ekran görüntüsü veya kayıt alındığında kök `screenshots/` klasörü oluşturulur (Sıfır Boş Klasör İlkesi).
