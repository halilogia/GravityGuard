#!/usr/bin/env python3
"""
GravityGuard Engine — Test Evidence Airbag Subsystem (T1, T2, T3).
Zero external dependencies.
"""
import ast
import fnmatch
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

DEFAULT_EXEMPT_PATTERNS: List[str] = [
    "types", "constants", "index", ".d.ts", "config", "interfaces", "schemas",
    "migration", "migrations", "fixtures", "mock", "mocks", "tools", "scripts"
]

_TEST_FILE_PATTERNS = ("test_*.py", "*_test.py", "*.test.*", "*.spec.*", "conftest.py")


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
        candidate_names = list(dict.fromkeys(candidate_names))
    elif suffix in [".ts", ".tsx", ".js", ".jsx"]:
        candidate_names = [
            f"{stem}.test{suffix}", f"{stem}.spec{suffix}",
            f"{stem_us}.test{suffix}", f"{stem_us}.spec{suffix}",
            f"{stem_hy}.test{suffix}", f"{stem_hy}.spec{suffix}",
            f"test_{stem}{suffix}", f"{stem}_test{suffix}"
        ]
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
    Triggers when production code changes but no candidate test file exists on disk,
    or candidate test file exists but was not updated in the active session window.
    Silent when the project has no test infrastructure at all.
    Returns: (warn_triggered, warn_message, candidate_test_path)
    """
    if not added_text.strip():
        return False, "", None

    if is_exempt_from_test_evidence(target_file, cfg):
        return False, "", None

    candidate_path, expected_name = resolve_candidate_test_file(target_file, cfg)

    if not candidate_path or not os.path.exists(candidate_path):
        if not project_has_test_infrastructure(target_file, cfg):
            return False, "", None
        return True, (
            f"Test Kanıtı Uyarısı (T1_MISSING_RELATED_TEST): Üretim kodunda değişiklik yapıldı "
            f"ancak ilişkili test dosyası ('{expected_name}') diskte bulunamadı. "
            f"Davranış değişikliği için ilgili test dosyasını oluşturmayı veya güncellemeyi değerlendirin."
        ), None

    session_window = 300
    if cfg and isinstance(cfg, dict):
        session_window = cfg.get("testEvidence", {}).get("sessionWindowSeconds", 300)

    try:
        test_mtime = os.path.getmtime(candidate_path)
        if (time.time() - test_mtime) > session_window:
            return True, (
                f"Test Kanıtı Uyarısı (T1_MISSING_RELATED_TEST): Üretim kodu değiştirildi ancak "
                f"ilişkili test dosyası ('{candidate_path}') bu oturumda ({session_window}s) güncellenmedi."
            ), candidate_path
    except OSError:
        test_mtime = 0.0

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
    added_line_numbers: Optional[Set[int]] = None
) -> Tuple[bool, str]:
    """
    T3 — SYMBOL_TO_TEST_LINK (WARN ONLY).
    Checks whether modified/added top-level functions or classes (including body-only changes)
    are referenced by name in the candidate test file.
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

    try:
        with open(candidate_test_path, "r", encoding="utf-8", errors="ignore") as f:
            test_content = f.read()
    except (IOError, OSError):
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
            t3_warn, t3_msg = check_t3_symbol_to_test_link(
                target_file, added_text, candidate_path, is_python, is_ts,
                projected_content=projected_content,
                added_line_numbers=added_line_numbers
            )
            if t3_warn:
                warnings.append(("T3_SYMBOL_TO_TEST_LINK", t3_msg))

    return warnings, actions
