# Changelog — GravityGuard

All notable changes to **GravityGuard** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.4] - 2026-10-10

### Fixed & Optimized
- **Açılış Tepkiselliği ve Dil Varsayılanı (TR)**:
  - Eklenti varsayılan dili doğrudan Türkçe (`tr`) olarak ayarlandı.
  - Sekme geçişleri (`setTab`) istemci tarafında saf DOM üzerinden 0 milisaniyede anlık hale getirildi; sekme tıklandığında bütün HTML'in tekrar çizilip arayüzü dondurması önlendi.
  - Dil değiştirme (`toggleLanguage`) çağrısı disk I/O'su beklenmeden anında render edilecek şekilde optimize edildi.
  - Ayarlar butonu (`handleOpenConfig`), `.gravityguard.json` dosyasını doğrudan `vscode.workspace.openTextDocument` ile editörde güvenilir şekilde açacak şekilde düzeltildi.

## [1.4.3] - 2026-10-10

### Fixed & Hardened
- **Webview `retainContextWhenHidden` ve Nonce CSP Standartlaştırması**:
  - `registerWebviewViewProvider` kaydına `retainContextWhenHidden: true` seçeneği eklendi. Kullanıcı kenar çubuğunu kapattığında veya başka bir sekmeye geçtiğinde webview iframe'inin ve context'inin yok edilip tekrar kurulması önlendi; servis çalışanı yaşam döngüsü güvenceye alındı.
  - İlk `resolveWebviewView` tetiklenmesinde HTML içeriğinin zorunlu (`force: true`) doldurulması sağlandı; boş doküman üzerine servis çalışanı kaydolma yarış durumu (race condition) ortadan kaldırıldı.
  - Güvenli `getNonce()` üreticisi ile CSP `script-src 'nonce-...'` ve `<script nonce="...">` standartlaştırması tamamlandı.

## [1.4.2] - 2026-10-10

### Added
- **Skills (Beceriler) Yönetim & Keşif Sekmesi**: GravityGuard canlı monitör paneline 5. sekme olarak "Beceriler" (Skills) eklendi.
  - Çalışma alanı (`.agent/skills/`, `.gemini/skills/`, `skills/`), Global (`~/.gemini/config/skills/`), Eklenti (`plugins/*/skills/`) ve Yerleşik Antigravity becerileri otomatik taranıp listelenir.
  - Her beceri için kapsam etiketi (Proje / Global / Eklenti / Yerleşik), başlık, açıklama ve tek tıkla `SKILL.md` açma kısayolu sunulur.
  - "Projeye Uygun Skill Bul" butonu ile `antigravityBridge.findSkills` komutu entegre edildi.
- **`antigravityBridge.findSkills` Komutu**: `find-skill` becerisini ve `skills.sh` internet kataloğu tarayıcısını doğrudan terminalde çalıştıran IDE komutu eklendi.
- **Pure TypeScript Beceriler Modülü (`src/skills.ts`)**: Sıfır bağımlılıkla YAML frontmatter ve markdown ayrıştırma yapan, SRP ve G1 sessiz hata kurallarına tam uyumlu beceri tarayıcı modülü geliştirildi.

### Fixed & Stabilized
- **Webview ServiceWorker InvalidStateError Çözümü**:
  - Webview gizli veya pasif durumdayken (`!this._view.visible`) her 1.5 saniyede bir arayüzün yeniden çizilerek Electron/Chromium Service Worker durumunu bozması engellendi.
  - `_lastHtml` önbellekleme mekanizması eklendi; HTML yalnızca içerik değiştiğinde DOM'a aktarılır, gereksiz iframe yeniden yüklemeleri ve servis çalışanı çökmeleri tamamen önlendi.
  - Görünürlük dinleyicisi (`onDidChangeVisibility`) ve kaynak temizleme (`onDidDispose`) entegre edildi.
  - Güvenli CSP (`Content-Security-Policy`) meta başlığı webview yapısına eklendi.

## [1.4.1] - 2026-10-10

### Fixed & Hardened (Audit, Reliability & Metrics Precision)
- **Kritik Eşzamanlılık Kilidi Senkronizasyonu (P0-A)**: `telemetry_dashboard.py` içindeki log rotasyonu/arşivleme kilidi, yazıcının (`audit.py`) kullandığı `.audit.lock` dosya yoluna eşitlendi. Klasör seviyesinde hatalı kilitleme giderildi; kilit zaman aşımında kopyalama işlemi derhal durdurularak yazma çakışmaları engellendi.
- **Kalıcı Günlük Doğrulamalı Spool İdempotency Protokolü (P0-B)**: Yedek havuz (`fallback spool`) tekrar oynatma mekanizması, 50 olaylık geçici canlı bellek penceresinden bağımsızlaştırıldı. Tekrarlanan olaylar doğrudan diske yazılmış kanonik `gravityguard_permanent_audit.jsonl` üzerinden taranıp tekilleştirildi. Canlı projeksiyon ve sıra numarası ilerletimi, yalnızca kanonik günlüğe dayanıklı yazım başarılı olduğunda devreye girecek şekilde sıralandı.
- **Dönemsel Medyan Hesaplama Doğruluğu (P1-B)**: `AggregatedMetrics` içindeki deneme dağılımından medyan hesaplama algoritması düzeltildi; tekil, çift ve çoklu frekans dağılımlarında matematiksel olarak doğru medyan (çift sayılarda ortadaki iki değerin ortalaması) hesaplanması sağlandı.
- **Akışlı Tekilleştirme Tahliyesi ve Çift Sayım Engelleme (P1-C)**: `LogStreamReader` içindeki 50.000 kayıtlık hafıza sıfırlaması (`seen_keys.clear()`), en eski anahtarları sırayla tahliye eden FIFO mekanizmasına dönüştürüldü. Ayrıca çoklu kaynak taramasında (`--all`), aktif günlük varken yedek zaman damgalı arşiv snapshot'larının (`*_20*.jsonl`) taranması engellenerek mükerrer sayım riski ortadan kaldırıldı.
- **Sınırlı Kardinalite ve Bellek Güvencesi (P1-A)**: `AggregatedMetrics` içindeki `_pending_warnings` ve `candidate_targets` yapılarına üst sınırlar getirilerek uzun süreli akışlarda bellek kontrolü sağlandı.
- **Arayüz Metrik Semantiği ve Tooltip Şeffaflığı**: Canlı arayüzdeki özet kartlarına (Engellendi, Uyarı, Onaylandı), bu sayaçların son 50 olayı kapsayan kayan pencereyi temsil ettiğini belirten açıklayıcı ipuçları (`title` tooltips) eklendi.
- **Antigravity IDE 1.4.1 Paketi**: Eklenti sürümü `1.4.1` olarak artırıldı ve Antigravity IDE'ye doğrudan kuruldu.

## [Unreleased]

> **Specialist Review (R1) — Uzman İnceleme Yükümlülüğü.** GravityGuard artık yönetilen
> üretim kodu değiştiğinde, oturum kapanmadan önce bağımsız bir `code-reviewer`
> uzmanından mekanik inceleme kanıtı (receipt) isteyebilir. Özellik **opt-in**dir
> (`review.enabled`) ve yol tabanlıdır; testler ve muaf desenler hariçtir.

### Added
- **Dil Tercihi Kalıcılığı (`context.globalState`)**: Webview ve komut paleti üzerinden seçilen dil ('tr' veya 'en') `context.globalState` üzerinde saklanarak IDE yeniden başlatıldığında dilin İngilizceye sıfırlanması sorunu giderildi.
- **Ayarlar İkonu ve Dosya Açma Güvenilirliği**: `.gravityguard.json` dosyasını açma eylemi (`openConfig`), webview odaklanma sorunlarını aşacak şekilde `vscode.commands.executeCommand('vscode.open')` ile doğrudan açılacak şekilde güçlendirildi.
- **Özet Bilgi Çubuğu ve Onaylanan İşlem Sayacı**: Arayüzdeki kafa karıştırıcı `0 TEMİZ` ibaresi yerine, temiz/onaylı geçen işlemleri anlık sayan yeşil `Onaylandı` (`approvedCount`) ve açıkta kalan test/doküman borçlarını gösteren `Bekleyen` (`totalObligations`) kartları getirildi. Esnek grid (`repeat(auto-fit, minmax(55px, 1fr))`) ile kart yerleşimi optimize edildi.
- **Antigravity IDE 1.4.0 Senkronizasyonu**: Antigravity IDE eklenti dizinindeki (`~/.antigravity-ide/extensions`) eski 1.3.1 sürümü temizlenip güncel 1.4.0 paketi yüklendi.
- **Kullanıcı düzeyinde varsayılan yapılandırma (`~/.gravityguard.json`)**: Yukarı doğru aramada projenin kendi `.gravityguard.json` dosyası bulunamazsa motor bu dosyayı okur (`GRAVITYGUARD_USER_CONFIG` ile başka bir dosya gösterilebilir); dosya yoksa ya da geçersiz JSON ise davranış eskisi gibidir. Projenin kendi dosyası varsa tamamen o geçerlidir, birleştirme yapılmaz. Ev dizinindeki dosya proje kökü işareti sayılmaz. Tüm okuyucular (kural modları ve shadow, eşikler, doküman yükümlülüğü, katmanlar) aynı `load_gravityguard_config` üzerinden geçer. Testler `engine/tests/test_project_context.py` ve `test_claude_adapter.py` içinde.
- **R1 — Uzman İnceleme Yükümlülüğü (Specialist Review V1)**: Yönetilen üretim kodu değiştiğinde Stop kapısı, bağımsız bir kod incelemesinin yapıldığını **işlem kanıtı** ile doğrular. Değişmez (invariant): *Bir uzman sonucu entegrasyonu yetkilendiremez; GravityGuard anlamsal doğruluğu değil, süreç kanıtını doğrular.* Ürün cümlesi (ADR ve kod yorumlarında): *"Bir inceleme makbuzu, incelemenin belirli bir aday duruma karşı yapıldığını kanıtlar; incelemenin doğru ya da eksiksiz olduğunu kanıtlamaz."* Sözlük (donmuş): Lead = Antigravity, Specialist = SwarmOrchestrator, Governor = GravityGuard.
  - `engine/gravityguard_engine/review_policy.py` (yeni): **Tetikleyici yalnızca**. `review.enabled` açık değilse hiçbir şey yapmaz; yalnızca üretim kodu uzantıları (`.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.gd`, `.cs`, `.go`, `.rs`, `.java`) inceleme doğurur; test/`test_*`/`*.test.ts` vb. hiçbir zaman tetiklemez; `review.exemptPatterns` (proje köküne göre glob) bastırır. `should_require_review` / `is_review_exempt_file` / `default_review_id`. Eskiden böyle bir kavram yoktu; yeni anlam: *belirli yollar için inceleme zorunlu olabilir.*
  - `engine/gravityguard_engine/review_governance.py` (yeni): **Yükümlülük + kanıt**. `record_review_obligation` bir oturumun yönettiği her dosyayı **tek bir aday** olarak biriktirir (`review_id` anahtarlı, `source_fingerprint` = değişen dosyaların newline-normalize metin hash'lerinin sıralı SHA-256'sı). `register_review_invocation` Lead'in MCP çağrısında gördüğü `review_id`/`nonce`/`source_fingerprint`i kaydeder (korelasyon çıpası). `evaluate_review_obligations` bir yükümlülüğü **yalnızca** şu koşulların tümü sağlanınca kapatır: (1) eşleşen bir MCP çağrısı gözlendi, (2) şema-geçerli receipt var, (3) `sourceFingerprint` eşleşiyor, (4) `nonce` eşleşiyor, (5) aday diskte hâlâ aynı fingerprint'e hash'leniyor (bayat değil). `hash_text` CRLF/CR → LF normalize eder (platformlar arası sahte "bayat"ı önler); `_norm_rel` her iki tarafı `resolve()` ederek Windows 8.3 kısa yol / uzun yol ayrışmasını kapatır. `RECEIPT_SUBDIR=(".gravityguard","runtime","reviews")`.
  - `dispatcher.py`:
    - **PreToolUse — MCP gözlemi**: `_MCP_REVIEW_TOOL_RE` (`mcp[_-].*code[_-]review`) ile eşleşen araç çağrıları, dosya yazımı sayılmadan önce ele alınır; `review_id` taşıyan çağrı `register_review_invocation` ile kaydedilir ve `allow` döner. Böylece "gerçekten Swarm MCP çağrısı yapıldı" kanıtı toplanır.
    - **PreToolUse — PASS bloğu**: Onaylanan yönetilen bir yazım `record_review_obligation` ile yükümlülüğü (aday fingerprint'iyle) doğurur; `should_require_review` bunu kendi içinde süzer.
    - **Stop — FINAL DIFF GUARD (durum kapısı)**: `record_final_diff_guard`, PreToolUse kancasından geçmemiş (ör. `run_command`/kabuk yazımı) diskteki yönetilen kodu `git status --porcelain` ile yakalar ve aynı oturum yükümlülüğüne katar. Fail-open: git yoksa/depo değilse boş liste, hiçbir şey değişmez. Ardından `evaluate_review_obligations` çalışır ve çözülmemiş incelemeler `REVIEW_OBLIGATION_UNRESOLVED` olarak Stop'u `continue` ile bağlar (diğer yükümlülüklerle aynı `stop_retries` devre kesicisi).
  - `engine/gravityguard_engine/governance.py`: `review_obligations` (global + oturum) ve `review_invocations` MCP çağrı kaydı varsayılanlara, budama döngülerine ve `clear_governance_state`'e eklendi. Yükümlülük görünürlüğü diğer kategorilerle aynı oturum izolasyonuna tabidir (`_visible_pending`).
  - `engine/gravity-validator.py`: yeni genel API yeniden dışa aktarıldı.
  - `plugin/hooks.json`: PreToolUse için `"matcher": "mcp_.*code[_-]review"` eşleştirici grubu eklendi.
  - **Kanıtlanabilen / kanıtlanamayan (dürüst sınır)**: GravityGuard mekanik olarak şunu kanıtlar: receipt var, çağrı gözlendi, fingerprint/nonce eşleşiyor, aday bayat değil, şema geçerli. Şunu kanıtlamaz: inceleme eksiksiz ya da anlamsal olarak doğruydu. Bu, gizlenmez; ADR ve kod yorumlarında açıkça yazılıdır. `run_command`'ın tüm yan etkileri hâlâ denetlenmez; final diff guard son savunmadır ve en iyi çabadır (git deposu gerektirir).
  - **HMAC yok**: Lead, Swarm ve GravityGuard aynı güven sınırında çalıştığı için kriptografik taklit engeli yerine **korelasyon** (gözlenen MCP çağrısı + review_id + nonce) kullanılır; bu, aynı kullanıcı bağlamında sahte bir güven hissi yaratmaz.
  - `docs/adr/0001-specialist-review-v1.md` (yeni): kararın ADR'si (sözlük, karar, değişmez, sonuçlar, V1 kapsam dışı).
  - `engine/tests/test_review_policy.py` ve `engine/tests/test_review_governance.py` (yeni) ile kapsama alındı.
- **`srp-modularizer` skill'i depoda**: `plugin/skills/srp-modularizer/SKILL.md` (hook'un gerçek SRP eşikleri + "değişim nedeni" kararı) eklendi; `tools/sync_plugin.py` bu dosyayı canlı plugin'e eşler (`--check` salt okunur kalır).
- **Merkezi Gizli Veri Maskeleme (Centralized Redaction Layer)**: `engine/gravityguard_engine/audit.py` içinde `redact_secrets` ve `redact_record` fonksiyonları eklendi. OpenAI (`sk-...`), Anthropic (`sk-ant-...`), GitHub (`ghp_...`), AWS (`AKIA...`), Bearer tokenlar, URI kimlik bilgileri (`user:pass@`) ve özel anahtar blokları hem canlı projeksiyona (`srp_guardian_live.json`) hem kalıcı günlüğe (`gravityguard_permanent_audit.jsonl`) yazılmadan önce tüm alanlar üzerinden merkezi olarak taranıp maskelenir.
- **Sıfır Kayıp İki Aşamalı Denetim Havuzu Protokolü (Two-Phase Crash-Safe Spool Protocol)**: `engine/gravityguard_engine/audit.py` içinde `_prepare_fallback_spool` ve `_commit_fallback_spool` ile iki aşamalı taahhüt mekanizması kuruldu. `StateLock` çekişmesi sırasında tamponlanan olaylar bağımsız süreç dosyalarına (`.processing.<pid>_<uuid>`) bölünür, ana günlüğe dayanıklı yazım (`flush` + `fsync`) doğrulanana kadar temizlenmez. Olası süreç çöküşlerinde yetim kalan tamponlar sonraki kilit ediniminde `eventId` bazlı idempotency korumasıyla tekilleştirilerek kayıpsız aktarılır; kümülatif engelleme ve iyileşme sayaçları (`_apply_event_to_live_state`) eksiksiz mutabakata varır.
- **Genişletilmiş Yapısal ve JSON Gizli Veri Maskelemesi (Structural & JSON Credential Redaction)**: Hem yapılandırılmış sözlük alanları (`_SENSITIVE_DICT_KEYS`) hem de gömülü JSON/kod metinlerindeki tırnaklı/tırnaksız anahtar-değer atamaları (`"api_key": "..."`, `'secret': '...'`, `api_key=...`) ve JWT belirteçleri (`[REDACTED_JWT]`) merkezi redaksiyon katmanına alındı. API anahtarlarının ve hassas sırların disk günlüklerine sızması engellendi.
- **Gerçek Akışlı Telemetri Analizi ($O(1)$ Bellek Tüketimi)**: `tools/telemetry_dashboard.py` içindeki `AggregatedMetrics` tüm olayları bellekte `list` olarak tutmak yerine doğrudan jeneratör üzerinden tek geçişte işleyen akışlı tüketiciye (`StreamingMetricsAggregator`) dönüştürüldü. Milyonlarca satırlık denetim kayıtlarında dahi bellek karmaşıklığı $O(1)$ düzeyinde sabitlendi; frekans dağılımından medyan hesaplama, son müdahaleler için sınırlı kaydırma penceresi ve tekilleştirme için sınırlı küme getirildi.
- **StateLock Korumalı Tahribatsız Log Rotasyonu**: `telemetry_dashboard.py` içindeki `--rotate` komutu eşzamanlı süreç çakışmalarını önlemek amacıyla `StateLock` altına alındı; aktif denetim günlüğünün sıfırlanması (`f.write("")`) engellenerek `auditSeq` sıra numarası ve canlı projeksiyon sayaçlarının sıfırlanma riski ortadan kaldırıldı.
- **Çoklu Proje Keşfi ve Zaman Dilimi Normalizasyonu**: Dashboard'a `--projects-root` seçeneği eklenerek tek komutla tüm çalışma alanı projelerindeki `.gravityguard/logs` dizinlerinin taranması sağlandı; `parse_iso_datetime` yerel saat dilimini (UTC+3) UTC'ye normalize edecek biçimde güçlendirildi.
- **Kapsamlı Güvenilirlik Test Süiti (`test_audit_reliability.py`)**: Sentetik JSON/JWT maskeleme, iki aşamalı spool çöküş kurtarma ve idempotency, bellek-sınırlı akış analizi ve tahribatsız rotasyonu doğrulayan uçtan uca testler eklendi.
- **İnteraktif Telemetri Konsolu (`telemetry.bat`)**: Parametresiz çift tıklandığında haftalık/aylık analiz, tüm logları birleştirme, Markdown rapor üretimi ve rotasyon seçeneklerini sunan menü desteği eklendi.


