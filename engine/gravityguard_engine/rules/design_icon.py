"""Standard emoji or icon characters in source code (advisory). Detection stays in architecture_rules.py."""
from gravityguard_engine.architecture_rules import find_design_icon_violations
from gravityguard_engine.plugin_rules import Rule


def _check(ctx):
    found = find_design_icon_violations(ctx.path, ctx.content, {n for n, _text in ctx.added})
    return [(v["line"], v["snippet"]) for v in found]


RULE = Rule(
    id="DESIGN_ICON_RULE",
    message="Kodda standart emoji/ikon kullanımı tespit edildi. Zero-Bloat ve Minimalist UI standardı gereği "
            "kaynak kodda emoji/ikon kullanılamaz; sadece temiz tipografi veya SVG kullanın.",
    tip="Standart emoji veya simge karakteri kullanma; projenin ikon bileşenini ya da düz metni kullan.",
    check=_check,
    bad='const label = "' + chr(0x2705) + '";\n',
    good='const label = "ok";\n',
    sample_ext=".ts",
    skip_tests=False,
)
