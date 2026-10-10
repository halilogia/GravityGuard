"""
GravityGuard Engine Domain Test Suite.
"""
import os
import tempfile

# Hermetic: the developer's real ~/.gravityguard.json must never leak into a test.
os.environ["GRAVITYGUARD_USER_CONFIG"] = os.path.join(tempfile.gettempdir(), "gg_no_such_user_config.json")