### Fixed
- **Güvenlik kuralları (G0/G2)**: tireli `sk-*` anahtarları (`sk-FAKE-do-not-use-0000` gibi, 20+ karakter, rakam + büyük harf içeren) artık G0'da engellenir; `sk-xxxx` / `sk-your-key-here` / kebab-case sluglar ve mevcut placeholder muafiyetleri aynen geçer. G2: `assert True`, `assert 1 == 1`, `assertTrue(True)`, `assertEqual(1, 1)` ve yoruma alınmış assert UYARI üretir; saf test yeniden adlandırma artık "silme" sayılıp reddedilmez.
- **Claude Code adaptörü**: `Read` aracı artık yönlendirilir (yalnız `.env` benzeri dosyalar motora gider; canlı `.env` okuması `G0_ENV_PROTECTION` ile reddedilir) ve `settings.example.json` eşleştiricisine eklendi; `CLAUDE_PROJECT_DIR` yoksa proje kökü `.git` / `.gravityguard.json` aranarak bulunur (iç içe `.gravityguard` oluşmaz); 100k iç içe `[` gibi yük `RecursionError` yerine stderr notuyla fail-open olur; denetim günlüğü varsayılan olarak `<proje>/.gravityguard/logs` içine yazılır (`GRAVITYGUARD_AUDIT_DIR` ile değiştirilebilir; `~/.gemini/logs` yalnız Antigravity varsayılanı). README ve adaptör docstring'indeki var olmayan "git pre-commit secret net" iddiası düzeltildi.
- **Mesajlar**: `G4_NO_BLIND_OVERWRITE` Claude Code (`Edit`) ve Antigravity (`replace_file_content`) için geçerli; G2 silme ve TS-SRP mesajları "bunun yerine ne yapılmalı" cümlesi taşır; Stop doküman borcu mesajı proje-göreli yol, `docs/KNOWLEDGE.md §6` yalnız dosya varsa, açık "CHANGELOG.md [Unreleased] bölümüne ... girdi ekle" cümlesi ve kalan deneme sayısıyla verilir.
- **Yapılandırma**: `GRAVITYGUARD_LOG_DIR` artık yalnız günlük/durum dizinini taşır; projenin kendi `.gravityguard.json` dosyası (shadow modları dahil) ve proje kökü çözümlemesi değişmez. Deposunun kendi `.gravityguard.json` dosyası motorun okuduğu `layers.<ad>.forbiddenImports` biçimine çevrildi. Motor `content` / `TargetContent` string değilse boş sayar (traceback yok).
- **Doküman borcu sırası**: CHANGELOG koddan ÖNCE güncellenirse (oturumun ilk doküman düzenlemesi, henüz borç yokken) bir sonraki yükümlülük tek seferlik bu düzenlemeyle kapanır; yanlış BLOCK oluşmaz.
- **VS Code Arayüzü & Sekme Durumu**: Webview arayüzünde aktif sekme (`_activeTab`) ve kaydırma konumu `vscode.setState()` ile kalıcı hale getirildi; arka planda 2 saniyelik yoklama veya yeni olay tetiklendiğinde Yükümlülükler veya Analiz sekmesinden Canlı sekmesine sıçrama sorunu çözüldü.
- **Ayarlar İkonu ve Yapılandırma Açma**: Webview başlığındaki ayarlar ikonuna (`openConfig`) tıklandığında açık bir çalışma alanı yoksa doğrudan ev dizinindeki `~/.gravityguard.json` dosyasını `ViewColumn.One` ile açma desteği ve bilgilendirme bildirimi eklendi.
- **i18n & Yerelleştirme**: `growthLabel`, `g3Label`, `Tavsiye • Gölge Modu (GÖLGE)` / `Tavsiye Uyarısı (UYARI)` ve WAL başlıkları hem TR hem EN sözlüklerinde eksiksiz eşitlendi.
- **Windows 8.3 Kısa Yol Desteği**: `project_context.py` içinde `os.path.realpath` kullanılarak `HALILE~1` biçimindeki Windows 8.3 kısa yollarının çözümlenmesi sağlandı, kök dizin aramasının ev dizinine taşması ve test kırılmaları önlendi.


## [1.4.0] - 2026-10-04

> **Yönetişim Olgunlaşma ve Çok-Platform Sürümü.** Claude Code adaptörü eklendi, oturum
> izolasyonu (session-scoped obligations, retries ve devre kesici) sağlandı, dokümantasyon
> politikası tek kaynağa (`doc_policy.py`) indirildi ve §6 yükümlülüğü Godot `.uid` gibi
> gürültüyü eleyecek biçimde hassaslaştırıldı.

### Added
- **Ürün Tasarım Felsefesi (README)**: `README.md` vitrinine (EN + TR) GravityGuard'ın çekirdek ilkesi eklendi: *"modele değil, mekanizmaya güven — yalnızca metin olarak yaşayan bir kural, bir dilektir."* Her yükümlülüğün ya diske yazılan bir artefakta ya da deterministik bir hava yastığı/linter/kancaya dayandığı; inisiyatif ve "bana güven" yerine kapalı kapı ilkesi belgelendi.

### Fixed
- **Ajan Davranış Dosyaları (Skill/Prompt) İçin Desen Önceliği ve Godot `.uid` Muafiyeti**:
  - `engine/gravityguard_engine/doc_policy.py`: Proje tarafından tanımlanan `governance.docObligationPatterns` kontrolleri genel `_NON_CODE_SUFFIXES` filtresinden **önce** değerlendirilecek şekilde yeniden sıralandı. Böylece `plugin/skills/**/*.md`, `commands/**/*.md`, `.claude-plugin/*.json` gibi doğrudan yapay zeka ajanının davranışını belirleyen skill ve prompt dosyaları `.md` veya `.json` uzantısı sebebiyle gözden kaçmaz; projelerce açıkça yönetilmesi sağlanır.
  - Godot oyun motorunun otomatik ürettiği `.uid` meta veri dosyaları (`foo.gd.uid`) `_NON_CODE_SUFFIXES` listesine eklenerek `addons/` klasörü yönetilen projelerde yanlış pozitif CHANGELOG yükümlülüğü oluşması engellendi.
  - `engine/tests/test_doc_policy.py`: `test_explicit_pattern_can_govern_markdown_and_json_files` ve `test_godot_uid_files_are_non_code_metadata` birim testleri eklenerek test sayısı 23'ten **25'e**, toplam Python test sayısı 263'ten **265'e** yükseltildi (%100 yeşil).
- **Claude Code Stop Kısayolu Kaldırıldı (`stop_hook_active` artık motoru atlatmıyor)**: İlk sürümde adaptör, Claude Code `stop_hook_active: true` bildirdiği an motoru hiç çağırmadan Stop'a izin veriyordu; yani ajan, yükümlülüğünü kapatmadan yalnızca **bir** ek tur atıp çıkabiliyordu ve çekirdeğin 5 denemelik devre kesicisi devre dışı kalıyordu. Artık her Stop motora sorulur; döngü, yükümlülük kapanınca, motorun devre kesicisi (oturum başına 5 engelli deneme) bırakınca ya da Claude Code art arda 8 engelden sonra kancayı geçersiz kılınca biter (sınır Claude Code'un hook rehberinde "Stop hook hits the block cap" olarak belgeli). Eski anlam: ikinci Stop koşulsuz serbest. Yeni anlam: ikinci ve sonraki Stop'lar da yükümlülüğe bakar. Uçtan uca testler: açık yükümlülük 5 kez engeller, 6. Stop'ta devre kesici bırakır; test dosyası diskte oluşunca Stop serbest kalır.
- **Belge Yönetişimi Politikası Tek Kaynağa İndirildi (`gravityguard_engine/doc_policy.py`)**: Hangi dosyanın CHANGELOG borcu doğurduğunu Stop zamanı izleyicisi (`project_context.is_doc_governed_target`) ve commit zamanı denetleyicisi (`tools/verify_doc_governance.py`) ayrı ayrı sabit listelerle tanımlıyordu ve ayrışmışlardı: `scripts` yalnızca Stop'ta, `tools` yalnızca commit'te yönetiliyordu; test/önbellek dışlamaları da farklıydı (denetleyici yola gömülü her `test_` parçasını dışlıyordu). Artık ikisi de `doc_policy.is_doc_governed_path` kullanır. Varsayılan klasörler birleşimdir: `engine`, `src`, `plugin`, `rules`, `scripts`, `tools`. `plugin/hooks.json` (kancaların davranışını değiştirdiği için) her iki kapıda da yönetilir.
  - `governance.docObligationPatterns` artık **proje köküne göre göreli** yolla eşleşir (`core/**`, `ui/**`, `addons/x/**/*.gd`); `**/` isteğe bağlıdır. Önceden desen mutlak yolla eşleştiği için göreli yazılan desenler hiçbir zaman tutmuyordu. Mutlak yola yazılmış eski desenler (`*/core/*`) çalışmaya devam eder.
  - Yeni `governance.docGovernedDirs`: varsayılan klasör listesini projenin kendi listesiyle **değiştirir** (ör. yalnızca `["addons"]`; ya da `["agent", "adapter", "bridge", "core", "tools", "ui"]`). `tools/` ya da `scripts/` altında atılabilir yardımcılar tutan, kodu `core/` ve `ui/` içinde olan projeler içindir; `docObligationPatterns` bunun üstüne eklenir. Bozuk değer (liste değil, boş ad) varsayılanlara döner; boş liste yalnızca desenleri yönetir.
  - Proje kökü biliniyorsa klasör adı yalnızca proje **içinde** aranır: `/home/ben/src/proje/` altındaki bir çıkış (checkout) artık her dosyayı yönetilen saymaz.
  - Denetleyici artık `.gravityguard.json` okur ve `governance.enforceDocObligations` açık değilse atlar (Stop tarafıyla aynı kural: açıkça isteyen projede çalışır). Motor betiğe göre bulunduğundan, başka bir deponun pre-commit kancasından `python <GravityGuard>/tools/verify_doc_governance.py` olarak çağrılabilir.
- **Oturum İzolasyonu: Bir Oturumun Borcu Başka Oturumun Stop'unu Artık Engellemiyor (Session-Scoped Obligations, Retries & Circuit Breaker)**:
  - Sorun: `get_unresolved_test_evidence` / `get_unresolved_doc_obligations` oturumun kendi listesi yoksa projenin ortak (global) listesine, `get_session_stop_retries` ise ortak `stop_retries` sayacına düşüyordu. Aynı projede A oturumu üretim kodu yazıp test eklemediyse, hiçbir şeye dokunmamış B oturumunun Stop'u da engelleniyordu; B'nin Stop yeniden denemeleri A'nın devre kesicisini (5 deneme) tüketebiliyordu. Hata iki oturumlu bir senaryoyla yeniden üretildi (A yazar, A Stop → continue, B Stop → continue ❌).
  - `engine/gravityguard_engine/governance.py`: yükümlülük görünürlüğü `_visible_pending` ile tanımlandı: **oturumun kendi bekleyenleri + hiçbir oturumun sahiplenmediği ortak kayıtlar**. Başka oturumun sahip olduğu kayıt görünmez; sahibi olmayan (oturumlar eklenmeden önce yazılmış, eski biçim) kayıtlar eskisi gibi herkes için geçerlidir. `get_session_stop_retries` yalnızca oturumun kendi sayacını okur (bozuk değer 0 sayılır); ortak `stop_retries` yalnızca canlı monitörün gösterim değeridir.
  - `engine/gravityguard_engine/dispatcher.py`: Stop hedef dosya taşımadığından çok kökenli (multi-root) pencerede yalnızca ilk çalışma alanına bakılıyordu. Yeni `_other_stop_roots`, durum dosyası zaten bulunan diğer kökleri de tarar; hiçbir kökte durum **oluşturmaz**, `GRAVITYGUARD_LOG_DIR` geçersiz kılması varken tek kök kullanılır. Yükümlülükler oturum kapsamlı olduğu için başka oturumların borcu bu kökte de görünmez.
  - Eski anlam: ortak liste her oturum için bağlayıcıydı. Yeni anlam: ortak liste yalnızca sahipsiz kayıtlar için bağlayıcıdır.
- **G0: Eski Biçimli OpenAI Anahtarları (`sk-` + 48 karakter, `sk-…T3BlbkFJ…`) Artık Yakalanıyor**: `security_rules.py` içine, sözcük sınırlı (`\b`) ve tireli slug'ları dışarıda bırakan sabit uzunluklu bir desen eklendi (`task-report-…`, `risk-…`, `disk-…`, `sk-learn-…` gibi sözcükler yanlış pozitif vermez; yer tutucular `is_placeholder` ile geçer). Önceden yalnızca modern `sk-proj-` / `sk-ant-` biçimleri BLOCK ediliyordu.
- `engine/test_gravity_validator.py::test_session_retries_circuit_breaker`: yükümlülüğü yaratan oturum ile Stop'u yeniden denenen oturum aynı `conversationId` ile çalışacak biçimde düzeltildi (eski test, başka oturumun borcunun global yoldan görünmesine dayanıyordu).
- **Test Kapsamı**: `engine/tests/test_governance.py` (+12: oturum/proje izolasyonu, sahipsiz eski kayıt, retries izolasyonu, `_other_stop_roots`), `test_security_rules.py` (+5: eski OpenAI anahtarı, yanlış pozitif sözcükler, yer tutucular), yeni `test_claude_adapter.py` (22) ve `test_doc_policy.py` (23). Python testleri 201'den **263'e**, toplam **300'e** (263 Python + 37 TypeScript) çıktı (%100 yeşil). Oturum izolasyonunun uçtan uca testi eski motorda başarısız olur (doğrulandı).
- **Canlı Akış Sıfırlama İmleci ve Sıra Numarası Tabanlı Filtreleme (Monotonic Sequence-Based View Filtering & i18n Truthfulness)**:
  - `src/view_filter.ts`: ASCII karakter sıralaması (`' ' < 'T'`) sebebiyle aynı gün içindeki yeni olayları gizleyen kırılgan string timestamp karşılaştırması tamamen kaldırıldı. Yerine GravityGuard'ın değişmez (invariant) `auditSeq` sıra numarasını temel alan deterministik `filterEventsAfterSeq` ve filigran çıkarıcı `resolveClearedAfterSeq` yardımcıları geliştirildi.
  - `src/extension.ts`: `GuardianViewProvider` içindeki `_clearedTimestamp` alanı `_clearedAfterSeq` ile değiştirildi. "Görünümü Temizle" tıklandığında diskteki son `lastAuditSeq` değeri yakalanarak sonraki olayların anında ve kesintisiz akması sağlandı; saat kayması ve format uyuşmazlıkları bertaraf edildi.
  - `src/i18n/index.ts`: Kilit mekanizması gösteriminde doğruluğu artırmak için aktif bir liveness kontrolü yapılıyormuş izlenimi veren `Sağlıklı (Çekirdek Kilit)` / `Healthy (Kernel-level lock)` ifadesi, mekanizmanın varlığını doğru niteleyen `Çekirdek düzeyi kilit etkin` / `Kernel-level lock enabled` olarak güncellendi.
  - `tests/view_filter.test.mjs`: `filterEventsAfterSeq` ve `resolveClearedAfterSeq` için 8 kapsamlı birim testi eklendi; TypeScript test sayısı 29'dan **37'ye**, toplam test sayısı ise **238'e** (201 Python + 37 TypeScript) yükseltildi (%100 yeşil).

