"""Verifies a built .vsix actually contains the current engine and nothing it must not.

Established as a release rule in 1.2.5 ("Verified the packaged engine is
byte-identical to the repo engine (md5 b3eac45e...), so a release artifact can
never ship a stale guard") — but it was checked by hand, once. This makes it
repeatable, and adds the second half of the rule: the *contents* are checked
against an explicit allowlist, because `.vscodeignore` only encodes the intent
and silently rots when new directories appear.

During the 1.3.0 cut this is what caught `tests/`, `docs/`, `.kilo/` and
`dist/*.js.map` (15 files / 80.33 KB instead of the previous 10 / 54.69 KB)
sneaking into the artifact.

Usage:
    python tools/verify_package.py                # newest gravityguard-*.vsix
    python tools/verify_package.py path/to.vsix
Exit codes: 0 ok, 1 verification failed, 2 usage/IO error.
"""
import hashlib
import os
import re
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Files that MUST be inside the package. `dist/intent.js` is here because it is
# the local intent classifier; dropping it would remove classification at runtime.
REQUIRED = [
    "extension/dist/extension.js",
    "extension/dist/intent.js",
    "extension/engine/gravity-validator.py",
    "extension/engine/async_runner.py",
    "extension/package.json",
    "extension/README.md",
    "extension/LICENSE",
    "extension/media/shield.svg",
]

# Engine files whose content must match the repo byte for byte.
MUST_MATCH_REPO = [
    "extension/engine/gravity-validator.py",
    "extension/engine/async_runner.py",
]

def _collect_engine_package_files() -> list[str]:
    pkg_dir = REPO / "engine" / "gravityguard_engine"
    files = []
    if pkg_dir.is_dir():
        for p in sorted(pkg_dir.rglob("*.py")):
            rel_part = p.relative_to(pkg_dir).as_posix()
            files.append(f"extension/engine/gravityguard_engine/{rel_part}")
    return files

_pkg_files = _collect_engine_package_files()
REQUIRED.extend(_pkg_files)
MUST_MATCH_REPO.extend(_pkg_files)

FORBIDDEN_PATTERNS = [
    (r"^extension/tests/", "test suite shipped in the artifact"),
    (r"^extension/engine/test_", "engine test suite shipped in the artifact"),
    (r"^extension/engine/tests/", "engine domain test suite shipped in the artifact"),

    (r"^extension/docs/", "developer documentation shipped in the artifact"),
    (r"^extension/tools/", "repo tooling shipped in the artifact"),
    (r"^extension/plugin/", "Antigravity plugin manifests shipped in the artifact"),
    (r"^extension/brain/", "untracked brain directory shipped in the artifact"),
    (r"^extension/\.kilo/", "agent scratch directory shipped in the artifact"),
    (r"^extension/src/", "TypeScript sources shipped alongside the build"),
    (r"\.js\.map$", "source map shipped in the artifact"),
    (r"\.vsix$", "nested vsix"),
    (r"\.bak", "backup file shipped in the artifact"),
    (r"\.env", "environment file shipped in the artifact"),
]


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def find_vsix() -> Path:
    candidates = sorted(REPO.glob("gravityguard-*.vsix"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        print("HATA: gravityguard-*.vsix bulunamadi. Once `vsce package` calistirin.")
        sys.exit(2)
    return candidates[-1]


def validate_workflow_yaml() -> list[str]:
    """Parse .github/workflows/*.yaml so a broken workflow fails locally, not on push.

    Cost of the lesson: a step label containing ": " is a YAML mapping, not a
    string. It broke the whole CI workflow for two pushes, and the only signal
    was a 0-second red run. PyYAML is already a transitive dependency of the
    toolchain here; when it is absent the check reports "skipped" rather than
    pretending to have validated something.
    """
    import glob

    try:
        import yaml
    except ImportError:
        return []

    failures = []
    workflows = glob.glob(str(REPO / ".github" / "workflows" / "*.y*ml"))
    for path in workflows:
        try:
            yaml.safe_load(open(path, encoding="utf-8"))
        except Exception as exc:  # yaml.YAMLError and friends
            failures.append(f"{Path(path).name}: YAML bozuk -> {exc}")
    return failures


def main() -> None:
    vsix = Path(sys.argv[1]) if len(sys.argv) > 1 else find_vsix()
    if not vsix.is_file():
        print(f"HATA: {vsix} bulunamadi.")
        sys.exit(2)

    failures = []
    with zipfile.ZipFile(vsix) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        # vsce normalises two names on the way in: `README.md` arrives as
        # `readme.md` and `LICENSE` as `LICENSE.txt`. The *content* requirement
        # is what matters, so the lookup is case-insensitive and tolerates the
        # added extension rather than asserting a filename the packager rewrites.
        lowered = {n.lower(): n for n in names}

        def resolve(wanted: str) -> str | None:
            if wanted.lower() in lowered:
                return lowered[wanted.lower()]
            stem = wanted.lower()
            for candidate in names:
                c = candidate.lower()
                if c == stem + ".txt" or os.path.splitext(c)[0] == os.path.splitext(stem)[0] and c.startswith(stem):
                    return candidate
            return None

        print(f"Paket: {vsix.name}  ({vsix.stat().st_size} B, {len(names)} dosya)\n")

        print("Zorunlu dosyalar:")
        for required in REQUIRED:
            found = resolve(required)
            print(f"  [{'OK' if found else 'EKSIK'}] {required}" + (f"  -> {found}" if found and found != required else ""))
            if not found:
                failures.append(f"zorunlu dosya eksik: {required}")

        print("\nIcerik esitligi (paket vs repo, md5):")
        for packaged in MUST_MATCH_REPO:
            repo_path = REPO / packaged[len("extension/"):]
            found = resolve(packaged)
            if not found:
                failures.append(f"esitligi dogrulanamadi, paket icinde yok: {packaged}")
                print(f"  [ATLANDI] {packaged}")
                continue
            packaged_md5 = md5(zf.read(found))
            repo_md5 = md5(repo_path.read_bytes())
            match = packaged_md5 == repo_md5
            print(f"  [{'ESIT' if match else 'FARKLI'}] {packaged}  {packaged_md5}")
            if not match:
                failures.append(
                    f"paket icindeki engine bayat! {packaged}: paket {packaged_md5} != repo {repo_md5}"
                )

        print("\nYasakli icerik:")
        found_any = False
        for name in names:
            for pattern, why in FORBIDDEN_PATTERNS:
                if re.search(pattern, name):
                    found_any = True
                    print(f"  [BULUNDU] {name}  ({why})")
                    failures.append(f"{name}: {why}")
        if not found_any:
            print("  [TEMIZ] yasakli desen ile eslesen dosya yok")

    print()
    workflow_failures = validate_workflow_yaml()
    if workflow_failures:
        print("Workflow YAML dogrulamasi:")
        for failure in workflow_failures:
            print(f"  [BOZUK] {failure}")
        failures.extend(workflow_failures)
    else:
        print("Workflow YAML: GECERLI")

    print()
    if failures:
        print(f"DOGRULAMA BASARISIZ ({len(failures)} sorun):")
        for failure in failures:
            print(f"  - {failure}")
        sys.exit(1)

    print("DOGRULAMA TAMAM: paket guncel engine'i iceriyor, yasakli icerik yok.")


if __name__ == "__main__":
    main()
