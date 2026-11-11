#!/usr/bin/env python3
"""
GravityGuard Engine — Test Evidence Discovery & Exemption Resolution.
Resolves candidate test files, subsystem glob mappings, and exemption patterns.
Zero external dependencies.
"""
import fnmatch
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DEFAULT_EXEMPT_PATTERNS: List[str] = [
    "types", "constants", "index", ".d.ts", "config", "interfaces", "schemas",
    "migration", "migrations", "fixtures", "mock", "mocks", "tools", "scripts",
    "lang-", "i18n", "locale", "locales", "translations",
    "scratch", "tmp_", "temp_",
    "/ui/", "/views/", "/components/", "/web/",
    "tui.ts", "tree.ts", "transcript.ts", "office_view.ts", "sessions.js", "app.js",
    "cli.ts", "cli.py", "main.py", "main.ts", "run_", "_launcher.", "_opener.",
    ".md", ".json", ".yml", ".yaml", ".toml", ".css", ".html", "/docs/", "adapter", "glue", "shim", "wrapper"
]

_TEST_FILE_PATTERNS = ("test_*.py", "*_test.py", "*.test.*", "*.spec.*", "conftest.py")

DEFAULT_SUBSYSTEM_MAPPINGS: Dict[str, List[str]] = {
    "src/webview/**": [
        "tests/webview_*.test.mjs",
        "tests/tasks.test.mjs",
        "tests/knowledge.test.mjs",
        "tests/obligations.test.mjs",
        "tests/agent_identity.test.mjs",
    ],
}


def _get_subsystem_mappings(cfg: Optional[dict] = None) -> Dict[str, List[str]]:
    """Default mappings merged with `testEvidence.subsystemMappings` (config wins per glob key)."""
    mappings: Dict[str, List[str]] = {k: list(v) for k, v in DEFAULT_SUBSYSTEM_MAPPINGS.items()}
    if cfg and isinstance(cfg, dict):
        te_cfg = cfg.get("testEvidence", {})
        custom = te_cfg.get("subsystemMappings") if isinstance(te_cfg, dict) else None
        if isinstance(custom, dict):
            for glob_key, test_globs in custom.items():
                if isinstance(test_globs, str):
                    test_globs = [test_globs]
                if isinstance(glob_key, str) and isinstance(test_globs, list):
                    mappings[glob_key] = [g for g in test_globs if isinstance(g, str)]
    return mappings


def resolve_subsystem_test_files(target_file: str, cfg: Optional[dict] = None) -> List[str]:
    """
    Returns existing test files accepted as evidence for `target_file` through subsystem glob mappings.
    Mapping globs match the normalized path (or any trailing portion of it); test globs are resolved
    against the target's ancestor directories.
    """
    normalized = target_file.replace("\\", "/")
    lowered = normalized.lower()

    matched_globs: List[str] = []
    for src_glob, test_globs in _get_subsystem_mappings(cfg).items():
        pat = src_glob.replace("\\", "/").lower()
        if fnmatch.fnmatch(lowered, pat) or fnmatch.fnmatch(lowered, f"*/{pat}"):
            matched_globs.extend(test_globs)
    if not matched_globs:
        return []

    roots: List[Path] = []
    curr = Path(normalized).parent
    roots.append(curr)
    for _ in range(5):
        if curr.parent == curr:
            break
        curr = curr.parent
        roots.append(curr)

    found: List[str] = []
    for root in roots:
        for tg in matched_globs:
            try:
                hits = sorted(root.glob(tg))
            except (ValueError, NotImplementedError, OSError):
                continue
            for hit in hits:
                if hit.is_file():
                    path = str(hit).replace("\\", "/")
                    if path not in found:
                        found.append(path)
    return found