### Added
- **Claude Code Adaptörü (`plugin/claude-code/`)**: Claude Code'un hook olaylarını motorun Antigravity biçimli yüküne çeviren ve **değiştirilmemiş** `engine/gravity-validator.py`'yi çalıştıran ince bir adaptör (`gravityguard_claude_hook.py`, yalnızca standart kütüphane). `Write` / `Edit` / `MultiEdit` → G0/G1/G2/G3/G4/SRP kuralları (BLOCK → `permissionDecision: "deny"`; uyarı → yalnızca `additionalContext`, asla `allow`: kullanıcının kendi izin istemi atlanmaz). `Stop` → yükümlülük kapısı (`{"decision":"block"}`; her Stop motora sorulur, `stop_hook_active` dahil: döngüyü motorun 5 denemelik devre kesicisi ve Claude Code'un art arda 8 engelden sonra Stop kancasını geçersiz kılan kendi sınırı bitirir). Oturum kimliği `claude:<session_id>` ön ekli (Antigravity ile çakışmaz), proje dizini `CLAUDE_PROJECT_DIR`. Motor yoksa ya da çökerse fail-open (stderr'e not). **Kapsam dışı (dürüst sınır)**: `Bash` ile yazılan dosyalar (`echo >`, `sed -i`) dosya kurallarına ulaşmaz; arka güvence git pre-commit gizli veri ağı ve Stop kapısıdır. `plugin/claude-code/README.md` mevcut bir koda geçiş için `G1_SILENT_EXCEPTION` gölge modunu (`rules.<ID>.mode: "shadow"`) önerir; `settings.example.json` hazır yapılandırmadır. Adaptör `plugin/` altında olduğundan VSIX'e girmez; canlı Antigravity eklentisine `tools/sync_plugin.py` ile ayrıca eşitlenen şey yalnızca motordur.
- **Causal State Koruma, Güvenli Clear View ve Başlatılmamış Projeksiyon Onarımı (Safe Clear View & Uninitialized Projection Healing)**:
  - `src/extension.ts`: `clearLogs()`'un diskteki `srp_guardian_live.json` dosyasını sıfırlayarak `activeViolations` ve causal analitiği silme riski tamamen ortadan kaldırıldı; yerine diske dokunmadan yalnızca arayüzdeki akışı filtreleyen güvenli `clearView()` motoru eklendi (`_clearedTimestamp`). Spekülatif `desyncAlertHtml` kaldırıldı; Tanılama özeti `WAL & Kilit Aktif` rozetine dönüştürüldü.
  - `engine/gravityguard_engine/audit.py`: `live_seq is None and journal_last_seq > 0` durumunda (dış kaynaklı sıfırlama veya başlatılmamış durum) kanonik kalıcı journal'dan otomatik tam rebuild (`_rebuild_live_state_from_permanent_audit`) mekanizması eklendi.
  - `engine/tests/test_audit.py`: `test_uninitialized_or_cleared_live_state_triggers_rebuild_from_journal` regresyon testi eklendi; toplam test sayısı **230'a** (201 Python + 29 TypeScript) yükseltildi (%100 yeşil).
  - `src/i18n/index.ts`: `actions.clearLogs` ("Görünümü Temizle"), `clearedNotice` ve `insights.diagnosticsBadge` simetrik olarak güncellendi.
- **Arayüz Kararlılık & Tanılama İyileştirmesi ve Gölge Modu Rozeti (UI Polish & Code Freeze)**:
  - `src/extension.ts`:
    - **İçgörüler Sekmesinde Kural Başına Ampirik Veriler**: `rulesToDisplay` listesine `ARCH_FILE_GROWTH` ve `G3_COMPILER_BYPASS` dahil edilerek her kural için müdahale/uyarı sayısı ($n$), iyileşme oranı (%), medyan deneme ve nitelik rozetleri (`Yetersiz Veri`, `Ön Sinyal`, `Yüksek Değer`, `Sürtünme`) bağlandı.
    - **Canlı Akış Çekmecesinde Akış Göstergesi**: `RECOVERED` olaylarında `BLOCKED → RECOVERED` akış rozeti, çözülen kural (`resolvedRuleId`), deneme sayısı ve çözüm süresi ($s$) görsel akış kartıyla donatıldı.
    - **Sessiz Tanılama (Diagnostics Accordion)**: `WAL`, `auditSeq`, `StateLock`, gecikme bütçeleri ve oturum bilgileri ana ekrandan kaldırılarak katlanabilir `<details class="diagnostics-details">` alanına taşındı; ana ekranda yalnızca bir tutarsızlık/hata olduğunda uyarı banner'ı belirmesi sağlandı.
    - **Dinamik Gölge Modu Rozeti (Dynamic Shadow Badge)**: Kurallar sekmesinde `.gravityguard.json` veya motor konfigürasyonunda `mode: "shadow"` olan kurallara mor renkli `SHADOW` rozeti (`lucide('eye')`) eklendi.
  - `src/i18n/index.ts`:
    - **Gösterim Doğruluğu ve Dürüst Telemetri İfadeleri (UI Truthfulness Polish)**: Gerçekte ölçülmeyen iddialardan kaçınmak için `Senkronize` yerine `Son projeksiyon: #seq` (`Last projected seq`), donanıma göre değişen alt süreç süresi için hardcoded `~220 ms` yerine `Platforma bağlı (~60–220 ms)`, kümülatif veri için `Aktif oturumda temiz` yerine `Kayıtlı veride 0 ihlal` ifadeleri hem TR hem EN sözlüklerinde güncellendi.
- **Lucide-Style Premium SVG İkon Sistemi ve %100 i18next Dinamik Yerelleştirme (Premium Lucide SVG Icons & Full i18n Localization)**:
  - `src/icons.ts`: Tüm standart emojiler yasaklanarak Lucide spesifikasyonuna (24x24 viewBox, stroke-width 2, rounded stroke) uygun 30 adet vektörel SVG ikonu (`shield`, `zap`, `lock`, `layers`, `flaskConical`, `checkCircle`, `octagonX`, `alertTriangle`, `eye`, `rotateCw`, `folder`, `fileText`, `copy`, `clipboardList`, `sliders`, `barChart`, `settings`, `trash2`, `globe`, `cpu`, `database`, `trophy`, `target`, `clock`, `sparkles`, `circleDot`, `arrowRight`) içeren sıfır bağımlılıklı tip-güvenli ikon motoru geliştirildi.
  - `src/i18n/index.ts`: Statik metin kullanımı tamamen kaldırılarak; hem Türkçe (`tr`) hem İngilizce (`en`) sözlükleri %100 simetrik hale getirildi. Parametre interpolasyon desteği (`{{var}}` ve `{var}`) eklenerek bildirimler, mod seçimleri, durum kartları, ampirik metrikler ve hata mesajları dinamik yerelleştirildi.
  - `src/extension.ts`: Header, hızlı sayaçlar, sekmeler, canlı eylem kartı, çekmece detayları, yükümlülük durum makinesi, kural kartları, içgörüler ve durum çubuğu butonları Lucide SVG ikonları ve `t()` yerelleştirme fonksiyonlarıyla donatıldı.
  - `tests/icons.test.mjs`: Lucide ikon motoru için 4 yeni birim testi eklendi; `tests/i18n.test.mjs` interpolasyon ve simetri testleriyle zenginleştirildi. Toplam test sayısı **229'a** (200 Python + 29 TypeScript) yükseltildi (%100 yeşil).
- **WAL Journal Kuyruk Satır Sonu Koruma ve Arayüz Zenginleştirmesi (Journal Tail Newline Restoration & UI Polish)**:
  - `engine/gravityguard_engine/audit.py`: Süreç kesintisi durumunda geçerli ve eksiksiz bir JSON nesnesi diske yazılmış ancak satır sonu ayracı (`\n`) henüz tamamlanmamışsa, `_repair_journal_tail()` artık olayı silmek yerine eksik `\n` ayırıcısını ekleyerek olayı sıfır kayıpla korur (`test_valid_journal_tail_without_newline_is_preserved`).
  - `src/extension.ts`: Canlı Akış çekmecesinde `SHADOW` ve `RECOVERED` (çözülen kural, deneme sayısı, süre) rozetleri; İçgörüler sekmesinde her kural için ampirik metrik kartları ($n$, düzeltme oranı %, medyan deneme, 3-kademeli eşik rozetleri) ve Canlı Telemetri & WAL Durumu kartı eklendi.
  - **Test Kapsamı**: `engine/tests/test_audit.py` test sayısı 18'den 19'a, toplam test sayısı **224'e** (200 Python + 24 TypeScript) yükseltildi (%100 yeşil).
- **Write-Ahead Journaling ve Projeksiyon Denetim Noktası Protokolü (Journal-Projection Checkpoint Protocol)**:
  - `engine/gravityguard_engine/audit.py`: Kalıcı denetim kütüğü (`gravityguard_permanent_audit.jsonl`) ile canlı durum projeksiyonu (`srp_guardian_live.json`) arasındaki çökme penceresi (divergence) Write-Ahead Logging (WAL) mimarisiyle tamamen kapatıldı:
    1. **Monotonik Sıra Numaralandırması (`auditSeq` / `lastAuditSeq`)**: Kalıcı kütüğe eklenen her olay monotonik artan bir sıra numarası (`auditSeq`) alır; canlı durum dosyası ise projeksiyona işlenen son olayı (`lastAuditSeq`) takip eder (`test_audit_seq_monotonic_increment`).
    2. **Write-Ahead Sıralaması (Journal FIRST, Projection SECOND)**: Olaylar önce kalıcı kütüğe (`gravityguard_permanent_audit.jsonl`) append edilir, ardından canlı bellek projeksiyonu güncellenir ve atomik dosya değişimi (`.tmp` -> `replace`) ile diske yazılır. Böylece kalıcı kütük kesin "Canonical Source of Truth" haline getirildi.
    3. **Çökme Kurtarma ve Eksik Olay Replay (`_replay_missing_journal_events`)**: Bir süreç kütüğe yazdıktan hemen sonra canlı durum dosyasını yazamadan çökerse (`live.lastAuditSeq < journal.lastSeq`), sonraki ilk işlem kilit altında eksik olayları tespit eder, canlı projeksiyona replay eder ve sayaçları/aktif ihlalleri sıfır kayıpla eşitler (`test_journal_ahead_of_live_triggers_projection_replay`).
    4. **Torn Tail Onarımı (`_repair_journal_tail`)**: Süreç çökmesi veya elektrik kesintisi anında yarım kalan bozuk JSONL satırları (`broken partial line`) kilit altında tespit edilerek dosya en son geçerli newline sınırına truncate edilir; yeni olayların bozuk satır sonuna yapışması engellenir (`test_torn_journal_tail_repair_and_append`).
    5. **Projeksiyon İlerideyse Uzlaştırma (`live_seq > journal_last_seq`)**: Canlı projeksiyonun beklenmedik şekilde journal'dan ileride olduğu tutarsızlıklarda (`live_seq > journal_last_seq`), kanonik kütük esas alınarak canlı durum sıfırdan güvenle uzlaştırılır (`reconcile projection`) (`test_projection_ahead_of_journal_triggers_reconciliation`).
    6. **Çoklu Kural Monotonik Sıralaması**: Çoklu kural çözümlemelerinde (`RECOVERED`) üretilen ek telemetri kayıtları da ardışık `auditSeq` değerleri alır (`test_multi_rule_recovery_assigns_monotonic_seq_to_extra_events`).
    7. **Fsync Destekli Dayanıklılık (`GRAVITYGUARD_DURABILITY`)**: `normal` modda tamponlanmış `f.flush()` çağrısı yapılarak OS çekirdeğine aktarım güvenceye alınırken, `GRAVITYGUARD_DURABILITY=durable` modunda `os.fsync(fileno)` ile fiziksel depolamaya best-effort sync sağlanır (`test_durability_mode_fsync_handling`).
  - **Test Kapsamı**: `engine/tests/test_audit.py` test sayısı 12'den 18'e, toplam test sayısı **223'e** (199 Python + 24 TypeScript) yükseltildi (%100 yeşil).
- **Canlı Durum Çökme Dayanıklılığı (Atomic Crash Consistency) ve Kendini Onarma (Self-Healing Rebuild)**:
  - `engine/gravityguard_engine/audit.py`: `srp_guardian_live.json` dosyasının yazımı doğrudan üzerine yazma yerine `.tmp` geçici dosyasına yazılıp atomic rename (`tmp.replace(log_path)`) edilerek süreç çökmesi anında dosyanın bozulması riski tamamen ortadan kaldırıldı (`test_live_state_atomic_replace_no_temp_leftover`).
  - **Kalıcı Kütükten Canlı Durum Yeniden Oluşturma (`_rebuild_live_state_from_permanent_audit`)**: `srp_guardian_live.json` dosyasının silinmesi veya bozulması durumunda, kalıcı veri kaynağı olan `gravityguard_permanent_audit.jsonl` otomatik taranarak tüm kümülatif etkinlik sayaçları, kural istatistikleri ve aktif ihlaller sıfır kayıpla canlı duruma geri yüklenir (`test_rebuild_live_state_from_permanent_audit_on_corruption`).
  - **Değişmez (Invariant) Denetimleri**: `recovered > blocked` veri anomalisinin tespit edilmesi halinde `min(100)` görsel maskelemesinin arkasına gizlenmeden stderr'e `[GravityGuard Invariant Violation]` uyarısı kaydedilmesi sağlandı (`test_telemetry_invariant_warning_on_anomaly`).
  - `tools/telemetry_dashboard.py`: Tavsiye Takip Oranı tablosunda $10 \le n < 30$ aralığı `🟡 Ön Sinyal` statüsüyle zenginleştirilerek kural tablosuyla tam eşik uyumu sağlandı.
  - **Test Kapsamı**: `engine/tests/test_audit.py` altına 3 yeni test eklenerek Python test sayısı 193'e, toplam test sayısı **217'ye** yükseltildi (%100 yeşil).
- **Çoklu Kural Kurtarma (Multi-Rule Recovery) ve Kümülatif İstatistikler**:
  - `engine/gravityguard_engine/audit.py`: Tek bir dosya üzerinde açık bulunan birden fazla kural ihlali (örn. hem `G1` hem `G2`) sonraki temiz onaylı düzenlemede (`APPROVED`) eksiksiz olarak çözülür. Her açık ihlal için ayrı bir `RECOVERED` telemetri kaydı (`resolvedRuleId`, `parentViolationId`, `recoveryAttempts`) üretilerek kalıcı denetim kütüğüne yazılır ve `ruleStats` sayaçları bağımsız artırılır; hiçbir kural kayıptan sessizce silinmez (`test_multi_rule_recovery_all_resolved`).
  - **Kümülatif Etkinlik Bütünlüğü**: `srp_guardian_live.json` içerisindeki `events` listesi UI performansı için son 50 olayla sınırlandırılırken, `effectiveness` ve `ruleStats` metrikleri kümülatif sayaçlarla yönetilir. Eski engelleme olaylarının 50 olaylık pencereden düşmesi sebebiyle iyileşme oranının %100'ü aşması veya istatistiksel sapma oluşması engellendi.
  - **Telemetri Kilit Zaman Aşımı Güvenliği (Fail-Closed Audit Lock)**: `StateLock.acquire()` fonksiyonunun `False` dönüşü açıkça kontrol edilerek kilit alınamadığı yüksek çekişme durumlarında kilitsiz telemetry yazımı kesin olarak engellendi (`test_audit_lock_timeout_fails_closed`).
- **Bilimsel Örneklem Eşik Değerleri ($n < 10$) ve Takip Oranı Terminolojisi**:
  - Hem `src/extension.ts` webview içgörülerinde hem `tools/telemetry_dashboard.py` üzerinde örneklem eşik değerleri bilimsel standartlara uyarlandı: $n < 10$ için `⚪ Yetersiz Veri`, $10 \le n < 30$ için `🟡 Ön Sinyal`, $n \ge 30$ için `🏆 Yüksek Değer / 🟢 Dengeli / ⚡ Sürtünme`.
  - Terminolojik dürüstlük: "Nedensel Gürültü Analizi" ifadesi yerine nedensellik iddiası taşımayan **"Tavsiye Kuralları ve Düzenleme Takip Oranı (Advisory Follow-up Rate / Temporal Action Proxy)"** terimi ve metodolojik dipnot benimsendi.
