#!/usr/bin/env python3
"""
Unit tests for GravityGuard StateLock (Cross-platform OS-level File Locking).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from gravityguard_engine.state_lock import StateLock


class TestStateLock(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="gg_lock_test_")
        self.lock_path = Path(self.temp_dir) / "test.lock"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_lock_acquire_and_release(self):
        lock = StateLock(self.lock_path, timeout=1.0)
        self.assertTrue(lock.acquire(), "First acquire should succeed")
        lock.release()

    def test_lock_context_manager(self):
        with StateLock(self.lock_path, timeout=1.0) as lock:
            self.assertIsNotNone(lock._fd)
        self.assertIsNone(lock._fd)

    def test_lock_contention_and_timeout(self):
        lock1 = StateLock(self.lock_path, timeout=1.0)
        self.assertTrue(lock1.acquire())

        # Second lock with very short timeout should fail
        lock2 = StateLock(self.lock_path, timeout=0.08, poll_interval=0.01)
        self.assertFalse(lock2.acquire(), "Second lock should time out while lock1 is held")

        lock1.release()

        # Now lock2 should succeed
        self.assertTrue(lock2.acquire(), "Lock2 should succeed after lock1 is released")
        lock2.release()

    def test_kernel_lock_auto_released_on_process_exit(self):
        """Child process acquires lock and terminates; parent can acquire immediately without stale lock."""
        worker_code = """
import sys, time
from pathlib import Path
_ENGINE_DIR = sys.argv[1]
sys.path.insert(0, _ENGINE_DIR)
from gravityguard_engine.state_lock import StateLock

lock = StateLock(Path(sys.argv[2]), timeout=2.0)
if lock.acquire():
    print("READY", flush=True)
    time.sleep(0.4)
"""
        script_p = Path(self.temp_dir) / "lock_holder.py"
        script_p.write_text(worker_code, encoding="utf-8")

        p = subprocess.Popen(
            [sys.executable, str(script_p), str(Path(_ENGINE_DIR).resolve()), str(self.lock_path)],
            stdout=subprocess.PIPE,
            text=True
        )
        ready_line = p.stdout.readline().strip()
        self.assertEqual(ready_line, "READY")

        # Parent attempts to acquire with very short timeout while child is alive -> should fail
        contention_lock = StateLock(self.lock_path, timeout=0.05, poll_interval=0.01)
        self.assertFalse(contention_lock.acquire(), "Parent must not acquire lock while child process holds it")

        # Wait for child to terminate
        p.wait()

        # Now parent must acquire immediately (kernel released byte lock on child termination)
        after_exit_lock = StateLock(self.lock_path, timeout=1.0)
        self.assertTrue(after_exit_lock.acquire(), "Parent must acquire lock immediately after child terminates")
        after_exit_lock.release()


if __name__ == "__main__":
    unittest.main()
