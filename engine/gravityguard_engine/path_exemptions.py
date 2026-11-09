"""Paths the architecture guards treat as vendor, cache or generated output."""
import re

_SCRATCH_PREFIX = re.compile(r"^.*?/\.gemini/antigravity/scratch/[^/]+")

_VENDOR_MARKERS = (
    "/node_modules/", "/venv/", "/.venv/", "/env/", "/.env/", "/dist/", "/build/",
    "/.git/", "/__pycache__/", "/runs/", "/scratch/", "/brain/",
    # Only the parts of ~/.gemini that are state or installed copies. Hand-written code under
    # ~/.gemini/config/tools and ~/.gemini/config/skills is ordinary source and stays governed.
    "/.gemini/antigravity/", "/.gemini/logs/", "/.gemini/tmp/", "/.gemini/cache/",
    "/.gemini/config/plugins/",
)


def is_vendor_or_cache_path(file_lower: str) -> bool:
    """file_lower: lowercase path with forward slashes."""
    stripped = _SCRATCH_PREFIX.sub("", file_lower)
    return any(marker in stripped for marker in _VENDOR_MARKERS)