def _project_relative_path(target_file: str) -> str:
    """Lowercased path inside the project, with a leading "/"."""
    normalized = target_file.replace("\\", "/").lower()
    if not os.path.isabs(target_file):
        return normalized
    try:
        curr = Path(os.path.abspath(target_file)).parent
        for _ in range(8):
            if (curr / ".git").exists() or (curr / ".gravityguard.json").is_file():
                rel = Path(os.path.abspath(target_file)).relative_to(curr)
                return "/" + str(rel).replace("\\", "/").lower()
            if curr.parent == curr:
                break
            curr = curr.parent
    except (ValueError, OSError):
        pass
    return normalized


def is_exempt_from_test_evidence(target_file: str, cfg: Optional[dict] = None) -> bool:
    """
    Checks if a target file is exempt from test evidence verification (e.g. types, constants, configs, tooling scripts).
    Supports substring patterns and fnmatch glob patterns.
    """
    normalized = _project_relative_path(target_file)
    basename = Path(normalized).name.lower()

    exempt_patterns = DEFAULT_EXEMPT_PATTERNS
    if cfg and isinstance(cfg, dict):
        te_cfg = cfg.get("testEvidence", {})
        if "exemptPatterns" in te_cfg and isinstance(te_cfg["exemptPatterns"], list):
            exempt_patterns = [p.lower() for p in te_cfg["exemptPatterns"]]

    for pat in exempt_patterns:
        if pat.startswith("/") and pat.endswith("/"):
            seg = pat.strip("/")
            if f"/{seg}/" in normalized or normalized.startswith(f"{seg}/"):
                return True
            continue
        pat_clean = pat.lstrip("/").rstrip("/*")
        if not any(ch in pat for ch in "*?[\\"):
            if pat in basename or pat_clean in normalized or pat == normalized or f"/{pat}/" in normalized or normalized.startswith(f"{pat}/"):
                return True
            continue
        if (
            pat in basename or
            f"/{pat}/" in normalized or
            normalized.startswith(f"{pat}/") or
            fnmatch.fnmatch(basename, pat) or
            fnmatch.fnmatch(normalized, pat) or
            fnmatch.fnmatch(normalized, f"*/{pat_clean}") or
            fnmatch.fnmatch(normalized, f"*{pat_clean}") or
            fnmatch.fnmatch(normalized, f"*/{pat_clean}/*") or
            fnmatch.fnmatch(normalized, f"*/{pat_clean}*") or
            fnmatch.fnmatch(normalized, f"*{pat_clean}*")
        ):
            return True

    if normalized.endswith(".d.ts"):
        return True
    if not normalized.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
        return True

    return False


