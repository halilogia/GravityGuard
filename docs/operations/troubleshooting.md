# 🛠️ Sorun Giderme & SSS (Troubleshooting)

GravityGuard ile çalışırken karşılaşılabilecek durumlar ve operasyonel çözümleri:

---

## 1. Webview "Could not register service worker: InvalidStateError"

### Neden Olur?
Bu bir GravityGuard hatası değil; VS Code / Antigravity çekirdeğinin (upstream issue microsoft/vscode#125993) uzun süre açık kalan oturumlarda webview servis worker deposunu geçersiz duruma düşürmesidir.

### Çözüm
1. Komut Paletini açın (`Ctrl+Shift+P`).
2. `GravityGuard: Paneli Sıfırla` (`antigravityBridge.resetWebview`) komutunu çalıştırın.
3. Sorun devam ederse sadece pencereyi yenilemek yetmeyebilir; **tüm Antigravity IDE pencerelerini tamamen kapatıp yeniden açın**.

---

## 2. Audit Kilit Zaman Aşımı (`Could not acquire audit lock`)

### Neden Olur?
Aynı anda birden fazla ajan veya arka plan süreci `srp_guardian_live.json` dosyasına yazmaya çalıştığında dosya kilit mekanizması devreye girer.

### Çözüm
GravityGuard iki aşamalı çökme korumasına (Two-Phase Fallback Spool) sahiptir:
- Kilit alınamazsa veriler kaybolmaz; `.gravityguard/spool/` klasöründe arabelleğe alınır.
- Kilit boşa çıktığı ilk işlemde eksik olaylar otomatik olarak canlı duruma oynatılır (replay).
- Manuel müdahale gerekmez.

---

## 3. IDE Güncellemesi Sonrası Hook Değişikliklerinin Tanınmaması

### Çözüm
GravityGuard hook dosyalarını veya uzantısını güncellediğinizde:
1. `Ctrl+Shift+P` tuşuna basın.
2. `Developer: Reload Window` seçeneğini çalıştırın.
3. Hook'lar ve uzantı arka planı belleğe yeniden yüklenir.
