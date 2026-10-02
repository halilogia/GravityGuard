"""
GravityGuard State Lock — Cross-platform OS-level file locking abstraction.
Provides exclusive mutual exclusion for concurrent hook processes across Windows and POSIX.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Optional

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import msvcrt
else:
    import fcntl


class StateLockTimeout(TimeoutError):
    """Raised when an exclusive state lock cannot be acquired within the timeout window."""
    pass


class StateLock:
    """
    Cross-platform exclusive lock on a lockfile descriptor.
    Uses msvcrt.locking on Windows and fcntl.flock on POSIX.
    Locks are kernel-managed: if a process crashes or terminates unexpectedly,
    the OS automatically releases the lock immediately, preventing stale lock file hangs.
    """

    def __init__(self, lock_path: Path, timeout: float = 5.0, poll_interval: float = 0.005):
        self.lock_path = lock_path
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._fd: Optional[int] = None

    def acquire(self) -> bool:
        """
        Attempts to acquire the exclusive lock within the timeout window.
        Returns True if acquired, False on timeout.
        Uses time.monotonic() to be immune against system clock shifts.
        """
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        start = time.monotonic()
        while True:
            if self._fd is None:
                try:
                    self._fd = os.open(str(self.lock_path), os.O_RDWR | os.O_CREAT, 0o666)
                except (OSError, IOError) as err:
                    _open_err = err

            if self._fd is not None:
                try:
                    if IS_WINDOWS:
                        # Ensure file has at least 1 byte so msvcrt can lock byte 0
                        try:
                            if os.lseek(self._fd, 0, os.SEEK_END) == 0:
                                os.write(self._fd, b"L")
                        except (OSError, IOError) as err:
                            _write_err = err
                        os.lseek(self._fd, 0, os.SEEK_SET)
                        msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return True
                except (OSError, IOError) as err:
                    _lock_err = err

            if time.monotonic() - start >= self.timeout:
                break

            time.sleep(self.poll_interval)

        if self._fd is not None:
            try:
                os.close(self._fd)
            except (OSError, IOError) as err:
                _close_err = err
            self._fd = None
        return False

    def release(self) -> None:
        """
        Releases the lock and closes the file descriptor.
        """
        if self._fd is not None:
            try:
                if IS_WINDOWS:
                    os.lseek(self._fd, 0, os.SEEK_SET)
                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
            except (OSError, IOError) as err:
                _unlock_err = err
            finally:
                try:
                    os.close(self._fd)
                except (OSError, IOError) as err:
                    _close_err = err
                self._fd = None

    def __enter__(self) -> StateLock:
        if not self.acquire():
            raise StateLockTimeout(
                f"Could not acquire state lock within {self.timeout}s: {self.lock_path}"
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()

