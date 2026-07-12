"""Stable, privacy-safe operator error records."""

from __future__ import annotations

from typing import Any


ERROR_REGISTRY: dict[str, dict[str, Any]] = {
    "SQLITE_BUSY": {
        "retryable": True,
        "problem": "The research ledger is temporarily busy.",
        "fix": "Retry after the bounded backoff; inspect concurrent writers if it persists.",
    },
    "CORRUPT_LEDGER": {
        "retryable": False,
        "problem": "Persisted research material failed an integrity check.",
        "fix": "Stop writes, restore a verified backup, and replay before resuming.",
    },
    "PINNED_VERSION_MISSING": {
        "retryable": False,
        "problem": "A version pinned by the run is unavailable.",
        "fix": "Restore the exact pinned corpus or engine version and replay.",
    },
    "RENDER_HASH_MISMATCH": {
        "retryable": False,
        "problem": "Rendered output does not match its committed hash.",
        "fix": "Reject the artifact and inspect the immutable event chain.",
    },
    "UNEXPECTED_INTERNAL": {
        "retryable": True,
        "problem": "An unexpected internal failure interrupted the operation.",
        "fix": "Retry once; then inspect privacy-safe logs using the run ID.",
    },
}


def error_record(
    error_code: str,
    *,
    run_id: str | None,
    stage: str,
    cause: str,
) -> dict[str, Any]:
    """Build the complete structured error envelope without exception contents."""
    definition = ERROR_REGISTRY[error_code]
    return {
        "error_code": error_code,
        "run_id": run_id,
        "stage": stage,
        "retryable": definition["retryable"],
        "problem": definition["problem"],
        "cause": cause,
        "fix": definition["fix"],
    }
