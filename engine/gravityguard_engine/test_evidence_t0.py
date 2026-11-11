#!/usr/bin/env python3
"""
GravityGuard Engine — T0 Dynamic Test Execution & LCOV Coverage Gate (Stop hook, opt-in).
Zero external dependencies.
"""
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
from typing import Any, Dict, List, Optional, Tuple

from .test_evidence_discovery import _TEST_FILE_PATTERNS, is_exempt_from_test_evidence

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
            pass
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
    min_coverage. Returns (violated, message, details).
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
        f"Kapsam Uyarısı: Değişen dosyaların satır kapsamı %{min_coverage:g} "
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
    m = re.search(r"^Ran (\d+) tests?\b", text, re.M)
    if m:
        return int(m.group(1))
    m = re.search(r"^(?:ℹ|#) tests (\d+)\s*$", text, re.M)
    if m:
        return int(m.group(1))
    m = re.search(r"^Tests:\s.*?(\d+) total", text, re.M)
    if m:
        return int(m.group(1))
    cargo = re.findall(r"test result: \w+\. (\d+) passed; (\d+) failed", text)
    if cargo:
        return sum(int(p) + int(f) for p, f in cargo)
    m = re.search(r"^\s*Tests\s+(.*\d+ (?:passed|failed).*)$", text, re.M)
    if m:
        return sum(int(n) for n in re.findall(r"(\d+) (?:passed|failed)", m.group(1)))
    if re.search(r"no tests ran", text, re.I):
        return 0
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if lines and re.search(r"\bin [\d.]+s\b", lines[-1]):
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
    if exit_code == 5 and "pytest" in " ".join(cmd):
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
    Stop-hook T0 gate. Returns [(rule_id, message)].
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
            f"Dinamik Test Uyarısı: '{cmd_text}' çıkış kodu {run['exit_code']} ile bitti "
            f"({run['tests_executed'] if run['tests_executed'] is not None else '?'} test). Son çıktı: {tail}"))]
    if status == "timeout":
        return [("T0_TEST_RUN_FAILED", (
            f"Dinamik Test Uyarısı: '{cmd_text}' {timeout} sn zaman aşımına uğradı ve sonlandırıldı."))]
    if status == "error":
        return [("T0_TEST_RUN_FAILED", f"Dinamik Test Uyarısı: test başlatılamadı: {tail}")]
    if status == "no_tests":
        return [("T0_NO_TESTS_EXECUTED", (
            f"Dinamik Test Uyarısı: '{cmd_text}' çalıştı ama hiç test koşulmadı (0 test). "
            f"Test kanıtı olarak sayılmaz."))]
    if status == "no_runner":
        return []

    lcov = te.get("lcovPath")
    candidates = [lcov] if isinstance(lcov, str) and lcov else list(_LCOV_CANDIDATES)
    lcov_path = next((str(Path(repo_root) / c) for c in candidates if (Path(repo_root) / c).is_file()), None)
    if not lcov_path or os.path.getmtime(lcov_path) < run["started_at"] - 1:
        return []
    targets = changed_files if changed_files is not None else _git_changed_source_files(repo_root)
    targets = [t for t in targets if not is_exempt_from_test_evidence(t, cfg)]
    if not targets:
        return []
    violated, msg, _ = evaluate_lcov_coverage(lcov_path, targets, get_min_coverage_percent(cfg), repo_root)
    return [("T0_COVERAGE_BELOW_THRESHOLD", msg)] if violated else []
