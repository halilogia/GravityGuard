"""
GravityGuard Engine — SRP_RESPONSIBILITY_MIX (WARN ONLY).

The blocking SRP check (srp_python.py) counts classes and UI+network imports, so it cannot see a procedural monolith:
one file or one giant function that talks to a database, the file system, the network and holds the business logic,
without a single class. This module reports exactly that, from the concerns a file touches:
  ui, net, db, fs, proc
- file level: >= 3 concerns once the file has `srpMixMinLoc` lines, or >= 2 concerns at twice that size;
- Python function level: one function of `srpMaxFunctionLoc`+ lines that touches >= 2 concerns;
- TypeScript / JavaScript: the same file-level rule, plus a "kitchen sink" module with many top-level exports.
It never blocks; a declared `srp: allow-monolith` marker silences it, and the debt ratchet keeps the file from growing.
"""
import ast
import re
from typing import Dict, List, Optional, Set

from .project_context import DEFAULT_COMPLEXITY_THRESHOLDS
from .srp_python import import_kinds, is_py_cohesive_monolith, is_test_path

RULE_ID = "SRP_RESPONSIBILITY_MIX"
KITCHEN_SINK_EXPORTS = 25

_DB_PACKAGES = {"sqlite3", "sqlalchemy", "psycopg", "psycopg2", "pymysql", "mysql", "pymongo", "peewee", "asyncpg",
                "aiosqlite", "redis", "tortoise"}
_FS_PACKAGES = {"shutil", "pathlib", "glob"}
_PROC_PACKAGES = {"subprocess"}
_SQL_RE = re.compile(r"\b(?:SELECT\s[\s\S]{1,200}?\sFROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|CREATE\s+TABLE)\b", re.IGNORECASE)

_TS_MARKER_RE = re.compile(r"(?://|/\*|#)\s*srp\s*:\s*(?:allow-monolith|cohesive-monolith|bypass|noqa)\b", re.IGNORECASE)
_TS_CONCERNS = {
    "ui": re.compile(r"""from\s+['"](?:react|react-dom|preact|vue|svelte|solid-js)['"]|\bdocument\.(?:getElementById|querySelector|createElement)\b"""),
    "net": re.compile(r"""\bfetch\(|\baxios\b|\bXMLHttpRequest\b|\bnew\s+WebSocket\(|from\s+['"](?:node:)?(?:https?|ws|socket\.io(?:-client)?)['"]"""),
    "db": re.compile(r"""from\s+['"](?:pg|mysql2?|sqlite3|better-sqlite3|mongodb|mongoose|@prisma/client|typeorm|knex|redis|ioredis)['"]|\bindexedDB\b|\blocalStorage\b"""),
    "fs": re.compile(r"""from\s+['"](?:node:)?fs(?:/promises)?['"]|require\(\s*['"](?:node:)?fs(?:/promises)?['"]"""),
    "proc": re.compile(r"""\bchild_process\b"""),
}
_TS_EXPORT_RE = re.compile(r"^export\s+(?:default\s+)?(?:async\s+)?(?:function|const|class|let)\b", re.MULTILINE)


def _loc(content: str) -> int:
    return sum(1 for line in content.splitlines() if line.strip())


def _mix_is_reportable(concerns: Set[str], loc: int, min_loc: int) -> bool:
    return (len(concerns) >= 3 and loc >= min_loc) or (len(concerns) >= 2 and loc >= 2 * min_loc)


def _alias_kinds(tree: ast.AST) -> Dict[str, str]:
    """Local name -> concern, for every imported module / name the file binds."""
    aliases: Dict[str, str] = {}

    def classify(module: str, names: tuple) -> Optional[str]:
        top = module.lower().split(".")[0]
        kinds = import_kinds(module, names)
        if kinds:
            return sorted(kinds)[0]
        for kind, packages in (("db", _DB_PACKAGES), ("fs", _FS_PACKAGES), ("proc", _PROC_PACKAGES)):
            if top in packages:
                return kind
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                kind = classify(alias.name, ())
                if kind:
                    aliases[(alias.asname or alias.name).split(".")[0]] = kind
        elif isinstance(node, ast.ImportFrom) and not node.level:
            for alias in node.names:
                kind = classify(node.module or "", (alias.name,))
                if kind:
                    aliases[alias.asname or alias.name] = kind
    return aliases


def _node_concerns(node: ast.AST, aliases: Dict[str, str]) -> Set[str]:
    found: Set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            if sub.id in aliases:
                found.add(aliases[sub.id])
            elif sub.id == "open":
                found.add("fs")
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str) and _SQL_RE.search(sub.value):
            found.add("db")
    return found


def analyze_python_responsibility_mix(content: str, file_path: str = "", thresholds: Optional[Dict[str, int]] = None) -> List[str]:
    if is_py_cohesive_monolith(content) or is_test_path(file_path):
        return []
    thresholds = thresholds or DEFAULT_COMPLEXITY_THRESHOLDS
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return []

    aliases = _alias_kinds(tree)
    messages: List[str] = []
    concerns = _node_concerns(tree, aliases)
    loc = _loc(content)
    if _mix_is_reportable(concerns, loc, thresholds["srpMixMinLoc"]):
        messages.append(
            f"Karışık Sorumluluk: Dosya {loc} satırda {len(concerns)} ayrı sorumluluğa dokunuyor "
            f"({', '.join(sorted(concerns))}). Sınıfı olmasa da veri erişimi, dosya/ağ işleri ve iş mantığı ayrı modüllere bölünmeli."
        )

    max_fn_loc = thresholds["srpMaxFunctionLoc"]
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        fn_loc = getattr(fn, "end_lineno", fn.lineno) - fn.lineno + 1
        fn_concerns = _node_concerns(fn, aliases)
        if fn_loc >= max_fn_loc and len(fn_concerns) >= 2:
            messages.append(
                f"Dev İşlev: '{fn.name}' {fn_loc} satır ve {', '.join(sorted(fn_concerns))} sorumluluklarını iç içe taşıyor. "
                f"Her sorumluluğu ayrı bir işleve çıkarın."
            )
            if len(messages) >= 3:
                break
    return messages


def analyze_ts_responsibility_mix(content: str, file_path: str = "", thresholds: Optional[Dict[str, int]] = None) -> List[str]:
    if _TS_MARKER_RE.search(content) or is_test_path(file_path) or (file_path or "").lower().endswith(".d.ts"):
        return []
    thresholds = thresholds or DEFAULT_COMPLEXITY_THRESHOLDS
    min_loc = thresholds["srpMixMinLoc"]
    loc = _loc(content)
    if loc < min_loc:
        return []

    messages: List[str] = []
    concerns = {name for name, pattern in _TS_CONCERNS.items() if pattern.search(content)}
    if _mix_is_reportable(concerns, loc, min_loc):
        messages.append(
            f"Karışık Sorumluluk: Dosya {loc} satırda {len(concerns)} ayrı sorumluluğa dokunuyor "
            f"({', '.join(sorted(concerns))}). Servis / hook dosyasını sorumluluğa göre bölün."
        )
    exports = len(_TS_EXPORT_RE.findall(content))
    if exports >= KITCHEN_SINK_EXPORTS:
        messages.append(
            f"Her Şey Bir Arada Modül: Dosya {loc} satırda {exports} dışa aktarım içeriyor. Konuya göre ayrı modüllere bölün."
        )
    return messages
