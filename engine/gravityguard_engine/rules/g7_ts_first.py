"""G7: new application JavaScript should be TypeScript (advisory). Detection stays in architecture_rules.py."""
from gravityguard_engine.architecture_rules import evaluate_g7_ts_first
from gravityguard_engine.plugin_rules import Rule


def _check(ctx):
    flagged, message = evaluate_g7_ts_first(ctx.path, ctx.content)
    return [(1, message)] if flagged else []


RULE = Rule(
    id="G7_TS_FIRST",
    message="Yeni uygulama kodu TypeScript olmalı; bu yalnızca bir uyarıdır.",
    tip="Yeni uygulama kodunu .ts olarak yaz; .js gerekiyorsa devam et; bu yalnızca bir uyarıdır.",
    check=_check,
    bad="const x = 1;\n",
    good="const x = 1;\n",
    extensions=(".js", ".jsx", ".cjs", ".mjs"),
    sample_ext=".js",
    good_ext=".min.js",  # bundles are exempt
)