def resolve_candidate_test_file(target_file: str, cfg: Optional[dict] = None) -> Tuple[Optional[str], str]:
    """
    Given a production file, searches for its candidate test file using standard naming conventions.
    Normalizes hyphens and underscores to handle modules named with hyphens.
    Returns: (found_path_or_None, primary_expected_name)
    """
    normalized = target_file.replace("\\", "/")
    target_path = Path(normalized)
    stem = target_path.stem
    stem_us = stem.replace("-", "_")
    stem_hy = stem.replace("_", "-")
    suffix = target_path.suffix.lower()
    parent_dir = target_path.parent

    candidate_names = []
    if suffix == ".py":
        candidate_names = [
            f"test_{stem}.py", f"{stem}_test.py",
            f"test_{stem_us}.py", f"{stem_us}_test.py",
            f"test_{stem_hy}.py", f"{stem_hy}_test.py"
        ]
        if "codex" in normalized:
            candidate_names.extend(["codex_adapter.test.mjs", "test_codex_adapter.py"])
        if "claude" in normalized:
            candidate_names.extend(["test_claude_adapter.py", "claude_adapter.test.mjs"])
        if "audit" in normalized:
            candidate_names.extend(["agent_identity.test.mjs", "test_audit.py"])
        candidate_names = list(dict.fromkeys(candidate_names))
    elif suffix in [".ts", ".tsx", ".js", ".jsx"]:
        candidate_names = [
            f"{stem}.test{suffix}", f"{stem}.spec{suffix}",
            f"{stem_us}.test{suffix}", f"{stem_us}.spec{suffix}",
            f"{stem_hy}.test{suffix}", f"{stem_hy}.spec{suffix}",
            f"test_{stem}{suffix}", f"{stem}_test{suffix}",
            f"{stem}.test.mjs", f"{stem}.spec.mjs",
            f"{stem_us}.test.mjs", f"{stem_us}.spec.mjs",
            f"{stem}.test.js", f"{stem}.spec.js",
            f"{stem_us}.test.js", f"{stem_us}.spec.js",
            f"test_{stem}.mjs", f"test_{stem_us}.mjs",
            f"test_{stem}.js", f"test_{stem_us}.js"
        ]
        if "webview" in normalized:
            candidate_names.append(f"webview_{stem}.test.mjs")
        candidate_names = list(dict.fromkeys(candidate_names))
    else:
        candidate_names = [f"test_{stem}{suffix}", f"test_{stem_us}{suffix}"]
        candidate_names = list(dict.fromkeys(candidate_names))

    primary_expected = candidate_names[0] if candidate_names else f"test_{stem}.py"

    for name in candidate_names:
        for candidate in (parent_dir / name, Path(name)):
            if candidate.is_file():
                return str(candidate).replace("\\", "/"), primary_expected

    search_dirs = [parent_dir]
    curr = parent_dir
    for _ in range(5):
        if curr.parent == curr:
            break
        curr = curr.parent
        search_dirs.append(curr)

    test_roots = ["tests", "__tests__", "test"]
    if cfg and isinstance(cfg, dict):
        te_cfg = cfg.get("testEvidence", {})
        if "testRoots" in te_cfg and isinstance(te_cfg["testRoots"], list):
            test_roots = te_cfg["testRoots"]

    source_roots = ["src", "lib", "app", "core", "agent", "engine"]
    if cfg and isinstance(cfg, dict):
        te_cfg = cfg.get("testEvidence", {})
        if "sourceRoots" in te_cfg and isinstance(te_cfg["sourceRoots"], list):
            source_roots = [r.lower() for r in te_cfg["sourceRoots"]]

    for root_cand in search_dirs:
        for tr in test_roots:
            td = root_cand / tr
            if td.is_dir():
                for name in candidate_names:
                    tfile = td / name
                    if tfile.is_file():
                        return str(tfile).replace("\\", "/"), primary_expected
                    try:
                        rel = target_path.relative_to(root_cand)
                        rel_parts = list(rel.parts)
                        if rel_parts and rel_parts[0].lower() in source_roots:
                            rel_parts.pop(0)
                        if rel_parts:
                            rel_parts[-1] = name
                            mirrored = td / Path(*rel_parts)
                            if mirrored.is_file():
                                return str(mirrored).replace("\\", "/"), primary_expected
                    except ValueError:
                        continue

    return None, primary_expected


def project_has_test_infrastructure(target_file: str, cfg: Optional[dict] = None) -> bool:
    """Does this project have ANY test evidence, anywhere?"""
    if cfg and isinstance(cfg, dict):
        te_cfg = cfg.get("testEvidence", {})
        if isinstance(te_cfg, dict) and te_cfg.get("requireTestInfrastructure") is False:
            return True

    test_roots = ["tests", "__tests__", "test"]
    if cfg and isinstance(cfg, dict):
        te_cfg = cfg.get("testEvidence", {})
        if isinstance(te_cfg, dict) and isinstance(te_cfg.get("testRoots"), list):
            test_roots = te_cfg["testRoots"]

    search_dirs = [Path(target_file).parent]
    curr = Path(target_file).parent
    for _ in range(5):
        if curr.parent == curr:
            break
        curr = curr.parent
        search_dirs.append(curr)

    for root_cand in search_dirs:
        for tr in test_roots:
            td = root_cand / tr
            if not td.is_dir():
                continue
            try:
                entries = list(td.iterdir())
            except OSError:
                continue
            if not entries:
                return True
            for entry in entries:
                name = entry.name
                if any(fnmatch.fnmatch(name, pattern) for pattern in _TEST_FILE_PATTERNS):
                    return True
    return False
