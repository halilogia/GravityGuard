#!/usr/bin/env python3
"""
GravityGuard Engine — Test Evidence Airbag Subsystem (T1, T2, T3).
Zero external dependencies.
"""
import ast
import fnmatch
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

DEFAULT_EXEMPT_PATTERNS: List[str] = [
    "types", "constants", "index", ".d.ts", "config", "interfaces", "schemas",
    "migration", "migrations", "fixtures", "mock", "mocks", "tools", "scripts"
]

_TEST_FILE_PATTERNS = ("test_*.py", "*_test.py", "*.test.*", "*.spec.*", "conftest.py")

# Subsystem / glob mapping (Testing Trophy): UI, webview and adapter layers are covered by
# integration tests rather than 1:1 mirror unit tests. Production glob -> accepted test globs,
# resolved against any ancestor of the target file. Extendable/overridable per glob key via
# `testEvidence.subsystemMappings` in .gravityguard.json.
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


def is_exempt_from_test_evidence(target_file: str, cfg: Optional[dict] = None) -> bool:
    """
    Checks if a target file is exempt from test evidence verification (e.g. types, constants, configs, tooling scripts).
    Supports substring patterns and fnmatch glob patterns.
    """
    normalized = target_file.replace("\\", "/").lower()
    basename = Path(normalized).name.lower()

    exempt_patterns = DEFAULT_EXEMPT_PATTERNS
    if cfg and isinstance(cfg, dict):
        te_cfg = cfg.get("testEvidence", {})
        if "exemptPatterns" in te_cfg and isinstance(te_cfg["exemptPatterns"], list):
            exempt_patterns = [p.lower() for p in te_cfg["exemptPatterns"]]

    for pat in exempt_patterns:
        pat_clean = pat.lstrip("/").rstrip("/*")
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
    Normalizes hyphens and underscores to handle modules named with hyphens (e.g. gravity-validator -> test_gravity_validator.py).
    Returns: (found_path_or_None, primary_expected_name)
    """
    normalized = target_file.replace("\\", "/")
    target_path = Path(normalized)
    stem = target_path.stem
    stem_us = stem.replace("-", "_")
    stem_hy = stem.replace("_", "-")
    suffix = target_path.suffix.lower()
    parent_dir = target_path.parent

    # Candidate file names with hyphen/underscore variations
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

    # 1. Search in the same directory
    for name in candidate_names:
        candidate = parent_dir / name
        if candidate.is_file():
            return str(candidate).replace("\\", "/"), primary_expected

    # 2. Search in common test root directories
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


def check_t1_missing_test(
    target_file: str,
    added_text: str,
    cfg: Optional[dict] = None
) -> Tuple[bool, str, Optional[str]]:
    """
    T1 — MISSING_RELATED_TEST (WARN ONLY).
    Triggers when production code changes but no candidate test file exists on disk
    (neither a 1:1 mirror test nor a subsystem-mapped integration test).
    Test existence is the evidence; the test file's mtime is never penalized.
    Silent when the project has no test infrastructure at all.
    Returns: (warn_triggered, warn_message, candidate_test_path)
    """
    if not added_text.strip():
        return False, "", None

    if is_exempt_from_test_evidence(target_file, cfg):
        return False, "", None

    candidate_path, expected_name = resolve_candidate_test_file(target_file, cfg)

    if not candidate_path or not os.path.exists(candidate_path):
        subsystem_files = resolve_subsystem_test_files(target_file, cfg)
        if subsystem_files:
            return False, "", subsystem_files[0]
        if not project_has_test_infrastructure(target_file, cfg):
            return False, "", None
        return True, (
            f"Test Kanıtı Uyarısı (T1_MISSING_RELATED_TEST): Üretim kodunda değişiklik yapıldı "
            f"ancak ilişkili test dosyası ('{expected_name}') diskte bulunamadı. "
            f"Davranış değişikliği için ilgili test dosyasını oluşturmayı veya güncellemeyi değerlendirin."
        ), None

    return False, "", candidate_path


def check_t2_observable_assertion(
    added_lines: List[str],
    added_text: str,
    is_python: bool,
    is_ts: bool,
    projected_content: str = "",
    added_line_numbers: Optional[Set[int]] = None
) -> Tuple[bool, str]:
    """
    T2 — NO_OBSERVABLE_ASSERTION (WARN ONLY).
    Triggers when an individual test case (def test_..., it(...), test(...)) is added or modified,
    but no observable assertion pattern is detected in THAT SPECIFIC test case's body.
    """
    if not added_text.strip():
        return False, ""

    if not projected_content:
        projected_content = added_text
    if added_line_numbers is None:
        added_line_numbers = set(range(1, added_text.count("\n") + 2))

    unasserted_tests: List[str] = []

    if is_python:
        ast_worked = False
        try:
            tree = ast.parse(projected_content)
            lines = projected_content.splitlines()
            funcs = []
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    funcs.append(node)
                elif isinstance(node, ast.ClassDef):
                    for sub in node.body:
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            funcs.append(sub)

            for fn in funcs:
                name = fn.name
                if not (name.startswith("test_") or name.startswith("test")):
                    continue
                if name in ("setUp", "tearDown", "setUpClass", "tearDownClass"):
                    continue
                start_line = getattr(fn, "lineno", 1)
                end_line = getattr(fn, "end_lineno", start_line)
                fn_lines = set(range(start_line, end_line + 1))
                if fn_lines & added_line_numbers:
                    body_slice = lines[start_line - 1 : end_line]
                    body_text = "\n".join(body_slice)
                    has_assert = bool(re.search(
                        r"\b(?:assert\b|self\.assert[A-Za-z0-9_]+|pytest\.raises|pytest\.approx)",
                        body_text
                    ))
                    if not has_assert:
                        unasserted_tests.append(name)
            ast_worked = True
        except Exception:
            ast_worked = False

        if not ast_worked:
            py_test_defs = re.findall(r"^\s*def\s+(test_[a-zA-Z0-9_]+)\s*\(", added_text, re.MULTILINE)
            if py_test_defs:
                has_assert = bool(re.search(
                    r"\b(?:assert\b|self\.assert[A-Za-z0-9_]+|pytest\.raises|pytest\.approx)",
                    added_text
                ))
                if not has_assert:
                    unasserted_tests.extend(py_test_defs)

    if is_ts or not is_python:
        pattern = re.compile(r"^\s*(?:it|test)\s*\(\s*[\"'\`]([^\"'\`]+)[\"'\`]", re.MULTILINE)
        matches = list(pattern.finditer(projected_content))

        if matches:
            for idx, match in enumerate(matches):
                test_name = match.group(1)
                start_char = match.start()
                start_line = projected_content[:start_char].count("\n") + 1

                if idx + 1 < len(matches):
                    end_char = matches[idx + 1].start()
                else:
                    end_char = len(projected_content)

                test_chunk = projected_content[start_char:end_char]
                end_line = start_line + test_chunk.count("\n")
                fn_lines = set(range(start_line, end_line + 1))

                if fn_lines & added_line_numbers:
                    has_assert = bool(re.search(
                        r"\b(?:expect\s*\(|assert\s*[\(\.]|\.to(?:Be|Equal|StrictEqual|Throw|HaveBeenCalled|Match|Contain|BeTruthy|BeFalsy|BeNull|BeUndefined|BeDefined|BeGreaterThan|BeLessThan|Reject|Resolve)\b|t\.(?:is|true|deepEqual|false)\b|\.should\.[a-zA-Z]+)",
                        test_chunk
                    ))
                    if not has_assert:
                        unasserted_tests.append(test_name)
        elif is_ts:
            ts_test_defs = re.findall(r"\b(?:it|test)\s*\(\s*[\"'\`]([^\"'\`]+)[\"'\`]", added_text)
            if ts_test_defs:
                has_assert = bool(re.search(
                    r"\b(?:expect\s*\(|assert\s*[\(\.]|\.to(?:Be|Equal|StrictEqual|Throw|HaveBeenCalled|Match|Contain|BeTruthy|BeFalsy|BeNull|BeUndefined|BeDefined|BeGreaterThan|BeLessThan|Reject|Resolve)\b|t\.(?:is|true|deepEqual|false)\b|\.should\.[a-zA-Z]+)",
                    added_text
                ))
                if not has_assert:
                    unasserted_tests.extend(ts_test_defs)

    if unasserted_tests:
        sample_tests = ", ".join(f"'{n}'" for n in unasserted_tests[:2])
        return True, (
            f"Test Gözlem Uyarısı (T2_NO_OBSERVABLE_ASSERTION): Eklenen/değiştirilen test case "
            f"({sample_tests}) içinde gözlemlenebilir bir assertion (assert, expect, self.assert*, pytest.raises) "
            f"tespit edilemedi. İçi boş veya assertionsız test yazılmasından kaçının."
        )

    return False, ""


def check_t3_symbol_to_test_link(
    target_file: str,
    added_text: str,
    candidate_test_path: Optional[str],
    is_python: bool,
    is_ts: bool,
    projected_content: str = "",
    added_line_numbers: Optional[Set[int]] = None,
    extra_test_paths: Optional[List[str]] = None
) -> Tuple[bool, str]:
    """
    T3 — SYMBOL_TO_TEST_LINK (WARN ONLY).
    Checks whether modified/added top-level functions or classes (including body-only changes)
    are referenced by name in the candidate test file (plus `extra_test_paths`, used for
    subsystem-mapped integration tests).
    """
    if not added_text.strip() or not candidate_test_path:
        return False, ""

    if not os.path.isfile(candidate_test_path):
        return False, ""

    if not projected_content:
        projected_content = added_text
    if added_line_numbers is None:
        added_line_numbers = set(range(1, added_text.count("\n") + 2))

    extracted_symbols: List[str] = []

    if is_python:
        try:
            tree = ast.parse(projected_content)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    name = node.name
                    if name.startswith("_"):
                        continue
                    start_line = getattr(node, "lineno", 1)
                    end_line = getattr(node, "end_lineno", start_line)
                    if set(range(start_line, end_line + 1)) & added_line_numbers:
                        extracted_symbols.append(name)
        except Exception:
            funcs = re.findall(r"^def\s+([a-zA-Z0-9_]+)\s*\(", added_text, re.MULTILINE)
            classes = re.findall(r"^class\s+([a-zA-Z0-9_]+)", added_text, re.MULTILINE)
            extracted_symbols = [s for s in funcs + classes if not s.startswith("_")]

    elif is_ts:
        func_pattern = re.compile(
            r"^(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+([a-zA-Z0-9_]+)",
            re.MULTILINE
        )
        class_pattern = re.compile(
            r"^(?:export\s+(?:default\s+)?)?class\s+([a-zA-Z0-9_]+)",
            re.MULTILINE
        )
        arrow_pattern = re.compile(
            r"^(?:export\s+)?const\s+([a-zA-Z0-9_]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_]+)\s*=>",
            re.MULTILINE
        )
        all_defs = []
        for pat in (func_pattern, class_pattern, arrow_pattern):
            for m in pat.finditer(projected_content):
                name = m.group(1)
                if not name.startswith("_"):
                    start_char = m.start()
                    start_line = projected_content[:start_char].count("\n") + 1
                    all_defs.append((start_line, name))

        all_defs.sort(key=lambda x: x[0])
        lines = projected_content.splitlines()
        for idx, (start_line, name) in enumerate(all_defs):
            if idx + 1 < len(all_defs):
                end_line = all_defs[idx + 1][0] - 1
            else:
                end_line = len(lines)
            if set(range(start_line, end_line + 1)) & added_line_numbers:
                extracted_symbols.append(name)

        if not extracted_symbols:
            exp_funcs = re.findall(r"export\s+(?:async\s+)?function\s+([a-zA-Z0-9_]+)", added_text)
            exp_arrows = re.findall(r"export\s+const\s+([a-zA-Z0-9_]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_]+)\s*=>", added_text)
            exp_classes = re.findall(r"export\s+class\s+([a-zA-Z0-9_]+)", added_text)
            extracted_symbols = [s for s in exp_funcs + exp_arrows + exp_classes if not s.startswith("_")]

    if not extracted_symbols:
        return False, ""

    test_content = ""
    for test_path in [candidate_test_path] + [p for p in (extra_test_paths or []) if p != candidate_test_path]:
        try:
            with open(test_path, "r", encoding="utf-8", errors="ignore") as f:
                test_content += f.read() + "\n"
        except (IOError, OSError):
            continue
    if not test_content.strip():
        return False, ""

    missing_symbols = []
    for sym in extracted_symbols:
        if not re.search(r"\b" + re.escape(sym) + r"\b", test_content):
            missing_symbols.append(sym)

    if missing_symbols:
        sample = ", ".join(f"'{s}'" for s in missing_symbols[:3])
        return True, (
            f"Sembol-Test İlişki Uyarısı (T3_SYMBOL_TO_TEST_LINK): Değiştirilen üretim sembolü "
            f"({sample}) ilgili test dosyasında ('{Path(candidate_test_path).name}') doğrudan referans edilmemiş. "
            f"Test dosyasının bu davranışı doğrudan veya dolaylı test ettiğinden emin olun."
        )

    return False, ""


def evaluate_test_evidence(
    target_file: str,
    is_test_file: bool,
    added_lines: List[str],
    added_text: str,
    projected_content: str = "",
    added_line_numbers: Optional[Set[int]] = None,
    cfg: Optional[dict] = None,
    is_python: bool = True,
    is_ts: bool = False
) -> Tuple[List[Tuple[str, str]], Dict[str, Any]]:
    """
    Evaluates Phase 2 Test Evidence rules (T1, T2, T3).
    Returns (warnings, actions) where actions contains pending mutations:
      - "resolve_test": bool
      - "record_test": Optional[Tuple[str, Optional[str], str, str]]
    """
    warnings = []
    actions: Dict[str, Any] = {
        "resolve_test": False,
        "record_test": None
    }

    if cfg and isinstance(cfg, dict):
        if not cfg.get("testEvidence", {}).get("enabled", True):
            return warnings, actions

    if is_test_file:
        actions["resolve_test"] = True

        t2_warn, t2_msg = check_t2_observable_assertion(
            added_lines, added_text, is_python, is_ts,
            projected_content=projected_content,
            added_line_numbers=added_line_numbers
        )
        if t2_warn:
            warnings.append(("T2_NO_OBSERVABLE_ASSERTION", t2_msg))
    else:
        t1_warn, t1_msg, candidate_path = check_t1_missing_test(target_file, added_text, cfg)
        if t1_warn:
            deferred = True
            if cfg and isinstance(cfg, dict):
                deferred = cfg.get("testEvidence", {}).get("deferredMode", True)

            if deferred:
                candidate_p, expected_n = resolve_candidate_test_file(target_file, cfg)
                actions["record_test"] = (target_file, candidate_p, expected_n, t1_msg)
            else:
                warnings.append(("T1_MISSING_RELATED_TEST", t1_msg))

        if candidate_path and os.path.isfile(candidate_path):
            direct_path, _ = resolve_candidate_test_file(target_file, cfg)
            extra_paths = None if direct_path else resolve_subsystem_test_files(target_file, cfg)
            t3_warn, t3_msg = check_t3_symbol_to_test_link(
                target_file, added_text, candidate_path, is_python, is_ts,
                projected_content=projected_content,
                added_line_numbers=added_line_numbers,
                extra_test_paths=extra_paths
            )
            if t3_warn:
                warnings.append(("T3_SYMBOL_TO_TEST_LINK", t3_msg))

    return warnings, actions


# ============================================================================
# T0 — DYNAMIC TEST EXECUTION & LCOV COVERAGE GATE (Stop hook, opt-in)
# ============================================================================
DEFAULT_MIN_COVERAGE_PERCENT = 80.0
_LCOV_CANDIDATES = ("coverage/lcov.info", "lcov.info", "coverage.lcov", "build/coverage/lcov.info")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _te_cfg(cfg: Optional[dict]) -> dict:
    te = cfg.get("testEvidence", {}) if isinstance(cfg, dict) else {}
    return te if isinstance(te, dict) else {}


def is_dynamic_execution_enabled(cfg: Optional[dict]) -> bool:
    """T0 runs the project's own test command, so it is opt-in: testEvidence.dynamicExecution must be true."""
    te = _te_cfg(cfg)
    return te.get("enabled", True) is not False and te.get("dynamicExecution", False) is True


