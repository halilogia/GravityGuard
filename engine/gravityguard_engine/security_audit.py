"""
GravityGuard Engine — Tier 4 deep security audit (OFF the hook fast path).

Never imported by PreToolUse/PostToolUse. It backs the standalone
``scan`` command: evidence-backed findings, SARIF v2.1.0 export, git-bound
reports with stale invalidation, and a fail-before / pass-after fix gate.

Zero external dependencies.
"""
import ast
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
STATUSES = ("UNVERIFIED", "CONFIRMED_EXPLOITABLE", "PATCHED_VERIFIED")
SARIF_SCHEMA = "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json"
DEFAULT_OUTPUT = Path(".gravityguard") / "reports" / "security-scan.sarif"
SCANNED_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".sh", ".rb", ".php", ".java", ".go"}
SKIP_DIRS = {".git", "node_modules", ".gravityguard", "__pycache__", "dist", "out", ".venv", "venv", "archives"}
MAX_FILE_BYTES = 1_000_000

_SARIF_LEVEL = {"CRITICAL": "error", "HIGH": "error", "MEDIUM": "warning", "LOW": "note"}
_SARIF_SCORE = {"CRITICAL": "9.5", "HIGH": "8.0", "MEDIUM": "5.0", "LOW": "2.0"}


@dataclass
class Finding:
    finding_id: str
    rule_id: str
    severity: str
    confidence: float
    message: str
    file: str
    line: int
    attack_path: List[Dict[str, Any]] = field(default_factory=list)  # [{file, line, description}]
    evidence_payload: str = ""
    reproduction_test: Optional[str] = None
    verification_status: str = "UNVERIFIED"
    unexamined_scope: List[str] = field(default_factory=list)
    stale: bool = False
    baseline: Optional[Dict[str, Any]] = None  # fail-before record

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"invalid severity: {self.severity}")
        if self.verification_status not in STATUSES:
            raise ValueError(f"invalid verification_status: {self.verification_status}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be within 0.0-1.0")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Finding":
        known = {key: data[key] for key in cls.__dataclass_fields__ if key in data}
        return cls(**known)


def make_finding_id(rule_id: str, file: str, line: int) -> str:
    return "GG-" + hashlib.sha256(f"{rule_id}|{file}|{line}".encode("utf-8")).hexdigest()[:12]


def dedupe(findings: Iterable[Finding]) -> List[Finding]:
    """One finding per (rule, file, line); the highest-confidence one wins."""
    best: Dict[Tuple[str, str, int], Finding] = {}
    for item in findings:
        key = (item.rule_id, item.file, item.line)
        if key not in best or item.confidence > best[key].confidence:
            best[key] = item
    return sorted(best.values(), key=lambda f: (SEVERITIES.index(f.severity), f.file, f.line, f.rule_id))


# ---------------------------------------------------------------- rules

RULES: Dict[str, Dict[str, str]] = {
    "GGS001": {"name": "HardcodedSecret", "desc": "Hardcoded credential or private key committed to source."},
    "GGS002": {"name": "UnescapedShellExecution", "desc": "Shell command built from non-constant input."},
    "GGS003": {"name": "InsecureDeserialization", "desc": "Deserialization of untrusted data can execute code."},
    "GGS004": {"name": "UnsafeEvalExec", "desc": "Dynamic code evaluation (eval/exec/Function)."},
    "GGS005": {"name": "PathTraversal", "desc": "File path derived from untrusted input without containment."},
}

_SECRET_RES = [
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"), "private key block"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"), "GitHub token"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "API secret key"),
    (re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key|token)\b\s*[:=]\s*['\"]([^'\"\s]{8,})['\"]"), "credential assignment"),
]
_PLACEHOLDER = re.compile(r"(?i)(example|placeholder|changeme|your[_-]|<.*>|\*{3,}|xxx|dummy|test|fake|sample|\$\{|%s|process\.env|os\.environ)")

_LINE_RULES = [
    ("GGS002", "HIGH", 0.55, re.compile(r"\b(?:child_process\.)?(?:exec|execSync)\s*\(\s*(?:`[^`]*\$\{|[^'\"`)\s][^)]*\+|['\"][^'\"]*['\"]\s*\+)"), "shell command concatenated from variables"),
    ("GGS002", "HIGH", 0.6, re.compile(r"\bsystem\s*\(\s*\$_(?:GET|POST|REQUEST)"), "shell command from request input"),
    ("GGS003", "HIGH", 0.7, re.compile(r"\b(?:unserialize|ObjectInputStream|Marshal\.load)\b"), "native object deserialization"),
    ("GGS004", "HIGH", 0.7, re.compile(r"\bnew\s+Function\s*\(|\beval\s*\((?!\s*['\"][^'\"]*['\"]\s*\))"), "dynamic code evaluation"),
    ("GGS005", "MEDIUM", 0.5, re.compile(r"\b(?:readFile|readFileSync|createReadStream|sendFile)\s*\([^)]*\b(?:req|request)\.(?:query|params|body)"), "file path taken from request"),
]

