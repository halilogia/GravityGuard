#!/usr/bin/env python3
"""Generate ARCHITECTURE_AUTO_GENERATED.md from the live source tree (stdlib only).

Usage:
    python tools/generate_architecture.py [--output PATH]
    python tools/generate_architecture.py --check [--output PATH]
"""
import argparse
import difflib
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = "ARCHITECTURE_AUTO_GENERATED.md"
SCAN_DIRS = ["engine", "src", "plugin", "tests"]
SOURCE_EXTS = {".py", ".ts", ".mjs", ".json", ".md"}
SKIP_DIRS = {"__pycache__", "node_modules", ".git", "dist", "fixtures", "sandbox"}
DATE_PREFIX = "> Üretim tarihi:"

ENGINE = "engine/gravityguard_engine/"
LAYERS = [
    ("Tier 1 Fast-Path Guardrail", "Hızlı, deterministik kural kapıları (her araç çağrısında)",
     [ENGINE + f for f in ("architecture_rules.py", "security_rules.py", "shell_rules.py",
                           "publication_guard.py", "removal_observer.py")]),
    ("Tier 4 Deep-Path Güvenlik Denetçisi", "Derin tarama: taint tracking, SARIF v2.1.0, git tree-hash bağlama",
     [ENGINE + "security_audit.py"]),
    ("Yönetişim & Yaşam Döngüsü", "Kapılar, inceleme, görev arşivi, test kanıtı, doküman politikası",
     [ENGINE + f for f in ("governance.py", "review_governance.py", "task_archiver.py",
                           "test_evidence.py", "doc_policy.py")]),
    ("Extension UI & Client", "VS Code uzantısı: komutlar, niyet, webview, görevler",
     ["src/extension.ts", "src/intent.ts", "src/tasks.ts", "src/webview/"]),
]


def _skip(path):
    return any(p in SKIP_DIRS for p in path.parts)


def scan_files(root):
    """Return sorted repo-relative posix paths of source files under SCAN_DIRS."""
    root = Path(root)
    found = []
    for d in SCAN_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            rel = p.relative_to(root)
            if p.is_file() and p.suffix in SOURCE_EXTS and not _skip(rel):
                found.append(rel.as_posix())
    return sorted(found)


def _read(root, rel):
    try:
        return (Path(root) / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def count_loc(root, rel):
    return sum(1 for line in _read(root, rel).splitlines() if line.strip())


def count_tests(root, rel):
    name = Path(rel).name
    text = _read(root, rel)
    if name.startswith("test_") and name.endswith(".py"):
        return len(re.findall(r"^\s*(?:async\s+)?def test_\w+", text, re.MULTILINE))
    if name.endswith(".test.mjs"):
        return len(re.findall(r"^\s*(?:test|it)\s*\(", text, re.MULTILINE))
    return 0


def is_test_file(rel):
    return rel.startswith("tests/") or "/tests/" in rel


def _is_test_module(rel):
    name = Path(rel).name
    return is_test_file(rel) and (name.startswith("test_") or name.endswith(".test.mjs"))


def _matches(rel, patterns):
    return any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in patterns)


def collect_metrics(root, files=None):
    files = scan_files(root) if files is None else files
    locs = {f: count_loc(root, f) for f in files}
    layers = []
    for name, role, patterns in LAYERS:
        members = [f for f in files if _matches(f, patterns)]
        layers.append({"name": name, "role": role, "files": len(members),
                       "loc": sum(locs[f] for f in members)})
    test_files = [f for f in files if _is_test_module(f)]
    areas = {}
    for f in files:
        area = "tests" if is_test_file(f) else f.split("/", 1)[0]
        a = areas.setdefault(area, {"files": 0, "loc": 0})
        a["files"] += 1
        a["loc"] += locs[f]
    return {
        "files": files,
        "total_files": len(files),
        "total_loc": sum(locs.values()),
        "test_loc": sum(locs[f] for f in files if is_test_file(f)),
        "areas": areas,
        "layers": layers,
        "test_files": len(test_files),
        "test_count": sum(count_tests(root, f) for f in test_files),
    }


def read_version(root):
    try:
        return json.loads(_read(root, "package.json")).get("version", "unknown")
    except ValueError:
        return "unknown"


