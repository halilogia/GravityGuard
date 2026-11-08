"""
GravityGuard Engine — logical clusters and copy-paste templates for refactor hints.

Instead of only naming the longest unit, this finds functions that belong together (shared name prefix such as `parse_*`,
or a public function with the private helpers only it calls) and gives the agent the sibling module path, the import line
to leave behind, the imports the new module needs, and a circular-import warning when the moved code still depends on
names that stay in the original file. A single giant class gets a mixin (or helper-function) split of its methods.
Python is read with the AST; TypeScript / JavaScript / Go / Rust / GDScript work on declaration blocks.
"""
import ast
import os
import re
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

MIN_CLUSTER_LOC = 30
MIN_CLASS_SPLIT_LOC = 60
MIN_CLASS_METHODS = 4
_MIN_HELPER_METHOD_LOC = 10
_MAX_LISTED = 5
_TS_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
_TOKEN_RE = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")
_WORD_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_TS_IMPORT_RE = re.compile(r"^import\s+(?P<spec>[^;]+?)\s+from\s+['\"][^'\"]+['\"]\s*;?[ \t]*$", re.M)
_TS_TOP_NAME_RE = re.compile(r"^(?:export\s+)?(?:const|let|var|enum|type)\s+([A-Za-z_$][A-Za-z0-9_$]*)", re.M)

Candidate = Tuple[int, str, FrozenSet[str]]


@dataclass
class _Unit:
    name: str
    loc: int
    names: Set[str]
    is_func: bool
    line: int
    node: ast.AST


def _prefix_key(name: str) -> str:
    tokens = _TOKEN_RE.findall(name.lstrip("_$").replace("_", " "))
    return tokens[0].lower() if len(tokens) > 1 else ""


def _snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).replace("-", "_").lstrip("_").lower()


def _sibling(file_path: str, suffix: str) -> Tuple[str, str]:
    """(project path, module stem) of the new sibling module next to `file_path`."""
    stem, ext = os.path.splitext(os.path.basename(file_path))
    module = f"{stem}_{suffix}"
    folder = os.path.dirname(file_path.replace("\\", "/"))
    return "/".join(p for p in (folder, module + ext) if p), module


def _listed(names: List[str]) -> str:
    shown = ", ".join(f"'{n}'" for n in names[:_MAX_LISTED])
    return shown + (f" (+{len(names) - _MAX_LISTED})" if len(names) > _MAX_LISTED else "")


def _deps_text(imports: List[str], leftovers: List[str], stem: str, what: str) -> str:
    parts = []
    if imports:
        parts.append("Hedef modülde gerekli importlar: " + ", ".join(f"`{s}`" for s in imports) + ".")
    if leftovers:
        parts.append(
            f"Döngüsel import uyarısı: {what} dosyada kalan {_listed(leftovers)} adlarını kullanıyor; hedef modül "
            f"'{stem}' dosyasını geri import etmesin — bunları da taşıyın veya parametre olarak geçirin."
        )
    return " ".join(parts)


def _is_func(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))


def _loc(node: ast.AST) -> int:
    return getattr(node, "end_lineno", node.lineno) - node.lineno + 1


class _PyModule:
    """Top-level units, defined names and import statements of one parsed Python file."""

    def __init__(self, tree: ast.Module):
        self.units: List[_Unit] = []
        self.imports: Dict[str, str] = {}
        self.top_defs: Set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.imports[alias.asname or alias.name.split(".")[0]] = (
                        f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else ""))
                continue
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name != "*":
                        self.imports[alias.asname or alias.name] = (
                            f"from {'.' * node.level}{node.module or ''} import {alias.name}"
                            + (f" as {alias.asname}" if alias.asname else ""))
                continue
            defined = self._defined_names(node)
            self.top_defs.update(defined)
            name = defined[0] if defined and isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) else ""
            self.units.append(_Unit(name or f"<stmt{node.lineno}>", _loc(node), self.free_names(node), _is_func(node), node.lineno, node))
        self.callers: Dict[str, Set[str]] = {}
        for unit in self.units:
            for used in unit.names - {unit.name}:
                self.callers.setdefault(used, set()).add(unit.name)

    @staticmethod
    def _defined_names(node: ast.AST) -> List[str]:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            return [node.name]
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        return [t.id for t in targets if isinstance(t, ast.Name)]

    @staticmethod
    def free_names(node: ast.AST) -> Set[str]:
        return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}

    def needs(self, used: Set[str], exclude: Set[str]) -> Tuple[List[str], List[str]]:
        """(import statements the moved code needs, names it uses that stay behind in the file)."""
        imports = sorted({self.imports[n] for n in used if n in self.imports and n not in self.top_defs})
        return imports, sorted((used & self.top_defs) - exclude)