_PY_SOURCES = ("input", "request", "sys.argv", "os.environ", "flask.request", "environ")
_PY_SHELL_CALLS = {"os.system", "os.popen", "commands.getoutput"}
_PY_SUBPROCESS = {"subprocess.run", "subprocess.call", "subprocess.check_call", "subprocess.check_output", "subprocess.Popen"}
_PY_DESERIAL = {"pickle.loads", "pickle.load", "cPickle.loads", "marshal.loads", "dill.loads", "shelve.open"}
_PY_FILE_SINKS = {"open", "send_file", "send_from_directory", "os.remove", "os.unlink", "shutil.copy", "shutil.rmtree"}


def _dotted(node: ast.AST) -> str:
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


class _TaintVisitor(ast.NodeVisitor):
    """Intra-file taint: sources -> assignments -> sinks (per function scope)."""

    def __init__(self, rel: str, lines: List[str]):
        self.rel, self.lines = rel, lines
        self.findings: List[Finding] = []
        self.scopes: List[Dict[str, int]] = [{}]  # tainted name -> source line

    def _is_source(self, node: ast.AST) -> bool:
        name = _dotted(node.func if isinstance(node, ast.Call) else node)
        return bool(name) and any(name == s or name.startswith(s + ".") for s in _PY_SOURCES)

    def _taint_line(self, node: ast.AST) -> Optional[int]:
        """Source line when the expression carries taint, else None."""
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id in self.scopes[-1]:
                return self.scopes[-1][child.id]
            if isinstance(child, (ast.Call, ast.Attribute, ast.Subscript)) and self._is_source(child if not isinstance(child, ast.Subscript) else child.value):
                return getattr(child, "lineno", None)
        return None

    @staticmethod
    def _is_const(node: ast.AST) -> bool:
        return isinstance(node, ast.Constant) or (
            isinstance(node, (ast.List, ast.Tuple)) and all(isinstance(e, ast.Constant) for e in node.elts))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scopes.append({})
        self.generic_visit(node)
        self.scopes.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scopes.append({})
        self.generic_visit(node)
        self.scopes.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        src = self._taint_line(node.value)
        if src is not None:
            for target in node.targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name):
                        self.scopes[-1][name.id] = src
        self.generic_visit(node)

    def _add(self, rule: str, sev: str, conf: float, node: ast.AST, msg: str, src: Optional[int]) -> None:
        line = getattr(node, "lineno", 1)
        path = []
        if src is not None and src != line:
            path.append({"file": self.rel, "line": src, "description": "untrusted input enters here"})
        path.append({"file": self.rel, "line": line, "description": msg})
        snippet = self.lines[line - 1].strip() if 0 < line <= len(self.lines) else ""
        self.findings.append(Finding(
            make_finding_id(rule, self.rel, line), rule, sev, conf, msg, self.rel, line,
            attack_path=path, evidence_payload=snippet,
            unexamined_scope=["cross-file data flow", "framework-level sanitization"]))

    def visit_Call(self, node: ast.Call) -> None:
        name = _dotted(node.func)
        arg = node.args[0] if node.args else None
        src = self._taint_line(arg) if arg is not None else None
        if name in ("eval", "exec") and arg is not None and not self._is_const(arg):
            self._add("GGS004", "CRITICAL" if src else "HIGH", 0.9 if src else 0.6, node, f"{name}() on non-constant input", src)
        elif name in _PY_SHELL_CALLS and arg is not None and not self._is_const(arg):
            self._add("GGS002", "CRITICAL" if src else "HIGH", 0.9 if src else 0.6, node, f"{name}() with non-constant command", src)
        elif name in _PY_SUBPROCESS and arg is not None:
            shell = any(k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords)
            if shell and not self._is_const(arg):
                self._add("GGS002", "CRITICAL" if src else "HIGH", 0.9 if src else 0.6, node, f"{name}(shell=True) with non-constant command", src)
        elif name in _PY_DESERIAL:
            self._add("GGS003", "CRITICAL" if src else "HIGH", 0.9 if src else 0.65, node, f"{name}() deserializes untrusted bytes", src)
        elif name == "yaml.load" and not any(k.arg == "Loader" and "Safe" in _dotted(k.value) for k in node.keywords):
            self._add("GGS003", "HIGH", 0.8, node, "yaml.load() without SafeLoader", src)
        elif name in _PY_FILE_SINKS and src is not None:
            self._add("GGS005", "HIGH", 0.8, node, f"{name}() path derived from untrusted input", src)
        self.generic_visit(node)


