"""Small filesystem and logging primitives for private runtime artifacts."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from pathlib import Path


def redact_log_value(_value: object) -> str:
    """Return a constant marker for values that may contain user data."""
    return "[REDACTED]"


def persist_private_artifact(
    data_root: Path, *, run_id: str, name: str, data: bytes
) -> Path:
    if not re.fullmatch(r"rr_[A-Za-z0-9._-]+", run_id):
        raise ValueError("invalid public run ID")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name) or name in {".", ".."}:
        raise ValueError("invalid artifact name")
    root = Path(data_root) / "artifacts"
    target = root / run_id / name
    atomic_write_private(target, data, root=root)
    return target


def prune_private_artifacts(
    data_root: Path, *, retention_seconds: int, now: float | None = None
) -> int:
    if isinstance(retention_seconds, bool) or retention_seconds < 0:
        raise ValueError("retention_seconds must be non-negative")
    root = Path(data_root) / "artifacts"
    if not root.exists():
        return 0
    cutoff = (time.time() if now is None else now) - retention_seconds
    removed = 0
    for child in root.iterdir():
        if child.is_symlink():
            child.unlink()
            removed += 1
        elif child.is_dir() and child.stat().st_mtime <= cutoff:
            delete_private_tree(child)
            removed += 1
    return removed


def _assert_private_path(path: Path, root: Path) -> None:
    if root.is_symlink():
        raise ValueError("artifact private root is a symlink")
    root_resolved = root.resolve()
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError as exc:
        raise ValueError("artifact path escapes private root") from exc
    if ".." in relative.parts:
        raise ValueError("artifact path escapes private root")
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("artifact path contains a symlink")
    try:
        path.resolve(strict=False).relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("artifact path escapes private root") from exc


def atomic_write_private(path: Path, data: bytes, *, root: Path | None = None) -> None:
    """Atomically replace a private file without following directory symlinks."""
    path = Path(path)
    private_root = Path(root) if root is not None else path.parent
    _assert_private_path(path, private_root)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor, raw_temp = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp = Path(raw_temp)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temp.unlink(missing_ok=True)
        raise


def delete_private_tree(root: Path) -> int:
    """Delete a retention root without following symlinks; return entries removed."""
    root = Path(root)
    if root.is_symlink():
        root.unlink()
        return 1
    if not root.exists():
        return 0
    count = sum(1 for _ in root.iterdir())
    shutil.rmtree(root)
    return count