def get_min_coverage_percent(cfg: Optional[dict]) -> float:
    value = _te_cfg(cfg).get("minCoveragePercent", DEFAULT_MIN_COVERAGE_PERCENT)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
        return DEFAULT_MIN_COVERAGE_PERCENT
    return float(value)


def parse_lcov(lcov_content: str) -> Dict[str, Any]:
    """
    Parses standard lcov.info. Returns {"files": {SF: {"lines": {lineno: hits}, "lf", "lh", "brf", "brh"}}}.
    LF/LH fall back to the DA records, BRF/BRH to the BRDA records when the summary lines are absent.
    """
    files: Dict[str, Dict[str, Any]] = {}
    rec: Optional[Dict[str, Any]] = None
    for raw in (lcov_content or "").splitlines():
        line = raw.strip()
        if line.startswith("SF:"):
            rec = {"lines": {}, "lf": None, "lh": None, "brf": None, "brh": None, "_brda": 0, "_brda_hit": 0}
            files[line[3:].strip()] = rec
        elif rec is None:
            continue
        elif line == "end_of_record":
            rec = None
        elif line.startswith("DA:"):
            parts = line[3:].split(",")
            try:
                no, hits = int(parts[0]), int(float(parts[1]))
            except (ValueError, IndexError):
                continue
            rec["lines"][no] = rec["lines"].get(no, 0) + hits
        elif line.startswith("BRDA:"):
            parts = line[5:].split(",")
            if len(parts) == 4:
                rec["_brda"] += 1
                if parts[3].strip() not in ("-", "0"):
                    rec["_brda_hit"] += 1
        else:
            for key, prefix in (("lf", "LF:"), ("lh", "LH:"), ("brf", "BRF:"), ("brh", "BRH:")):
                if line.startswith(prefix):
                    try:
                        rec[key] = int(line[len(prefix):])
                    except ValueError:
                        pass
    for rec in files.values():
        lines = rec["lines"]
        if rec["lf"] is None:
            rec["lf"] = len(lines)
        if rec["lh"] is None:
            rec["lh"] = sum(1 for h in lines.values() if h > 0)
        if rec["brf"] is None:
            rec["brf"] = rec["_brda"]
        if rec["brh"] is None:
            rec["brh"] = rec["_brda_hit"]
        del rec["_brda"], rec["_brda_hit"]
    return {"files": files}


