"""
Web SRP Analyzer for GravityGuard (HTML & Web Separation of Concerns)
Enforces deterministic budgets and structural Separation of Concerns on HTML files.

Rules enforced:
- WEB_INLINE_JS_BUDGET: Executable inline JS >30 LOC or >2048 bytes -> DENY (>10 LOC -> WARN)
- WEB_INLINE_CSS_BUDGET: Inline CSS >60 LOC or >4096 bytes -> DENY (>20 LOC -> WARN)
- WEB_MIXED_RESPONSIBILITIES: JS (>10 LOC) and CSS (>20 LOC) embedded together -> DENY
- WEB_DOCUMENT_SIZE: HTML >350 LOC -> WARN, HTML >600 LOC + structural violation -> DENY
"""

import re
from typing import List, Tuple, Dict, Any

# Non-executable script types that are exempt from JS code budgets
NON_EXECUTABLE_SCRIPT_TYPES = {
    "application/json",
    "application/ld+json",
    "importmap",
    "speculationrules",
    "text/html",
    "text/plain",
    "text/template"
}

def strip_html_comments(html: str) -> str:
    """Removes <!-- ... --> comments from HTML content."""
    return re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)

def strip_js_comments(js: str) -> str:
    """Removes single-line and multi-line comments from JS content."""
    js_no_multi = re.sub(r'/\*.*?\*/', '', js, flags=re.DOTALL)
    js_clean = re.sub(r'//.*', '', js_no_multi)
    return js_clean

def strip_css_comments(css: str) -> str:
    """Removes /* ... */ comments from CSS content."""
    return re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)

def count_clean_lines(text: str) -> int:
    """Counts non-empty lines in text."""
    return len([line for line in text.splitlines() if line.strip()])

def extract_style_blocks(html: str) -> List[Dict[str, Any]]:
    """
    Extracts all <style> blocks from HTML.
    Returns list of dicts with attrs, raw_content, clean_loc, byte_size.
    """
    results = []
    pattern = re.compile(r'<style(?P<attrs>[^>]*)>(?P<content>.*?)</style>', re.IGNORECASE | re.DOTALL)
    for m in pattern.finditer(html):
        attrs = m.group('attrs')
        content = m.group('content')
        clean_content = strip_css_comments(content)
        loc = count_clean_lines(clean_content)
        byte_size = len(content.strip().encode('utf-8'))
        results.append({
            'attrs': attrs,
            'raw_content': content,
            'clean_loc': loc,
            'byte_size': byte_size
        })
    return results

def extract_script_blocks(html: str) -> List[Dict[str, Any]]:
    """
    Extracts all <script> blocks from HTML, identifying executable vs non-executable/external scripts.
    """
    results = []
    pattern = re.compile(r'<script(?P<attrs>[^>]*)>(?P<content>.*?)</script>', re.IGNORECASE | re.DOTALL)
    for m in pattern.finditer(html):
        attrs = m.group('attrs')
        content = m.group('content')
        
        # Check if external script with src attribute
        has_src = bool(re.search(r'\bsrc\s*=\s*["\']?[^"\'>\s]+', attrs, re.IGNORECASE))
        
        # Check script type
        type_match = re.search(r'\btype\s*=\s*["\']?([^"\'>\s]+)', attrs, re.IGNORECASE)
        script_type = type_match.group(1).lower() if type_match else ""
        
        is_executable = not has_src and (script_type not in NON_EXECUTABLE_SCRIPT_TYPES)
        
        clean_content = strip_js_comments(content) if is_executable else content
        loc = count_clean_lines(clean_content)
        byte_size = len(content.strip().encode('utf-8'))
        
        results.append({
            'attrs': attrs,
            'raw_content': content,
            'has_src': has_src,
            'type': script_type,
            'is_executable': is_executable,
            'clean_loc': loc,
            'byte_size': byte_size
        })
    return results

