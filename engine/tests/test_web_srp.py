import unittest
import os
import sys

# Ensure engine path is available
_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine.web_srp_analyzer import analyze_html_srp


class TestWebSrpAnalyzer(unittest.TestCase):

    def test_pure_html_skeleton_allowed(self):
        """T02: Pure 100 LOC HTML skeleton without inline CSS/JS must be ALLOWED."""
        lines = ["<!DOCTYPE html>", "<html>", "<head><title>App</title></head>", "<body>"]
        for i in range(100):
            lines.append(f'  <div id="row-{i}" class="container p-4"><span>Row {i}</span></div>')
        lines.extend(["</body>", "</html>"])
        html = "\n".join(lines)
        
        is_violation, rule_id, reason, warnings = analyze_html_srp(html, "index.html")
        self.assertFalse(is_violation, f"Pure HTML skeleton should not violate SRP: {reason}")
        self.assertEqual(rule_id, "")

    def test_inline_js_budget_deny(self):
        """T03: Inline executable JS > 30 LOC must be DENIED with WEB_INLINE_JS_BUDGET."""
        js_lines = [f"  console.log('step {i}'); window.state = {i};" for i in range(35)]
        html = f"""<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
  <h1>App</h1>
  <script>
{chr(10).join(js_lines)}
  </script>
</body>
</html>"""
        is_violation, rule_id, reason, warnings = analyze_html_srp(html, "index.html")
        self.assertTrue(is_violation)
        self.assertEqual(rule_id, "WEB_INLINE_JS_BUDGET")
        self.assertIn("35 satır çalıştırılabilir", reason)

    def test_inline_js_budget_warn(self):
        """T04: Inline executable JS between 11 and 30 LOC must be ALLOWED with a WARN."""
        js_lines = [f"  console.log('step {i}');" for i in range(15)]
        html = f"""<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
  <h1>App</h1>
  <script>
{chr(10).join(js_lines)}
  </script>
</body>
</html>"""
        is_violation, rule_id, reason, warnings = analyze_html_srp(html, "index.html")
        self.assertFalse(is_violation, f"15 LOC should not be DENIED: {reason}")
        warn_rules = [w[0] for w in warnings]
        self.assertIn("WEB_INLINE_JS_BUDGET", warn_rules)

    def test_inline_css_budget_deny(self):
        """T05: Inline CSS > 60 LOC must be DENIED with WEB_INLINE_CSS_BUDGET."""
        css_lines = [f"  .item-{i} {{ color: red; margin: {i}px; padding: 2px; }}" for i in range(65)]
        html = f"""<!DOCTYPE html>
<html>
<head>
  <style>
{chr(10).join(css_lines)}
  </style>
</head>
<body><h1>App</h1></body>
</html>"""
        is_violation, rule_id, reason, warnings = analyze_html_srp(html, "index.html")
        self.assertTrue(is_violation)
        self.assertEqual(rule_id, "WEB_INLINE_CSS_BUDGET")
        self.assertIn("65 satır gömülü", reason)

    def test_non_executable_scripts_exempt(self):
        """T06: Data blocks like type='application/json' must be EXEMPT from the executable JS budget."""
        json_lines = [f'  "key_{i}": "value_{i}",' for i in range(100)]
        html = f"""<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
  <script type="application/json" id="app-config">
  {{
{chr(10).join(json_lines)}
    "final": true
  }}
  </script>
</body>
</html>"""
        is_violation, rule_id, reason, warnings = analyze_html_srp(html, "index.html")
        self.assertFalse(is_violation, f"application/json should be exempt from JS budget: {reason}")

    def test_external_script_exempt(self):
        """T09: External scripts with src='...' must NOT count toward inline JS budget."""
        html = """<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
  <script src="/js/formations.js"></script>
  <script src="/js/pitch.js"></script>
  <script src="/js/app.js"></script>
</body>
</html>"""
        is_violation, rule_id, reason, warnings = analyze_html_srp(html, "index.html")
        self.assertFalse(is_violation)

    def test_minified_js_byte_limit_deny(self):
        """T07: Single-line minified JS exceeding 2 KiB (2048 bytes) must be DENIED."""
        # 3000 bytes on a single line
        long_js = "var a=1;" * 400  # 3200 bytes
        html = f"""<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
  <script>{long_js}</script>
</body>
</html>"""
        is_violation, rule_id, reason, warnings = analyze_html_srp(html, "index.html")
        self.assertTrue(is_violation)
        self.assertEqual(rule_id, "WEB_INLINE_JS_BUDGET")
        self.assertIn("KiB", reason)

    def test_multi_block_js_aggregation(self):
        """T08: Multiple inline script blocks must have their LOC aggregated."""
        block1 = [f"  let x{i} = {i};" for i in range(18)]
        block2 = [f"  let y{i} = {i};" for i in range(18)]
        # Total = 36 LOC
        html = f"""<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
  <script>
{chr(10).join(block1)}
  </script>
  <script>
{chr(10).join(block2)}
  </script>
</body>
</html>"""
        is_violation, rule_id, reason, warnings = analyze_html_srp(html, "index.html")
        self.assertTrue(is_violation)
        self.assertEqual(rule_id, "WEB_INLINE_JS_BUDGET")
        self.assertIn("36 satır çalıştırılabilir", reason)

    def test_mixed_responsibilities_deny(self):
        """T10: Embedding both JS (>10 LOC) and CSS (>20 LOC) in HTML violates Separation of Concerns."""
        js_lines = [f"  const step{i} = {i};" for i in range(15)]
        css_lines = [f"  .rule-{i} {{ color: blue; }}" for i in range(25)]
        html = f"""<!DOCTYPE html>
<html>
<head>
  <style>
{chr(10).join(css_lines)}
  </style>
</head>
<body>
  <script>
{chr(10).join(js_lines)}
  </script>
</body>
</html>"""
        is_violation, rule_id, reason, warnings = analyze_html_srp(html, "index.html")
        self.assertTrue(is_violation)
        self.assertEqual(rule_id, "WEB_MIXED_RESPONSIBILITIES")

    def test_football_manager_monolith_regression(self):
        """T01: The original 880 LOC Football Manager index.html monolith must be strictly DENIED."""
        # Simulate original monolith: 880 lines with CSS and JS combined
        css = "\n".join([f".pitch-line-{i} {{ width: {i}px; }}" for i in range(70)])
        js = "\n".join([f"function handleTactic{i}() {{ return {i}; }}" for i in range(100)])
        markup = "\n".join([f"<div class='player-{i}'>Player {i}</div>" for i in range(600)])
        html = f"""<!DOCTYPE html>
<html>
<head>
  <style>
{css}
  </style>
</head>
<body>
{markup}
  <script>
{js}
  </script>
</body>
</html>"""
        is_violation, rule_id, reason, warnings = analyze_html_srp(html, "index.html")
        self.assertTrue(is_violation, "Original 880 LOC monolith must be blocked by GravityGuard")
        self.assertIn(rule_id, ["WEB_INLINE_JS_BUDGET", "WEB_INLINE_CSS_BUDGET", "WEB_MIXED_RESPONSIBILITIES", "WEB_DOCUMENT_SIZE"])

    def test_escape_hatch_marker(self):
        """T11: Explicit escape hatch marker allows monolith when consciously required."""
        js_lines = [f"  console.log({i});" for i in range(40)]
        html = f"""<!DOCTYPE html>
<!-- srp: allow-monolith -->
<html>
<body>
  <script>
{chr(10).join(js_lines)}
  </script>
</body>
</html>"""
        is_violation, rule_id, reason, warnings = analyze_html_srp(html, "index.html")
        self.assertFalse(is_violation, "Escape hatch marker should exempt file")


if __name__ == '__main__':
    unittest.main()