def render_tree(files):
    tree = {}
    for f in files:
        node = tree
        for part in f.split("/"):
            node = node.setdefault(part, {})
    lines = []

    def walk(node, prefix):
        items = sorted(node.items(), key=lambda kv: (not kv[1], kv[0]))
        for i, (name, child) in enumerate(items):
            last = i == len(items) - 1
            lines.append(f"{prefix}{'└── ' if last else '├── '}{name}{'/' if child else ''}")
            if child:
                walk(child, prefix + ("    " if last else "│   "))

    walk(tree, "")
    return "\n".join(lines)


MERMAID = """```mermaid
flowchart LR
    subgraph Client["Extension UI & Client (src/)"]
        EXT[extension.ts] --> WV[webview/]
        EXT --> INT[intent.ts]
        EXT --> TSK[tasks.ts]
    end
    subgraph Hooks["plugin/ (kancalar & adaptörler)"]
        CC[claude-code hook]
        CX[codex hook]
    end
    subgraph Engine["engine/gravityguard_engine"]
        DSP[dispatcher.py]
        subgraph T1["Tier 1 Fast-Path"]
            AR[architecture_rules]
            SR[security_rules]
            SH[shell_rules]
            PG[publication_guard]
            RO[removal_observer]
        end
        subgraph T4["Tier 4 Deep-Path"]
            SA["security_audit<br/>taint + SARIF v2.1.0"]
        end
        subgraph GOV["Yönetişim & Yaşam Döngüsü"]
            G[governance]
            RG[review_governance]
            TA[task_archiver]
            TE[test_evidence]
            DP[doc_policy]
        end
    end
    CC --> DSP
    CX --> DSP
    DSP --> T1
    DSP --> GOV
    GOV -->|derin tarama| T4
    EXT -->|durum / görevler| GOV
```"""


def render_markdown(root, metrics=None, today=None):
    m = metrics or collect_metrics(root)
    today = today or date.today().isoformat()
    out = [
        "# GravityGuard — Otomatik Mimari Raporu",
        "",
        f"{DATE_PREFIX} {today}",
        f"> GravityGuard sürümü: {read_version(root)}",
        "> Bu dosya `npm run docs:arch` ile üretilir; elle düzenlemeyin.",
        "",
        "## Genel Metrikler",
        "",
        f"- Toplam dosya: **{m['total_files']}**",
        f"- Dolu satır (non-empty LOC): **{m['total_loc']}**",
        f"- Test dosyası: **{m['test_files']}**, test sayısı: **{m['test_count']}**",
        "",
        "| Alan | Dosya | Dolu satır |",
        "|---|---:|---:|",
    ]
    for area in sorted(m["areas"]):
        a = m["areas"][area]
        out.append(f"| `{area}` | {a['files']} | {a['loc']} |")
    out += ["", "## Bileşen & Veri Akışı", "", MERMAID, "",
            "## Katman ve Sorumluluk Matrisi", "",
            "| Katman | Sorumluluk | Dosya | Dolu satır |", "|---|---|---:|---:|"]
    for layer in m["layers"]:
        out.append(f"| {layer['name']} | {layer['role']} | {layer['files']} | {layer['loc']} |")
    out.append(f"| Testler | Python + Node test paketleri ({m['test_count']} test) | "
               f"{m['test_files']} | {m['test_loc']} |")
    out += ["", "## Dizin Ağacı", "", "```text", render_tree(m["files"]), "```", ""]
    return "\n".join(out)


ARCH_START = "<!-- ARCH-AUTO:START (tools/generate_architecture.py --sync; elle düzenlemeyin) -->"
ARCH_END = "<!-- ARCH-AUTO:END -->"
ARCH_MAX_LINES = 200  # anti-bloat: an auto-generated section never exceeds this many lines


def render_compact_block(root, metrics=None, today=None):
    """Compact auto-managed block (metrics + layer matrix) for embedding into a hand-written ARCHITECTURE.md."""
    m = metrics or collect_metrics(root)
    today = today or date.today().isoformat()
    out = [
        ARCH_START,
        "## Otomatik Metrikler (Stop hook ile güncellenir)",
        "",
        f"{DATE_PREFIX} {today} — sürüm {read_version(root)}",
        "",
        f"- Toplam dosya: **{m['total_files']}**, dolu satır: **{m['total_loc']}**",
        f"- Test dosyası: **{m['test_files']}**, test sayısı: **{m['test_count']}**",
        "",
        "| Katman | Dosya | Dolu satır |",
        "|---|---:|---:|",
    ]
    for layer in m["layers"]:
        out.append(f"| {layer['name']} | {layer['files']} | {layer['loc']} |")
    for area in sorted(m["areas"]):
        a = m["areas"][area]
        out.append(f"| `{area}/` (alan) | {a['files']} | {a['loc']} |")
    out.append(ARCH_END)
    return "\n".join(out)


