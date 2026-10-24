# 🔒 G0: Güvenlik, Gizli Anahtar & Politika Bütünlüğü

G0 kuralları, GravityGuard'ın **en yüksek öncelikli ve zorunlu güvenlik tabanıdır (Mandatory Floor)**. Bu kurallar hiçbir proje veya kullanıcı konfigürasyonuyla gölge moda alınamaz veya pasife çekilemez.

---

## 1. Alt Kurallar

### `G0_SECRET_LEAK` (P0 Hard Gate)
- **Tanım**: Kod içerisine doğrudan gömülen API anahtarlarını, özel token'ları, AWS/GCP kimlik bilgilerini ve JWT anahtarlarını engeller.
- **Tetikleyici**: Desteklenen gizli anahtar desenleri ve bağlamsal kontroller; genel bir entropi tarayıcısı değildir.
- **Uzantı Bağımsızlığı**: Dosya uzantısı `.png`, `.bin` veya `.txt` olsa bile metin içerik G0 filtresinden geçer (Codex uzantı açığı düzeltmesi).

### `G0_ENV_PROTECTION` (P0 Hard Gate)
- **Tanım**: `.env`, `.env.production`, `.env.local` gibi hassas ortam değişkeni dosyalarının ajan tarafından doğrudan değiştirilmesini veya üzerine yazılmasını engeller.
- **Telemetri**: BLOCK, korunan işlemin reddedildiğini gösterir. Ajanın vazgeçtiğini veya güvenli bir alternatif uyguladığını tek başına kanıtlamaz. Güvenlik engelleri kod düzeltme oranından ayrı sayılır; otomatik yüzde 100 caydırma değeri üretilmez.

### `POLICY_INTEGRITY` (Bütünlük Koruması)
- **Tanım**: Ajanın kendisini denetleyen koruma mekanizmalarını zayıflatmasını engeller.
- **Kapsam**:
  - Ajanın `.gravityguard.json` dosyasında G0 kurallarını `shadow` yapması yasaktır.
  - Ajanın `hooks.json` veya eklenti çalışma kancalarını değiştirmesi/silmesi engellenir.

---

## 2. İhlal ve Doğru Çözüm Örneği

### ❌ Hatalı Davranış (Engellenir)
```python
# Ajan kodu içine doğrudan gerçek token/key gömmeye çalışır:
API_SECRET_TOKEN = "PROD_SECRET_TOKEN_EXAMPLE_1234567890"
```
```bash
🛑 [BLOCK] G0_SECRET_LEAK: Tespit edilen API anahtarı veya token doğrudan kaynak koda yazılamaz.
```

### ✅ Doğru Çözüm (İzin Verilir)
```python
import os
API_SECRET_TOKEN = os.getenv("API_SECRET_TOKEN")
if not API_SECRET_TOKEN:
    raise ValueError("API_SECRET_TOKEN ortam değişkeni tanımlanmalıdır.")
```