- **Kural Bazlı Nedensel İzolasyon ve resolvedRuleId Takibi (Rule-Specific Causal Chaining & Resolution Attribution)**:
  - `engine/gravityguard_engine/audit.py`: İhlal takip anahtarı `f"{conv_id}::{norm_target}"` yerine `f"{conv_id}::{norm_target}::{rule_id}"` olarak kural bazlı yalıtıldı. Aynı dosya üzerinde art arda tetiklenen farklı kural ihlallerinin (örn. G1 ardından gelen G2) yanlışlıkla `REPEATED_VIOLATION` olarak etiketlenmesi engellendi; her kural kendi bağımsız deneme sayacını korur.
  - Çözümleme anında oluşturulan `APPROVED` etkinliğine çözülen kuralın gerçek kimliği (`resolvedRuleId: "G1_SILENT_EXCEPTION"`), `parentViolationId`, `recoveryAttempts` ve `resolutionMs` bağlandı. Böylece telemetri ve gösterge panellerinde onay kaydının `ruleId="PASS"` olması sebebiyle kural kurtarma oranlarının sıfır görünmesi bug'ı giderildi.
  - `log_event()` fonksiyonuna doğrudan `conversation_id` parametresi eklendi ve `engine/gravityguard_engine/dispatcher.py` PreToolUse ve Stop kancalarındaki tüm olay kayıtları `_log(...)` yardımcısı aracılığıyla oturum kimliğini açıkça parametre olarak aktaracak şekilde refactor edildi; ortam değişkenlerine olan gevşek bağımlılık ortadan kaldırıldı.
  - `srp_guardian_live.json` ve kalıcı audit akışının (`gravityguard_permanent_audit.jsonl`) eşzamanlı subprocess'lerden bozulmaması için `StateLock` ile atomic kilit koruması entegre edildi.
  - `engine/gravityguard_engine/state_lock.py`: `StateLock` yapıcısı hem `Path` hem `str` kabul edecek şekilde esnetildi (`Union[Path, str]`).
- **Veri Odaklı ve Dürüst İçgörü Arayüzü (Data-Driven Insights)**:
  - `src/extension.ts`: Kenar çubuğu "Ajan İçgörüleri (Insights)" sekmesindeki statik/tahmini ifadeler (`%100 Önleme`, `Yüksek İyileşme (1 deneme)` vb.) tamamen kaldırılarak motorun `data.effectiveness.ruleStats` ampirik verilerini dinamik olarak render eden yapıya geçildi.
- **Test Kapsamı**: `engine/tests/test_audit.py` altına multi-rule recovery ve lock timeout fail-closed için 2 yeni test eklenerek Python test sayısı 190'a, toplam test sayısı **214'e** yükseltildi (%100 yeşil).
- **Nedensel Etkinlik Telemetrisi ve Gölge Modu (Causal Effectiveness Telemetry & Shadow Mode)**:
  - `engine/gravityguard_engine/audit.py`: Her güvenlik olayına benzersiz bir `eventId` atanarak nedensel olay zincirleme (`parentViolationId`, `outcome`, `recoveryAttempts`, `resolutionMs`) altyapısı kuruldu.
  - Ajanın bir ihlal sonrası sonraki hamlesinde durumu düzeltip düzeltmediğini ölçen gerçek zamanlı iyileşme takibi (`BLOCKED` -> `RECOVERED` veya `REPEATED_VIOLATION`) eklendi.
  - `engine/gravityguard_engine/dispatcher.py`: Kuralların deneysel olarak ajana hissettirilmeden izlenmesini sağlayan **Gölge Modu (Shadow Mode - `is_rule_shadow`)** desteği eklendi (`.gravityguard.json` içinde `"mode": "shadow"` olan kurallar ajanı engellemeden `SHADOW_TRIGGER` telemetrisi üretir).
  - `tools/telemetry_dashboard.py`: Basit olay sayıcısından bilimsel **Etkinlik Analitiği (Effectiveness Analytics)** merkezine dönüştürüldü; kural bazlı iyileşme oranları (`Recovery Rate %`), sürtünme faktörü (`Friction Delta / attempts`), tavsiye uyarılarının eyleme dönüşme oranı (`Advisory Action Rate`) ve gürültü adayları (`Noise Candidates`) raporlanması sağlandı.
  - `engine/tests/test_audit.py`: Causal chaining, recovery outcome, repeated violations ve shadow mode için 4 adet bağımsız regresyon testi eklendi.
  - Arayüz kural ve içgörü ayrımı: `src/extension.ts` üzerinde kural şiddeti (`Severity: WARN`) ile yaşam döngüsü kapanış yükümlülüğü (`Lifecycle Effect: Stop Obligation`) net olarak ayrıştırıldı; yüksek değerli muhafızlar (G0, G1, G2) ve tavsiye kuralları (T1, G3, ARCH_GROWTH) analiz sekmesine yansıtıldı.
- **Canlı Ajan Güvenlik Konsolu ve Yenilenen Kenar Çubuğu (Live Agent Security Console & Webview Overhaul)**:
  - Kenar çubuğu webview'ı statik bir gösterge panelinden anlık çalışan bir **Canlı Ajan Güvenlik Konsolu**'na dönüştürüldü.
  - **Canlı Eylem Kartı (Current Action Card)**: Ajanın en son tetiklediği dosya eylemini (`write_file`, `create_file` vb.), hedef dosya yolunu ve GravityGuard'ın güvenlik kararını (`ALLOWED` / `BLOCKED`, aktif kurallar G0-G4) tepe kartında anlık gösterir.
  - **Hızlı Sayaçlar (Quick Counters Bar)**: `X Blocked`, `Y Warnings`, `Z Pending` durum sayaçları doğrudan başlık altına yerleştirildi.
  - **Dört Özel Sekme**:
    - **Canlı Akış (Live)**: Ajanın araç çağrılarını kompakt satırlar halinde sunar; tıklandığında genişleyen neden çekmecesi, `[Dosyayı Aç]` ve `[Nedeni Kopyala]` butonları sunar.
    - **Yükümlülükler (Obligations)**: Açık dokümantasyon ve test yükümlülüklerini 4 adımlı görsel durum makinesi (`BEKLİYOR → NİYET KAYDEDİLDİ → DOĞRULANDI → ÇÖZÜLDÜ`) ile adım adım takip eder.
    - **Kurallar (Rules)**: Güvenlik (G0, G1, G2), Mimari (G3, G4, SRP, Growth) ve Kalite (T1, T2, T3) kategorilerine ayrılarak durum, şiddet ve açıklamaları gösterir; tek tıkla `.gravityguard.json` dosyasını açma imkanı sunar.
    - **Ajan İçgörüleri (Insights - Telemetry)**: Ajanın engelleme sonrası kendini düzeltme başarısını ölçen **Ajan İyileşme Oranı (Agent Recovery Rate %)**, motor gecikmesi ve oturum bütünlüğü (State Lock, 2PC, Circuit breaker) metrikleri sunar.
  - **Çift Yönlü Webview Mesajlaşması**: Webview içerisinden Antigravity IDE editöründe dosya açma (`openFile`), yapılandırma dosyasını açma (`openConfig`) ve engelleme nedenini panoya kopyalama (`copyReason`) komutları eklendi.
  - **Sıfır Bağımlılıklı Çeviri Motoru (Zero-Dependency i18n)**: Yeni konsol elemanları, sekmeler ve durum adımları hem Türkçe (`tr`) hem İngilizce (`en`) dillerine tam olarak yerelleştirildi.
- **Çoklu Süreç Durum Dosyası Kilitlemesi ve İşlem Güvenliği (State File Locking & Atomic RMW Transactions)**:
  - `engine/gravityguard_engine/state_lock.py` modülü eklendi: Windows (`msvcrt.locking`) ve POSIX (`fcntl.flock`) çekirdek kilitlerini soyutlayan, işlem çökmesi durumunda işletim sistemi tarafından kilit askıda kalmadan (stale lock hang) derhal serbest bırakılan platformlar arası `StateLock` sınıfı uygulandı.
  - `governance_transaction()` bağlam yöneticisi (context manager): `governance.json` üzerindeki `load -> mutate -> save` döngüsünü baştan sona tek parça (atomic read-modify-write) özel dosya kilidi altına alarak bağımsız iki hook sürecinin aynı anda durum güncellemesi durumunda oluşabilecek kayıp güncelleme (lost-update) riski tamamen ortadan kaldırıldı.
  - **Özyinelemeli/İç İçe İşlem Koruması (Re-entrant Transactions via ContextVar)**: Aynı thread ve yürütme bağlamında iç içe çağrılan `reconcile_obligations_on_disk()` ve `resolve_pending_*` fonksiyonları için bellek içi durum paylaşımı sağlandı; gereksiz disk okuma/yazma ve kilit kilitlenmesi (deadlock) önlendi.
  - **Hata Durumunda Geri Alma (Atomic Abort)**: `governance_transaction` bloğu içerisinde beklenmedik bir istisna oluştuğunda disk üzerine bozuk veya eksik durum yazılması engellendi (`test_governance_transaction_nested_and_abort`).
  - **Gerçek Çoklu Süreç Eşzamanlılık Regresyon Testi (`test_concurrent_processes_no_lost_update`)**: İki bağımsız işletim sistemi sürecinin (`proc-A` ve `proc-B`) eşzamanlı olarak aynı `governance.json` dosyasına dokümantasyon yükümlülüğü eklediği negatif yarış durumu test edildi; her iki sürecin yükümlülüğünün de kayıpsız kaydedildiği doğrulandı.
- **Gerçek İki Fazlı Taahhüt ve Çözümleme Niyetleri (True Two-Phase Commit with Resolution Intents)**:
  - PreToolUse aşamasındaki erken/iyimser (optimistic) yükümlülük silme davranışı tamamen kaldırıldı.
  - PreToolUse aşamasında dokümantasyon veya test dosyası onaylandığında, `governance.json` içerisinde `resolution_intents` listesine dosyanın SHA-256 özeti, boyutu ve değiştirilme zamanından oluşan taban çizgi anlık görüntüsü (`pre_hash`, `pre_mtime`, `pre_size`) kaydedilir; yükümlülük `pending` durumunda tutulur.
  - **Kriptografik İçerik Doğrulaması (Hash-Only Mutation)**: Mevcut dosyalarda yalnızca `mtime` veya `size` değişimine bakarak yükümlülük çözme riski giderildi. Editörün dosyayı aynı içerikle yeniden kaydetmesi (`touch` veya no-op save) durumunda `curr_hash == pre_hash` kaldığı için yükümlülük haksız yere düşürülmez. Karar doğrudan `curr_hash != pre_hash` kontrolüne bağlandı (`test_same_content_touch_does_not_resolve_obligation`).
  - **Çapraz Oturum Çözümleme İzolasyonu (Cross-Conversation Resolution Isolation)**: `reconcile_obligations_on_disk()` fonksiyonu yalnızca çağrıldığı `conversation_id`'ye ait intent'leri işler; diğer açık oturumların intent'leri korunur. `resolve_pending_doc_obligations()` ve `resolve_pending_test_evidence()` oturuma özgü pending listesi üzerinden çözümleme yapar ve diğer paralel oturumların yükümlülüklerini asla silmez (`test_concurrent_sessions_intents_do_not_collide`).
  - **Deterministik Test Kanıtı Fallback'i (Fully Hash-Aware Test Evidence Fallback)**: `test_info` içinde `"baseline_hash"` alanı varsa, aday test dosyasının başlangıçta olmaması durumu (`baseline_hash is None`) sonradan dosya oluşturulduğunda (`curr_h is not None`) deterministik olarak çözülür. `mtime` toleransına yalnızca eski formatlı kayıtlar için başvurulur (`test_test_evidence_fallback_hash_based`).
  - Başarısızlık regresyon testi (`test_two_phase_commit_unwritten_file_keeps_obligation_open`): PreToolUse aşamasında yazma izni verilmesine rağmen araç iptal edildiğinde veya dosya diske yazılmadığında, Stop hook'un oturumun kapanmasını engelleyip `continue` dönmeye devam ettiği doğrulandı.
  - Etki alanı testleri: `engine/tests/test_governance.py` altında 10 adet ve `engine/tests/test_state_lock.py` altında 4 adet bağımsız iki fazlı taahhüt, oturum izolasyonu ve kilit testi eklendi.
- **Özyinelemeli (Recursive) Geliştirici Araçları (`tools/sync_plugin.py`, `tools/verify_package.py`)**:
  - `tools/sync_plugin.py`: Düz dizin taraması yerine `os.walk` kullanılarak `engine/gravityguard_engine/` altındaki tüm iç içe alt paket ve modüllerin canlı eklentiye (`scripts/gravityguard_engine/`) otomatik ve özyinelemeli senkronizasyonu sağlandı.
  - `tools/verify_package.py`: `rglob("*.py")` ile VSIX paketleme denetimi tam özyinelemeli hale getirildi.

### Changed
- **Motor Modülerizasyonu (`gravityguard_engine`)**: 2.635 satırlık tek parça `engine/gravity-validator.py` monolitik dosyası, SRP ve bakım kolaylığı ilkelerine uygun olarak `engine/gravityguard_engine/` alt modüllerine ayrıştırıldı (`project_context.py`, `audit.py`, `diffing.py`, `security_rules.py`, `architecture_rules.py`, `diagnostics.py`, `test_evidence.py`, `governance.py`, `dispatcher.py`, `state_lock.py`). Ana giriş noktası `engine/gravity-validator.py` 118 satırlık ince bir ön yüz (facade) haline getirilerek geriye dönük tam uyumluluk sağlandı.
- **Test Kapsamı**: 145 motor testi + 36 etki alanı testi + 24 TypeScript testi = **Toplam 205 test**, %100 başarılı. Çekirdek mantık gecikmesi ~0.030 ms (<10ms bütçesi korunuyor).

### Fixed
- **Devre Kesici Doğruluğu (Defect A)**: Stop kancasındaki `or (isinstance(exec_num, int) and exec_num > 5)` koşulu kaldırıldı. Araç çağrı sıra numarası (`executionNum`), uzun konuşmalarda erken devre kesici tetikleyip denetimi devre dışı bırakamıyor; devre kesici yalnızca ajanın art arda 5 kez Stop hook'u atlatmaya çalıştığı `session_retries >= 5` durumunda devreye giriyor.
- **Çoklu Çalışma Alanı Çözümleme (Defect C)**: `resolve_project_root`, `payload.workspacePaths` listesinde hedef dosyanın (`target_file`) gerçek üst dizinini içeren çalışma alanını ilk sıraya alarak birden fazla projenin açık olduğu oturumlarda kök dizin sapmalarını önledi.
- **Eklenti Arayüzü Yükleme ve Sıfır Bağımlılık (Zero-Dependency i18n Fix)**: VSIX paketi derlenirken `node_modules` dışarıda kaldığı için Antigravity IDE tarafında `Cannot find module 'i18next'` hatasıyla Webview'ın siyah ekranda/mavi yükleme çizgisinde takılması giderildi. Dış `i18next` bağımlılığı kaldırılarak hafif, bellek içi ve sıfır bağımlılıklı (zero-dependency) saf TypeScript çeviri motoru (`src/i18n/index.ts`) entegre edildi.
- **Kilit Zaman Aşımı ve Hata Durumunda Kapalı Kalma (StateLock Fail-Closed on Timeout)**:
  - `StateLockTimeout` exception sınıfı tanımlandı. `StateLock.__enter__()` ve `governance_transaction()` kilit alınamadığında fail-open davranışı terk edilerek `StateLockTimeout` fırlatacak şekilde fail-closed hale getirildi. Yüksek kilit çekişmesi (contention) altında asla kilitsiz durum okunup yazılmaz.
  - **Hook Sınır Güvenliği**: PreToolUse aşamasında kilit zaman aşımına uğrarsa `decision: deny` ve `STATE_LOCK_TIMEOUT` kuralıyla işlem engellenir; Stop hook aşamasında kilit zaman aşımına uğrarsa `decision: continue` dönülerek oturumun kontrolsüz/doğrulanmamış sonlanması engellenir.
  - **Monotonik Zaman ve Sonsuz Döngü Koruması**: `StateLock.acquire()` döngüsü `time.monotonic()` ile sistem saati sıçramalarına karşı korundu; `os.open` aralıksız `OSError` üretse dahi `self.timeout` süresi sonunda sonsuz döngüye girmeden güvenle `False` dönmesi sağlandı.

## [1.3.1] - 2026-10-02


> **Doğruluk (Correctness) ve Mimari Olgunlaşma Sürümü.** İki fazlı commit modeliyle
> erken yükümlülük düşmesi (premature resolution) giderildi, proje root izolasyonu sağlandı,
> Stop hook fiziksel disk doğrulaması kazandı ve eklenti arayüzüne çok sekmeli (Olaylar /
> Yükümlülükler / Kurallar & Context) canlı görünüm eklendi.

