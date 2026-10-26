# 🧠 GravityGuard Mühendislik Hafızası (KNOWLEDGE.md)

Bu dosya, GravityGuard deterministik koruma kalkanının mimari karar kayıtlarını (ADR) ve teknik tuzaklarını (Gotchas) belgeler.

---

## 🏛️ Mimari Karar Kayıtları (ADR)

### [ADR-01] Deterministik Pre-Tool Hook Koruması
- **Karar:** Yapay zeka ajanlarının dosya yazma ve komut çalıştırma araçları, disk ve işletim sistemine erişmeden önce Node.js / TypeScript tabanlı kancalarla (hooks) kesilir.
- **Gerekçe:** LLM çıktısı üretildikten sonra değil, diske yazılmadan önce (Pre-Tool) sızıntıları (API anahtarları, gizli tokenlar), yutulan istisnaları (silent catch) ve devre dışı bırakılan testleri engellemek.

### [ADR-02] Sıfır Sahte Pozitif Prensibi (Zero False Positive)
- **Karar:** Statik AST ve regex denetimleri kesin kanıt temeline dayandırılır. Belirsiz durumlarda ajan bloklanmaz, uyarı (`WARN`) seviyesinde telemetri tutulur.

---

## ⚠️ Kritik Teknik Tuzaklar (Gotchas)

### [GOTCHA-01] Windows Path Ayracı Farklılıkları
- **Tuzak:** Windows `\` ve POSIX `/` karmaşası, hook izin mekanizmalarında dosya yolu eşleşmeme sorunlarına yol açabilir.
- **Çözüm:** Tüm denetimlerde yollar `path.normalize` veya standart `/` biçimine çevrilerek regex/glob eşleştirmesi yapılır.

### [GOTCHA-02] Dosya Kilitleme ve Eşzamanlı Ajan Çağrıları
- **Tuzak:** Birden fazla ajan veya alt süreç aynı anda çalıştığında governance state dosyalarında yarış koşulu (race condition) oluşabilir.
- **Çözüm:** Atomik yazma ve kilit mekanizması (`governance.lock`) ile eyalet bütünlüğü garantiye alınır.
