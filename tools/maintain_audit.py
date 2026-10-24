"""Archive and clear active audit records without resetting sequence or debt."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from gravityguard_engine.audit import _resolve_log_dir
from gravityguard_engine.audit_maintenance import maintain_audit

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--archive-root", type=Path)
    args = parser.parse_args()
    print(json.dumps(maintain_audit(args.log_dir or Path(_resolve_log_dir()), args.archive_root), ensure_ascii=False))