def _norm_cov_path(path: str) -> str:
    return re.sub(r"^(?:\./)+", "", path.replace("\\", "/").lower())


def _match_lcov_entry(target: str, files: Dict[str, Any], repo_root: str = "") -> Optional[str]:
    t_abs = _norm_cov_path(target if os.path.isabs(target) or not repo_root else os.path.join(repo_root, target))
    t_rel = _norm_cov_path(target)
    if repo_root and os.path.isabs(target):
        try:
            t_rel = _norm_cov_path(os.path.relpath(target, repo_root))
        except ValueError:
            pass  # different drive: keep the absolute form
    for sf in files:
        s = _norm_cov_path(sf)
        if s in (t_abs, t_rel) or t_abs.endswith("/" + s) or s.endswith("/" + t_rel):
            return sf
    return None


def _pct(hit: int, found: int) -> Optional[float]:
    return round(hit * 100.0 / found, 2) if found > 0 else None


def evaluate_lcov_coverage(
    lcov_path: str,
    target_files: List[str],
    min_coverage: float = DEFAULT_MIN_COVERAGE_PERCENT,
    repo_root: str = ""
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    T0_COVERAGE_BELOW_THRESHOLD: line coverage of every changed file that appears in the lcov report must reach
    min_coverage. Branch coverage is computed and reported but does not trip the gate. Files absent from the
    report are listed under details["unmeasured"] (not a violation). Returns (violated, message, details).
    """
    details: Dict[str, Any] = {"min": min_coverage, "files": {}, "below": [], "unmeasured": []}
    try:
        with open(lcov_path, "r", encoding="utf-8", errors="replace") as fh:
            report = parse_lcov(fh.read())["files"]
    except OSError:
        details["status"] = "no_lcov"
        return False, "", details

    for target in target_files:
        sf = _match_lcov_entry(target, report, repo_root)
        if sf is None:
            details["unmeasured"].append(target)
            continue
        rec = report[sf]
        line_pct = _pct(rec["lh"], rec["lf"])
        entry = {
            "line_pct": line_pct, "branch_pct": _pct(rec["brh"], rec["brf"]),
            "lf": rec["lf"], "lh": rec["lh"], "brf": rec["brf"], "brh": rec["brh"],
        }
        details["files"][target] = entry
        if line_pct is not None and line_pct < min_coverage:
            details["below"].append(target)

    details["status"] = "ok"
    if not details["below"]:
        return False, "", details
    parts = []
    for target in details["below"]:
        e = details["files"][target]
        branch = f", dal %{e['branch_pct']:.1f}" if e["branch_pct"] is not None else ""
        parts.append(f"'{os.path.basename(target)}' satır %{e['line_pct']:.1f} ({e['lh']}/{e['lf']}{branch})")
    return True, (
        f"Kapsam Uyarısı (T0_COVERAGE_BELOW_THRESHOLD): Değişen dosyaların satır kapsamı %{min_coverage:g} "
        f"eşiğinin altında: {', '.join(parts)}. Eksik satırlar için test ekleyin."
    ), details


def detect_test_runner(repo_root: str) -> Optional[List[str]]:
    """Auto-detects the project's test command: package.json -> npm test / vitest, pytest markers, Cargo.toml."""
    root = Path(repo_root)
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        script = ((data.get("scripts") or {}).get("test") or "") if isinstance(data, dict) else ""
        if script and "no test specified" not in script:
            return ["npm", "test"]
        deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})} if isinstance(data, dict) else {}
        if "vitest" in deps:
            return ["npx", "vitest", "run"]
    if any((root / marker).is_file() for marker in ("pytest.ini", "conftest.py", "setup.py")):
        return [sys.executable, "-m", "pytest", "-q"]
    if (root / "Cargo.toml").is_file():
        return ["cargo", "test"]
    return None


