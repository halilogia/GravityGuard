"""Private, locked audit maintenance with a durable sequence checkpoint."""
import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from .audit import _rebuild_live_state_from_permanent_audit, _get_journal_last_seq
from .state_lock import StateLock, StateLockTimeout


def _atomic_json(path: Path, value, jsonl=False):
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def maintain_audit(log_dir: Path, archive_root: Path = None) -> dict:
    log_dir = Path(log_dir).resolve()
    archive_root = Path(archive_root or Path.home() / ".gravityguard" / "maintenance").resolve()
    if any((parent / ".git").exists() for parent in (archive_root, *archive_root.parents)):
        raise ValueError("Private audit backups must be outside Git repositories")
    journal = log_dir / "gravityguard_permanent_audit.jsonl"
    if not journal.is_file():
        raise FileNotFoundError("Audit journal not found")
    lock = StateLock(log_dir / ".audit.lock", timeout=10)
    if not lock.acquire():
        raise StateLockTimeout("Audit maintenance could not acquire the writer lock")
    try:
        # Reject corruption instead of silently archiving an incomplete history.
        records = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines() if line.strip()]
        if any(not isinstance(record, dict) for record in records):
            raise ValueError("Invalid journal record")
        state = _rebuild_live_state_from_permanent_audit(str(journal))
        high_water = _get_journal_last_seq(str(journal))
        if state.get("lastAuditSeq", 0) != high_water:
            raise ValueError("Journal sequence mismatch")
        run_id = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
        archive = archive_root / run_id
        archive.mkdir(parents=True, exist_ok=False)
        files = {}
        for name in (journal.name, "srp_guardian_live.json", "gravityguard_session_deltas.json"):
            source = log_dir / name
            if source.is_file():
                dest = archive / name
                shutil.copy2(source, dest)
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
                if hashlib.sha256(dest.read_bytes()).hexdigest() != digest:
                    raise OSError("Audit backup verification failed")
                files[name] = {"sha256": digest, "bytes": dest.stat().st_size}
        checkpoint = {"recordType": "audit_checkpoint", "eventId": run_id, "auditSeq": high_water,
            "timestamp": datetime.now().astimezone().isoformat(), "status": "MAINTENANCE",
            "ruleId": "MAINTENANCE_CHECKPOINT", "snapshot": {
                "effectiveness": state.get("effectiveness", {}),
                "activeViolations": state.get("activeViolations", {})}}
        manifest = {"maintenanceId": run_id, "highWaterSeq": high_water,
            "archivedRecords": len(records), "files": files}
        _atomic_json(archive / "manifest.json", manifest)
        # The checkpoint is the durable commit point. A crash before live-state
        # replacement is recovered by audit.log_event via maintenanceId.
        _atomic_json(journal, checkpoint, jsonl=True)
        state["events"] = []
        state["maintenanceId"] = run_id
        state["lastAuditSeq"] = high_water
        _atomic_json(log_dir / "srp_guardian_live.json", state)
        return {**manifest, "archive": str(archive), "activeEventCount": 0}
    finally:
        lock.release()