def _scan_python(rel: str, text: str) -> List[Finding]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    visitor = _TaintVisitor(rel, text.splitlines())
    visitor.visit(tree)
    return visitor.findings


def _scan_lines(rel: str, text: str, skip_rules: Iterable[str] = ()) -> List[Finding]:
    out: List[Finding] = []
    skip = set(skip_rules)
    for number, line in enumerate(text.splitlines(), 1):
        for pattern, label in _SECRET_RES:
            match = pattern.search(line)
            if match and not _PLACEHOLDER.search(match.group(0)):
                out.append(Finding(make_finding_id("GGS001", rel, number), "GGS001", "HIGH", 0.8,
                                   f"Hardcoded secret ({label})", rel, number,
                                   attack_path=[{"file": rel, "line": number, "description": "secret readable by anyone with repository access"}],
                                   evidence_payload=_redact(line.strip()),
                                   unexamined_scope=["secret validity not checked against live service"]))
                break
        for rule, sev, conf, pattern, msg in _LINE_RULES:
            if rule not in skip and pattern.search(line):
                out.append(Finding(make_finding_id(rule, rel, number), rule, sev, conf, msg, rel, number,
                                   attack_path=[{"file": rel, "line": number, "description": msg}],
                                   evidence_payload=line.strip()[:200],
                                   unexamined_scope=["taint source not proven (pattern match)"]))
    return out


def _redact(line: str) -> str:
    return re.sub(r"(['\"])([^'\"]{4})[^'\"]{4,}(['\"])", r"\1\2****\3", line)[:200]


def scan_text(rel: str, text: str) -> List[Finding]:
    """Scan one file body. Python gets AST taint analysis; others get line rules."""
    if rel.endswith(".py"):
        py = _scan_python(rel, text)
        return dedupe(py + _scan_lines(rel, text, skip_rules={"GGS002", "GGS003", "GGS004", "GGS005"}))
    return dedupe(_scan_lines(rel, text))


# ---------------------------------------------------------------- file selection

def _git(root: Path, *args: str) -> Optional[str]:
    try:
        proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def list_files(root: Path, mode: str) -> List[str]:
    """``diff``: staged + unstaged + untracked changes; ``all``: every scannable file."""
    root = Path(root)
    rels: List[str] = []
    if mode == "diff":
        for args in (("diff", "--name-only", "--diff-filter=ACMR", "HEAD"), ("diff", "--name-only", "--cached", "--diff-filter=ACMR"),
                     ("ls-files", "--others", "--exclude-standard")):
            rels += (_git(root, *args) or "").splitlines()
    else:
        tracked = _git(root, "ls-files", "--cached", "--others", "--exclude-standard")
        if tracked is not None:
            rels = tracked.splitlines()
        else:
            rels = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    seen, out = set(), []
    for rel in rels:
        rel = rel.strip().strip('"').replace("\\", "/")
        path = Path(rel)
        if (not rel or rel in seen or path.suffix.lower() not in SCANNED_SUFFIXES
                or any(part in SKIP_DIRS for part in path.parts) or not (root / rel).is_file()):
            continue
        seen.add(rel)
        out.append(rel)
    return sorted(out)


def scan_paths(root: Path, rels: List[str]) -> Tuple[List[Finding], Dict[str, str]]:
    """Returns ``(findings, {rel: text_hash})`` for the files actually read."""
    from .diffing import hash_text
    findings: List[Finding] = []
    hashes: Dict[str, str] = {}
    for rel in rels:
        path = Path(root) / rel
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hashes[rel.lower()] = hash_text(text)
        findings += scan_text(rel, text)
    return dedupe(findings), hashes


# ---------------------------------------------------------------- reports

def build_report(root: Path, findings: List[Finding], file_hashes: Dict[str, str], mode: str) -> Dict[str, Any]:
    from .diffing import git_binding
    return {
        "version": 1, "mode": mode,
        "binding": {**git_binding(root), "file_hashes": file_hashes},
        "findings": [f.to_dict() for f in findings],
    }