def _count_tests(output: str) -> Optional[int]:
    """Number of executed tests parsed from runner output, or None when the format is unknown."""
    text = _ANSI_RE.sub("", output)
    m = re.search(r"^Ran (\d+) tests?\b", text, re.M)  # unittest
    if m:
        return int(m.group(1))
    m = re.search(r"^(?:ℹ|#) tests (\d+)\s*$", text, re.M)  # node:test / TAP
    if m:
        return int(m.group(1))
    m = re.search(r"^Tests:\s.*?(\d+) total", text, re.M)  # jest
    if m:
        return int(m.group(1))
    cargo = re.findall(r"test result: \w+\. (\d+) passed; (\d+) failed", text)
    if cargo:
        return sum(int(p) + int(f) for p, f in cargo)
    m = re.search(r"^\s*Tests\s+(.*\d+ (?:passed|failed).*)$", text, re.M)  # vitest
    if m:
        return sum(int(n) for n in re.findall(r"(\d+) (?:passed|failed)", m.group(1)))
    if re.search(r"no tests ran", text, re.I):  # pytest
        return 0
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if lines and re.search(r"\bin [\d.]+s\b", lines[-1]):  # pytest summary: "1 failed, 2 passed in 0.5s"
        return sum(int(n) for n in re.findall(r"(\d+) (?:passed|failed|errors?|xfailed|xpassed)\b", lines[-1]))
    return None


