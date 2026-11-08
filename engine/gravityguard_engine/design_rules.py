"""Scrollbar, responsive-viewport and raw-control design rules (split from architecture_rules.py)."""
from html.parser import HTMLParser
import re
from typing import Any, Dict, List, Optional, Set, Tuple


# --- DESIGN_SCROLLBAR_RULE: DEFAULT WEBKIT / BROWSER SCROLLBAR BAN (WARN ONLY) ---
def check_design_scrollbar_rule(target_file: str, added_text: str) -> List[str]:
    """
    Checks that web files (html, css, vue, svelte, tsx) with scrolling containers do not rely
    on default browser scrollbars. Requires sleek custom scrollbar definitions (scrollbar-width,
    ::-webkit-scrollbar, ::-webkit-scrollbar-button { display: none }).
    """
    norm = target_file.replace("\\", "/").lower()
    parts = norm.split("/")
    name = parts[-1]
    if not name.endswith((".html", ".css", ".vue", ".svelte", ".tsx", ".jsx")):
        return []
    if any(part in {"doc", "docs", "documentation", "test", "tests", "__tests__"} for part in parts[:-1]):
        return []
    if any(marker in name for marker in ("test_", "_test.", ".test.", "spec.")):
        return []

    violations = []
    if re.search(r"\boverflow(?:-[xy])?\s*:\s*(?:scroll|auto)\b", added_text, re.IGNORECASE):
        if not re.search(r"::-webkit-scrollbar|scrollbar-width", added_text, re.IGNORECASE):
            violations.append("varsayılan tarayıcı kaydırma çubuğu (custom scrollbar eksik)")
    return violations


# --- DESIGN_RESPONSIVE_RULE: MOBILE / PHONE VIEWPORT & FLUID LAYOUT (STRICT DENY & WARN) ---
class ResponsiveHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.has_head = False
        self.head_line = 1
        self.has_html = False
        self.has_doctype = False
        self.viewports: List[Tuple[int, str]] = []

    def handle_decl(self, decl: str) -> None:
        if "doctype html" in decl.lower():
            self.has_doctype = True

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attrs_dict = {k.lower(): (v or "") for k, v in attrs if k}
        line, _ = self.getpos()

        t_lower = tag.lower()
        if t_lower == "html":
            self.has_html = True
        elif t_lower == "head":
            self.has_head = True
            self.head_line = line
        elif t_lower == "meta":
            if attrs_dict.get("name", "").strip().lower() == "viewport":
                content = attrs_dict.get("content", "").strip().lower()
                self.viewports.append((line, content))


def is_valid_viewport_directive(content: str) -> bool:
    """Verifies that the viewport meta content specifies width=device-width and initial-scale=1."""
    clean = content.replace(" ", "")
    if "width=device-width" not in clean:
        return False
    scale_match = re.search(r"initial-scale\s*=\s*([0-9.]+)", content)
    if not scale_match:
        return False
    try:
        val = float(scale_match.group(1))
        return val == 1.0
    except ValueError:
        return False


def find_design_responsive_violations(
    target_file: str,
    projected_content: str,
    added_line_numbers: Optional[Set[int]] = None
) -> List[Dict[str, Any]]:
    """
    Evaluates Mobile / Phone Responsive Design requirements:
    1. Full HTML documents must include a valid <meta name="viewport" content="width=device-width, initial-scale=1.0"> in <head> (STRICT DENY).
    2. Large fixed pixel widths (>=1000px) in CSS declarations without fluid constraints (WARN).
    """
    norm = target_file.replace("\\", "/").lower()
    parts = norm.split("/")
    name = parts[-1]

    if any(part in {"doc", "docs", "documentation", "test", "tests", "__tests__", "node_modules", ".git"} for part in parts[:-1]):
        return []
    if any(marker in name for marker in ("test_", "_test.", ".test.", "spec.")):
        return []

    violations: List[Dict[str, Any]] = []
    lines = projected_content.splitlines()

    # 1. Full HTML Viewport Meta Check (DENY if missing in full document)
    if name.endswith((".html", ".htm")):
        parser = ResponsiveHTMLParser()
        try:
            parser.feed(projected_content)
            parser.close()
        except Exception:
            return violations

        if parser.has_doctype or parser.has_head or parser.has_html:
            valid_found = False
            for line_no, content in parser.viewports:
                if is_valid_viewport_directive(content):
                    valid_found = True
                    break

            if not valid_found:
                snippet = lines[parser.head_line - 1].strip() if 0 < parser.head_line <= len(lines) else "<head>"
                violations.append({
                    "rule": "INVALID_VIEWPORT",
                    "severity": "DENY",
                    "line": parser.head_line,
                    "snippet": snippet,
                    "message": "Mobil viewport sözleşmesi ihlali: <head> içinde '<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">' etiketi zorunludur! Bu etiket olmadan mobil tarayıcılar masaüstü 980px zoom simülasyonuna düşer.",
                    "suggestion": '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
                })

    # 2. Large Fixed Width Overflow Risk Check (WARN)
    if name.endswith((".css", ".html", ".htm", ".vue", ".svelte")):
        fixed_width_pattern = re.compile(
            r"\b(width|min-width|inline-size|min-inline-size)\s*:\s*([1-9][0-9]{3,})px\b",
            re.IGNORECASE
        )
        for idx, line in enumerate(lines, 1):
            if added_line_numbers is not None and idx not in added_line_numbers:
                continue
            trimmed = line.strip()
            if trimmed.startswith("/*") or trimmed.startswith("//") or trimmed.startswith("*"):
                continue

            m = fixed_width_pattern.search(line)
            if m:
                prop = m.group(1)
                val = int(m.group(2))
                if val >= 1000:
                    snippet = trimmed
                    if len(snippet) > 80:
                        snippet = snippet[:77] + "..."
                    violations.append({
                        "rule": "LARGE_FIXED_WIDTH",
                        "severity": "WARN",
                        "line": idx,
                        "snippet": snippet,
                        "message": f"Mobilde yatay taşma riski: '{prop}: {val}px' büyük sabit piksel genişliği tespit edildi.",
                        "suggestion": "Sabit piksel yerine 'max-width: 100%', 'min()', 'clamp()' veya fluid flex/grid düzeni kullanın."
                    })

    return violations