def to_sarif(findings: List[Finding], binding: Optional[Dict[str, Any]] = None, tool_version: str = "1.4.18") -> Dict[str, Any]:
    """OASIS SARIF v2.1.0 log. Findings are deduplicated by (rule, file, line)."""
    findings = dedupe(findings)
    used = sorted({f.rule_id for f in findings})
    rules = [{
        "id": rid,
        "name": RULES.get(rid, {}).get("name", rid),
        "shortDescription": {"text": RULES.get(rid, {}).get("desc", rid)},
        "helpUri": "https://github.com/halilogia/GravityGuard#security-scan",
    } for rid in used]
    index = {rid: i for i, rid in enumerate(used)}
    results = []
    for f in findings:
        result: Dict[str, Any] = {
            "ruleId": f.rule_id, "ruleIndex": index[f.rule_id],
            "level": _SARIF_LEVEL[f.severity],
            "message": {"text": f.message},
            "locations": [{"physicalLocation": {
                "artifactLocation": {"uri": f.file.replace("\\", "/")},
                "region": {"startLine": max(1, f.line)}}}],
            "partialFingerprints": {"gravityguardFindingId/v1": f.finding_id},
            "properties": {
                "security-severity": _SARIF_SCORE[f.severity], "severity": f.severity,
                "confidence": f.confidence, "verificationStatus": f.verification_status,
                "stale": f.stale, "evidencePayload": f.evidence_payload,
                "reproductionTest": f.reproduction_test, "unexaminedScope": f.unexamined_scope,
            },
        }
        if f.attack_path:
            result["codeFlows"] = [{"threadFlows": [{"locations": [{"location": {
                "physicalLocation": {"artifactLocation": {"uri": str(step.get("file", f.file)).replace("\\", "/")},
                                     "region": {"startLine": max(1, int(step.get("line", 1)))}},
                "message": {"text": str(step.get("description", ""))}}} for step in f.attack_path]}]}]
        results.append(result)
    run: Dict[str, Any] = {
        "tool": {"driver": {"name": "GravityGuard", "version": tool_version,
                            "informationUri": "https://github.com/halilogia/GravityGuard", "rules": rules}},
        "results": results,
    }
    if binding:
        run["versionControlProvenance"] = [{"revisionId": binding.get("commit") or "", "properties": {"treeHash": binding.get("tree")}}]
        run["properties"] = {"binding": binding}
    return {"$schema": SARIF_SCHEMA, "version": "2.1.0", "runs": [run]}


def render_text(findings: List[Finding]) -> str:
    if not findings:
        return "GravityGuard scan: no findings."
    rows = [f"{f.severity:<8} {f.rule_id} {f.file}:{f.line}  {f.message} (confidence {f.confidence:.2f})" for f in findings]
    return "\n".join(rows + [f"{len(findings)} finding(s)."])


def report_findings(report: Dict[str, Any]) -> List[Finding]:
    return [Finding.from_dict(item) for item in report.get("findings", [])]


