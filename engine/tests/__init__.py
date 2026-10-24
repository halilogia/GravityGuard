"""
GravityGuard Engine Domain Test Suite.
"""
import os
import tempfile
import atexit
import shutil

# Hermetic: the developer's real ~/.gravityguard.json must never leak into a test.
os.environ["GRAVITYGUARD_USER_CONFIG"] = os.path.join(tempfile.gettempdir(), "gg_no_such_user_config.json")
# Domain tests also run standalone, without test_gravity_validator's isolation.
_DOMAIN_AUDIT_DIR = tempfile.mkdtemp(prefix="gg_domain_audit_")
os.environ.setdefault("GRAVITYGUARD_AUDIT_DIR", _DOMAIN_AUDIT_DIR)
atexit.register(shutil.rmtree, _DOMAIN_AUDIT_DIR, ignore_errors=True)