### Fixed
- **İki Fazlı Durum Taahhüdü (Two-Phase State Commit)**: PreToolUse sırasında yükümlülüklerin erken çözülmesi veya henüz onaylanmamış işlemler için yükümlülük kaydedilmesi engellendi. G0 (gizli anahtar), G1 (sessiz hata) veya G4 (katman) ihlali nedeniyle reddedilen (`deny`) bir yazma çağrısı artık `governance.json` durumunu kirletemez. Değişiklikler yalnızca tüm guardlar onay verdiğinde (`allow`) diske yazılır.
- **Proje Kökü ve Çalışma Alanı İzolasyonu (Project Scoping)**: Antigravity hook çağrılarında çalışma dizini (`cwd`) eklenti dizinine ayarlandığından `Path.cwd()` kullanımı çoklu çalışma alanlarında durumu bozuyordu. Proje kökü artık öncelikle payload içerisindeki `workspacePaths`, ardından hedef dosyanın yukarı doğru aranmasıyla deterministik olarak çözülüyor.
- **Oturum Bazlı Devre Kesici (Session-Scoped Circuit Breaker)**: `executionNum > 5` varsayımı (araç çağrı sıra numarası) düzeltildi. Ajanın Stop talepleri her `conversationId` bazında `governance.json` içerisinde ayrı bir sayaç olarak tutulur ve 5 ardışık devam (`continue`) cevabından sonra devre kesici devreye girerek sonsuz döngüyü önler.
- **Sessiz Yapılandırma Taşması (Config Bleed)**: `.gravityguard.json` arayıcısı, harici veya geçici dizinlerdeki dosyalar için çalışma dizini fallback'ini devre dışı bırakarak bağımsız test ve projelerin birbirinin kurallarını devralmasını engelledi.
- **T1 Test Dosyası Eşleme ve Tire/Alt Çizgi Normalizasyonu**: Tire içeren dosya adları (`gravity-validator.py`) ile geçerli Python/TS test modül adları (`test_gravity_validator.py`) arasındaki adlandırma uyuşmazlığı çözüldü; aday çözücü artık otomatik olarak `_` ve `-` alternatiflerini tarar.
- **Geliştirici Araçları ve Script Muafiyeti**: `tools/`, `scripts/` klasörlerindeki yardımcı geliştirici araçları ile `src/extension.ts` varsayılan olarak test kanıtı (T1) yükümlülüğünden muaf tutuldu; `.gravityguard.json` yapılandırmasına `exemptPatterns` eklendi.
- **Stop Hook Konfigürasyon ve Oturum İzolasyonu Güçlendirmesi**: Stop kancasında proje yapılandırmasının (`cfg`) erken yüklenmesi sağlandı; `load_governance_state` budama döngüsünde boş oturumlara sahte yükümlülük nesnesi enjekte edilmesi düzeltildi.

### Added
- **Stop Hook Fiziksel Disk Doğrulaması**: Ajan oturumu bitirirken, `CHANGELOG.md` veya beklenen test dosyasının disk üzerinde fiziksel olarak oluşturulup güncellendiği (`mtime` kontrolü) tespit edilirse yükümlülük Stop anında otomatik çözülür.
- **Opt-in Dokümantasyon Yönetişimi**: §6 Same-Commit dokümantasyon kuralı yalnızca projenin `.gravityguard.json` dosyasında açıkça `{"governance": {"enforceDocObligations": true}}` ayarlandığında aktifleştirilir.
- **Takip Edilen Git Hook'ları & CI Entegrasyonu**: `.githooks/pre-commit` ve platformlar arası `tools/install_hooks.py` oluşturuldu. `tools/verify_doc_governance.py` aracına yorum/boşluk filtreli semantik diff kontrolü eklendi; GitHub Actions CI iş akışına dokümantasyon yönetişimi adımı dahil edildi.
- **Mekanik Kural Enjeksiyonu (Plugin Rules)**: Antigravity'nin ajan sistem promptuna otomatik enjekte ettiği `plugin/rules/gravityguard_invariants.md` (`always_on: true`) kuralı eklendi. Ajan oturum başında G0-G4, SRP ve §6 kurallarını mekanik olarak bağlamında görür.
- **Çok Sekmeli VS Code / Antigravity Eklenti Arayüzü**: `src/extension.ts` içerisindeki `GuardianViewProvider` yenilendi:
  - `[🛡️ Olaylar]`: Canlı engelleme, uyarı ve onay akışı.
  - `[📋 Yükümlülükler]`: `governance.json` üzerinden canlı bekleyen test ve dokümantasyon listesi ile devre kesici sayacı.
  - `[📐 Kurallar & Context]`: `.gravityguard.json` katmanları, SRP sınırları, opt-in yönetişim durumu ve güvenlik değişmezleri özeti.
- **Öğrenme Defteri (Learning Ledger) İyileştirmesi**: `tools/telemetry_dashboard.py --candidates` çıktısına minimum 3 ihlal eşiği, farklı oturum çeşitliliği ve ihlal yüzdesi oranı hesaplaması eklendi.
- **Çok Dilli Uluslararasılaştırma (i18next TR/EN Desteği)**: `src/i18n/index.ts` modülü oluşturuldu. Eklenti arayüzündeki tüm sekmeler, istatistik kartları, yükümlülük uyarıları ve kurallar Türkçe ve İngilizce sözlük kaynaklarına bağlandı; başlıkta tek tıkla canlı dil değiştirme (`🌐 TR` / `🌐 EN`) ve `antigravityBridge.toggleLanguage` komutu eklendi.
- **Test Kapsamı**: 143 Python unit testi + 24 TypeScript/JavaScript testi = **Toplam 167 test**, %100 başarılı.
- **`\p{L}` in a `new RegExp` string collapsed to the letter "p", silently disabling the Turkish word guard.** `tr()` builds its pattern as a *string*, where an unescaped `\p` is an identity escape; the resulting regex read `[^p{L}]` — "any character except p, {, L or }" — so the "must follow a non-letter" guard matched *inside* ordinary words. Consequences found by the new corpus: "ölçeklenir" contains "ekle", so `implement:tr-add` fired on a scaling question; "eksileri" contains "sil", so `implement:tr-delete` fired on a pros/cons question. Fixed with `\\p{L}`, and the reason is now documented at the function, because this is a bug that recompiles silently and looks like a data problem.
- **The same word could fire two patterns of the same mode, doubling its weight.** `dead code|unused|technical debt` appeared in both the Turkish and the English smell patterns, so one English "unused" scored 6 instead of 3 — enough to outrank a build order. The two lists are now disjoint.
- **A question mark outweighed a semantic signal.** `?` and the Turkish `mı/mi/mu/mü` particle each scored 2, and the question mark was also matched by the trailing-particle pattern, so a single "?" could score 4 — more than "kalitesi nasıl, risk var mı?" needed to be recognised as an audit request. Question marks are syntactic, not semantic: they say a request is a question, never *which* kind. Both now score 1, and the ordering rule is written down: **specific beats generic** — a build verb or audit verb (4) outranks a question (1–2), and a named assessment topic (5) outranks both.
- **Turkish keywords silently failed on every inflected form.** `\b`-anchored patterns cannot match "teknik borç" in "teknik borcu" (the accusative softens ç→c) or "ölü kod" in "ölü kodu". Those failures are invisible: the prompt still comes out, just aimed at the wrong job. Turkish signals are now stems with a bounded suffix allowance, with two documented exceptions — consonant softening is expressed as a character class, and the potential suffix *-A-bil-* ("yaz**a**biliriz") is excluded, because a hypothetical is not an order: "how many ways could we write this?" was classified as an implementation request because it mentioned a build verb.

### Added
- **5-Katmanlı Yükümlülük Odaklı Yönetişim Modeli (5-Layer Obligation-Driven Governance)**:
  - **L0 (Ajan Protokolü)**: `docs/KNOWLEDGE.md` §0 (`ALWAYS_LOAD`) ve `.gravityguard/CONTEXT.md` dosyalarında en kritik değişmezler (<40 satır) özetlendi.
  - **L1 (PreTool Airbag)**: G0 (gizli anahtar), G1 (sessiz hata), G2 (test bütünlüğü / atlatma engelleyici), G4 (mimari katman matrisi), SRP ve kümülatif büyüme guardları tek çatı altında diff-bazlı ve deterministik (<10ms) çalışmaya devam ediyor.
  - **L2 (Asenkron Kanıt & Yönetişim Durumu)**: `.gravityguard/runtime/governance.json` state motoru ile hem `test_obligations` hem de `doc_obligations` tek bir merkezde takip ediliyor. Eski `test_evidence_state.json` ile çift taraflı geriye dönük uyumluluk korundu.
  - **L3 (Yaşam Döngüsü Kapısı / Stop Hook)**: `plugin/hooks.json` manifestine `Stop` kancası eklendi. Antigravity Stop kontratına tam uygun olarak çözülmemiş test veya dokümantasyon yükümlülüğü varsa oturum `{"decision": "continue", "reason": "..."}` ile zorunlu olarak açık tutulup ajanın işi bitirmesi engelleniyor; yükümlülükler tamamlandığında `{"decision": "allow"}` ile sonlandırılıyor. Döngü tuzaklarına karşı 5 denemelik devre kesici (`circuit-breaker`) eklendi.
  - **L4 (Git Pre-Commit Gate)**: `tools/verify_doc_governance.py` aracı yazıldı ve `.git/hooks/pre-commit` aşamasına 3. adım olarak entegre edildi. Motor veya kural dosyaları değiştirilip `CHANGELOG.md` stage edilmediğinde commit engelleniyor (`docs/KNOWLEDGE.md` §6 Same-Commit Rule).
  - **L5 (Öğrenme Defteri / Learning Ledger)**: `tools/telemetry_dashboard.py` aracına `--candidates` bayrağı eklendi. Kalıcı telemetri verilerindeki (`gravityguard_permanent_audit.jsonl`) tekrarlayan ihlal ve uyarıları analiz ederek insan denetimi (Human-in-the-Loop) için yapılandırılmış `Kural Adayları` raporluyor.
- **Test Kapsamı**: 139/139 motor testi (125'ten 139'a çıkarıldı; 14 yeni hasmane/red-team ve yönetişim testi eklendi, hepsi yeşil).
- **GitHub Actions CI** (`.github/workflows/ci.yml`) — closes the debt that 124 engine + 20 TypeScript tests only ever ran by hand, on one machine. Matrix: ubuntu / windows / macos, because cross-platform is a claim that has to be kept true rather than assumed. `npm ci` is impossible here (no lockfile is committed), so it is `npm install`; the workflow comment says so instead of leaving the next person to discover it.
  - **First run passed on all three platforms** (`36304712956`, 43s, every step green, no platform breakage). The product is a Windows-first hook, but it is pure standard-library Python that spawns real subprocesses; "works everywhere" was an assumption until this run made it a tested claim.
- **Hand-labelled intent corpus** (`tests/fixtures/intent-corpus.txt`, 32 prompts) + `tests/intent-corpus.test.mjs`. The corpus is hand-written, and its header says why: the live audit stream records file events, never prompts, so there is no ground truth to sample from. It therefore cannot prove the classifier is right about real users — only that a signal edit does not break what the author already understood. On first run it failed **4/32**, and every one of those four became a fix above. The gate is 100% with 0 low-confidence cases: a labelled prompt that needed confirmation would mean the signal set is too narrow for that phrasing.
- **A classifier with low confidence now asks instead of guessing.** `shouldAskForMode()` returns true unless the classification is high-confidence, and `handleEnhancePrompt` shows a `showQuickPick` with the current guess as the default. A silent wrong guess is worse than an extra click: an audit directive sent to an implementation request actively misleads the model and the output still looks like a normal answer. An explicit `#denetle:`-style override is never questioned.
- **Retroactive tags and releases for v1.2.6 and v1.2.7** — both were full changelog entries with no git tag and no GitHub Release, so `git describe` and the release history disagreed with the record. Tags are annotated (`v1.2.6` → a8f55a3, `v1.2.7` → 46f82f4) and state in their message that they are retroactive. The releases were published on request, with the artifacts **rebuilt from those commits** rather than reconstructed: `git archive <commit>` into a scratch tree, `npm install`, `npm run build`, `vsce package`, and then the packaged engine's md5 compared against that commit's engine — `434dccb9…` for 1.2.6 (58,622 B) and `77dae357…` for 1.2.7 (60,603 B), both byte-identical. Both assets were downloaded back after publishing and match the local build, so a 1.2.6 user gets 1.2.6's guard rather than a rebuilt approximation of it. Release notes were written for a reader who has not read the changelog, and the changelog's own detail stayed in the changelog.
- `gh` marked the most recently *published* release as Latest, so v1.2.7 briefly displaced v1.3.0 on the releases page. Restored with `gh release edit v1.3.0 --latest` — worth knowing before publishing any back-dated release. The release list is ordered by publication date, not version, so a back-dated release always floats to the top of the page regardless of the Latest flag, and v1.3.0's title was normalised to `GravityGuard v1.3.0` so all four entries are visually consistent. Publication dates were left as they are: they are the record, and the changelog already carries the real 1.2.6/1.2.7 dates.

### Changed
- **The release cadence question is now a written policy, not an open item.** The roadmap carried it as a decision waiting for the user for three revisions, which is a decision the project should have made and justified itself. Settled: changes accumulate on `main` under `[Unreleased]`; a release is cut when there is a coherent set worth shipping and at least one user-visible behaviour change, with an Upgrade Notes entry per behaviour change; bug fixes and debt closures do not require a release of their own; and if `[Unreleased]` passes ~10 commits or a month, a release is cut even without a behaviour change. The measured basis: v1.3.0 accumulated eight-plus commits, and a version per commit would have meant eight packaging and verification cycles for changes most users never see. The accumulation cost was paid in a longer notes section, which is the thing that makes a release trustworthy rather than work to be avoided. Recorded in `docs/KNOWLEDGE.md` §5.0.
- **The two engine copies are now one name, and the plugin's entry point is version controlled.**
  - **The name divergence is gone.** The live plugin script is `scripts/gravity-validator.py`, the same name as the repo file; a search for either name previously found no reference to the other, which is the same invisibility that let a dead `lefthook` sit unnoticed. The rename was done in four steps so live protection was never left unverified: copy the new file in, sync the manifest, invoke the new path exactly as the harness does, and only then remove the old file (backed up to `~/.git-hook-backups/plugin-sync/srp-validator.py.pre-rename-20260927.bak`). Verified on the live plugin afterwards: a real-looking GitHub token is **denied** with `[G0_SECRET_LEAK]` and a masked value, a clean write is **allowed**, and the old path no longer resolves.
  - **`hooks.json` and `plugin.json` are version controlled** (`plugin/`) and synced by `tools/sync_plugin.py`. `hooks.json` is the single most safety-critical line in the product: if the script name there is wrong, the hook never runs, and a hook that never runs fails open **without a trace**. Both copies previously lived only in the user profile, unversioned. `plugin.json` also claimed "9Router Swarm Batch Integration" in its description, which the 1.3.0 work made false.
  - **The sync list existed in two places, which is exactly how the old name would have come back.** `autosync_plugin.py` carried its own copy of the pair list; after the rename it would have kept writing `scripts/srp-validator.py` and quietly re-created the stale file on the next commit. It now imports the list from `sync_plugin.py`, so there is one definition. This is the real closure of the debt: not the header comment, the single source of truth.
- **T1 no longer nags a project that has no test suite.** The 1.2.6 notes recorded this case and called the warning "real" without resolving it. It is true and it is also unactionable: "the related test file" cannot exist in a project with no tests, so the advice repeats on every write until the reader stops reading warnings. `project_has_test_infrastructure()` is now a precondition: T1 stays silent until the project has a `tests/` / `__tests__` / `test` directory (an *empty* one counts — it is a declared intent) or a test-shaped file in one, and from then on behaves exactly as before. Bounded to the same six directories and three roots the candidate resolver already walks, only on the path that would have warned, short-circuiting on the first hit, so the fast path is untouched. `testEvidence.requireTestInfrastructure: false` restores the old behaviour for anyone who wants the nag on purpose. Two existing T1 tests were given a `tests/` directory rather than having the precondition weakened — they test `deferredMode` and pending de-duplication, not the zero-test case, which now has its own test.
- **Debt #3 (the "web-only checks") and debt #4 (regenerating runtime dirs) were measured and turned out not to be defects.** They sat in the register as accepted debts for months without anyone checking whether they caused harm. Both are closed by measurement rather than by code, which is the cheaper and more honest outcome:
  - **The four structural checks in `~/.git-template/hooks/loss-guard.py` are self-gating, so in a Python repository they cannot produce a false positive — they find nothing because the pattern is absent.** Each gate, quoted: `check_visual_loss` reports a lost `<svg>` / Motion / Canvas tag only when the *original* content contained one; `check_hook_loss` likewise for React hook calls; `check_ts_ignore_spike` only counts `@ts-ignore`; `check_lazy_placeholders` matches `//` and `/*` comment shapes that a `.py` file does not have. `evaluate_net_balance` returns `True` only when a staged path contains `components/`. On a Python repo each is a few regex scans returning `[]`. `check_line_drop` is language-agnostic and useful everywhere, so it stays. **No project-type gate was added**: a gate would add a code path to remove a cost that is already microseconds, and the register entry was an assumption rather than an observation.
  - **The empty `.gravityguard/runtime/` directories are the feature, not litter.** The engine creates its runtime state directory on every tool call, and the files inside it are what make T1's deferred evidence, the lint debounce and the diagnostics bridge work. They only *look* empty on a project that has never had a tool call. Deleting them changes nothing, and it is already documented in `docs/KNOWLEDGE.md` §2.1.
- **The "whisper or warning" question is settled** (ARCHITECTURE 3.3.1): `reason` is the only agent-visible text channel, so an architectural whisper is a WARN rule with its own id, never a new mechanism. `TestHookStdoutContract` gains a sibling test pinning the allowed key set, so a future attempt to add a second channel fails as a test rather than as protojson discarding the response in production.
- Test Count: **125/125 engine** (was 124) **+ 20/20 TypeScript** (was 14; +3 corpus, +3 confidence).
- `npm run test:engine` now passes `-t engine` to `unittest discover`, so the top-level directory is explicit instead of inferred from the shell's working directory.

## [1.3.0] - 2026-09-27

