#!/usr/bin/env python3
"""
GravityGuard Engine — Evidence-Based Delivery Gate (EBDG) Subsystem.
Zero-AI, 100% deterministic verification gate.
Verifies concrete physical artifacts (screenshots, test outputs) before allowing task delivery.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

UI_EXTENSIONS: Set[str] = {
    ".css", ".scss", ".sass", ".less",
    ".html", ".htm",
    ".vue", ".svelte",
    ".tscn"
}

UI_DIR_SUBSTRINGS: Tuple[str, ...] = (
    "/ui/", "/views/", "/components/", "/pages/", "/web/", "/frontend/", "/client/",
    "\\ui\\", "\\views\\", "\\components\\", "\\pages\\", "\\web\\", "\\frontend\\", "\\client\\"
)

IMAGE_EXTENSIONS: Set[str] = {".png", ".jpg", ".jpeg", ".webp"}


def is_ui_file(path_str: str) -> bool:
    """Returns True if the given path represents a UI/frontend artifact."""
    norm = path_str.replace("\\", "/").lower()
    suffix = Path(norm).suffix

    if suffix in UI_EXTENSIONS:
        return True

    # TypeScript/JavaScript files only count as UI if they reside in UI-dedicated directories
    if suffix in {".tsx", ".jsx"}:
        for marker in ("/ui/", "/views/", "/components/", "/pages/", "/web/", "/frontend/"):
            if marker in norm:
                return True

    return False


def find_recent_screenshots(
    search_dirs: List[Path],
    max_age_seconds: int = 600,
    min_size_bytes: int = 1024
) -> List[Path]:
    """Scans candidate directories for fresh, non-empty image files."""
    now = time.time()
    found: List[Path] = []

    for directory in search_dirs:
        if not directory.is_dir():
            continue
        try:
            items = list(directory.rglob("*"))
        except (OSError, PermissionError):
            items = []
        for item in items:
            try:
                if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS:
                    st = item.stat()
                    if st.st_size >= min_size_bytes and (now - st.st_mtime) <= max_age_seconds:
                        found.append(item)
            except (OSError, PermissionError):
                continue

    # Return newest first
    return sorted(found, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)


def get_git_modified_files(project_root: Path) -> List[str]:
    """Retrieves list of modified/added files in project git working tree."""
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5
        )
        if proc.returncode != 0:
            return []
        files = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                files.append(parts[1].strip('"'))
        return files
    except (OSError, subprocess.SubprocessError):
        return []


def write_delivery_receipt(
    project_root: Path,
    conversation_id: str,
    status: str,
    category: str,
    evidence_details: Dict[str, Any]
) -> Optional[Path]:
    """Writes a machine-readable delivery receipt to .gravityguard/runtime/delivery_receipt.json."""
    runtime_dir = project_root / ".gravityguard" / "runtime"
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        receipt_file = runtime_dir / "delivery_receipt.json"

        data = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "conversationId": conversation_id,
            "deliveryStatus": status,
            "category": category,
            "evidence": evidence_details
        }
        receipt_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return receipt_file
    except OSError as err:
        sys.stderr.write(f"[GravityGuard EBDG] Receipt write warning: {err}\n")
        return None


def evaluate_ebdg_ui_gate(
    project_root: Path,
    conversation_id: str,
    session_retries: int = 0,
    cfg: Optional[Dict[str, Any]] = None,
    custom_modified_files: Optional[List[str]] = None
) -> Tuple[bool, Optional[str], Optional[Path]]:
    """
    Evaluates Phase 0 Evidence-Based Delivery Gate for UI modifications.
    Returns: (is_allowed, warning_message, verified_evidence_path)
    """
    cfg = cfg or {}
    ebdg_cfg = cfg.get("deliveryGate", {})
    if ebdg_cfg.get("enabled") is False:
        return True, None, None

    modified_files = custom_modified_files if custom_modified_files is not None else get_git_modified_files(project_root)
    ui_files = [f for f in modified_files if is_ui_file(f)]

    # If no UI files changed, gate immediately passes
    if not ui_files:
        return True, None, None

    # Candidate directories for visual evidence
    search_dirs: List[Path] = [
        project_root / ".gravityguard" / "evidence",
        project_root / "artifacts",
        project_root / "screenshots",
    ]

    # Include Antigravity session brain directory if accessible
    user_home = Path.home()
    if conversation_id and conversation_id != "default":
        search_dirs.extend([
            user_home / ".gemini" / "antigravity" / "brain" / conversation_id,
            user_home / ".gemini" / "antigravity" / "brain" / conversation_id / ".user_uploaded",
            project_root / "brain" / conversation_id,
        ])

    screenshots = find_recent_screenshots(search_dirs, max_age_seconds=600)

    if screenshots:
        verified_path = screenshots[0]
        write_delivery_receipt(
            project_root=project_root,
            conversation_id=conversation_id,
            status="VERIFIED",
            category="UI",
            evidence_details={
                "screenshot": str(verified_path),
                "modifiedUiFiles": ui_files,
                "verifiedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
        )
        return True, None, verified_path

    # Circuit breaker: Never lock the user/agent infinitely
    max_retries = ebdg_cfg.get("maxRetries", 2)
    if session_retries >= max_retries:
        write_delivery_receipt(
            project_root=project_root,
            conversation_id=conversation_id,
            status="UNVERIFIED_CIRCUIT_BREAKER",
            category="UI",
            evidence_details={
                "warning": "Delivery allowed after max retries exceeded without screenshot evidence",
                "modifiedUiFiles": ui_files
            }
        )
        return True, None, None

    # Warning triggered before completion
    short_file_list = ", ".join(ui_files[:4]) + (f" (+{len(ui_files) - 4} dosya)" if len(ui_files) > 4 else "")
    warning_msg = (
        f"Görsel Doğrulama Uyarısı (EBDG_UI_SCREENSHOT_PENDING): Arayüz dosyaları ({short_file_list}) güncellendi "
        f"ancak son 10 dakikaya ait bir ekran görüntüsü kanıtı (.png) bulunamadı. "
        f"Lütfen Playwright veya tarayıcı ekran yakalama aracıyla ekran görüntüsü alıp arayüzün doğruluğunu kontrol edin. "
        f"(Kalan deneme: {max(0, max_retries - session_retries)})"
    )

    write_delivery_receipt(
        project_root=project_root,
        conversation_id=conversation_id,
        status="PENDING_EVIDENCE",
        category="UI",
        evidence_details={
            "missingEvidence": "screenshot",
            "modifiedUiFiles": ui_files
        }
    )

    return False, warning_msg, None
