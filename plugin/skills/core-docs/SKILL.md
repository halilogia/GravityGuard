---
name: core-docs
description: Use when starting, scaffolding, creating, or planning a new project (e.g. "projeye başlayalım", "yeni proje oluştur", "start project", "projeyi başlatıyoruz", "core docs kur"). Automatically scaffolds the mandatory 8 core documentation files (README, ARCHITECTURE, ROADMAP, CHANGELOG, KNOWLEDGE, TASKS, AGENTS, LICENSE) following the 200-line anti-bloat standard.
---

# 📜 Core Docs (8 Temel Dokümantasyon Standardı ve Kurulumu)

Kullanıcı yeni bir projeye başlandığını belirttiğinde (örneğin: *"Yeni bir projeye başlıyoruz"*, *"Yeni proje oluştur"*, *"Projeye başla"*, *"X projesini başlatıyoruz"* vb.), derin kodlamaya geçmeden önce **OTOMATİK VE EKSİKSİZ OLARAK** aşağıdaki 8 temel dokümanı proje dizininde oluşturun.

> **⚠️ 200 Satır Kuralı (Anti-Bloat):** Her doküman tek bir sorumluluğa (**SRP**) sahiptir ve gereksiz ders kitabı bilgilerinden arındırılmıştır. Hiçbir doküman dosyası 200 satırı aşamaz.

---

## 🏛️ Core Docs Dosya Listesi ve Şablonları

1. **`README.md` (Brifing & Vitrin — Max 50 satır)**:
   - Projenin tek cümlelik misyonu.
   - Teknoloji rozetleri (Shields.io) ve durum bilgisi.
   - Hızlı Başlangıç (3 temel komut: install, dev, test).
   - Dokümantasyon tablosu (diğer 7 çekirdek dosyaya bağlantılar).

2. **`ARCHITECTURE.md` (Mekan & Katman Mimarisi — Max 80 satır)**:
   - Katmanlar: `presentation/` (UI), `domain/` (iş mantığı), `infrastructure/` (ağ/veri).
   - Katı SRP Kuralı: 1 Dosya = 1 Sorumluluk.
   - Veri akışı Mermaid diyagramı.
   - Dokunulmaz sınırlar ve değişmez mimari kurallar.

3. **`ROADMAP.md` (Gelecek & Kilometre Taşları — Max 50 satır)**:
   - Sürüm aşamaları: `v1.0 (MVP/Tamamlanan)`, `v1.1 (Aktif Sprint)`, `v2.0 (Gelecek Vizyon)`.
   - Eylem kontrol listeleri (`- [x]` ve `- [ ]`).

4. **`CHANGELOG.md` (Geçmiş & Sürüm Tarihçesi)**:
   - **Keep a Changelog** ve **Semantic Versioning (SemVer)** standardı.
   - `Added`, `Changed`, `Fixed`, `Removed` başlıkları altında tarihli döküm.

5. **`KNOWLEDGE.md` (Antigravity Kalıcı Hafızası — Max 100 satır)**:
   - Projenin oturumlar arası kalıcı mühendislik hafızası.
   - Tekrarlayan tuzaklar (Gotchas) ve mimari kararlar (ADR).
   - Kural: *"Kanıt yoksa iddia yok."* Her madde kısa, kanıtlı ve neden-sonuç odaklıdır. Asla gizli anahtar/token içermez.

6. **`TASKS.md` (Şimdi & Aktif Görev Takibi — Max 60 satır)**:
   - Bölümler: `## 🚀 Aktif Sprint` (`[/]`), `## ⏳ Backlog` (`[ ]`), `## ✅ Tamamlananlar` (`[x]`).

7. **`AGENTS.md` (Ajan Anayasası & Sınırları — Max 100 satır)**:
   - Nihai amaç ve istenen hissiyat (Vibe).
   - Katı sınırlar (Dokunulmaz klasörler, yasaklı kütüphaneler).
   - Cerrahi kod düzenleme kuralı (`replace_file_content`).
   - Tamamlanma kriteri (Done Definition: test/lint/build komutları).

8. **`LICENSE` (GNU General Public License v3.0 - GPL-3.0)**:
   - **ZORUNLU LİSANS:** Kullanıcının tüm açık kaynak projelerinde varsayılan lisans daima **GNU General Public License v3.0 (GPL-3.0)** tam metnidir. Asla onay almadan değiştirilemez.

---

## 📂 Varsayılan Proje Konumu ve Kurallar

- Açık kaynak projelerin varsayılan dizini: `C:\Users\Halil Emre\Desktop\GitHub\Public\<ProjeAdı>\`
- Core Docs'a ek olarak teknolojiye uygun temiz bir **`.gitignore`** dosyası da eş zamanlı eklenmelidir.

---

## ⚡ OTONOM İNİSİYATİF: Otomatik Karar & Kural Yakalama Protokolü (Autonomous Invariant Capture)

Kullanıcının açıkça *"Bunu kaydet"*, *"Not al"* demesini **BEKLEMEKSİZİN**:
1. Kullanıcı projeyle ilgili bir kural, mimari tercih veya kısıtlama belirttiğinde (Örn: *"Bundan sonra X yerine Y kullanalım"*, *"Z klasörüne dokunma"*, *"Şu hataya dikkat et"*), cevabını tamamlamadan önce **KENDİLİĞİNDEN İNİSİYATİF ALARAK** projenin `KNOWLEDGE.md` dosyasına yeni bir `### [ADR-xx]` veya `### [GOTCHA-xx]` maddesi ekleyin.
2. Bir iş başarıyla tamamlandığında, `TASKS.md` dosyasındaki ilgili maddeyi `[x]` olarak işaretleyin ve gerekiyorsa `CHANGELOG.md`'ye kısa bir kayıt düşün.

---