> **Upgrade Notes — davranış değişiklikleri.** Bu sürüm, 1.2.7'ye göre geriye dönük
> uyumlu, ama **gözle görülür davranış değişiklikleri** içeriyor. `.gravityguard.json`
> içinde kendi eşiğinizi tanımladıysanız iki kuralın davranışını doğrudan etkiler.
>
> 1. **`ARCH_FILE_GROWTH` artık büyüme olayı ölçüyor, dosya durumunu değil.**
>    Önceden "dosya 1000 satırı geçtiyse uyar" idi; bu, monolit dosyayı oluşturan
>    yazmayla, sonraki üç satırlık düzeltmeyi ve ondan sonraki her düzeltmeyi
>    *aynı* uyarıyla cezalandırıyordu. Artık uyarı, dosyayı eşiğin **üzerine taşıyan**
>    yazma için çalışır; sonraki büyümeler için 800+/80 kuralı geçerlidir.
> 2. **Yeni oluşturulan dosyalar boyutlarından dolayı uyarılmıyor.** 250 satırlık
>    yeni bir modül, tam olarak kuralların istediği sonuçtur; 1.636 gerçek dosya
>    oluşturmanın 359'u 180+ satır ekliyordu ve bunların hepsine uyarı veriliyordu.
>    Dosya **doğuştan** 1000 satırın üstündeyse yine de uyarılır.
> 3. **`srp: allow-monolith` işareti büyüme kurallarını susturuyor** (SRP kuralının
>    zaten kullandığı işaret sözlüğü). Kasıtlı olarak tek parça olan dosyalar artık
>    her yazımda uyarılmıyor. Monolit *oluşturma* yazımı yine de raporlanıyor.
> 4. **Yeni `.gravityguard.json` → `complexity` bloğu.** Anahtarlar: `monolithLoc`
>    (1000), `singleWriteLoc` (180), `creepBaseLoc` (800), `creepAddedLoc` (80),
>    `overEngineeringMaxLoc` (50), `overEngineerAbstractions` (2). Varsayılanlar
>    ölçülmüş değerlerdir; geçersiz bir değer yok sayılır, hata fırlatılmaz.
> 5. **Prompt Geliştirici artık yerel AI geçidine zorunlu bağımlı değil.** Geçid
>    kapalıysa komut hata vermez; belirlenimci çevrimdışı şablon moduna düşer ve
>    bunu bildirimde açıkça söyler. `ping` komutu artık gerçek bir sağlık kontrolü
>    yapar.
> 6. **Yeni niyet sınıflandırıcı.** İstekler artık `İSTİŞARE` / `UYGULAMA` /
>    `DENETİM / REFACTOR` modlarından birine **yerelde** karar verilir ve modele
>    yalnızca o modun direktifi gönderilir. `#denetle:`, `#danış:`, `#kodla:`
>    öneki kararı siz geçersiz kılar.
>
> **Etkilemeyenler:** hiçbir BLOCK kuralı, hiçbir eşik değeri ve `G0`–`G4`, `SRP`,
> `T1`–`T3` kural semantiği değişmedi. `OE_SPIKE` ölçümde zaten doğru bulunduğu
> için **bilerek değiştirilmedi** (fire rate %1,27).

### Fixed
- **Every edited file created its own `.gravityguard` directory (non-git projects)**:
  - `find_project_root()` recognized only `.gravityguard.json` and `.git` as project-root markers. Any project without a git checkout — a Godot project, a bare npm package, a standalone Python tool — matched neither, so resolution fell through to `return p.parent if p.is_file() else p`. Because GravityGuard is a `PreToolUse` hook, `get_runtime_dir()` then ran `mkdir(parents=True)` on that guess, and each file landed in a different directory, so each write produced a fresh state tree.
  - Measured on a real Godot project: four edits across `src/map/`, `src/data/`, `tools/` and `tools/fixtures/` produced **four** `.gravityguard` trees. After the fix the same four edits produce **one**, at the project root. The two functions ran with identical inputs, which is what makes the divergence provable rather than inferred.
  - Fix, in two parts:
    1. **Root markers** now cover the ecosystems actually in use — `project.godot`, `package.json`, `tsconfig.json`, `pyproject.toml`, `setup.py`/`setup.cfg`, `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle[.kts]`, `composer.json`, `Gemfile`, plus `.hg`/`.svn`.
    2. **Working-directory anchor.** The hook spawns the runner without a `cwd` argument, so the runner inherits the agent's workspace directory — already relied upon by `get_test_evidence_file_path()` (`gravity-validator.py`). When that directory is a genuine ancestor of the target it is now the root, which rescues a real project that carries no manifest at all. A cwd that is *not* an ancestor is still rejected, so an unrelated directory can never be adopted.
  - **Trust gate.** Root resolution and directory creation were split. `get_runtime_dir()` now only `mkdir`s for a root that is marker-anchored, already holds a `.gravityguard` directory, or is the working directory. The file-parent fallback remains reachable for unresolvable paths, but it is treated as a *guess* and is never created into — the "misread becomes mkdir, therefore a bogus tree inside the user's source" chain documented in 1.2.6 no longer has a path to run.
  - **Trade-off, stated explicitly:** an untrusted root now silently persists nothing instead of persisting to the wrong place. That is the safer failure direction — the guard's diagnostics and debounce state are advisory, whereas an unrequested write into a source tree is not recoverable by the user. The two functions are asserted to agree, since a root that resolution can return but that creation refuses would make state a silent no-op.
  - `CHANGELOG.md:73` in v1.2.5 had already noted two such mojibake/empty shells, each holding a lone `debounce_state.json`. Detected, never fixed — this is that fix.
- **`is_ts_cohesive_monolith()` was the wrong predicate for a monolith exemption.** It answers "is this an ordinary module rather than a tabbed web page?" and returns `True` for nearly every TypeScript file, so the first cut of the marker check exempted almost everything. Replaced with `_has_declared_cohesion_marker()`, which matches only the marker comment. Caught by an existing test — `test_arch_file_growth_creeping_growth_800_plus_80_triggers_warn` went silent — which is the argument for keeping these as behaviour tests rather than unit tests of the predicate.
- **The 1.3.0 package shipped 15 files / 80.33 KB instead of 10 / 54.69 KB**: `.vscodeignore` was written when `tests/` and `docs/` did not exist, so `tests/intent.test.mjs`, `docs/KNOWLEDGE.md`, `.kilo/.gitignore` and four `dist/*.js.map` files entered the artifact unnoticed. The engine was correct; the artifact was 46% larger than it should have been, carrying a test file and source maps to every user's extension directory. Fixed by extending `.vscodeignore` (`tests/`, `docs/`, `.kilo/`, `dist/**/*.js.map`) and by adding the check that should have existed since 1.2.5 (below), which is what caught it.
- **`test_sub_50ms_performance` measured the host, not the guard.** The assertion was a fixed 400 ms ceiling on `python.exe` spawn. Measured four times on identical code during this cut: **268 ms idle → 1184 ms with three other agent sessions compiling on the machine** — it failed 3 runs out of 4, at random, while catching nothing. Worse, it was not sensitive to the defect it names: a 300 ms `sleep()` at import time would have passed it. It is now measured **differentially** against a `python -c pass` control in the same time slice, asserting the validator's own import + evaluation stays a small multiple of the interpreter's own startup (with a 1500 ms absolute backstop). That is stable under load and strictly more sensitive. The real product invariant is unaffected: `test_core_in_memory_latency` still asserts the in-memory path at `<10ms` (measured 0.1084 ms avg / 0.1388 ms p95 over 1,000 runs), and the differential measurement shows the validator adds ~17 ms of its own on top of interpreter startup.

### Added
- **`TestProjectRootResolution`** (6 tests): manifest anchoring, single-runtime-dir invariant, working-directory anchoring for a markerless project, rejection of an unrelated cwd, the no-mkdir trust gate, and resolution/creation agreement.
- **Local intent classifier (`src/intent.ts`) — the intent is now decided in the extension, not delegated to the model**:
  - Until now the "intent detection" was a paragraph of system prompt asking the *downstream* model to classify the user's own request. ROADMAP 2.2 flagged this as `[~]` for exactly that reason: there was no classifier, only an instruction. Behaviour depended entirely on the model's compliance, and nothing in the repository could prove it complied.
  - `classifyIntent()` is a deterministic weighted-keyword scorer over Turkish and English signals. It returns `{ mode, confidence, score, runnerUpScore, signals, source }`, so a decision can be explained and asserted rather than hoped for. The model no longer receives intent-classification instructions at all: it is told which mode it is in, and the other two directives are never sent.
  - **The user can override it.** A `#denetle:` / `#danış:` / `#kodla:` prefix (also `[audit]:`, `#code:`) pins the mode, reported as `source: 'override'`. A classifier the user cannot contradict is a classifier the user will not trust.
  - Ties resolve towards `consult` when the consult score is the higher of the equal pair, and a prompt with no signal at all resolves to `implement` (the mode the feature was originally built for) with `confidence: 'low'` — a guess, labelled as one.
  - Determinism is a tested property, not an aspiration: `tests/intent.test.mjs` asserts identical output for identical input, and that the decision always carries at least one signal.
- **Directive C — DENETİM / REFACTOR mode** (the mode ROADMAP 2.2 listed as absent):
  - Forbids producing new production code, requires findings with `dosya:satır` evidence, an impact rating per finding, and a separate list for anything that could not be verified — a suspicion must not be presented as a finding.
  - Names the inspection targets explicitly: layer and dependency boundary violations, SRP violations, dead code and duplicated logic, swallowed errors, embedded credentials, comment/behaviour divergence, and test integrity (deleted, silenced, or hollowed-out tests).
  - Restates the integrity boundary: with G2 active, a suggestion to delete or skip a test may be written as a note, never applied. This is the AI-side half of Anti-Goal 5.
  - Refactor advice must be split into small, revertible steps, each with its own verification method.
- **`complexity` block in `.gravityguard.json`**: `monolithLoc`, `singleWriteLoc`, `creepBaseLoc`, `creepAddedLoc`, `overEngineeringMaxLoc`, `overEngineerAbstractions`. Values below a per-key floor (`monolithLoc: 3` would flag every file), non-numeric values, booleans, and a malformed block are all ignored and degrade to the defaults. The block is a convenience, not a boundary: a typo must never turn a WARN-only rule into a hook error, which would fail the write open.
- **Offline deterministic composer (`buildOfflinePrompt`)**: when no local model answers, the enhancer produces a structured brief from the classified mode instead of showing an error. Same event the user asked for, one prompt, plus a notification that says it came from the offline path.
- **`tools/verify_package.py` + `npm run verify:package`**: the 1.2.5 rule ("the packaged engine must be byte-identical to the repo engine, so a release artifact can never ship a stale guard") had been verified by hand, exactly once. It is now a repeatable gate: it checks the artifact's required files, compares the md5 of both packaged engine modules against the repo, and rejects forbidden content (`tests/`, `docs/`, `tools/`, `brain/`, `.kilo/`, `src/`, `*.js.map`, `.env`, `*.bak`) from an explicit list — because `.vscodeignore` only encodes the intent and rots silently when new directories appear. It also encodes `dist/intent.js` as **required**, so a future over-eager ignore rule cannot quietly remove the intent classifier from a shipped build.

### Changed
- **Version 1.3.0.** `package.json` 1.2.7 → 1.3.0. `package.json` scripts gained `package` and `verify:package` alongside `test` / `test:engine`.
- **Published.** Tag `v1.3.0` pushed, and the GitHub Release created with the artifact attached: `https://github.com/halilogia/GravityGuard/releases/tag/v1.3.0` (`gravityguard-1.3.0.vsix`, 67,015 B, marked Latest). Verified by **downloading the asset back** and comparing md5 (`898E0802…`) against the locally built file — byte-identical, so the artifact on the release page is provably the one this tree produced. Final package: **10 files / 65.44 KB**, with `dist/extension.js`, `dist/intent.js` and both engine modules md5-identical to the repo. The same engine md5 (`010966a0…`) is also what the live plugin copy is running.
- Test Count: **124/124 engine tests passing** (was 118/118; +6), plus **14/14** TypeScript tests (`npm test`) for the classifier and prompt composer — a new zero-dependency `node --test` suite in `tests/intent.test.mjs`, wired to `npm test` / `npm run test:engine`. Two pre-existing tests now anchor their temp roots with a manifest: they exercised state round-tripping, not the trust policy, and were passing only because `get_runtime_dir()` once created directories unconditionally.
- **9Router is no longer a hard dependency of the prompt enhancer** (previously the only thing standing between `Ctrl+Alt+E` and an error dialog):
  - `gravityguard.models` (array) and `gravityguard.routerTimeoutMs` (number) are new settings; `ROUTER_MODELS` is honoured as an env fallback. Any OpenAI-compatible `/v1` endpoint works — 9Router, Ollama, LM Studio, llama.cpp — so the extension is no longer coupled to one gateway's model naming.
  - **Connection-level failures abort the cascade.** `ECONNREFUSED` / `ENOTFOUND` / `EHOSTUNREACH` and friends mean no model behind that host can answer, so the remaining models are skipped instead of each burning its own timeout. A stopped gateway now costs one connection attempt rather than three model attempts; model-level failures (HTTP errors, empty content, timeouts) still fall through to the next model, which is what the cascade is for.
  - `antigravityBridge.ping` performs a real health check (`GET /v1/models`, 3s) and reports the endpoint, the model count, or the exact connection error. It previously reported "🚀 GravityGuard is Live!" unconditionally, which was true of the extension and said nothing about the dependency it depends on.
  - The user-facing strings no longer name 9Router: the feature works against any local gateway, and an error message naming a specific product misleads everyone who is not running that product.
  - ARCHITECTURE invariant 2 ("the guard engine *and* the prompt enhancer function fully offline") was previously aspirational for the enhancer. It is now true.
- **Complexity threshold calibration (6,404 real production file-writes across 11 repositories)**: the numbers did not move, but two rules were measuring the wrong thing.
  - **Method.** `git log --numstat` over the last 400 commits of each repository under `GitHub/Public`, one file per commit as the unit of work (the closest available proxy to a per-tool-call diff), test files excluded. File sizes come from the corpus at HEAD, which over-estimates the size at older commits — noted because it biases the *absolute* rule downward, i.e. against the change being justified.
  - **Rule A became a crossing event, not a file state.** `projected_loc >= 1000` is a *state* check: a three-line fix to a 1,200-line file produced the same "you are building a monolith" warning as the write that created the monolith, and would produce it again on the next one, forever. Measured: 60 writes land on files already past the line, and only **30** of them carry a material addition — **half of rule A's fires told the agent nothing it had not already been told**, on repeat. It now fires on the write that *crosses* the line. No coverage is lost: for any modification, passing 1,000 lines implies an addition large enough to trip the creep rule anyway, so rule A is redundant there; its only load-bearing case is a file created over the line, which still fires. In this repository the effect is direct — 53% of its own production writes (17 of 32) targeted an already-large file.
  - **Rule B no longer fires on file creation.** 1,636 of the writes were file creations and **359 of them added 180+ lines** — 21.9% of creations versus 4.3% of modifications. A brand-new cohesive module of 250 lines is exactly the outcome the rule asks for; warning on it penalises modularisation. The rule now applies to additions to an *existing* file, where "a huge block was dumped into something that already existed" is a real smell.
  - **`srp: allow-monolith` now silences the growth rules too.** The escape hatch already existed for the SRP boundary rule, so the same marker vocabulary is reused rather than invented twice. It deliberately does **not** suppress rule A: the marker means "this file is intentionally one unit", so incremental growth is not news, but the write that makes a file a monolith is still worth reporting. A WARN-only rule is the right place for a human-authored exemption.
  - **OE_SPIKE was left alone, on evidence.** Its fire rate is 59 / 4,639 eligible writes (**1.27%**), and only **2 of those 59** are attributable to conventional scaffolding (exceptions, dataclasses, Protocols, Enums) — a scaffolding exemption would change 3% of fires and is not worth the code. Raising the declaration threshold to 3 would cut fires by 68% (59 → 19) but would also drop genuinely coupled pairs, which is most of what remains. **Tuning a number that measurement says is already right is not tuning.**
  - **Latency, measured A/B against `git HEAD` in an interleaved run (4,000 iterations each, same time slice):** median 0.0854ms vs 0.0852ms, **1.015x — within noise.** The first implementation regressed 1.35x by copying the threshold dict on every call, which is why thresholds are now resolved once per tool call and the default mapping is shared rather than copied. The marker scan was also moved behind the condition it can affect, since it walks the whole projected file and can only ever suppress the growth reasons.

## [1.2.7] - 2026-09-21

### Fixed
- **G0 Secret Leak Fast-Pass Bypass (Critical Security Boundary)**:
  - In v1.2.6 and earlier, `is_vendor_or_cache` and `is_data_or_doc` bypassed the validator prior to running `check_g0_secret_leak()`. This allowed plaintext secrets and tokens to be written without inspection into configuration files (`.json`, `.yaml`, `.yml`, `.toml`, `.ini`), documentation (`.md`, `.txt`), vectors (`.svg`), lockfiles (`.lock`), or vendor/cache paths (`node_modules`, `venv`).
  - Fix: The pipeline order was inverted. Fast-pass is now strictly restricted to non-text pure binary assets (`.png`, `.jpg`, `.blend`, `.exe`, etc.). All text files (code, config, docs, vendor) are unconditionally scanned by G0. Only after G0 passes are non-code/vendor files fast-passed.
  - Added AWS Access Key ID regex (`\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b`) with dummy placeholder tolerance.