def _kill_process_tree(proc: "subprocess.Popen[str]") -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        proc.kill()


def run_dynamic_tests(
    repo_root: str,
    timeout_sec: int = 30,
    command: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Runs the project's tests in a subprocess (no shell, own process group, hard timeout, CI=1).
    Returns {"status": ok|failed|no_tests|timeout|no_runner|error, "exit_code", "tests_executed", "command",
    "duration_sec", "output_tail", "started_at"}. rule: failed -> T0_TEST_RUN_FAILED, no_tests -> T0_NO_TESTS_EXECUTED.
    """
    result: Dict[str, Any] = {
        "status": "no_runner", "exit_code": None, "tests_executed": None,
        "command": None, "duration_sec": 0.0, "output_tail": "", "started_at": time.time(),
    }
    cmd = command or detect_test_runner(repo_root)
    if not cmd:
        return result
    exe = shutil.which(cmd[0])
    if exe is None:
        result.update(status="error", command=cmd, output_tail=f"Test çalıştırıcı bulunamadı: {cmd[0]}")
        return result
    cmd = [exe, *cmd[1:]]
    result["command"] = cmd

    popen_kwargs: Dict[str, Any] = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        popen_kwargs["start_new_session"] = True
    started = time.perf_counter()
    try:
        proc = subprocess.Popen(
            cmd, cwd=repo_root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env={**os.environ, "CI": "1", "NO_COLOR": "1"}, **popen_kwargs
        )
    except OSError as err:
        result.update(status="error", output_tail=str(err))
        return result
    try:
        output, _ = proc.communicate(timeout=timeout_sec)
        timed_out = False
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        try:
            output, _ = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            output = ""
        timed_out = True
    result["duration_sec"] = round(time.perf_counter() - started, 2)
    output = output or ""
    result["output_tail"] = _ANSI_RE.sub("", output)[-1500:]
    if timed_out:
        result["status"] = "timeout"
        return result

    exit_code = proc.returncode
    count = _count_tests(output)
    if exit_code == 5 and "pytest" in " ".join(cmd):  # pytest: no tests collected
        count = 0
    result.update(exit_code=exit_code, tests_executed=count)
    if count == 0:
        result["status"] = "no_tests"
    elif exit_code != 0:
        result["status"] = "failed"
    else:
        result["status"] = "ok"
    return result


def _git_changed_source_files(repo_root: str) -> List[str]:
    """Absolute paths of changed non-test source files (git status --porcelain), best effort / fail-open."""
    try:
        proc = subprocess.run(["git", "status", "--porcelain"], cwd=repo_root, capture_output=True,
                              text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    changed = []
    for line in proc.stdout.splitlines():
        path = line[3:].split(" -> ")[-1].strip().strip('"') if len(line) > 3 else ""
        base = os.path.basename(path)
        if not path or "D" in line[:2] or any(fnmatch.fnmatch(base, p) for p in _TEST_FILE_PATTERNS):
            continue
        changed.append(os.path.join(repo_root, path))
    return changed


def evaluate_t0_gate(
    repo_root: str,
    cfg: Optional[dict] = None,
    changed_files: Optional[List[str]] = None,
    timeout_sec: Optional[int] = None
) -> List[Tuple[str, str]]:
    """
    Stop-hook T0 gate. Returns [(rule_id, message)]:
      T0_TEST_RUN_FAILED / T0_NO_TESTS_EXECUTED from the dynamic run, then T0_COVERAGE_BELOW_THRESHOLD for the
      changed files when a *fresh* lcov report (written by that run) exists. Disabled unless
      testEvidence.dynamicExecution is true. Optional config: testCommand (list), timeoutSec, minCoveragePercent, lcovPath.
    """
    if not is_dynamic_execution_enabled(cfg):
        return []
    te = _te_cfg(cfg)
    command = te.get("testCommand") if isinstance(te.get("testCommand"), list) and te.get("testCommand") else None
    timeout = timeout_sec or (te.get("timeoutSec") if isinstance(te.get("timeoutSec"), int) and te.get("timeoutSec") > 0 else 30)

    run = run_dynamic_tests(repo_root, timeout_sec=timeout, command=command)
    cmd_text = " ".join(run["command"]) if run["command"] else "?"
    tail = run["output_tail"].strip()[-400:]
    status = run["status"]
    if status == "failed":
        return [("T0_TEST_RUN_FAILED", (
            f"Dinamik Test Uyarısı (T0_TEST_RUN_FAILED): '{cmd_text}' çıkış kodu {run['exit_code']} ile bitti "
            f"({run['tests_executed'] if run['tests_executed'] is not None else '?'} test). Son çıktı: {tail}"))]
    if status == "timeout":
        return [("T0_TEST_RUN_FAILED", (
            f"Dinamik Test Uyarısı (T0_TEST_RUN_FAILED): '{cmd_text}' {timeout} sn zaman aşımına uğradı ve sonlandırıldı."))]
    if status == "error":
        return [("T0_TEST_RUN_FAILED", f"Dinamik Test Uyarısı (T0_TEST_RUN_FAILED): test başlatılamadı: {tail}")]
    if status == "no_tests":
        return [("T0_NO_TESTS_EXECUTED", (
            f"Dinamik Test Uyarısı (T0_NO_TESTS_EXECUTED): '{cmd_text}' çalıştı ama hiç test koşulmadı (0 test). "
            f"Test kanıtı olarak sayılmaz."))]
    if status == "no_runner":
        return []

    lcov = te.get("lcovPath")
    candidates = [lcov] if isinstance(lcov, str) and lcov else list(_LCOV_CANDIDATES)
    lcov_path = next((str(Path(repo_root) / c) for c in candidates if (Path(repo_root) / c).is_file()), None)
    if not lcov_path or os.path.getmtime(lcov_path) < run["started_at"] - 1:
        return []  # no report, or a stale one this run did not produce
    targets = changed_files if changed_files is not None else _git_changed_source_files(repo_root)
    targets = [t for t in targets if not is_exempt_from_test_evidence(t, cfg)]
    if not targets:
        return []
    violated, msg, _ = evaluate_lcov_coverage(lcov_path, targets, get_min_coverage_percent(cfg), repo_root)
    return [("T0_COVERAGE_BELOW_THRESHOLD", msg)] if violated else []
