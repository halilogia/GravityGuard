// Zero-dependency pure TypeScript translation registry
// Full i18next-style dictionary with parameter interpolation support

export const resources = {
  tr: {
    translation: {
      appName: 'GravityGuard',
      tagline: 'Canlı Ajan Güvenlik Konsolu',
      statusOnline: 'KORUNUYOR',
      tabs: {
        events: 'Olaylar',
        live: 'Canlı',
        obligations: 'Yükümlülükler',
        rules: 'Kurallar',
        insights: 'Analiz'
      },
      current: {
        title: 'SON İŞLEM',
        idle: 'Ajan bekleniyor (Sistem aktif ve dinliyor)',
        allPassed: 'Tüm güvenlik muhafızları geçti',
        openFile: 'Dosyayı Aç',
        copyReason: 'Nedeni Kopyala',
        whyBlocked: 'Neden engellendi?',
        statusAllowed: 'ONAYLANDI',
        statusBlocked: 'ENGELLENDİ',
        statusWarning: 'UYARI',
        statusShadow: 'GÖLGE',
        statusRecovered: 'İYİLEŞTİ',
        allGuardsPassed: 'G0 G1 G2 G4 Geçti'
      },
      live: {
        empty: 'Henüz kaydedilmiş güvenlik olayı yok.',
        recoveryHeader: 'İyileşme (Recovery): {{rule}}',
        recoveryFlowBlocked: 'BLOCKED',
        recoveryFlowRecovered: 'RECOVERED',
        recoveryAttempts: '{{attempts}}. denemede çözüldü',
        recoveryDuration: 'Süre: {{duration}}s',
        shadowDesc: 'Gölge Modu (Shadow): Ajan engellenmedi; gölge telemetrisi kaydedildi.',
        openFileBtn: 'Dosyayı Aç',
        copyReasonBtn: 'Nedeni Kopyala'
      },
      insights: {
        title: 'Ajan Davranış & Kurtarma Analizi',
        recoveryTitle: 'Ajan Kurtarma Oranı (Recovery Rate)',
        recoveryDesc: 'Engellenen eylemlerin ajanca düzeltilme başarısı',
        fixedNext: 'sonraki denemede düzeltildi',
        latencyFast: 'Hızlı yol mantığı',
        latencySpawn: 'Alt süreç (Subprocess)',
        lockStatus: 'Durum Kilidi (StateLock)',
        lockHealthy: 'Çekirdek düzeyi kilit etkin',
        twoPhase: 'İki Fazlı Taahhüt (2PC)',
        twoPhaseActive: 'Fiziksel Disk Doğrulama Aktif',
        highValueTitle: 'Yüksek Değerli Muhafızlar (Kanıtlanmış Sinyal)',
        highValueDesc: 'G0 (Sızıntı), G1 (Sessiz Hata), G2 (Test Bütünlüğü)',
        tuningTitle: 'Tavsiye & Ayar Değerlendirmesi',
        tuningDesc: 'T1 (Stop Yükümlülüğü), G3 / Büyüme (Tavsiye Uyarısı)',
        subClean: 'Henüz engellenen işlem yok (Temiz Oturum)',
        subSample: '{{recovered}} / {{blocked}} düzeltildi (Yetersiz Örneklem, n={{blocked}})',
        subRate: '{{recovered}} / {{blocked}} ihlal ajan tarafından düzeltildi (%{{rate}})',
        reportCardTitle: 'Gardiyan Etkinlik Karnesi (Ampirik Veri)',
        ruleClean: 'Kayıtlı veride 0 ihlal',
        ruleInterventions: '{{blocked}} müdahale • {{recovered}} düzeltildi (%{{rate}})',
        ruleWarnings: '{{count}} uyarı • %{{rate}} takip / düzeltme',
        medianAttempts: 'Medyan: {{attempts}} deneme',
        badgeNoViolations: '0 İhlal',
        badgeInsufficient: 'Yetersiz Veri (n={{n}})',
        badgeEarlySignal: 'Ön Sinyal (n={{n}})',
        badgeHighValue: 'Yüksek Değer (n={{n}})',
        badgeFriction: 'Sürtünme (n={{n}})',
        badgeBalanced: 'Dengeli (n={{n}})',
        lifecycleTitle: 'Yaşam Döngüsü ve Tavsiye Kuralları',
        t1Label: 'T1 Test Kanıtı:',
        t1Pending: '{{count}} Bekleyen Test Kanıtı',
        t1Verified: 'Kapanış Doğrulandı',
        docLabel: 'Dokümantasyon Yönetişimi (§6):',
        docPending: '{{count}} Bekleyen Dokümantasyon',
        docActive: 'Aktif (Kapanış Şartı)',
        docDisabled: 'Devre Dışı',
        growthLabel: 'Dosya Büyümesi (ARCH_FILE_GROWTH):',
        growthValue: 'Tavsiye • Gölge Modu (GÖLGE)',
        growthValueShadow: 'Tavsiye • Gölge Modu (GÖLGE)',
        growthValueWarn: 'Tavsiye Uyarısı (UYARI)',
        g3Label: 'G3 Derleyici Atlatması (Compiler Bypass):',
        g3Value: 'Tavsiye Uyarısı (UYARI)',
        g3ValueShadow: 'Tavsiye • Gölge Modu (GÖLGE)',
        walTitle: 'Telemetri & WAL Durumu',
        walJournalLabel: 'Denetim Günlüğü (Audit Journal):',
        walJournalValue: 'Önceden Yazmalı Günlük (WAL)',
        walLiveLabel: 'Canlı Kontrol Noktası (Live Checkpoint):',
        walLiveValue: 'Son projeksiyon (Seq #{{seq}})',
        perfTitle: 'Gecikme & Motor Performansı',
        fastBudget: '< 1 ms (Bellek içi)',
        spawnBudget: 'Platforma bağlı (~60–220 ms)',
        integrityTitle: 'Oturum & Eşzamanlılık Bütünlüğü',
        sessionLabel: 'Oturum Kimliği:',
        circuitLabel: 'Devre Kesici Sayacı:',
        circuitValue: '{{retries}} / 5 deneme',
        diagnosticsTitle: 'Sistem Bilgisi & Tanılama',
        diagnosticsBadge: 'WAL & Kilit Aktif'
      },
      stats: {
        blocked: 'Engellendi',
        warning: 'Uyarı',
        approved: 'Onaylandı',
        total: 'Toplam',
        pending: 'Bekleyen',
        clean: 'Temiz',
        blockedTooltip: 'Canlı akıştaki engellenen eylemler (Son 50 olay penceresi)',
        warningTooltip: 'Canlı akıştaki uyarılar (Son 50 olay penceresi)',
        approvedTooltip: 'Canlı akıştaki onaylanan eylemler (Son 50 olay penceresi)',
        pendingTooltip: 'Bekleyen test ve dokümantasyon yükümlülükleri (T1 ve §6)',
        shadowTooltip: 'Gölge modunda kaydedilen kural gözlemleri'
      },
      actions: {
        refresh: 'Yenile',
        clear: 'Temizle',
        enhancePrompt: 'Prompt Geliştir',
        toggleLang: 'EN',
        openConfig: 'Ayarlar',
        clearedNotice: 'Olay akışı görünümü temizlendi (Kalıcı veriler korundu).',
        switchLang: 'Dili Değiştir',
        clearLogs: 'Görünümü Temizle',
        statusBarTooltip: 'GravityGuard: Yerel AI ağ geçidi ile Promptu Geliştir (Ctrl+Alt+E)',
        pingLive: 'GravityGuard devrede — yerel AI geçidi: {{detail}}',
        pingWarning: 'GravityGuard aktif, ancak yerel AI geçidine ulaşılamıyor: {{detail}}. Prompt Geliştir yine de çalışır (çevrimdışı şablon modu).',
        langSwitched: 'GravityGuard dili: {{lang}}',
        promptInputTitle: 'Geliştirmek istediğiniz prompt veya talimatı girin (GravityGuard AI):',
        promptInputPlaceholder: 'Örn: SRP kuralına uygun websocket bağlantı yöneticisi oluştur... | Mod sabitlemek için: "#denetle: ..."',
        promptPreparing: 'GravityGuard: {{mode}} modunda prompt hazırlanıyor...',
        promptFailed: 'Prompt geliştirilemedi.',
        promptSuccess: 'Prompt geliştirildi ve panoya kopyalandı ({{mode}}{{note}})',
        promptOfflineNote: ' — çevrimdışı şablon modu',
        openInNewDoc: 'Yeni Belgede Aç',
        promptError: 'Prompt geliştirme hatası: {{error}}',
        modeAuto: 'Otomatik — {{mode}}',
        modeAutoDesc: 'Sınıflandırıcının tahmini (düşük güven)',
        modePlaceholder: 'Niyet belirsiz — modu seçin (varsayılan: Otomatik)',
        modeConsultDesc: 'Fikir, seçenek ve trade-off iste',
        modeImplementDesc: 'Savunmacı teknik şartname üret',
        modeAuditDesc: 'Kod değiştirmeden, kanıtlı bulgu listesi üret',
        fileOpenError: 'Dosya açılamadı: {{path}}',
        configOpenError: 'Yapılandırma dosyası açılamadı: {{error}}',
        configNoWorkspaceNotice: 'Açık bir çalışma alanı bulunamadı; kullanıcı düzeyindeki yapılandırma (~/.gravityguard.json) açılıyor.',
        reasonCopied: 'Kural engelleme nedeni panoya kopyalandı.'
      },
      obligations: {
        title: 'Aktif Yönetişim & Yükümlülük Durumu',
        testTitle: 'Bekleyen Test Kanıtları (T1)',
        docTitle: 'Bekleyen Dokümantasyon Yükümlülükleri (§6)',
        circuitBreaker: 'Devre Kesici Sayacı',
        cleanState: 'Bekleyen hiçbir yükümlülük yok. Tüm test ve doküman kontrolleri temiz.',
        expectedTest: 'Beklenen test',
        requiredDoc: 'Gereken',
        retries: 'deneme',
        stepPending: 'BEKLİYOR',
        stepIntent: 'NİYET',
        stepVerified: 'DOĞRULANDI',
        stepResolved: 'ÇÖZÜLDÜ',
        hintTestIntent: 'İki fazlı taahhüt alındı; diske yazım doğrulanması bekleniyor',
        hintTestPending: 'Ajanın test dosyasını oluşturması/düzenlemesi bekleniyor',
        hintDocIntent: 'Dokümantasyon taahhüdü alındı; diske yazım doğrulanması bekleniyor',
        hintDocPending: 'docs/KNOWLEDGE.md §6 uyarınca CHANGELOG güncellenmeli'
      },
      rules: {
        title: 'Aktif Konfigürasyon (.gravityguard.json)',
        secTitle: 'Güvenlik Muhafızları (Sıfır Tolerans)',
        g0Title: 'G0 Secret Leak Shield',
        g0Desc: 'Tüm dosyalarda API key, JWT, özel anahtar sızıntılarını engeller.',
        g1Title: 'G1 Silent Error Swallowing',
        g1Desc: "Hataların 'except: pass' ile sessizce yutulmasını kesinlikle engeller.",
        g2Title: 'G2 Test Integrity Protection',
        g2Desc: "Testlerin sahte 'assert True' ile geçilmesini veya silinmesini engeller.",
        archTitle: 'Mimari Muhafızlar',
        g4Title: 'G4 Import Matrix & Layers',
        g4Desc: 'Katmanlar arası döngüsel veya ters yönde yasadışı importları engeller.',
        srpTitle: 'SRP & Cohesion Boundary',
        srpDesc: 'Tek dosyada çoklu iş yapılmasını önler; cohesive monolith istisnası korur.',
        g3Title: 'G3 Compiler/Linter Bypass (Derleyici Atlatması)',
        g3Desc: '@ts-ignore veya # type: ignore tespitinde tavsiye uyarısı verir; engellemez.',
        growthTitle: 'ARCH_FILE_GROWTH (Dosya Büyümesi)',
        growthDesc: 'Tek hamlede devasa kod yığılmasında tavsiye uyarısı verir; gölge modu destekler.',
        govTitle: 'Kalite & Yönetişim',
        t1Title: 'T1/T2 Test Evidence',
        t1Desc: 'PreTool: Tavsiye Uyarısı • Stop Hook: Kapanış Yükümlülüğü (Fiziksel Disk Doğrulama).',
        docGovTitle: 'Dokümantasyon Yönetişimi (§6 Same-Commit)',
        docGovDesc: 'Motor dosyası değiştiğinde oturum kapanışında CHANGELOG güncellenmesini zorlar.',
        badgeBlock: 'BLOCK',
        badgeShadow: 'GÖLGE (SHADOW)',
        badgeWarnAdvisory: 'WARN (TAVSİYE)',
        badgeWarnStop: 'WARN (KAPANIŞ ŞARTI)',
        badgeOptInStop: 'OPT-IN (KAPANIŞ ŞARTI)',
        badgeOff: 'KAPALI',
        layers: 'Mimari Katman Matrisi (Yasaklı Importlar)',
        srpLimits: 'SRP & Dosya Büyüme Sınırları',
        docGovernance: 'Opt-in Dokümantasyon Yönetişimi',
        testEvidence: 'Test Kanıtı Yapılandırması',
        invariantsTitle: 'Ajan Bağlam Değişmezleri (Invariants)',
        active: 'Aktif',
        inactive: 'Pasif',
        maxLoc: 'Maksimum Dosya Satırı',
        maxChunk: 'Tek Seferde Ekleme Sınırı',
        complexity: 'Karmaşıklık Eşiği',
        deferred: 'Erteleme Modu'
      },
      events: {
        noEvents: 'Henüz kaydedilmiş güvenlik olayı yok.',
        lastCheck: 'Son Kontrol'
      }
    }
  },
  en: {
    translation: {
      appName: 'GravityGuard',
      tagline: 'Live Agent Security Console',
      statusOnline: 'PROTECTED',
      tabs: {
        events: 'Events',
        live: 'Live',
        obligations: 'Obligations',
        rules: 'Rules',
        insights: 'Insights'
      },
      current: {
        title: 'CURRENT ACTION',
        idle: 'Watching agent filesystem actions...',
        allPassed: 'All active guards passed',
        openFile: 'Open File',
        copyReason: 'Copy Reason',
        whyBlocked: 'Why was this blocked?',
        statusAllowed: 'ALLOWED',
        statusBlocked: 'BLOCKED',
        statusWarning: 'WARNING',
        statusShadow: 'SHADOW',
        statusRecovered: 'RECOVERED',
        allGuardsPassed: 'G0 G1 G2 G4 Passed'
      },
      live: {
        empty: 'No security events recorded yet.',
        recoveryHeader: 'Recovery: {{rule}}',
        recoveryFlowBlocked: 'BLOCKED',
        recoveryFlowRecovered: 'RECOVERED',
        recoveryAttempts: 'Resolved on attempt {{attempts}}',
        recoveryDuration: 'Duration: {{duration}}s',
        shadowDesc: 'Shadow Mode: Agent was not blocked; shadow telemetry recorded.',
        openFileBtn: 'Open File',
        copyReasonBtn: 'Copy Reason'
      },
      insights: {
        title: 'Agent Behavior & Recovery Analysis',
        recoveryTitle: 'Agent Recovery Rate',
        recoveryDesc: 'Agent self-correction success after guard blocks',
        fixedNext: 'fixed on next attempt',
        latencyFast: 'In-memory fast path',
        latencySpawn: 'Subprocess spawn',
        lockStatus: 'State Lock',
        lockHealthy: 'Kernel-level lock enabled',
        twoPhase: 'Two-Phase Commit (2PC)',
        twoPhaseActive: 'Physical Disk Verification Active',
        highValueTitle: 'High-Value Guardrails (Proven Signal)',
        highValueDesc: 'G0 (Secret Leak), G1 (Silent Error), G2 (Test Integrity)',
        tuningTitle: 'Advisory & Tuning Evaluation',
        tuningDesc: 'T1 (Stop Obligation), G3 / Growth (Advisory Warn)',
        subClean: 'No blocked operations yet (Clean Session)',
        subSample: '{{recovered}} / {{blocked}} recovered (Insufficient Sample, n={{blocked}})',
        subRate: '{{recovered}} / {{blocked}} violations self-corrected (%{{rate}})',
        reportCardTitle: 'Guardrail Effectiveness Scorecard (Empirical Data)',
        ruleClean: '0 violations in recorded data',
        ruleInterventions: '{{blocked}} blocks • {{recovered}} recovered (%{{rate}})',
        ruleWarnings: '{{count}} warnings • {{rate}}% follow-up / fixed',
        medianAttempts: 'Median: {{attempts}} attempts',
        badgeNoViolations: '0 Violations',
        badgeInsufficient: 'Insufficient Data (n={{n}})',
        badgeEarlySignal: 'Early Signal (n={{n}})',
        badgeHighValue: 'High Value (n={{n}})',
        badgeFriction: 'Friction (n={{n}})',
        badgeBalanced: 'Balanced (n={{n}})',
        lifecycleTitle: 'Lifecycle & Advisory Guardrails',
        t1Label: 'T1 Test Evidence:',
        t1Pending: '{{count}} Pending Test Evidence',
        t1Verified: 'Verified for Close',
        docLabel: 'Documentation Governance (§6):',
        docPending: '{{count}} Pending Documentation',
        docActive: 'Active (Close Gate)',
        docDisabled: 'Disabled',
        growthLabel: 'File Growth (ARCH_FILE_GROWTH):',
        growthValue: 'Advisory • Shadow Mode (SHADOW)',
        growthValueShadow: 'Advisory • Shadow Mode (SHADOW)',
        growthValueWarn: 'Advisory Warning (WARN)',
        g3Label: 'G3 Compiler Bypass:',
        g3Value: 'Advisory Warning (WARN)',
        g3ValueShadow: 'Advisory • Shadow Mode (SHADOW)',
        walTitle: 'Telemetry & WAL Status',
        walJournalLabel: 'Audit Journal:',
        walJournalValue: 'Write-Ahead Journal',
        walLiveLabel: 'Live Checkpoint:',
        walLiveValue: 'Last projected seq: #{{seq}}',
        perfTitle: 'Latency & Engine Performance',
        fastBudget: '< 1 ms (In-memory)',
        spawnBudget: 'Platform-dependent (~60–220 ms)',
        integrityTitle: 'Session & Concurrency Integrity',
        sessionLabel: 'Session ID:',
        circuitLabel: 'Circuit Breaker Counter:',
        circuitValue: '{{retries}} / 5 attempts',
        diagnosticsTitle: 'System Info & Diagnostics',
        diagnosticsBadge: 'WAL & Lock Active'
      },
      stats: {
        blocked: 'Blocked',
        warning: 'Warning',
        approved: 'Approved',
        total: 'Total',
        pending: 'Pending',
        clean: 'Clean',
        blockedTooltip: 'Blocked actions in active stream (sliding 50-event window)',
        warningTooltip: 'Advisory warnings in active stream (sliding 50-event window)',
        approvedTooltip: 'Approved actions in active stream (sliding 50-event window)',
        pendingTooltip: 'Pending test and documentation governance debts (T1 & §6)',
        shadowTooltip: 'Shadow-mode rule observations'
      },
      actions: {
        refresh: 'Refresh',
        clear: 'Clear',
        enhancePrompt: 'Enhance Prompt',
        toggleLang: 'TR',
        openConfig: 'Settings',
        clearedNotice: 'Event stream view cleared (Persistent data preserved).',
        switchLang: 'Switch Language',
        clearLogs: 'Clear View',
        statusBarTooltip: 'GravityGuard: Enhance Prompt with local AI gateway (Ctrl+Alt+E)',
        pingLive: 'GravityGuard is Live — local AI gateway: {{detail}}',
        pingWarning: 'GravityGuard active, but local AI gateway unreachable: {{detail}}. Enhance Prompt still works (offline template mode).',
        langSwitched: 'GravityGuard language: {{lang}}',
        promptInputTitle: 'Enter prompt or instruction to enhance (GravityGuard AI):',
        promptInputPlaceholder: 'E.g.: Create SRP-compliant websocket connection manager... | Pin mode: "#audit: ..."',
        promptPreparing: 'GravityGuard: Preparing prompt in {{mode}} mode...',
        promptFailed: 'Failed to enhance prompt.',
        promptSuccess: 'Prompt enhanced and copied to clipboard ({{mode}}{{note}})',
        promptOfflineNote: ' — offline template mode',
        openInNewDoc: 'Open in New Document',
        promptError: 'Prompt enhancement error: {{error}}',
        modeAuto: 'Automatic — {{mode}}',
        modeAutoDesc: 'Classifier guess (low confidence)',
        modePlaceholder: 'Ambiguous intent — select mode (default: Automatic)',
        modeConsultDesc: 'Ask for ideas, options, and trade-offs',
        modeImplementDesc: 'Generate defensive technical spec',
        modeAuditDesc: 'Generate evidence-based findings without code changes',
        fileOpenError: 'Could not open file: {{path}}',
        configOpenError: 'Could not open configuration file: {{error}}',
        configNoWorkspaceNotice: 'No active workspace found; opening user-level configuration (~/.gravityguard.json).',
        reasonCopied: 'Rule violation reason copied to clipboard.'
      },
      obligations: {
        title: 'Active Governance & Obligations State',
        testTitle: 'Pending Test Evidence (T1)',
        docTitle: 'Pending Documentation Obligations (§6)',
        circuitBreaker: 'Circuit Breaker Counter',
        cleanState: 'No pending obligations. All test and documentation gates are clean.',
        expectedTest: 'Expected test',
        requiredDoc: 'Required',
        retries: 'attempts',
        stepPending: 'PENDING',
        stepIntent: 'INTENT',
        stepVerified: 'VERIFIED',
        stepResolved: 'RESOLVED',
        hintTestIntent: 'Two-phase intent recorded; awaiting disk verification',
        hintTestPending: 'Awaiting agent to create/modify test file',
        hintDocIntent: 'Documentation intent recorded; awaiting disk verification',
        hintDocPending: 'CHANGELOG must be updated per docs/KNOWLEDGE.md §6'
      },
      rules: {
        title: 'Active Configuration (.gravityguard.json)',
        secTitle: 'Security Guardrails (Zero Tolerance)',
        g0Title: 'G0 Secret Leak Shield',
        g0Desc: 'Prevents API keys, JWTs, and secret leaks across all files.',
        g1Title: 'G1 Silent Error Swallowing',
        g1Desc: "Blocks silent exception suppression via except: pass.",
        g2Title: 'G2 Test Integrity Protection',
        g2Desc: "Blocks fake assert True bypasses or test deletion.",
        archTitle: 'Architectural Guardrails',
        g4Title: 'G4 Import Matrix & Layers',
        g4Desc: 'Prevents circular or reverse illegal architectural imports.',
        srpTitle: 'SRP & Cohesion Boundary',
        srpDesc: 'Prevents multi-job files; protects cohesive monoliths.',
        g3Title: 'G3 Compiler/Linter Bypass',
        g3Desc: 'Advises on @ts-ignore or # type: ignore bypass; does not block.',
        growthTitle: 'ARCH_FILE_GROWTH (File Growth)',
        growthDesc: 'Advises on massive code bloat in a single turn; supports shadow mode.',
        govTitle: 'Quality & Governance',
        t1Title: 'T1/T2 Test Evidence',
        t1Desc: 'PreTool: Advisory Warn • Stop Hook: Stop Obligation (Physical Disk Verification).',
        docGovTitle: 'Documentation Governance (§6 Same-Commit)',
        docGovDesc: 'Enforces CHANGELOG update on session close when engine files change.',
        badgeBlock: 'BLOCK',
        badgeShadow: 'SHADOW',
        badgeWarnAdvisory: 'WARN (ADVISORY)',
        badgeWarnStop: 'WARN (STOP OBLIGATION)',
        badgeOptInStop: 'OPT-IN (STOP OBLIGATION)',
        badgeOff: 'OFF',
        layers: 'Architectural Layer Matrix (Forbidden Imports)',
        srpLimits: 'SRP & File Growth Limits',
        docGovernance: 'Opt-in Documentation Governance',
        testEvidence: 'Test Evidence Configuration',
        invariantsTitle: 'Agent Context Invariants',
        active: 'Active',
        inactive: 'Inactive',
        maxLoc: 'Max File Lines',
        maxChunk: 'Max Single Addition',
        complexity: 'Complexity Threshold',
        deferred: 'Deferred Mode'
      },
      events: {
        noEvents: 'No security events recorded yet.',
        lastCheck: 'Last Check'
      }
    }
  }
};

