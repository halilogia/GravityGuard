// Zero-dependency pure TypeScript translation registry

export const resources = {
  tr: {
    translation: {
      appName: 'GravityGuard',
      tagline: 'Canlı Ajan Güvenlik Konsolu',
      statusOnline: 'KORUNUYOR',
      tabs: {
        events: '🛡️ Olaylar',
        live: '⚡ Canlı',
        obligations: '📋 Yükümlülükler',
        rules: '📐 Kurallar',
        insights: '📊 Analiz'
      },
      current: {
        title: 'SON İŞLEM',
        idle: 'Ajan bekleniyor (Sistem aktif ve dinliyor)',
        allPassed: 'Tüm güvenlik muhafızları geçti',
        openFile: 'Dosyayı Aç',
        copyReason: 'Nedeni Kopyala',
        whyBlocked: 'Neden engellendi?'
      },
      insights: {
        title: 'Ajan Davranış & Kurtarma Analizi',
        recoveryTitle: 'Ajan Kurtarma Oranı (Recovery Rate)',
        recoveryDesc: 'Engellenen eylemlerin ajanca düzeltilme başarısı',
        fixedNext: 'sonraki denemede düzeltildi',
        latencyFast: 'Hızlı yol mantığı',
        latencySpawn: 'Alt süreç (Subprocess)',
        lockStatus: 'Durum Kilidi (StateLock)',
        lockHealthy: 'Sağlıklı (Çekirdek Kilit)',
        twoPhase: 'İki Fazlı Taahhüt (2PC)',
        twoPhaseActive: 'Fiziksel Disk Doğrulama Aktif',
        highValueTitle: 'Yüksek Değerli Muhafızlar (Kanıtlanmış Sinyal)',
        highValueDesc: 'G0 (Sızıntı), G1 (Sessiz Hata), G2 (Test Bütünlüğü)',
        tuningTitle: 'Tavsiye & Ayar Değerlendirmesi',
        tuningDesc: 'T1 (Stop Yükümlülüğü), G3 / Büyüme (Tavsiye Uyarısı)'
      },
      stats: {
        blocked: 'Engellendi',
        warning: 'Uyarı',
        approved: 'Onaylandı',
        total: 'Toplam'
      },
      actions: {
        refresh: 'Yenile',
        clear: 'Temizle',
        enhancePrompt: 'Prompt Geliştir',
        toggleLang: 'EN',
        openConfig: 'Ayarlar'
      },
      obligations: {
        title: 'Aktif Yönetişim & Yükümlülük Durumu',
        testTitle: 'Bekleyen Test Kanıtları (T1)',
        docTitle: 'Bekleyen Dokümantasyon Yükümlülükleri (§6)',
        circuitBreaker: 'Devre Kesici Sayacı',
        cleanState: 'Bekleyen hiçbir yükümlülük yok. Tüm test ve doküman kontrolleri temiz.',
        expectedTest: 'Beklenen test',
        requiredDoc: 'Gereken',
        retries: 'deneme'
      },
      rules: {
        title: 'Aktif Konfigürasyon (.gravityguard.json)',
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
        events: '🛡️ Events',
        live: '⚡ Live',
        obligations: '📋 Obligations',
        rules: '📐 Rules',
        insights: '📊 Insights'
      },
      current: {
        title: 'CURRENT ACTION',
        idle: 'Watching agent filesystem actions...',
        allPassed: 'All active guards passed',
        openFile: 'Open File',
        copyReason: 'Copy Reason',
        whyBlocked: 'Why was this blocked?'
      },
      insights: {
        title: 'Agent Behavior & Recovery Analysis',
        recoveryTitle: 'Agent Recovery Rate',
        recoveryDesc: 'Agent self-correction success after guard blocks',
        fixedNext: 'fixed on next attempt',
        latencyFast: 'In-memory fast path',
        latencySpawn: 'Subprocess spawn',
        lockStatus: 'State Lock',
        lockHealthy: 'Healthy (Kernel-level lock)',
        twoPhase: 'Two-Phase Commit (2PC)',
        twoPhaseActive: 'Physical Disk Verification Active',
        highValueTitle: 'High-Value Guardrails (Proven Signal)',
        highValueDesc: 'G0 (Secret Leak), G1 (Silent Error), G2 (Test Integrity)',
        tuningTitle: 'Advisory & Tuning Evaluation',
        tuningDesc: 'T1 (Stop Obligation), G3 / Growth (Advisory Warn)'
      },
      stats: {
        blocked: 'Blocked',
        warning: 'Warning',
        approved: 'Approved',
        total: 'Total'
      },
      actions: {
        refresh: 'Refresh',
        clear: 'Clear',
        enhancePrompt: 'Enhance Prompt',
        toggleLang: 'TR',
        openConfig: 'Settings'
      },
      obligations: {
        title: 'Active Governance & Obligations State',
        testTitle: 'Pending Test Evidence (T1)',
        docTitle: 'Pending Documentation Obligations (§6)',
        circuitBreaker: 'Circuit Breaker Counter',
        cleanState: 'No pending obligations. All test and documentation gates are clean.',
        expectedTest: 'Expected test',
        requiredDoc: 'Required',
        retries: 'retries'
      },
      rules: {
        title: 'Active Configuration (.gravityguard.json)',
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
    return cur;
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
    return fallback;
  }
  return key;
}