- **T1 Premature PreToolUse Warnings (Stateful Test Evidence Airbag)**:
  - In v1.2.6, when an AI agent created a new production file (e.g. `service.ts`), `check_t1_missing_test()` executed during `PreToolUse` before the file was written to disk. Because test files (`service.test.ts`) are typically created in subsequent tool calls, T1 emitted an immediate `T1_MISSING_RELATED_TEST` warning on every new file write, creating false noise.
  - Fix: T1 is now stateful. When production code is written or updated without immediate test evidence, the pending expectation is saved to `.gravityguard/runtime/test_evidence_state.json`.
  - When the corresponding test file is written or updated in subsequent tool calls, the pending entry is automatically resolved.
  - Consolidated unresolved T1 warnings are surfaced during final evaluation (`Stop` / `PostInvocation` hook or `--stop` CLI flag).
  - Backward compatibility: `testEvidence.deferredMode: false` in `.gravityguard.json` restores legacy immediate PreToolUse warnings.
  - Added fnmatch glob pattern support to `testEvidence.exemptPatterns` (e.g. `src/components/*`, `*.config.ts`).

- **Test File Path Classification Refinement**:
  - `is_test_file` previously checked `"test_"` as an arbitrary substring of the full path, causing files within temporary directories containing `test_` in their parent path to be misclassified as test files. Path classification now isolates filename tokens (`test_*`, `*_test.*`, `*.test.*`, `*.spec.*`) from directory segments (`/tests/`, `/test/`, `/__tests__/`).

### Added
- **`TestV127G0ZeroBypassAndStatefulEvidence`** (11 tests):
  - G0 secret scans in `.json`, `.yaml`, `.svg`, `.md`, and vendor paths are blocked.
  - G0 AWS access key detection and placeholder tolerance.
  - G0 clean non-code files pass without false positives.
  - Stateful T1 lifecycle: pending state creation, auto-resolution on test write, clean Stop hook.
  - Glob support in `testEvidence.exemptPatterns`.
  - Backward compatibility test for `deferredMode: false`.

### Changed
- Test Count: **104/104 passing** (was 93/93; +11 new regression and lifecycle tests).
- Anti-bloat invariant intact: in-memory guard logic execution avg **0.029–0.030 ms** (bound < 10 ms).

## [1.2.6] - 2026-09-21

### Fixed
- **Non-ASCII Paths Were Corrupted, and One Class of Them Crashed the Guard Open (Windows)**:
  - `hooks.json` launches the guard as a bare `python scripts/srp-validator.py`. On Windows that does **not** enable UTF-8: measured on the affected host, `sys.flags.utf8_mode == 0` and `stdin`/`stdout`/`stderr` all default to `cp1252`, while the harness writes its JSON payload as **UTF-8 bytes**. Three distinct harms followed from that single mismatch:
    1. **Lossy decode.** Non-ASCII paths were reinterpreted as mojibake — the live audit log literally contained `PropogandasÄ±nÄ±n sÃ¶ylem` instead of `Propogandasının söylem`. The guard then queried a path that does not exist and silently lost the target file's real content, degrading the T1/T3 evidence checks.
    2. **A bogus directory tree inside the user's project.** Because `get_runtime_dir()` creates its directories with `mkdir(parents=True, exist_ok=True)`, the corrupted path did not merely misread — the guard *created* a mojibake-named folder next to the real one.
    3. **Hard crash → FAIL-OPEN.** Characters absent from cp1252 decode to lone surrogates, so `ast.parse()` raised `UnicodeEncodeError` (`ast.parse` was the only unguarded call site; the other two already used `except Exception`). The process exited 1 with **empty stdout**. A hook that returns no decision does not block the write, so **the guard was bypassed silently** — a security-boundary failure, not a cosmetic logging bug.
  - Measured crashing inputs: `U+201D` (the typographic right double quote that Word inserts automatically) and `ZWJ U+200D`. Twenty-six other tested non-ASCII characters, including every Turkish letter, were safe.
  - **Proof of fail-open:** a probe file containing `U+201D` was written to disk with **zero** audit entries; an ASCII control probe produced 2 entries.
  - Fix: both entry points (`gravity-validator.py`, `async_runner.py`) now force `stdin`/`stdout`/`stderr` to UTF-8 with `errors="replace"` at import time, so the guard is correct regardless of how it is launched instead of depending on a launcher flag that lives outside version control. The sole unguarded `ast.parse` gained a defensive fallback to the regex path, re-raising inside the fallback so the underlying defect stays visible.

- **G0 Denied Legitimate Files Containing Sample Private Key Blocks**:
  - The G0 PEM rule (`check_g0_secret_leak`) matched `-----BEGIN ... PRIVATE KEY-----` and denied immediately, **without ever inspecting the body**. Every neighbouring rule (GitHub, Anthropic, OpenAI, Gemini, Slack) guarded itself with `if not is_placeholder(...)`; the PEM rule alone did not. The inconsistency was the defect.
  - Consequence: any test or documentation file containing a sample key block could not be written at all. Measured occurrence: `engine/test_gravity_validator.py` — GravityGuard's **own G0 test** — caused the commit-time secret scanner to reject a legitimate commit (`[KRITIK GUVENLIK ENGELI] ... engine/test_gravity_validator.py`). The project could not commit its own tests.
  - Fix: PEM matches are now classified as fixtures when the body is provably non-live. A real key body is hundreds of base64 characters and **cannot contain `.`** (not in the base64 alphabet), so an ellipsis or a body under 48 base64 characters is conclusive evidence of sample data. The same check was added to the standalone commit-time scanner (`~/.git-template/hooks/guard/secret_checker.py`) and propagated to all 12 repository hook copies (MD5-verified, zero remaining drift).
  - **This is a deliberate, narrow relaxation of a security control, and the threshold is a judgement call — not a standard.** Justification for the size of risk: an elided key is unusable, because base64 decoding fails and no partial key can be reconstructed from a truncated body. The margin is conservative: a real RSA key body is ~1600 characters and an EC key ~230, while the shortest possible real PEM still exceeds 64. Verified end-to-end against the live hook: **8/8** cases behaved correctly, including full-length RSA, EC, OPENSSH, PGP **and** DSA keys, which are all still denied.
  - `test_g0_block_private_key` was **not** weakened to accommodate this: it was re-pointed at a real-length body so the exemption cannot mask a genuine key. A companion test (`test_g0_allows_elided_pem_fixture`) covers the fixture case. Both the test bodies and headers are assembled at runtime, so the test file contains no literal PEM block that would trip the scanners it is testing.
- **`ROADMAP.md` had 25 corrupted lines**: a botched patch left a literal `+` prefix on every line of §3.6 and §3.7, so the `### 3.6.` heading rendered as `+### 3.6.`. Prefixes stripped; the file went 145 → 144 lines.

### Added
- **`TestWindowsEncodingRegression`** (3 tests): the typographic quote must yield a valid decision rather than kill the process; the guard must leave an audit entry (silence would mean it failed open); and a Turkish path must cross the stdin boundary verbatim.
- **`run_validator_raw_bytes()`** test helper: writes the payload as raw UTF-8 bytes with `ensure_ascii=False` and deliberately does **not** pass `-X utf8`, mirroring `hooks.json` exactly.
- The pre-existing `run_validator()` used `text=True` and `json.dumps`' default `ensure_ascii=True`, so its payload was **pure ASCII** — the one configuration immune to this bug. That is precisely why 89 green tests coexisted with a guard that was broken in production; the suite could not have observed the defect.
- **PEM fixture regression tests** (`guard_test.py`, 3 tests) covering both directions: sample blocks allowed, full-length real keys still blocked, so the control cannot silently weaken.

### Changed
- Test Count: **93/93 passing** (was 89/89; +3 encoding, +1 elided-PEM fixture). The 3 encoding tests were confirmed **non-vacuous**: they fail 3/3 against the pre-fix validator and pass 3/3 after it.
- `guard_test.py` (commit-time scanner suite): 9/9 passing (was 6/6; +3 PEM).
- Anti-bloat invariant intact: in-memory guard logic measured avg **0.051–0.069 ms**, p99 **0.175–0.995 ms** (bound < 10 ms).

### Notes
- **Scope limit:** this fixes encoding and the G0 false positive, not the T1 policy. `T1_MISSING_RELATED_TEST` is `WARN ONLY` (returns `decision: allow`) and still fires on the affected project, because that project genuinely contains zero test files. Silencing it requires either adding tests or a `.gravityguard.json` exemption — a separate, deliberate choice.
- Nothing was deleted from the user's project: the two mojibake folders removed were guard-generated empty shells containing a single `debounce_state.json`, and the real 251-file project folder was verified intact afterwards.

## [1.2.5] - 2026-09-20

### Added
- **Packaging support** — first `.vsix` build:
  - Added `.vscodeignore`. Without it the packager bundles `node_modules/`, the test suite, `brain/` and `tools/` into the artifact. The resulting package carries 10 files (54.69 KB): the compiled extension, both engine modules, `media/shield.svg`, `LICENSE`, `README.md`, `package.json`.
  - Added `repository`, `bugs` and `homepage` to `package.json`; the packager requires the repository field.
  - Verified the packaged engine is byte-identical to the repo engine (`md5 b3eac45e…`), so a release artifact can never ship a stale guard.
  - `*.vsix` is gitignored — build artifacts attach to the GitHub Release, they are not committed.

### Fixed
- **`engines.vscode` and `@types/vscode` were inconsistent**, and `vsce package` refused to build:
  - `@types/vscode` declared `^1.134.0` while `engines.vscode` advertised `^1.80.0`. The packager rejects a type package newer than the declared engine, because the extension could then reference APIs absent from the engine it claims to support.
  - Both are now pinned to `^1.107.0`, matching the Antigravity IDE build actually running on this machine (`product.json` → `1.107.0`, quality `stable`). The previous `^1.80.0` figure was never verified against a real host.
  - All 14 `vscode.*` APIs used by `src/extension.ts` exist in 1.107.0.
- **Wrong GitHub account in install instructions:** `README.md` and `package.json` referenced `halilemre`, while the actual remote is `halilogia/GravityGuard`. The documented `git clone` command would have failed. Both now match the remote.

- **Hook Stdout Violated the PreToolUse Schema — Silently Blocked Every File Write**:
  - On the WARN path the validator printed `{"decision": "allow", "warnings": [...], "warning_rule_ids": [...]}`.
  - The Antigravity hook contract permits only `decision`, `reason`, `permissionOverrides` and `overwrite`; payloads are protojson-encoded and protojson **rejects unknown fields**.
  - The harness therefore discarded the **entire** response (`proto: unknown field "warnings"`). An intended, non-blocking warning became a hard tool failure, so `write_to_file` / `replace_file_content` / `multi_replace_file_content` were blocked outright instead of merely annotated. The failure mode was inverted: the *safer* the guard (WARN, not DENY), the more damaging the outcome.
  - Warnings are now folded into `reason` — the only schema-valid field surfaced to the user/agent — formatted as `[RULE_ID] message` and joined with `" ⚠ "`, so rule IDs stay machine-readable via the prefix.
  - Confirmed occurrence: `antigravity/brain/2e98ccd8-...` (Antigravity 2.0), 10 matches of `failed to unmarshal result from hook`. In that session the agent could not use the file-writing tools at all and fell back to PowerShell.
  - Scope note: the same hook code is shared, so the IDE/CLI were equally exposed. A genuine occurrence in the IDE logs was **not** found (the IDE hits were a different, unrelated payload); this fix is preventive there, not a confirmed reproduction.

### Added
- **Stdout contract regression tests** (`TestHookStdoutContract`): the warn path must emit no schema-invalid key, must still deliver its warning through `reason`, and a clean edit must emit a minimal allow.
- **Schema gate in the test harness**: `run_validator()` now asserts `set(res.keys()) <= {decision, reason, permissionOverrides, overwrite}`. The previous harness used plain `json.loads`, which accepts any key — which is precisely why the suite stayed green while the live guard was blocked. A protocol-level bug was invisible to a protocol-blind test.

### Changed
- Warning assertions migrated from `res.get("warning_rule_ids", [])` to `_warnings_from(res)` (reads `reason`); substring semantics preserved.
- Test Count: 89/89 passing (was 87/87).

### Notes
- No governance guard was altered: no block/warn threshold, no TSC debounce, no hidden-console spawn contract. The `deny` paths already emitted only `decision` + `reason` and were correct.
- Whether `allow` + `reason` is *rendered* to the agent is documented as "shown to the user/agent" but was not empirically verified. The field is schema-valid either way, warnings remain in the audit log, and the previous behaviour is strictly worse regardless of the answer.
- `package.json` had drifted to `1.2.3` while `1.2.4` was already released; corrected to `1.2.5`.

## [1.2.4] - 2026-09-20

### Fixed
- **Test Suite Was Flooding the Real Security Audit Log**:
  - Every `run_validator()` call spawned a real `python.exe` that appended to the *live* audit stream (`~/.gemini/logs/srp_guardian_live.json`) via a hard-coded path in `log_event()`.
  - The stream keeps only the newest 50 events (`events[:50]`), so a single suite run (64 spawns) evicted **every** genuine security event. The Live Security Monitor webview therefore displayed test fixtures (`C:/fake_project/...`, `%TEMP%\tmp...`) as if they were real activity.
  - `log_event()` now resolves its directory through a new `_resolve_log_dir()` helper, which honours a `GRAVITYGUARD_LOG_DIR` environment override and falls back to `~/.gemini/logs`.
  - The test harness points that variable at a per-run temp directory **before** the first spawn, so every child inherits the redirect.
  - Verified: after a full suite run the live log contains 0 fixture targets, and its real events are preserved.
- **Malformed Audit Log Discarded History**: when the JSON log existed but failed to parse, the `except` branch silently kept the pre-built empty structure. It now resets to a valid default explicitly instead of relying on an unstated fall-through.
- **`%TEMP%` Leak**: the harness's isolated audit directory was never deleted, so every suite run left a `gg_audit_*` folder behind. Registered `atexit` cleanup via `shutil.rmtree(..., ignore_errors=True)`.

### Changed
- **De-flaked `test_sub_50ms_performance`**: the test averaged 5 measurements, so one scheduler/antivirus outlier (observed worst case: 329 ms against a 250 ms threshold) failed the suite. It now takes the **median**, prints min/max for diagnosis, and uses a regression-oriented 400 ms bound. The genuine latency invariant is still covered strictly by `test_core_in_memory_latency` (< 10 ms, measured ~0.03 ms) — this test only guards against spawn latency regressions.

### Notes
- No behavioural change to any governance guard (G0-G4, SRP, T1-T3, ARCH, OE), to the TSC debounce, or to the hidden-console spawn contract.
- Test Count: 87/87 passing.

## [1.2.3] - 2026-09-20

### Fixed
- **TSC Debounce Worker Lifecycle Deadlock**:
  - `run_debounce_worker()` exited on the `max_lifetime` guard (120s) **without** clearing `worker_running` in `debounce_state.json`.
  - Sequence: worker claims `worker_running = True` → an edit burst exceeds 120s → the guard fires → the process exits → the persisted flag stays `True` → `trigger_debounce_worker_if_needed()` sees an "active" worker forever and never spawns another one.
  - The safety mechanism disabled the feature it was protecting: the TSC debounce silently stopped working with no error surfaced.
  - The guard now clears `worker_running = False` before exiting, but only when the state file still exists — an absent state file is never re-created, so the deleted runtime directory tree is not resurrected.
  - The project-root and state-file-missing exit paths were deliberately left unchanged.

### Added
- **Lifecycle Regression Tests**: `max_lifetime` expiry must release the claim (followed by a `should_spawn_worker()` consequence check proving a new trigger can claim again), plus a companion test asserting an absent state file is not re-created. Both use a mocked clock — no real 120s wait.
- **Test Count**: 87/87 passing (was 85/85).

## [1.2.2] - 2026-09-20

### Fixed
- **Newly Created Files Were Never Linted**:
  - GravityGuard is a `PreToolUse` hook, so it fires **before** the AI writes the file. `async_runner.py`'s `main()` bailed out with `sys.exit(0)` when the target did not exist yet, so a file created *after* the worker spawned was never linted.
  - Removed that early exit. The per-file coalescing worker now waits its 300 ms quiet window, then spends a **bounded** grace period (2.0 s) for the file to appear.
  - If the file lands, the normal linter runs once. If it never lands, the worker releases its claim and exits silently — no infinite wait, no state leak.
  - `execute_single_file_lint()` retains its own existence check as the final safety net.
- **Documentation Accuracy**: replaced absolute concurrency claims ("exactly 1 worker", "never block") with *state-based duplicate suppression*, since the claim is not a mutex and concurrent `load → claim → save` sequences are not formally atomic.

### Added
- **Regression Coverage for the New-File Path**: `target file initially absent → worker waits → file appears → lint called exactly once`, plus a companion test asserting a never-written file exits cleanly. Both use a mocked clock (`time.sleep` / `time.time` patched) — no real sleeps, no subprocesses.
- **Test Count**: 87/87 passing (was 85/85). Added lifecycle regression tests for the `max_lifetime` claim release.