def load_report(path: Path) -> Dict[str, Any]:
    """Reads a JSON report, or the findings embedded in a SARIF log."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "runs" in data:
        run = data["runs"][0]
        findings = []
        for res in run.get("results", []):
            loc = res["locations"][0]["physicalLocation"]
            props = res.get("properties", {})
            findings.append(Finding(
                res.get("partialFingerprints", {}).get("gravityguardFindingId/v1") or make_finding_id(res["ruleId"], loc["artifactLocation"]["uri"], loc["region"]["startLine"]),
                res["ruleId"], props.get("severity", "MEDIUM"), props.get("confidence", 0.5), res["message"]["text"],
                loc["artifactLocation"]["uri"], loc["region"]["startLine"],
                evidence_payload=props.get("evidencePayload", ""), reproduction_test=props.get("reproductionTest"),
                verification_status=props.get("verificationStatus", "UNVERIFIED"), unexamined_scope=props.get("unexaminedScope", []),
                stale=props.get("stale", False)).to_dict())
        return {"version": 1, "binding": run.get("properties", {}).get("binding", {}), "findings": findings}
    return data


def invalidate_stale_report(report: Dict[str, Any], root: Path) -> Dict[str, Any]:
    """Marks every finding stale (and unverified) once the git tree / file hashes moved on."""
    from .diffing import binding_is_stale
    if binding_is_stale(report.get("binding") or {}, Path(root)):
        for item in report.get("findings", []):
            item["stale"] = True
            item["verification_status"] = "UNVERIFIED"
            item["baseline"] = None
    return report


# ---------------------------------------------------------------- fix verification (fail-before / pass-after)

TestRunner = Callable[[Path, Path], int]


def default_test_runner(root: Path, test_path: Path) -> int:
    """Runs one reproduction test file; exit code 0 means PASS."""
    if test_path.suffix == ".py":
        cmd = [sys.executable, "-m", "unittest", "-q", test_path.relative_to(root).with_suffix("").as_posix().replace("/", ".")]
        probe = subprocess.run([sys.executable, "-c", "import pytest"], capture_output=True)
        if probe.returncode == 0:
            cmd = [sys.executable, "-m", "pytest", "-q", str(test_path)]
    else:
        cmd = ["node", "--test", str(test_path)]
    try:
        return subprocess.run(cmd, cwd=str(root), capture_output=True, timeout=300).returncode
    except (OSError, subprocess.SubprocessError):
        return 1


def _resolve_test(root: Path, finding: Finding) -> Path:
    if not finding.reproduction_test:
        raise ValueError("finding has no reproduction_test")
    root = Path(root).resolve()
    path = (root / finding.reproduction_test).resolve()
    if root not in path.parents or not path.is_file():
        raise ValueError("reproduction_test must be an existing file inside the repository")
    return path


def record_baseline(finding: Finding, root: Path, runner: TestRunner = default_test_runner) -> Finding:
    """Pre-patch step: the reproduction test must FAIL on the vulnerable code."""
    from .diffing import git_binding
    test = _resolve_test(root, finding)
    code = runner(Path(root).resolve(), test)
    if code == 0:
        raise ValueError("reproduction_test passes on vulnerable code; it does not reproduce the finding")
    finding.verification_status = "CONFIRMED_EXPLOITABLE"
    finding.baseline = {"exit_code": code, "binding": {**git_binding(root), "file_hashes": _hash_files(root, [finding.file])}}
    return finding


def verify_patched(finding: Finding, root: Path, runner: TestRunner = default_test_runner) -> Finding:
    """Post-patch step: needs a recorded FAIL baseline, changed code, and a now-PASSING test."""
    from .diffing import binding_is_stale
    if finding.verification_status != "CONFIRMED_EXPLOITABLE" or not finding.baseline:
        raise ValueError("no fail-before baseline recorded; run record_baseline on the unpatched code first")
    if not binding_is_stale(finding.baseline["binding"], Path(root)):
        raise ValueError("code unchanged since the baseline; nothing was patched")
    test = _resolve_test(root, finding)
    if runner(Path(root).resolve(), test) != 0:
        raise ValueError("reproduction_test still fails after the patch")
    finding.verification_status = "PATCHED_VERIFIED"
    return finding


def _hash_files(root: Path, rels: List[str]) -> Dict[str, str]:
    from .diffing import read_disk_text_hash
    return {rel.lower(): h for rel in rels if (h := read_disk_text_hash(Path(root) / rel)) is not None}


# ---------------------------------------------------------------- CLI

def run_scan(root: Path, mode: str = "diff", fmt: str = "sarif", output: Optional[str] = None) -> Tuple[int, str]:
    """Executes a scan. Returns ``(exit_code, written_path_or_empty)``; exit 1 when findings exist."""
    root = Path(root).resolve()
    findings, hashes = scan_paths(root, list_files(root, mode))
    report = build_report(root, findings, hashes, mode)
    if fmt == "text":
        body = render_text(findings)
    elif fmt == "json":
        body = json.dumps(report, indent=2)
    else:
        body = json.dumps(to_sarif(findings, report["binding"]), indent=2)
    target = Path(output) if output else DEFAULT_OUTPUT
    if not target.is_absolute():
        target = root / target
    if fmt == "text" and not output:
        print(body)
        return (1 if findings else 0), ""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    print(f"GravityGuard scan: {len(findings)} finding(s) -> {target}")
    return (1 if findings else 0), str(target)


def main(argv: List[str]) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="gravityguard scan", description="Tier 4 deep security scan (not a hook).")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--diff", action="store_true", help="scan changed/staged/untracked files (default)")
    scope.add_argument("--all", action="store_true", help="scan the whole repository")
    parser.add_argument("--format", choices=("sarif", "json", "text"), default="sarif")
    parser.add_argument("--output", default=None, help=f"report path (default {DEFAULT_OUTPUT.as_posix()})")
    parser.add_argument("--root", default=".", help="repository root")
    args = parser.parse_args(argv)
    code, _ = run_scan(Path(args.root), "all" if args.all else "diff", args.format, args.output)
    return code
