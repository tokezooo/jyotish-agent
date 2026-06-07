"""Download Swiss Ephemeris (.se1) files so calculations use Swiss precision.

PyJHora wheels ship no .se1 files, so pyswisseph falls back to its built-in Moshier
ephemeris. The fallback is sub-arcsecond accurate for modern dates, but installing
the Swiss files removes the precision gap AND enables star-based ayanamsas
(TRUE_CITRA / TRUE_REVATI / TRUE_PUSHYA), which crash under Moshier.

Files (cover years 1800-2399, our supported birth range): planets, moon, asteroids.
They are downloaded into the installed ``jhora/data/ephe`` directory so PyJHora picks
them up automatically. They are NOT committed (license + size); re-run this after a
fresh ``uv sync``.

Integrity: the source is pinned to a specific commit of the official Swiss Ephemeris
repository and each file is verified against a hardcoded SHA-256, so an upstream
change can never silently alter calculations.

Usage:
    python scripts/install_ephemeris.py            # install into jhora/data/ephe
    python scripts/install_ephemeris.py --target DIR

Swiss Ephemeris data is licensed separately (AGPL or commercial from astro.com);
this only downloads it locally and never redistributes it.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
import urllib.request
from pathlib import Path

# Pinned commit of github.com/aloistr/swisseph for reproducibility.
_COMMIT = "cae9ecd4b201544d85e411aced17660932514d43"
_BASE = f"https://github.com/aloistr/swisseph/raw/{_COMMIT}/ephe"

# filename -> (sha256, expected size). Verified against the pinned commit.
_FILES = {
    "sepl_18.se1": ("ca1393ceab3a44fbc895887cf789c68819ae6a1cbc9b22225872dbe4ccd99a66", 484061),
    "semo_18.se1": ("1ca07bd67c24374d77226180c20a4f9996cba013697894810518e7eb582ca4f7", 1304771),
    "seas_18.se1": ("a2cd8fc33807c78ca9a700c91c2e042258b12fc4796519e00781440b5ad8b2e2", 223004),
}


def _ephe_dir() -> Path:
    import jhora

    return Path(jhora.__file__).resolve().parent / "data" / "ephe"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install Swiss Ephemeris .se1 files.")
    parser.add_argument(
        "--target",
        type=Path,
        default=None,
        help="Destination dir. Default: the installed jhora/data/ephe (the only path "
        "PyJHora auto-discovers).",
    )
    args = parser.parse_args(argv)

    if args.target is not None:
        target = args.target
    else:
        try:
            target = _ephe_dir()
        except ImportError:
            print("PyJHora not importable; run `uv sync` first.", file=sys.stderr)
            return 1

    target.mkdir(parents=True, exist_ok=True)
    print(f"installing Swiss ephemeris into {target} (commit {_COMMIT[:12]})")
    for name, (sha, size) in _FILES.items():
        dest = target / name
        # Re-validate an already-present file by checksum, not just size.
        if dest.is_file() and dest.stat().st_size == size and _sha256(dest) == sha:
            print(f"  {name}: already present and verified")
            continue
        url = f"{_BASE}/{name}"
        tmp = Path(tempfile.mkstemp(dir=target, suffix=".part")[1])
        try:
            urllib.request.urlretrieve(url, tmp)
            actual = _sha256(tmp)
            if actual != sha:
                print(
                    f"  {name}: SHA-256 mismatch (expected {sha[:12]}…, got {actual[:12]}…)",
                    file=sys.stderr,
                )
                return 1
            tmp.replace(dest)  # atomic rename only after verification
            print(f"  {name}: downloaded and verified ({size} bytes)")
        except Exception as exc:  # noqa: BLE001
            print(f"  {name}: FAILED ({exc})", file=sys.stderr)
            return 1
        finally:
            tmp.unlink(missing_ok=True)

    print("done. Run `python scripts/check_pyjhora_data.py --strict` to verify.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