### Changed
- `async_runner.py` pure helpers: added `should_wait_for_target_file()`; added `_await_target_file()` polling helper. No changes to the TS debounce behavior or governance guards (G0-G4, SRP, T1-T3, ARCH, OE).

## [1.2.1] - 2026-09-20

### Fixed
- **Visible Terminal Windows on Windows (Regression Fix)**:
  - Background validation spawned subprocesses with `DETACHED_PROCESS` (`0x00000008`). A detached process owns **no console**, so every console child it launched (`cmd.exe` via `npx`, `ruff.exe`, `godot.exe`, `node.exe`) allocated a brand-new **visible** console window — the source of the flashing terminal windows.
  - Replaced with `CREATE_NO_WINDOW` (`0x08000000`) plus `STARTUPINFO` / `SW_HIDE`, which grants a hidden console that all descendant processes inherit.
  - Routed **all** Tier 2/3 linter invocations through one `run_hidden()` policy in `engine/async_runner.py`; previously `subprocess.run` was called with no window-suppression flags anywhere.
  - Applied the same hidden-spawn policy to the debounce worker in both `engine/gravity-validator.py` and `engine/async_runner.py`.
- **Orphaned Process Accumulation**: a timed-out linter previously left `cmd.exe`/`node.exe` grandchildren running (the direct child was killed but not its tree). Added `_kill_process_tree()` using `taskkill /F /T` on Windows.
- **Runaway Debounce Worker (Infinite Loop)**:
  - `run_debounce_worker()` used `while True` and could only exit through `should_run_after_idle()`, which **always** returns `False` when `last_edit_time <= 0.0`.
  - If `debounce_state.json` disappeared (temp workspace cleaned up, deleted project), the worker spun forever in 3-second intervals. Worse, `get_runtime_dir()` calls `mkdir` on every pass, so the worker kept **re-creating the deleted directory tree**, making the orphan self-sustaining.
  - Verified live: 4 zombie `--debounce-worker` processes with dead parents but re-created project roots under `%TEMP%`.
  - Added four termination guards (quiet window reached, project root gone, debounce state gone, `last_edit_time <= 0`) plus a hard `max_lifetime` bound (120s). Replaced `break`/`continue` with explicit `return`.
- **Test Harness Hermeticity**: added the `GRAVITYGUARD_DISABLE_ASYNC=1` kill switch, honored by both spawn paths. The suite sets it before importing any module, so no test can launch a real background worker.
- **Test Count**: 83/83 passing (was reported as 81/81). Added regression tests for the hidden-console contract and for the kill switch.
  - Note: the suite sets `GRAVITYGUARD_DISABLE_ASYNC=1`, so it exercises guard/decision logic but does **not** spawn real Windows process trees. The new-file path is covered by a mocked-clock test (see 1.2.2).

### Changed
- Documentation (`ARCHITECTURE.md`, `README.md`) no longer describes `DETACHED_PROCESS` as the spawn mechanism; the hidden-console contract is documented instead.

## [1.2.0] - 2026-09-20

### Added
- **ARCH_FILE_GROWTH Guard (Fast Guard — WARN ONLY)**:
  - Multi-condition heuristic radar detecting uncontrolled monolithic code accumulation without blocking the AI agent.
  - Triggers on: (1) Projected lines >= 1000, (2) Single tool-call addition >= 180 LOC, or (3) Creeping growth on 800+ LOC files with >= 80 LOC additions.
  - Exemption rules for test files (`test_*.py`, `*.test.ts`, `*.spec.ts`) and configured cohesive modules.
- **Detached Asynchronous Orchestration & Background Trigger**:
  - Implemented `trigger_background_validation(target_file)` in `engine/gravity-validator.py`.
  - Spawns `engine/async_runner.py` as a background OS subprocess without waiting for completion (returns in ~1 ms).
  - Superseded in `1.2.1`: originally used `DETACHED_PROCESS`, which caused visible console windows; now uses `CREATE_NO_WINDOW` + `SW_HIDE`.
  - Evaluates changed code files strictly in the background without adding any synchronous delay to the AI tool-call loop.
- **State-Based TypeScript Debounce Worker**:
  - Implemented `run_debounce_worker` and `trigger_debounce_worker_if_needed` in `engine/async_runner.py`.
  - Persists state in `.gravityguard/runtime/debounce_state.json`.
  - Enforces a real 3.0-second idle window after tool bursts before triggering `tsc --noEmit`, completely eliminating repetitive compiler executions during rapid AI edits.
- **Tier 2 / Tier 3 Diagnostics State Bridge**:
  - Background findings recorded in `.gravityguard/runtime/diagnostics.json`.
  - `STATIC_LINTER_DIAGNOSTIC (WARN)`: Injects recent background linter findings into AI context during subsequent pre-tool calls (< 0.5 ms).
- **Per-File TypeScript Diagnostics Integration**:
  - Implemented `parse_tsc_output` in `engine/async_runner.py` parsing raw compiler output (`file(line,col): error TSxxxx: message`) into normalized per-file diagnostic entries.
  - Resolved the critical feedback loop gap: `read_recent_diagnostics(target_file)` now matches TypeScript compiler errors directly against modified target files (e.g. `auth.ts`) instead of dropping them in an unindexed global bucket.
- **Per-File Lint Burst Coalescing & Worker State Cleanup**:
  - Implemented 300 ms quiet-window coalescing (`run_coalesced_file_lint_worker`, `should_spawn_file_worker`, `should_run_file_lint`) in `engine/async_runner.py`.
  - Dedupes rapid consecutive edits (bursts) on the same file via state-based suppression: the first trigger claims the file in `debounce_state.json`, subsequent triggers within the window update the timestamp and exit immediately. For sequential tool calls this yields a single linter run; the claim is best-effort rather than a formally atomic mutex.
  - Once the 300 ms quiet window elapses with no further edits, linter runs once against the final file state.
  - Multi-file isolation: edits across different files (e.g. `auth.ts` vs `calc.py`) maintain separate claims and do not block each other.
  - State cleanup: `clean_file_state` automatically deletes `active_lint_workers` and `file_edits` records upon completion so `debounce_state.json` remains minimal.
  - Floating-point epsilon tolerance (`1e-6`) prevents IEEE 754 precision boundary issues.
- **Automated Test Suite Expansion (81/81 Passing)**:
  - Expanded test suite to **81 automated unit tests** (`engine/test_gravity_validator.py`), 81/81 passing.
  - Added 7 pure deterministic decision tests and 1 integration-style coalescing end-to-end contract test (no sleep, no subprocess).
  - Conducted 1,000-iteration statistical latency distribution benchmark:
    - **Average (Avg):** `0.103 ms`
    - **95th Percentile (p95):** `0.204 ms`
    - **99th Percentile (p99):** `0.454 ms`

---

## [1.1.0] - 2026-09-20

### Added
- **G0 — Secret Leak Guard (BLOCK / WARN)**:
  - High-confidence credential airbag blocking OpenAI, Anthropic/Claude, Google/Gemini, Slack, GitHub tokens, and private keys in diffs.
  - Audit warnings for raw connection URIs and bearer tokens.
  - Strict evidence masking (`sk-ant-****...****890`) preventing secondary leaks in logs or stdout.
- **G1 — Silent Exception Hardening (Diff-Safe)**:
  - Upgraded to `difflib.SequenceMatcher` to prevent false positives when existing handlers are touched.
- **G2 — Test Integrity Hardening**:
  - Implemented `collections.Counter` full-file comparison to block test deletion.
  - Downgraded `.only()` to `WARN` and allowed `@pytest.mark.xfail`.
- **G4 — Import Matrix Boundary Hardening**:
  - Added support for Python relative imports (`from .network import ...`) and TypeScript side-effects (`import './network'`).
  - Added strict path-segment matching preventing substring collisions (e.g. `networking` vs `network`).
- **Phase 2 — Test Evidence Analyzer (T1, T2, T3) Hardening**:
  - `T1_MISSING_RELATED_TEST (WARN)`: Candidate test resolution honoring `sourceRoots` and `testRoots` from `.gravityguard.json` with recent modification window tracking (`sessionWindowSeconds`). Exemption allowlist for `types`, `constants`, `migrations`, `*.d.ts`.
  - `T2_NO_OBSERVABLE_ASSERTION (WARN)`: Case-level AST and line-span tracking ensuring every modified/added test case individually contains observable assertions (`assert`, `self.assert*`, `pytest.raises`, `expect()`, `.toBe()`, `.toEqual()`). Prevents assertions in adjacent tests from masking unasserted stubs.
  - `T3_SYMBOL_TO_TEST_LINK (WARN)`: Body-aware line-span verification resolving parent functions/classes even when declarations are unchanged. Ignores scalar constants while tracking exported arrow functions. Emits grouped warning if any changed symbol is absent.
- **Automated Test Suite Expansion**:
  - Expanded test suite from 13 to **59 automated unit tests** (`engine/test_gravity_validator.py`).
  - Measured core evaluator in-memory execution latency at `~0.032 ms` and Phase 2 evaluator at `~0.015 ms`.

---

## [1.0.0] - 2026-09-20

### Added
- **Initial Public Release of GravityGuard**:
  - Evolved and rebranded from the internal *SRP Guardian* project into a universal, open-source architectural gatekeeper for Antigravity IDE and AI Coding Agents.
- **TypeScript Extension Architecture**:
  - Full TypeScript rewrite of the Antigravity extension (`src/extension.ts`).
  - Compiled and bundled with `tsc` to `./dist/extension.js`.
- **Status Bar Prompt Enhancer (`$(sparkle) Prompt Geliştir`)**:
  - Interactive status bar button positioned at the bottom right of the IDE.
  - Global shortcut **`Ctrl + Alt + E`** (`Cmd + Alt + E` on macOS).
  - Automatically captures active editor selection or opens an interactive `InputBox`.
  - Sends raw user instructions to the local 9Router endpoint (`http://127.0.0.1:20128`) with automated model fallbacks (`ag/gemini-3.8-flash-low` -> `ag/gemini-3.7-flash-medium` -> `all`).
  - Automatically writes the enhanced technical specification directly to the system clipboard for instantaneous paste (`Ctrl + V`) into the chat.
  - Provides a *"Yeni Belgede Aç"* (Open in New Document) review action.
- **GravityGuard Live Monitor Webview**:
  - Dedicated Activity Bar sidebar panel with custom shield icon (`media/shield.svg`).
  - Real-time audit log cards showing timestamp, target file, action, and detailed architectural verdict.
  - Live statistics dashboard tracking **Engellenen (Blocked)** vs. **Onaylanan (Approved)** events.
  - Dual-mode synchronization combining OS filesystem watcher (`fs.watch`) with an active 1.5-second heartbeat poll.
  - Interactive "Temizle" (Clear Logs) and "Yenile" (Refresh) buttons.
- **Python Guard Engine (`engine/gravity-validator.py`)**:
  - Deterministic check engine running in < 50ms.
  - Enforces Single Responsibility Principle (SRP) by disallowing the dangerous combination of raw UI components with HTTP/Network requests in the same file.
  - Replaced arbitrary line-count restrictions with intelligent semantic responsibility analysis.
- **Native Antigravity Skill (`skills/enhance`)**:
  - Added native `/enhance` slash command support for direct in-chat prompt expansion without external popups.
  - **Comprehensive Project Engineering Documentation ("Kutsal 6'lı")**:
  - `README.md` (Bilingual English & Türkçe), `ARCHITECTURE.md`, `ROADMAP.md`, `CHANGELOG.md`, `brain/knowledge.md`, and `LICENSE` (GNU GPL v3.0).

---

## Appendix: Repository & Machine-Layer History (2026-09-20 → 2026-09-21)

> Not a release. These items are **not shipped in the `.vsix`**: they are either
> repository tooling (`tools/`) or a local machine layer living in `.git/hooks`,
> which git does not version. They lived only in `ROADMAP.md` until the roadmap
> was narrowed to unfinished work; this appendix is their record.

### P3-03 · Commit-time secret safety net (local machine layer)
- **The trigger was dead.** A `lefthook` reference pointed at nothing, so the secret scan had never actually run. Replaced with a portable `loss-guard.py` call with no hardcoded user paths, then applied to `~/.git-template` + **12 repositories** (8 previously dead, 4 previously alive).
- **Scope widened from 9 file types to a two-list design**: `SECRET_EXTENSIONS` (~30 types, secret scan only) and `STRUCTURAL_EXTENSIONS` (narrow, code files only, the four structural checks). A 16-type probe had shown `.env`, `.json`, `.yaml`, `.toml`, `.ipynb`, `.sh`, `.ps1`, `.bat`, `.gd`, `.godot` passing through completely unscanned. Two lists widen detection without adding a single warning to non-code files.
- **`secret_checker.py` hardened**: added AWS (`AKIA`), HuggingFace (`hf_`), GitLab (`glpat-`), Stripe (`sk_live_`/`rk_live_`), Telegram bot, npm and PyPI patterns, plus PEM private-key block headers. Placeholder skipping added so `.env.example` and documentation examples do not false-block; value masking and line numbers added to the block message.
- **The interactive confirmation prompt hung forever** with no console attached (`CONIN$`), so the commit never completed. Removed entirely — warnings are informational and never block. Verified: a warning-producing commit completes in 0.7s.
- **`pre-push` reverted to a no-op in 9 repositories**: it inspected staged files, which is meaningless at push time.
- **All 12 repository copies verified byte-identical to `~/.git-template/hooks`.**
- **`core.excludesFile` was unset** — there was no global protection at all, only per-repo hooks. Created `~/.gitignore_global` (`.env*`, `*.key`, `*.pem`, `credentials.json`, `secrets.*`, `id_rsa`, …) so secrets are not even *staged* across all **55 repositories**; the hook remains the detection layer for `git add -f` overrides.
- **105 scattered `.bak-before-*` files (161.5 KB)** moved out of hidden `.git/hooks` directories into `~/.git-hook-backups/`, tagged with their originating repository. Nothing deleted.
- **Verified**: synthetic `.ts` / `.js` / `.py` / `.pyw` commits are blocked; a clean file passes.
- **Scope limit, still true:** of the 5 checks in `loss-guard`, only the secret check is relevant to Python projects. The other four (visual tags, React hooks, lazy placeholders, `components/` line balance) target web/React code.

### P3-04 · Repo ↔ live plugin synchronisation
> The engine exists as **two copies** by necessity: the repo source (`engine/gravity-validator.py`) and the live plugin copy (`~/.gemini/config/plugins/srp-swarm-guardian/scripts/srp-validator.py`, renamed because `hooks.json` invokes `python scripts/srp-validator.py`). Separate deployment targets, so the duplicate can only be *kept in check*, not eliminated. Without tooling this is the same failure mode as the dead `lefthook`: one copy gets edited, the other silently rots, and live protection degrades with no signal.
- **`tools/sync_plugin.py`** — copies repo engine → live plugin: `--check` reports drift and exits `1` (safe for CI), `--dry-run` prints the plan, default mode backs the old target up into `~/.git-hook-backups/plugin-sync/`, validates the source with `ast.parse` **before** copying, and verifies with MD5 **after** (mismatch = exit `2`). Tracked pairs: `gravity-validator.py → srp-validator.py`, `async_runner.py → async_runner.py`.
- **`tools/autosync_plugin.py`** — wired into `.git/hooks/pre-commit` right after the secret scan, so the repo is the single source of truth at commit time. **Deliberate boundary**: it never blocks a commit when the plugin directory is absent or a copy fails; it stops the commit *only* when a source file fails `ast.parse`, so a broken file can never reach the live hook. Silent when there is no drift.
- **Verified three ways**: (1) no drift → silent, exit `0`; (2) injected drift (a synthetic 21-byte line) → copied and MD5-confirmed, exit `0`; (3) deliberately broken source → exit `1` **with the live plugin still intact** (`f1bbb2af…`). Also confirmed through a real `git commit` where the hook fired and repaired the drift; all test residue and the temporary commit were reverted.
- Observed in normal operation: the hook reports `[autosync] DRIFT <file> -> <bytes> (dogrulandi)` and ends with a reload reminder.

### Repository hygiene (2026-09-20)
- Removed the `.kilo/worktrees/magnificent-earth` git worktree with `git worktree remove --force`. It was **not** a stale copy: it sat on the same commit (`2377035`) with identical line counts, and the 1,526-byte delta exactly matched the line count — a pure CRLF-vs-LF difference under `core.autocrlf=true`.
- Removed `srp-validator.py.bak-v123` (63,454 B). Confirmed as a manual snapshot of v1.2.3: its size matches `git cat-file -s 8ad8bef:engine/gravity-validator.py` exactly, so it stays recoverable from history. (Its original location was not conclusively re-verified before deletion; the size match is the evidence that matters.)
- The plugin's `skills/srp-modularizer/` contained five unrelated files (`SKILL (1).md` SOLID Principles, `SKILL (2).md` @json-render/solid, `SKILL(3).md` Requesting Code Review, `solid.md`, `solid-skills-main.zip`). Their word-overlap with the real `SKILL.md` was 7–10% — unrelated content — the `(1)`/`(2)` suffixes indicated browser download duplicates, and no other file referenced them. **Moved (not deleted)** to `Desktop/GG-artik/`, leaving only `SKILL.md` and `Single-Responsibility-Principle.md`.
- **Note that still holds:** empty `.gravityguard/runtime/` directories regenerate on their own because the engine recreates them. Deleting them is pointless.