def analyze_html_srp(
    html_content: str,
    file_path: str = ""
) -> Tuple[bool, str, str, List[Tuple[str, str]]]:
    """
    Analyzes an HTML file against GravityGuard Web SRP & Separation of Concerns budgets.
    
    Returns:
        (is_violation, rule_id, deny_reason, list_of_warnings)
    """
    warnings: List[Tuple[str, str]] = []
    
    # 1. Total Document clean LOC
    clean_html = strip_html_comments(html_content)
    total_doc_loc = count_clean_lines(clean_html)
    
    # 2. Extract style and script blocks
    style_blocks = extract_style_blocks(html_content)
    script_blocks = extract_script_blocks(html_content)
    
    total_css_loc = sum(b['clean_loc'] for b in style_blocks)
    total_css_bytes = sum(b['byte_size'] for b in style_blocks)
    
    exec_scripts = [s for s in script_blocks if s['is_executable']]
    total_js_loc = sum(s['clean_loc'] for s in exec_scripts)
    total_js_bytes = sum(s['byte_size'] for s in exec_scripts)
    
    # Check for escape hatch marker (e.g. <!-- srp: allow-monolith -->)
    if re.search(r'<!--\s*(?:srp\s*:\s*(?:allow-monolith|cohesive-monolith|bypass|noqa)|noqa\s*:\s*srp)\s*-->', html_content, re.IGNORECASE):
        return False, "", "SRP Exempted via comment marker", []

    # RULE 1: WEB_INLINE_JS_BUDGET
    # Executable inline JS > 30 LOC or > 2048 bytes -> DENY
    if total_js_loc > 30:
        return (
            True,
            "WEB_INLINE_JS_BUDGET",
            f"HTML dosyasında {total_js_loc} satır çalıştırılabilir gömülü JavaScript tespit edildi (Azami sınır: 30 LOC). "
            f"İş mantığı, durum yönetimi ve veri yapılarını bağımsız .js/.ts modüllerine taşıyın.",
            warnings
        )
    if total_js_bytes > 2048:
        return (
            True,
            "WEB_INLINE_JS_BUDGET",
            f"HTML dosyasında {total_js_bytes} bayt (~{(total_js_bytes/1024):.1f} KiB) gömülü JavaScript tespit edildi (Azami sınır: 2 KiB). "
            f"Komut dosyalarını harici bir .js dosyasına çıkarıp <script src=\"...\"> ile bağlayın.",
            warnings
        )
    if total_js_loc > 10:
        warnings.append((
            "WEB_INLINE_JS_BUDGET",
            f"Gömülü JavaScript {total_js_loc} LOC seviyesinde (Önerilen sınır: 10 LOC). Küçük yardımcı işlevler dışında betikleri harici dosyalara ayırın."
        ))

    # RULE 2: WEB_INLINE_CSS_BUDGET
    # Inline CSS > 60 LOC or > 4096 bytes -> DENY
    if total_css_loc > 60:
        return (
            True,
            "WEB_INLINE_CSS_BUDGET",
            f"HTML dosyasında {total_css_loc} satır gömülü <style> CSS tespit edildi (Azami sınır: 60 LOC). "
            f"Stil tanımlarını harici bir .css dosyasına taşıyın ve <link rel=\"stylesheet\"> ile bağlayın.",
            warnings
        )
    if total_css_bytes > 4096:
        return (
            True,
            "WEB_INLINE_CSS_BUDGET",
            f"HTML dosyasında {total_css_bytes} bayt (~{(total_css_bytes/1024):.1f} KiB) gömülü CSS tespit edildi (Azami sınır: 4 KiB). "
            f"Stil kurallarını bağımsız .css dosyasına ayırın.",
            warnings
        )
    if total_css_loc > 20:
        warnings.append((
            "WEB_INLINE_CSS_BUDGET",
            f"Gömülü CSS {total_css_loc} LOC seviyesinde (Önerilen sınır: 20 LOC). Stilleri harici .css dosyasında toplamayı değerlendirin."
        ))

    # RULE 3: WEB_MIXED_RESPONSIBILITIES
    # If both JS (>10 LOC) and CSS (>20 LOC) are embedded together in the same HTML file
    if total_js_loc > 10 and total_css_loc > 20:
        return (
            True,
            "WEB_MIXED_RESPONSIBILITIES",
            f"Separation of Concerns (SoC) İhlali: HTML dosyası hem {total_js_loc} satır gömülü JS hem de {total_css_loc} satır gömülü CSS içeriyor. "
            f"Görsel stilleri ayrı .css dosyasına, betik mantığını ise bağımsız .js modülüne ayırın.",
            warnings
        )

    # RULE 4: WEB_DOCUMENT_SIZE
    # > 350 LOC -> WARN, > 600 LOC + structural violation -> DENY
    if total_doc_loc > 600 and (total_js_loc > 10 or total_css_loc > 20 or len(style_blocks) + len(exec_scripts) >= 3):
        return (
            True,
            "WEB_DOCUMENT_SIZE",
            f"Monolitik HTML İhlali: Belge {total_doc_loc} satır uzunluğunda ve gömülü stil/betik sorumluluklarını aynı dosyada biriktiriyor. "
            f"HTML yalnızca saf DOM iskeletini barındırmalıdır.",
            warnings
        )
    elif total_doc_loc > 350:
        warnings.append((
            "WEB_DOCUMENT_SIZE",
            f"HTML belgesi {total_doc_loc} satıra ulaştı (Önerilen modüler sınır: 350 LOC). Arayüz bileşenlerini şablonlara veya alt modüllere bölmeyi değerlendirin."
        ))

    return False, "", "HTML SRP Compliant", warnings
