"""One-line "do this instead" guidance per rule, shared by rejection messages and the session briefing.

A rejection that only says "forbidden" costs the agent a second wrong attempt; the tip and a short correct example make
the retry land. Keep each tip one imperative sentence and each example a few tokens of real code.
"""
import json
import re
from typing import Dict, Optional, Tuple

# rule id -> (tip, example or "")
TIPS: Dict[str, Tuple[str, str]] = {
    "G0_SECRET_LEAK": ("Gizli değeri koda yazma; ortam değişkeninden oku.", "api_key = os.environ['API_KEY']"),
    "G0_ENV_PROTECTION": (".env dosyasını okuma veya yazma; gereken anahtar adını kullanıcıya sor.", ""),
    "G1_SILENT_EXCEPTION": ("Hatayı yutma; logla ve yeniden fırlat ya da anlamlı bir yedek davranış yaz.",
                            "except ValueError as e:\n    log.warning('parse failed: %s', e)\n    raise"),
    "G2_TEST_INTEGRITY": ("Testi silme veya assert True ile geçirme; kodu düzelt ya da testi gerçek davranışa göre güncelle.", ""),
    "G3_COMPILER_BYPASS": ("Susturma yorumu ekleme; uyarının kök nedenini düzelt.", ""),
    "G4_IMPORT_MATRIX": ("Katman kuralına uy: core dış katmanları import etmez, feature'lar birbirinin iç dosyalarına girmez.", ""),
    "G4_NO_BLIND_OVERWRITE": ("Var olan doküman veya kural dosyasını baştan yazma; önce oku, sonra yalnızca değişen bölümü düzenle.", ""),
    "G7_TS_FIRST": ("Yeni uygulama kodunu .ts olarak yaz; .js gerekiyorsa devam et; bu yalnızca bir uyarıdır.", ""),
    "DESIGN_ICON_RULE": ("Standart emoji veya simge karakteri kullanma; projenin ikon bileşenini ya da düz metni kullan.", ""),
    "DESIGN_SCROLLBAR_RULE": ("Varsayılan kaydırma çubuğunu bırakma; ince, temaya uygun scrollbar stili tanımla.", ""),
    "DESIGN_RESPONSIVE_RULE": ("<head> içine width=device-width ve initial-scale=1 içeren viewport meta etiketini ekle; sabit genişlik yerine max-width veya % kullan.", '<meta name="viewport" content="width=device-width, initial-scale=1">'),
    "DESIGN_RAW_CONTROLS_RULE": ("Ham kontrolü bırakma: dosya seçiciyi ::file-selector-button ile stillendir, sayı alanında spinner okunu gizle.", "input[type=number]::-webkit-inner-spin-button { display: none; }"),
    "STATIC_LINTER_DIAGNOSTIC": ("Önceki yazımdaki linter hatasını aynı dosyada şimdi düzelt; yeni kod eklemeden önce temizle.", ""),
    "SEC_UNSAFE_PATTERN": ("Riskli yapı yerine güvenli olanı kullan.", "el.textContent = value  // innerHTML yerine"),
    "SHELL_SECURITY": ("İndirileni doğrudan yorumlayıcıya verme; dosyaya indir, içeriğini kontrol et, sonra çalıştır.", ""),
    "ARCH_FILE_GROWTH": ("Büyük kodu tek dosyaya yığma; sorumluluğa göre ayrı modüllere böl.", ""),
    "G5_NEW_FILE_BLOAT_DENY": ("Yeni dosyayı tek hamlede yazma; sorumluluğa göre alt modüllere böl, her birini ayrı oluştur.", ""),
    "STOP_CIRCUIT_BREAKER_BLOCKED": ("Kritik mimari/test regresyonunu gider; devre kesici bunu affetmez.", ""),
    "SRP_RESPONSIBILITY_MIX": ("Veri erişimi, dosya/ağ işleri ve iş mantığını ayrı modüllere/işlevlere böl.", ""),
    "ARCH_RATCHET_REGRESSION": ("Eşiği aşmış dosyaya satır ekleme; yeni mantığı ayrı modüle çıkar.", ""),
    "ARCH_RATCHET_GROWTH_DENY": ("Sınırı aşmış dosyaya satır ekleme; özelliği yeni modüle yaz, taşıdığın bloğu tek düzenlemede silip yerine import koy.", ""),
    "ARCH_RATCHET_REGRESSION_WARN": ("Eşiği aşmış dosyaya satır ekleme; yeni mantığı ayrı modüle çıkar.", ""),
    "SRP_BOUNDARY": ("Tek dosyada birden çok sorumluluk toplama; yeni sorumluluğu kendi modülüne taşı.", ""),
    "OE_SINGLE_IMPL": ("Tek uygulaması olan arayüz veya soyut sınıf ekleme; sınıfı doğrudan kullan.", ""),
    "ARCH_PMA_HORIZONTAL_DENY": ("controllers/services/repositories klasörü açma; kodu features/<özellik>/ altına dikey dilim olarak koy.", ""),
    "ARCH_PMA_DEEP_IMPORT": ("Başka bir feature'ın iç dosyasını import etme; onun index.ts üzerinden açtığı API'yi kullan.", ""),
    "WEB_INLINE_JS_BUDGET": ("HTML içine uzun script yazma; ayrı bir .ts/.js dosyasına taşıyıp bağla.", ""),
    "WEB_INLINE_CSS_BUDGET": ("HTML içine uzun <style> yazma; ayrı bir .css dosyasına taşıyıp <link> ile bağla.", ""),
    "WEB_DOCUMENT_SIZE": ("HTML belgesini büyütme; bölümleri şablonlara veya bileşenlere ayır.", ""),
    "T3_SYMBOL_TO_TEST_LINK": ("Değiştirdiğin fonksiyonun testini de güncelle veya ekle.", ""),
    "T1_FINAL_UNRESOLVED": ("Değiştirdiğin üretim kodu için testi çalıştır veya ekle; oturumu test kanıtı olmadan kapatma.", ""),
    "TOOL_OUTPUT_BLOAT": ("Büyük dosyayı bütün okuma; satır aralığıyla oku veya önce taslağını çıkar.", ""),
    "PROJECTION_UNSUPPORTED": ("Aranan metin dosyada yok: dosyayı yeniden oku, bloğu bir iki satıra kısalt ya da StartLine/EndLine ver; kabuk veya python -c ile düzenlemeye kaçma.", ""),
    "ENGINE_SELF_INTEGRITY": ("Motor dosyasını bozacak yazımı yapma; tanımsız adları ve importları kontrol et.", ""),
}