def _absorb_helpers(members: Set[str], funcs: Dict[str, _Unit], callers: Dict[str, Set[str]], claimed: Set[str]) -> None:
    grown = True
    while grown:
        grown = False
        for name in funcs:
            who = callers.get(name)
            if name.startswith("_") and name not in members and name not in claimed and who and who <= members:
                members.add(name)
                grown = True


def _function_plans(module: _PyModule) -> List[Tuple[str, Set[str]]]:
    funcs = {u.name: u for u in module.units if u.is_func}
    groups: Dict[str, Set[str]] = {}
    for name in funcs:
        key = _prefix_key(name)
        if key:
            groups.setdefault(key, set()).add(name)
    plans = [(key, members) for key, members in groups.items() if len(members) >= 2]
    claimed = set().union(*(m for _, m in plans)) if plans else set()
    for _, members in plans:
        _absorb_helpers(members, funcs, module.callers, claimed)
        claimed |= members
    for name in funcs:
        if name.startswith("_") or name in claimed:
            continue
        members = {name}
        _absorb_helpers(members, funcs, module.callers, claimed)
        if len(members) > 1:
            plans.append((_snake(name), members))
            claimed |= members
    return plans


def _function_cluster(module: _PyModule, key: str, members: Set[str], file_path: str) -> Optional[Candidate]:
    units = sorted((u for u in module.units if u.name in members), key=lambda u: u.line)
    loc = sum(u.loc for u in units)
    if loc < MIN_CLUSTER_LOC:
        return None
    names = [u.name for u in units]
    path, stem = _sibling(file_path, key)
    outside = {n for n in members if module.callers.get(n, set()) - members}
    exported = [n for n in names if not n.startswith("_") or n in outside]
    used = set().union(*(u.names for u in units))
    imports, leftovers = module.needs(used, members)
    text = (
        f"'{os.path.basename(file_path)}' içindeki {_listed(names)} işlevlerini ({loc} satır) birlikte '{path}' altına "
        f"taşıyın; eski dosyada yerine `from .{stem} import {', '.join(exported)}` bırakın. "
        + _deps_text(imports, leftovers, os.path.splitext(os.path.basename(file_path))[0], "bu işlevler")
    ).strip()
    return loc, text, frozenset(members)


