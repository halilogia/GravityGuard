#!/usr/bin/env python3
"""
GravityGuard Engine — Test Evidence Airbag Subsystem (T1, T2, T3).
Zero external dependencies.
"""
import ast
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .test_evidence_discovery import (  # noqa: F401 (re-export)
    DEFAULT_EXEMPT_PATTERNS,
    DEFAULT_SUBSYSTEM_MAPPINGS,
    _TEST_FILE_PATTERNS,
    _get_subsystem_mappings,
    _project_relative_path,
    is_exempt_from_test_evidence,
    project_has_test_infrastructure,
    resolve_candidate_test_file,
    resolve_subsystem_test_files,
)
from .test_evidence_t0 import (  # noqa: F401 (re-export)
    DEFAULT_MIN_COVERAGE_PERCENT,
    _ANSI_RE,
    _LCOV_CANDIDATES,
    _count_tests,
    _git_changed_source_files,
    _kill_process_tree,
    _match_lcov_entry,
    _norm_cov_path,
    _pct,
    _te_cfg,
    detect_test_runner,
    evaluate_lcov_coverage,
    evaluate_t0_gate,
    get_min_coverage_percent,
    is_dynamic_execution_enabled,
    parse_lcov,
    run_dynamic_tests,
)


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
            f"Test Kanıtı Uyarısı: Üretim kodunda değişiklik yapıldı "
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
            f"Test Gözlem Uyarısı: Eklenen/değiştirilen test case "
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
            r"^(export\s+)?(?:default\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_]+)",
            re.MULTILINE
        )
        class_pattern = re.compile(
            r"^(export\s+)?(?:default\s+)?class\s+([a-zA-Z0-9_]+)",
            re.MULTILINE
        )
        arrow_pattern = re.compile(
            r"^(export\s+)?const\s+([a-zA-Z0-9_]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_]+)\s*=>",
            re.MULTILINE
        )
        all_defs = []
        for pat in (func_pattern, class_pattern, arrow_pattern):
            for m in pat.finditer(projected_content):
                is_exp = bool(m.group(1)); name = m.group(2)
                if not name.startswith("_"):
                    start_char = m.start()
                    start_line = projected_content[:start_char].count("\n") + 1
                    all_defs.append((start_line, name, is_exp))

        all_defs.sort(key=lambda x: x[0])
        lines = projected_content.splitlines()
        for idx, (start_line, name, is_exp) in enumerate(all_defs):
            if not is_exp:
                continue
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
            f"Sembol-Test İlişki Uyarısı: Değiştirilen üretim sembolü "
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
        deferred = True
        if cfg and isinstance(cfg, dict):
            deferred = cfg.get("testEvidence", {}).get("deferredMode", True)
        if t1_warn:
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
            if t3_warn and deferred:
                if actions["record_test"] is None:
                    actions["record_test"] = (target_file, candidate_path, os.path.basename(candidate_path), t3_msg)
            elif t3_warn:
                warnings.append(("T3_SYMBOL_TO_TEST_LINK", t3_msg))

    return warnings, actions


def final_test_evidence_warnings(unresolved: dict) -> List[Tuple[str, str]]:
    """Stop-time warnings for pending test obligations, as (rule_id, message)."""
    out: List[Tuple[str, str]] = []
    stale = {p: i for p, i in unresolved.items() if str(i.get("reason", "")).startswith("Sembol-Test")}
    if stale:
        out.append(("T3_SYMBOL_TO_TEST_LINK", " ".join(str(i["reason"]) for i in stale.values())))
    missing = [f"'{p}' (beklenen test: {i.get('expected_name', 'test')})" for p, i in unresolved.items() if p not in stale]
    if missing:
        out.append(("T1_FINAL_UNRESOLVED", "Test Kanıtı Uyarısı: Oturum tamamlandı ancak şu üretim kodları için "
                    f"test kanıtı bulunamadı: {', '.join(missing)}"))
    return out