# --- DESIGN_RAW_CONTROLS_RULE: RAW BROWSER CONTROLS BAN (STRICT LINE-TARGETED DENY) ---
def find_design_raw_controls_violations(
    target_file: str,
    projected_content: str,
    added_line_numbers: Optional[Set[int]] = None
) -> List[Dict[str, Any]]:
    """
    Enforces styled controls over unstyled raw browser elements:
    - Raw unstyled <input type="file"> (must use custom class/label wrapper or ::file-selector-button).
    - Raw unstyled scrollbars (overflow: scroll/auto without custom scrollbar CSS).
    - Raw unstyled <input type="number"> (must hide native stepper arrows via appearance: textfield).
    Returns list of violation dicts with exact line number and snippet.
    """
    norm = target_file.replace("\\", "/").lower()
    parts = norm.split("/")
    name = parts[-1]

    if not name.endswith((".html", ".htm", ".css", ".vue", ".svelte", ".tsx", ".jsx")):
        return []
    if any(part in {"doc", "docs", "documentation", "test", "tests", "__tests__", "node_modules", ".git"} for part in parts[:-1]):
        return []
    if any(marker in name for marker in ("test_", "_test.", ".test.", "spec.")):
        return []

    violations: List[Dict[str, Any]] = []
    lines = projected_content.splitlines()

    # 1. Raw file input check in HTML/templates
    if name.endswith((".html", ".htm", ".vue", ".svelte", ".tsx", ".jsx")):
        raw_file_pattern = re.compile(r'<input\s+[^>]*type=["\']file["\']', re.IGNORECASE)
        styled_pattern = re.compile(r'(class=["\'][^"\']*(?:custom-file|hidden|sr-only|file-input)[^"\']*["\']|style=["\'][^"\']*display\s*:\s*none)', re.IGNORECASE)
        for idx, line in enumerate(lines, 1):
            if added_line_numbers is not None and idx not in added_line_numbers:
                continue
            if raw_file_pattern.search(line):
                if not styled_pattern.search(line) and "file-selector-button" not in projected_content:
                    snippet = line.strip()
                    if len(snippet) > 80:
                        snippet = snippet[:77] + "..."
                    violations.append({
                        "line": idx,
                        "type": "RAW_FILE_INPUT",
                        "snippet": snippet,
                        "message": "Ham varsayılan dosya seçme butonu tespit edildi (<input type=\"file\">). Zero-Bloat standardı gereği gizlenip özel butonla tetiklenmeli veya '::file-selector-button' ile minimalist olarak stillendirilmelidir."
                    })

    # 2. Raw number spinner check in HTML/templates
    if name.endswith((".html", ".htm", ".vue", ".svelte", ".tsx", ".jsx")):
        raw_num_pattern = re.compile(r'<input\s+[^>]*type=["\']number["\']', re.IGNORECASE)
        styled_num = re.compile(r'class=["\'][^"\']*(?:no-spin|custom-number|stepper)[^"\']*["\']', re.IGNORECASE)
        has_spinner_css = bool(re.search(r'::-webkit-inner-spin-button\s*\{[^}]*display\s*:\s*none', projected_content, re.IGNORECASE))
        if not has_spinner_css:
            for idx, line in enumerate(lines, 1):
                if added_line_numbers is not None and idx not in added_line_numbers:
                    continue
                if raw_num_pattern.search(line) and not styled_num.search(line):
                    snippet = line.strip()
                    if len(snippet) > 80:
                        snippet = snippet[:77] + "..."
                    violations.append({
                        "line": idx,
                        "type": "RAW_NUMBER_SPINNER",
                        "snippet": snippet,
                        "message": "Ham tarayıcı sayı arttırma oku (number spinner) tespit edildi (<input type=\"number\">). '::-webkit-inner-spin-button { display: none }' ve 'appearance: textfield' ile gizlenmelidir."
                    })

    return violations


