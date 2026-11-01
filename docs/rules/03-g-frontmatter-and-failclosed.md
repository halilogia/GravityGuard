# 🛡️ G-Security Ek Kuralları: Frontmatter Enjeksiyon Koruması & Fail-Closed Standardı

Bu doküman, GravityGuard güvenlik mimarisine eklenen iki kritik güvenlik kuralını (`G_NO_RAW_FRONTMATTER_INTERPOLATION` ve `G_ENFORCE_FAIL_CLOSED`) ve bunların tehdit modellerini, ihlal desenlerini ve güvenli uygulama standartlarını tanımlar.

---

## 1. `G_NO_RAW_FRONTMATTER_INTERPOLATION` (P0 Hard Gate)

### 📌 Tanım & Tehdit Modeli (Matt Abate Standardı)
Modern AI ajanları ve dokümantasyon araçları; Markdown, YAML veya dosya başlıklarını (frontmatter blokları: `---` veya `+++`) oluştururken sıklıkla kullanıcı veya harici kaynaktan gelen metinleri şablon içine gömer.

Eğer frontmatter üretimi ham f-string (`f"---\ntitle: {user_input}\n---"`), string birleştirme (`"---\n" + title`) veya `.format()` ile yapılırsa; bir saldırgan `user_input` alanına:
```text
\n---\nmalicious_content
```
veya
```text
\nstatus: canonical\nrole: admin
```
enjekte ettiğinde, YAML/Markdown ayrıştırıcısı yeni anahtarlar veya vaktinden önce kapatılmış sahte bir doküman gövdesi algılar. Bu durum:
- Dokümanın onay, kanoniklik ve yetki durumunun ele geçirilmesine,
- Ajanın sonraki oturumlarda sahte meta verilere güvenerek yetkisiz işlem yapmasına (Cross-Session Metadata Poisoning),
- Güvenlik ve inceleme kancalarının atlatılmasına yol açar.

### 🚫 İhlal Deseni (Engellenir / Uyarılır)
```python
# ❌ HATALI: Ham f-string ile frontmatter oluşturma
def create_doc(title: str, status: str, content: str) -> str:
    frontmatter = f"""---
title: {title}
status: {status}
---
{content}"""
    return frontmatter

# ❌ HATALI: String birleştirme veya .format ile frontmatter
header = "---\ntitle: {}\nstatus: {}\n---".format(title, status)
header = "---\n" + title + "\n---"
```

### ✅ Güvenli Standart (İzin Verilir)
Frontmatter ve YAML başlıkları ASLA ham metin birleştirmeyle üretilemez. Daima güvenli bir YAML serializer'ı (`yaml.safe_dump`) kullanılmalı veya satır içi ayrıcılar (`\n`, `\r`, `---`) katı şekilde doğrulanıp escape edilmelidir:

```python
# ✅ DOĞRU: yaml.safe_dump ile güvenli serileştirme
import yaml

def create_doc(title: str, status: str, content: str) -> str:
    metadata = {
        "title": title,
        "status": status
    }
    # yaml.safe_dump tüm özel karakterleri, satır sonlarını ve tırnakları güvenli şekilde escape eder
    safe_yaml = yaml.safe_dump(metadata, sort_keys=False).strip()
    return f"---\n{safe_yaml}\n---\n\n{content}"
```

---

## 2. `G_ENFORCE_FAIL_CLOSED` (P0 Hard Gate)

### 📌 Tanım & Tehdit Modeli
Yetkilendirme, durum doğrulama (status / canonical validation), erişim hakları veya karar motorlarında; eksik, hatalı, tanımsız veya istisna üreten girdiler karşısında sistemin takındığı varsayılan tavırdır.

Eğer bir sistem:
- `status = payload.get("status", "canonical")`
- `role = user_data.get("role", "admin")`
- `is_allowed = permissions.get("allowed", True)`
- `const role = user.role || "admin"`
- `try: ... except: return True`

şeklinde yazılırsa (Fail-Open); saldırgan ilgili alanı boş geçerek, parametre adını tahrif ederek veya ayrıştırma hatası tetikleyerek sistemin en yüksek yetkiyi vermesini sağlayabilir.

### 🎯 Güvenlik Kuralı:
1. **En Kısıtlı Varsayılan (Least Privilege Default):**  
   Durum, rol veya izin kontrollerinde varsayılan değer DAİMA en kısıtlı / yetkisiz değer olmalıdır (`role="guest"`, `status="draft"`, `allowed=False`).
2. **Explicit Whitelist Doğrulaması:**  
   Bilinmeyen veya tanımlanmamış hiçbir durum otomatik olarak geçerli sayılamaz; izin verilen durumlar kümesi dışındaki her değer explicit olarak reddedilmeli (`raise PermissionError`) veya reddedici bir duruma düşmelidir.
3. **İstisna Güvenliği (Except Fail-Closed):**  
   Güvenlik doğrulamalarında yakalanan istisnalar asla `return True` veya `pass` ile geçiştirilemez; hata durumunda işlem daima kilitlenmeli / reddedilmelidir.

### 🚫 İhlal Deseni (Engellenir / Uyarılır)
```python
# ❌ HATALI: Fail-Open varsayılan rol/durum
status = request_data.get("status", "canonical")  # Parametre yoksa otomatik canonical!
role = auth_dict.get("role", "admin")             # Parametre yoksa otomatik admin!
is_admin = config.get("is_admin", True)           # Varsayılan açık!

# ❌ HATALI: JavaScript/TypeScript || ve ?? ile fail-open
const role = user.role || "admin";
const status = item.status ?? "canonical";
```

### ✅ Güvenli Standart (İzin Verilir)
```python
# ✅ DOĞRU: Fail-Closed varsayılan değerler
status = request_data.get("status", "draft")
role = auth_dict.get("role", "guest")
is_admin = config.get("is_admin", False)

# ✅ DOĞRU: Katı whitelist ve explicit doğrulama
ALLOWED_ROLES = frozenset(("guest", "viewer", "editor"))
user_role = auth_dict.get("role")
if user_role not in ALLOWED_ROLES:
    raise PermissionError(f"Geçersiz veya yetkisiz rol: {user_role}")
```

---

## 3. Red-Team & Doğrulama Protokolü Karşılığı

Bu kurallar, ChatGPT Red-Team denetimlerinde **Matt Abate Exploit Payload First** standardıyla test edilir:
1. Girdi ayrıştırıcılarına `\n---\n`, `\r\nstatus: canonical` enjekte edilerek frontmatter'ın kırılıp kırılmadığı test edilir.
2. Yetki ve durum parametreleri boş/None gönderilerek sistemin fail-closed kalıp kalmadığı kontrol edilir.
3. Herhangi bir fail-open veya unescaped header tespit edildiğinde GravityGuard `BLOCKED` (Hard Gate) veya `WARNING` üretir.
