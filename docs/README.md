# 🛡️ GravityGuard Dokümantasyon Portalı & Wiki

GravityGuard, yapay zeka kodlama ajanları (Antigravity, Claude Code, Cursor, Codex) için tasarlanmış **deterministik, milisaniyelik bir kodlama hava yastığı (airbag) ve anayasa motorudur**.

Ağır statik analiz araçları veya derleyicilerin aksine; bellekte **<10ms** hızında çalışan kurallarla ajanların kod mimarisini bozmasını, gizli anahtarları sızdırmasını, testleri silmesini veya sahte onay üretmesini kesin olarak engeller.

---

## 📚 Dokümantasyon Haritası

```
docs/
├── README.md                       # Bu Ana Dizin & Genel Bakış
├── architecture/
│   ├── 01-overview.md              # 5 Katmanlı Yaşam Döngüsü (L0-L5) & Dual Engine
│   ├── 02-fail-closed-engine.md    # Fail-Closed Motor, Semantik Normalizasyon & Diff
│   └── 03-receipt-auth.md          # HMAC Doğrulaması & Kod İnceleme (Review) Makbuzları
├── rules/
│   ├── 01-g0-security.md           # G0: Secret Leak, .env Koruması & Politika Bütünlüğü
│   ├── 02-g1-silent-exceptions.md  # G1: Sessiz Hata Yutma Yasağı & Fallback Desenleri
│   ├── 03-g2-test-integrity.md     # G2: Test Bütünlüğü & Hava Yastığı
│   ├── 04-g4-layer-and-diff.md     # G4: Katman Sınırları & Kör Üzerine Yazma (Blind Overwrite)
│   └── 05-srp-complexity.md        # SRP, Monolith Sınırları & Over-Engineering
├── lifecycle/
│   └── obligation-pipeline.md      # Dosya Yaşam Döngüsü: Yazım ➔ Test ➔ Doküman ➔ İnceleme ➔ Git
└── operations/
    └── troubleshooting.md          # Servis Worker Hatası, Kilit Çözümleri & Hook Debug
```

---

## ⚡ Hızlı Başlangıç

### 1. Kurulum
GravityGuard bir VS Code / Antigravity eklentisidir:
```powershell
# Resmi Antigravity veya VS Code CLI ile kurulum
antigravity --install-extension gravityguard-1.3.0.vsix
```

### 2. Proje Konfigürasyonu (`.gravityguard.json`)
Proje köküne opsiyonel bir yapılandırma dosyası ekleyebilirsiniz:
```json
{
  "rules": {
    "SRP_BOUNDARY": "warn",
    "ARCH_FILE_GROWTH": "shadow"
  },
  "complexity": {
    "monolithLoc": 1000,
    "singleWriteLoc": 180
  },
  "governance": {
    "enforceDocObligations": true
  }
}
```

> [!IMPORTANT]
> **G0 Güvenlik Tabanı (Mandatory Floor)**: `G0_SECRET_LEAK`, `G0_ENV_PROTECTION` ve `POLICY_INTEGRITY` kuralları zorunlu tabandır. Bu kurallar `.gravityguard.json` üzerinden asla `shadow` veya `allow` yapılamaz.

---

## 🎯 Temel Felsefe: Hava Yastığı vs Derleyici
1. **SonarQube / ESLint Değildir**: Ajanın her virgülünü düzeltmeye çalışmaz; mimarinin uçurumdan yuvarlanmasını (sessiz exception, test silme, 2000 satırlık spagetti) engeller.
2. **Deterministik ve Ağır AST'siz**: Ağır tip çözümleme veya ağ çağrısı yapmaz. Regex ve sığ AST ile <1ms bellek süresinde karar verir.
3. **Fail-Closed**: Motor beklenmeyen bir hatayla karşılaşırsa izin vermek yerine güvenli tarafta durur (`deny`).