let currentLang: 'tr' | 'en' = 'tr';

export function initI18n(initialLang: string = 'tr'): { language: string } {
  currentLang = initialLang.toLowerCase().startsWith('tr') ? 'tr' : 'en';
  return { language: currentLang };
}

export function setLanguage(lang: 'tr' | 'en'): void {
  currentLang = lang;
}

export function getCurrentLanguage(): 'tr' | 'en' {
  return currentLang;
}

function interpolate(text: string, options?: Record<string, unknown>): string {
  if (!options) return text;
  let res = text;
  for (const [k, v] of Object.entries(options)) {
    res = res.replace(new RegExp(`\\{\\{${k}\\}\\}|\\{${k}\\}`, 'g'), String(v));
  }
  return res;
}

export function t(key: string, options?: Record<string, unknown>): string {
  const parts = key.split('.');
  let cur: any = resources[currentLang]?.translation;
  for (const p of parts) {
    if (cur && typeof cur === 'object' && p in cur) {
      cur = cur[p];
    } else {
      cur = undefined;
      break;
    }
  }
  if (typeof cur === 'string') {
    return interpolate(cur, options);
  }
  // Fallback to English
  let fallback: any = resources.en.translation;
  for (const p of parts) {
    if (fallback && typeof fallback === 'object' && p in fallback) {
      fallback = fallback[p];
    } else {
      fallback = undefined;
      break;
    }
  }
  if (typeof fallback === 'string') {
    return interpolate(fallback, options);
  }
  return key;
}