_RULE_TAG = re.compile(r"\[([A-Z][A-Z0-9_]{2,})\]")


def tip_for(rule_id: str) -> Optional[Tuple[str, str]]:
    return TIPS.get(rule_id)


def lesson_text(rule_id: str) -> str:
    """The text appended to a rejection, or "" when the rule has no tip."""
    entry = TIPS.get(rule_id)
    if not entry:
        return ""
    tip, example = entry
    out = f"\nDoğru yol: {tip}"
    if example:
        out += f"\nÖrnek:\n{example}"
    return out


def strip_symbol_prefix(reason: str) -> str:
    """Drops the leading stop-sign emoji the engine used to prefix rejections with."""
    return re.sub(r"^\s*\U0001F6D1\s*", "", reason)


def enrich_hook_output(text: str) -> str:
    """Rewrites engine stdout: every deny decision gets the lesson for its rule. Other lines pass through unchanged."""
    if not text or '"deny"' not in text:
        return text
    out_lines = []
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("{") and '"deny"' in stripped:
            try:
                payload = json.loads(stripped)
            except ValueError:
                out_lines.append(line)
                continue
            reason = payload.get("reason") if isinstance(payload, dict) else None
            if isinstance(payload, dict) and payload.get("decision") == "deny" and isinstance(reason, str):
                reason = strip_symbol_prefix(reason)
                m = _RULE_TAG.search(reason)
                if m and "Doğru yol:" not in reason:
                    reason += lesson_text(m.group(1))
                payload["reason"] = reason
                # ASCII-escaped like the engine's own json.dumps: hosts decode hook output with different codecs.
                out_lines.append(json.dumps(payload) + ("\n" if line.endswith("\n") else ""))
                continue
        out_lines.append(line)
    return "".join(out_lines)
