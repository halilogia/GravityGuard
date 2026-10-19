"""
GravityGuard — Task Archiver Subsystem.
Automatically archives completed tasks ([x]) from tasks.md into taskslog.md
when triggers fire (completed count > threshold, or lines > max_lines, or Stop hook).
Zero external dependencies.
"""
from __future__ import annotations

import datetime
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

TASK_LINE_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s*\[([ /xX])\]\s+(.+)$")
DONE_TASK_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s*\[[xX]\]\s+(.+)$")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")

DEFAULT_COMPLETED_THRESHOLD = 10
DEFAULT_MAX_LINES = 150
DEFAULT_KEEP_RECENT = 5


def archive_completed_tasks(
    task_file_path: Path | str,
    threshold: int = DEFAULT_COMPLETED_THRESHOLD,
    max_lines: int = DEFAULT_MAX_LINES,
    keep_recent: int = DEFAULT_KEEP_RECENT,
    force: bool = False,
    date_str: Optional[str] = None,
    log_file_name: str = "taskslog.md",
) -> Dict[str, object]:
    """
    Archives completed tasks from a markdown task file into taskslog.md.

    Returns a dict with:
      - 'archived_count': int
      - 'retained_done_count': int
      - 'tasks_log_path': str
      - 'performed': bool
    """
    path = Path(task_file_path)
    if not path.is_file():
        return {"archived_count": 0, "retained_done_count": 0, "tasks_log_path": "", "performed": False}

    raw = path.read_bytes().decode("utf-8-sig")
    is_crlf = "\r\n" in raw
    lines = raw.splitlines()

    # Track fenced code blocks and find done items
    in_fence = False
    fence_token = None
    done_indices: List[int] = []

    for idx, line in enumerate(lines):
        fm = FENCE_RE.match(line)
        if fm:
            token = fm.group(1)
            if not in_fence:
                in_fence = True
                fence_token = token
            elif fence_token and token.startswith(fence_token[0]) and len(token) >= len(fence_token):
                in_fence = False
                fence_token = None
            continue

        if in_fence:
            continue

        if DONE_TASK_RE.match(line):
            done_indices.append(idx)

    total_done = len(done_indices)
    total_lines = len(lines)

    # Check trigger condition
    should_archive = force or (total_done > threshold) or (total_lines > max_lines and total_done > keep_recent)
    if not should_archive:
        return {"archived_count": 0, "retained_done_count": total_done, "tasks_log_path": "", "performed": False}

    # Decide how many to archive
    keep_count = max(0, keep_recent)
    if total_done <= keep_count:
        if not force:
            return {"archived_count": 0, "retained_done_count": total_done, "tasks_log_path": "", "performed": False}
        archive_count = total_done
    else:
        archive_count = total_done - keep_count

    if archive_count <= 0:
        return {"archived_count": 0, "retained_done_count": total_done, "tasks_log_path": "", "performed": False}

    to_archive_set = set(done_indices[:archive_count])
    archived_lines = [lines[i] for i in done_indices[:archive_count]]
    remaining_lines = [line for i, line in enumerate(lines) if i not in to_archive_set]

    # Target taskslog.md in the same directory
    log_path = path.parent / log_file_name
    today = date_str or datetime.date.today().isoformat()

    # Read or initialize taskslog.md
    log_content = ""
    if log_path.is_file():
        log_content = log_path.read_bytes().decode("utf-8-sig")

    if not log_content.strip():
        header = (
            "# 📜 Tasks Log (Görev Arşivi)\n\n"
            "> Bu dosya GravityGuard Task Archiver tarafından otomatik yönetilir.\n"
            "> tasks.md dosyasının şişmesini önlemek için tamamlanan görevler buraya aktarılır.\n"
        )
        log_content = header

    # Append archived items under today's date section
    date_header = f"## [{today}]"
    archived_block = "\n".join(archived_lines)

    if date_header in log_content:
        # Insert under existing date section
        parts = log_content.split(date_header, 1)
        log_content = parts[0] + date_header + "\n" + archived_block + "\n" + parts[1].lstrip("\n")
    else:
        if not log_content.endswith("\n\n"):
            log_content = log_content.rstrip("\n") + "\n\n"
        log_content += f"{date_header}\n{archived_block}\n"

    # Write taskslog.md
    log_path.write_text(log_content, encoding="utf-8")

    # Write remaining lines to tasks.md
    nl = "\r\n" if is_crlf else "\n"
    path.write_text(nl.join(remaining_lines) + (nl if remaining_lines else ""), encoding="utf-8")

    return {
        "archived_count": len(archived_lines),
        "retained_done_count": total_done - len(archived_lines),
        "tasks_log_path": str(log_path),
        "performed": True,
    }