def _cap_lines(text, limit=ARCH_MAX_LINES):
    lines = text.splitlines()
    if len(lines) <= limit:
        return text
    kept = lines[: limit - 3]
    if sum(1 for l in kept if l.startswith("```")) % 2:
        kept.append("```")
    kept.append(f"> … {len(lines) - len(kept)} satır anti-bloat sınırı ({limit}) nedeniyle kırpıldı.")
    return "\n".join(kept)


def sync_architecture(root, target="ARCHITECTURE.md", today=None):
    """Update the architecture doc in place and never overwrite hand-written content.

    - missing file      -> create it from the full report, capped at ARCH_MAX_LINES lines
    - markers present   -> replace only the text between the markers (skipped when only the date differs)
    - no markers        -> append the compact marker block once; everything else stays untouched
    Returns (status, path) where status is created | updated | appended | unchanged.
    """
    path = Path(target)
    if not path.is_absolute():
        path = Path(root) / path
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_cap_lines(render_markdown(root, today=today)) + "\n", encoding="utf-8", newline="\n")
        return "created", path
    current = path.read_text(encoding="utf-8")
    block = render_compact_block(root, today=today)
    start, end = current.find(ARCH_START), current.find(ARCH_END)
    if start != -1 and end > start:
        old = current[start:end + len(ARCH_END)]
        if _strip_date(old) == _strip_date(block):
            return "unchanged", path
        new_text = current[:start] + block + current[end + len(ARCH_END):]
        status = "updated"
    else:
        new_text = current.rstrip("\n") + "\n\n" + block + "\n"
        status = "appended"
    path.write_text(new_text, encoding="utf-8", newline="\n")
    return status, path


def _strip_date(text):
    return "\n".join(l for l in text.splitlines() if not l.startswith(DATE_PREFIX))


def check(root, output):
    """Return (exit_code, message). The date line is ignored when comparing."""
    path = Path(output)
    if not path.is_absolute():
        path = Path(root) / path
    if not path.is_file():
        return 1, f"{path} bulunamadı. `npm run docs:arch` çalıştırın."
    current = _strip_date(path.read_text(encoding="utf-8"))
    fresh = _strip_date(render_markdown(root))
    if current == fresh:
        return 0, f"{path.name} güncel."
    diff = "\n".join(list(difflib.unified_diff(
        current.splitlines(), fresh.splitlines(), "disk", "canlı", lineterm="", n=1))[:60])
    return 1, f"{path.name} eski. `npm run docs:arch` çalıştırın.\n{diff}"


def main(argv=None, root=ROOT):
    ap = argparse.ArgumentParser(description="GravityGuard otomatik mimari raporlayıcı")
    ap.add_argument("--output", default=DEFAULT_OUTPUT)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--sync", nargs="?", const="ARCHITECTURE.md", metavar="PATH",
                    help="update the marker block of ARCHITECTURE.md (or PATH) in place")
    args = ap.parse_args(argv)
    if args.sync and args.check:
        path = Path(root) / args.sync
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        start, end = current.find(ARCH_START), current.find(ARCH_END)
        fresh = render_compact_block(root)
        valid = start >= 0 and end > start and _strip_date(current[start:end + len(ARCH_END)]) == _strip_date(fresh)
        print(f"{'current' if valid else 'stale'}: {path}")
        return 0 if valid else 1
    if args.sync:
        status, path = sync_architecture(root, args.sync)
        print(f"{status}: {path}")
        return 0
    if args.check:
        code, msg = check(root, args.output)
        print(msg, file=sys.stderr if code else sys.stdout)
        return code
    out = Path(args.output)
    if not out.is_absolute():
        out = Path(root) / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(root), encoding="utf-8", newline="\n")
    print(f"Yazıldı: {out}")
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        _s.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
