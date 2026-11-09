"""Default browser scrollbars in web files. Moved out of dispatcher.py; the detection stays in design_rules.py."""
from gravityguard_engine.design_rules import check_design_scrollbar_rule
from gravityguard_engine.plugin_rules import Rule


def _check(ctx):
    added_text = "".join(text + "\n" for _n, text in ctx.added)
    return [ctx.added[0]] if ctx.added and check_design_scrollbar_rule(ctx.path, added_text) else []


RULE = Rule(
    id="DESIGN_SCROLLBAR_RULE",
    message="Tasarım kuralına uymuyor hemen düzelt: webin varsayılan yukarı aşağı kaydırma barları kullanılamaz. "
            "Evrensel minimalist / görünmez scrollbar standardı uygulanmalıdır.",
    tip="Varsayılan kaydırma çubuğunu bırakma; ince, temaya uygun scrollbar stili tanımla.",
    check=_check,
    bad=".panel { overflow-y: auto; height: 200px; }\n",
    good=".panel { overflow-y: auto; scrollbar-width: none; }\n.panel::-webkit-scrollbar { display: none; }\n",
    extensions=(".html", ".css", ".vue", ".svelte", ".tsx", ".jsx"),
    skip_tests=False,
)
