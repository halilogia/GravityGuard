"""GravityGuard Engine — audit fallback spool, log dir and permanent journal helpers."""
import json
import os
import sys
import time
import uuid
from typing import Optional, Dict, Any, List, Tuple, Set


def _prepare_fallback_spool(log_dir: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Atomically renames the fallback spool and recovers orphaned processing files.
    Two-phase protocol: files are only deleted after verified append to canonical journal.
    """
    processing_files: List[str] = []
    spool_events: List[Dict[str, Any]] = []

    fallback_spool_path = os.path.join(log_dir, "gravityguard_audit_fallback.jsonl")

    # 1. Recover any orphaned .processing files from previous crashes
    try:
        if os.path.isdir(log_dir):
            for fname in os.listdir(log_dir):
                if fname.startswith("gravityguard_audit_fallback.processing."):
                    processing_files.append(os.path.join(log_dir, fname))
                elif fname.startswith("gravityguard_audit_spool.") and fname.endswith(".jsonl"):
                    sp_full = os.path.join(log_dir, fname)
                    p_id = f"gravityguard_audit_fallback.processing.{os.getpid()}_{uuid.uuid4().hex[:8]}"
                    p_path = os.path.join(log_dir, p_id)
                    try:
                        os.replace(sp_full, p_path)
                        processing_files.append(p_path)
                    except Exception as ren_sp_err:
                        sys.stderr.write(f"[GravityGuard Spool Multi-Process Recovery Notice: {fname}] {ren_sp_err}\n")
    except Exception as scan_err:
        sys.stderr.write(f"[GravityGuard Spool Recovery Scan Notice] {scan_err}\n")

    # 2. Atomically rename active fallback spool if it exists and has content
    if os.path.exists(fallback_spool_path):
        try:
            if os.path.getsize(fallback_spool_path) > 0:
                p_id = f"gravityguard_audit_fallback.processing.{os.getpid()}_{uuid.uuid4().hex[:8]}"
                p_path = os.path.join(log_dir, p_id)
                os.replace(fallback_spool_path, p_path)
                processing_files.append(p_path)
            else:
                try:
                    os.remove(fallback_spool_path)
                except OSError as empty_rm_err:
                    sys.stderr.write(f"[GravityGuard Spool Empty Clean Notice] {empty_rm_err}\n")
        except Exception as rename_err:
            sys.stderr.write(f"[GravityGuard Spool Rename Warning] {rename_err}\n")

    # 3. Read events from all processing files (do NOT delete yet!)
    for p_path in processing_files:
        try:
            with open(p_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped:
                        try:
                            ev = json.loads(stripped)
                            if isinstance(ev, dict):
                                spool_events.append(ev)
                        except Exception as json_parse_err:
                            sys.stderr.write(f"[GravityGuard Spool Parse Warning: {p_path}] {json_parse_err}\n")
        except Exception as read_err:
            sys.stderr.write(f"[GravityGuard Spool Read Error: {p_path}] {read_err}\n")

    return processing_files, spool_events


def _commit_fallback_spool(processing_files: List[str]) -> None:
    """
    Second phase of spool protocol: deletes processing files ONLY after
    they have been successfully written and flushed to the canonical journal.
    """
    for p_path in processing_files:
        try:
            if os.path.exists(p_path):
                os.remove(p_path)
        except Exception as rm_err:
            sys.stderr.write(f"[GravityGuard Spool Commit Warning: {p_path}] {rm_err}\n")


def _find_committed_event_ids(permanent_log_path: str, candidate_ids: Set[str]) -> Set[str]:
    """
    Checks the canonical permanent audit journal directly to discover which candidate
    eventIds are already persistently committed. Guarantees true idempotency independent
    of the sliding 50-event live memory window.
    """
    committed: Set[str] = set()
    if not candidate_ids or not os.path.exists(permanent_log_path):
        return committed

    try:
        with open(permanent_log_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                for cid in candidate_ids:
                    if cid not in committed and cid in line_str:
                        try:
                            rec = json.loads(line_str)
                            if isinstance(rec, dict) and rec.get("eventId") == cid:
                                committed.add(cid)
                        except (json.JSONDecodeError, ValueError) as parse_err:
                            sys.stderr.write(f"[GravityGuard Idempotency Parse Warning] {parse_err}\n")
                if len(committed) == len(candidate_ids):
                    break
    except Exception as err:
        sys.stderr.write(f"[GravityGuard Idempotency Scan Warning] {err}\n")

    return committed




def _resolve_log_dir() -> str:
    """
    Resolves the audit-log directory.
    GRAVITYGUARD_LOG_DIR lets the test suite / CI redirect the audit stream to a
    temp directory. Without it, test runs append to ~/.gemini/logs.
    GRAVITYGUARD_AUDIT_DIR relocates the audit stream only (opt-in project-local or custom folder);
    GRAVITYGUARD_LOG_DIR wins when both are set.
    """
    for var in ("GRAVITYGUARD_LOG_DIR", "GRAVITYGUARD_AUDIT_DIR"):
        override = os.environ.get(var, "").strip()
        if override:
            return os.path.expanduser(override)
    return os.path.expanduser(r"~/.gemini/logs/gravityguard")


def _generate_event_id() -> str:
    """Generates a unique, timestamp-prefixed event ID for causal chaining."""
    now_ms = int(time.time() * 1000)
    suffix = uuid.uuid4().hex[:8]
    return f"evt_{now_ms}_{suffix}"


def _is_durable_mode() -> bool:
    """Checks whether hardware fsync durability mode is requested."""
    return os.environ.get("GRAVITYGUARD_DURABILITY", "normal").strip().lower() == "durable"


def _read_last_journal_entry(permanent_log_path: str) -> Optional[Dict[str, Any]]:
    """Reads the last valid JSON entry from the permanent audit log."""
    if not os.path.exists(permanent_log_path):
        return None
    try:
        with open(permanent_log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size == 0:
                return None
            # Checkpoints and large tool payloads may exceed one read block.
            # Parse only complete lines, extending backwards when necessary.
            remaining = size
            buffer = b""
            while remaining:
                chunk_size = min(remaining, 8192)
                remaining -= chunk_size
                f.seek(remaining)
                buffer = f.read(chunk_size) + buffer
                lines = buffer.splitlines()
                for line in reversed(lines if remaining == 0 else lines[1:]):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        if isinstance(record, dict):
                            return record
                    except (ValueError, UnicodeDecodeError):
                        continue
    except Exception as err:
        sys.stderr.write(f"[GravityGuard Journal Read Error] {err}\n")
    return None


def _repair_journal_tail(permanent_log_path: str) -> None:
    """
    Repairs a torn or partial tail in the permanent audit journal (WAL).
    If a process crashes or loses power mid-write, the last line may be truncated
    or unparseable JSON. Truncates the file back to the last valid newline boundary.
    """
    if not os.path.exists(permanent_log_path):
        return
    try:
        with open(permanent_log_path, "rb+") as f:
            f.seek(0, os.SEEK_END)
            total_size = f.tell()
            if total_size == 0:
                return

            chunk_size = min(total_size, 16384)
            f.seek(total_size - chunk_size)
            chunk = f.read(chunk_size)

            lines = chunk.splitlines(keepends=True)
            if not lines:
                return

            last_line = lines[-1]
            stripped = last_line.strip()
            if stripped:
                try:
                    json.loads(stripped.decode("utf-8"))
                    # Complete valid JSON! If trailing newline delimiter was omitted, append it
                    if not (last_line.endswith(b"\n") or last_line.endswith(b"\r")):
                        f.seek(0, os.SEEK_END)
                        f.write(b"\n")
                        f.flush()
                    return
                except Exception as parse_err:
                    # Broken / partial JSON: fall through to truncate
                    sys.stderr.write(f"[GravityGuard WAL Tail Notice] Incomplete trailing JSON: {parse_err}\n")
            elif last_line.endswith(b"\n") or last_line.endswith(b"\r"):
                # Clean trailing whitespace/newline
                return

            sys.stderr.write("[GravityGuard WAL Repair] Torn journal tail detected; repairing to last valid newline\n")

            valid_offset = 0
            found_valid = False
            curr_offset = total_size - len(last_line)
            for prev_line in reversed(lines[:-1]):
                p_strip = prev_line.strip()
                if not p_strip:
                    curr_offset -= len(prev_line)
                    continue
                try:
                    json.loads(p_strip.decode("utf-8"))
                    found_valid = True
                    valid_offset = curr_offset
                    break
                except Exception:
                    curr_offset -= len(prev_line)

            if not found_valid and chunk_size < total_size:
                f.seek(0)
                all_data = f.read()
                all_lines = all_data.splitlines(keepends=True)
                accum = 0
                for line in all_lines:
                    l_str = line.strip()
                    if l_str:
                        try:
                            json.loads(l_str.decode("utf-8"))
                            accum += len(line)
                            valid_offset = accum
                        except Exception:
                            break
                    else:
                        accum += len(line)
                        valid_offset = accum
            elif not found_valid:
                valid_offset = 0

            f.seek(valid_offset)
            f.truncate()
            f.flush()
    except Exception as err:
        sys.stderr.write(f"[GravityGuard WAL Tail Repair Error] {err}\n")


def _get_journal_last_seq(permanent_log_path: str) -> int:
    """
    Returns the highest auditSeq in the permanent audit journal.
    If the journal has entries without explicit auditSeq (legacy logs),
    counts non-empty lines to establish the initial monotonic sequence.
    """
    if not os.path.exists(permanent_log_path):
        return 0
    last_entry = _read_last_journal_entry(permanent_log_path)
    if last_entry and "auditSeq" in last_entry and isinstance(last_entry["auditSeq"], int):
        return last_entry["auditSeq"]
    count = 0
    try:
        with open(permanent_log_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.strip():
                    count += 1
    except Exception as err:
        sys.stderr.write(f"[GravityGuard Journal Count Error] {err}\n")
    return count