def _class_split(module: _PyModule, unit: _Unit, file_path: str) -> Optional[Candidate]:
    cls = unit.node
    if not isinstance(cls, ast.ClassDef):
        return None
    methods =[(m, _loc(m)) for m in cls.body if _is_func(m) and not (m.name.startswith("__") and m.name.endswith("__"))]
    if unit.loc < MIN_CLASS_SPLIT_LOC or len(methods) < MIN_CLASS_METHODS:
        return None
    groups: Dict[str, List[Tuple[ast.AST, int]]] = {}
    for method, loc in methods:
        key = _prefix_key(method.name)
        if key:
            groups.setdefault(key, []).append((method, loc))
    groups = {k: v for k, v in groups.items() if len(v) >= 2}
    base = os.path.splitext(os.path.basename(file_path))[0]
    head = f"'{unit.name}' sınıfı {unit.loc} satır / {len(methods)} metot: "
    if groups:
        key = max(groups, key=lambda k: sum(loc for _, loc in groups[k]))
        picked = groups[key]
        mixin = f"{unit.name}{key.capitalize()}Mixin"
        path, stem = _sibling(file_path, f"{_snake(unit.name)}_{key}")
        used = set().union(*(module.free_names(m) for m, _ in picked))
        imports, leftovers = module.needs(used, set())
        text = (
            f"{head}{_listed([m.name for m, _ in picked])} metotlarını ({sum(loc for _, loc in picked)} satır) '{path}' "
            f"içinde '{mixin}' sınıfına taşıyıp `class {unit.name}({mixin}):` yapın (`from .{stem} import {mixin}`); "
            f"self üzerinden erişim aynı kalır, mixin dosyası '{base}' dosyasını import etmemeli. "
            + _deps_text(imports, leftovers, base, "bu metotlar")
        ).strip()
        return unit.loc, text, frozenset({unit.name})
    big = sorted((p for p in methods if p[1] >= _MIN_HELPER_METHOD_LOC), key=lambda p: -p[1])[:3]
    if not big:
        return None
    path, stem = _sibling(file_path, f"{_snake(unit.name)}_helpers")
    helpers = [f"{m.name.lstrip('_')}_impl" for m, _ in big]
    text = (
        f"{head}en büyük metotların ({_listed([m.name for m, _ in big])}; {sum(loc for _, loc in big)} satır) gövdesini "
        f"'{path}' içinde self'i parametre alan modül işlevlerine taşıyın, metot yalnızca çağırsın "
        f"(örn. `from .{stem} import {', '.join(helpers)}`). Yardımcı dosya '{base}' dosyasını import etmemeli."
    )
    return unit.loc, text, frozenset({unit.name})


def python_candidates(content: str, file_path: str) -> List[Candidate]:
    """Cluster and class-split candidates (size, sentence, covered names) for a Python file."""
    try:
        module = _PyModule(ast.parse(content))
    except (SyntaxError, ValueError):
        return []
    found = [_function_cluster(module, key, members, file_path) for key, members in _function_plans(module)]
    found += [_class_split(module, u, file_path) for u in module.units if isinstance(u.node, ast.ClassDef)]
    return [c for c in found if c]


def block_candidates(blocks: List[Tuple[str, bool, int, str]], content: str, file_path: str) -> List[Candidate]:
    """Prefix clusters for declaration-block languages; `blocks` = (name, is_function, loc, text)."""
    groups: Dict[str, List[Tuple[str, bool, int, str]]] = {}
    for block in blocks:
        key = _prefix_key(block[0]) if block[1] else ""
        if key:
            groups.setdefault(key, []).append(block)
    is_ts = file_path.lower().endswith(_TS_SUFFIXES)
    top_names = {b[0] for b in blocks} | set(_TS_TOP_NAME_RE.findall(content))
    found = []
    for key, members in groups.items():
        loc = sum(b[2] for b in members)
        if len(members) < 2 or loc < MIN_CLUSTER_LOC:
            continue
        names = [b[0] for b in members]
        path, stem = _sibling(file_path, key)
        text = f"'{os.path.basename(file_path)}' içindeki {_listed(names)} işlevlerini ({loc} satır) birlikte '{path}' altına taşıyın"
        if is_ts:
            words = set(_WORD_RE.findall("\n".join(b[3] for b in members)))
            public = [n for n in names if not n.startswith("_")] or names
            imports = [m.group(0).strip() for m in _TS_IMPORT_RE.finditer(content) if words & set(_WORD_RE.findall(m["spec"]))]
            text += (
                f"; taşınanları export edip eski dosyada `import {{ {', '.join(public)} }} from './{stem}';` kullanın. "
                + _deps_text(imports, sorted((words & top_names) - set(names)), os.path.splitext(os.path.basename(file_path))[0], "bu işlevler")
            )
        else:
            text += "."
        found.append((loc, text.strip(), frozenset(names)))
    return found
