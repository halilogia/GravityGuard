# 🔇 G1: Sessiz Hata Yutma Yasağı (No Silent Exceptions)

G1 kuralı, yapay zeka ajanlarının karşılaştıkları hataları çözmek yerine boş `except` veya boş `catch` bloklarıyla örtbas etmesini engelleyen temel kod kalitesi ve güvenilirlik filtresidir.

---

## 1. Kural Tanımı (`G1_SILENT_EXCEPTION`)

Yapay zeka modelleri bazen bir testin geçmesi veya kodun patlamaması için şu tarz kodlar üretir:
- Python: `except: pass` veya `except Exception: ...`
- TypeScript / JavaScript: `catch (e) {}`

Bu durum hataların sessizce yutulmasına, veritabanı tutarsızlıklarına ve üretim ortamında teşhis edilemeyen hayalet hatalara (ghost bugs) yol açar.

---

## 2. İhlal ve Kurtarma (Recovery) Örnekleri

### ❌ Engellenen Kod (BLOCK)
```python
# Python
try:
    user = db.get_user(user_id)
except Exception:
    pass  # 🛑 [BLOCK] G1_SILENT_EXCEPTION: Hatalar sessizce yutulamaz.
```

```typescript
// TypeScript
try {
  const data = JSON.parse(raw);
} catch (err) {
  // 🛑 [BLOCK] G1_SILENT_EXCEPTION: Boş catch bloğu tespit edildi.
}
```

### ✅ Kabul Edilen Kodlar (İzin Verilir)

#### 1. Anlamlı Fallback / Kurtarma Davranışı (Meaningful Recovery)
```python
try:
    user = db.get_user(user_id)
except DatabaseTimeoutError:
    logger.warning("DB zaman aşımına uğradı, önbelleğe başvuruluyor.")
    user = cache.get_user(user_id)
```

#### 2. Loglama ve Yeniden Fırlatma (Log & Rethrow)
```typescript
try {
  const data = JSON.parse(raw);
} catch (err) {
  logger.error("JSON parse hatası oluştu:", err);
  throw new InvalidPayloadError("Geçersiz veri formatı", { cause: err });
}
```

---

## 3. Kurtarma Oranı (Recovery Rate) Başarısı
G1 kuralı, ajanın kodu hemen düzeltmesine olanak sağlayan kurallardandır. Ajan ihlal mesajını aldığında hatayı loglayarak veya fallback ekleyerek kodu yeniden dener. G1 kuralında otonom ajanların düzeltme (recovery) başarı oranı **%93.8** seviyesindedir.
