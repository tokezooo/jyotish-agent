"""Stable, privacy-safe operator error records."""

from __future__ import annotations

from typing import Any


ERROR_REGISTRY: dict[str, dict[str, Any]] = {
    "RUN_NOT_FOUND": {
        "retryable": False,
        "problem": "The requested research run does not exist.",
        "cause": "No authoritative ledger matches the supplied run ID.",
        "fix": "Check the rr_ run ID and retry.",
    },
    "OPERATION_CONFLICT": {
        "retryable": False,
        "problem": "The requested run transition conflicts with authoritative state.",
        "cause": "The operation ID, revision, or current run stage is stale or incompatible.",
        "fix": "Inspect the run, use its current revision, and retry with a fresh operation ID.",
    },
    "UNSUPPORTED_TIMEZONE": {
        "retryable": False,
        "problem": "The timezone mode is unsupported.",
        "cause": "The request does not identify a supported deterministic timezone mode.",
        "fix": "Use a supported IANA or fixed-offset timezone specification.",
    },
    "SQLITE_BUSY": {
        "retryable": True,
        "problem": "The research ledger is temporarily busy.",
        "cause": "The bounded SQLite lock wait expired.",
        "fix": "Retry after the bounded backoff; inspect concurrent writers if it persists.",
    },
    "CORPUS_INTEGRITY_ERROR": {
        "retryable": False,
        "problem": "The governed corpus failed an integrity check.",
        "cause": "Stored fragment bytes or search-index membership differ from their committed checksums.",
        "fix": "Stop retrieval, restore a verified corpus backup, and validate the index before resuming.",
    },
    "MISSING_PINNED_VERSION": {
        "retryable": False,
        "problem": "A version pinned by the run is unavailable.",
        "cause": "At least one required immutable runtime or corpus version is absent.",
        "fix": "Restore the exact pinned corpus or engine version and replay.",
    },
    "MEMO_HASH_MISMATCH": {
        "retryable": False,
        "problem": "Rendered output does not match its committed hash.",
        "cause": "Re-rendered memo bytes differ from the immutable answer artifact.",
        "fix": "Reject the artifact and inspect the immutable event chain.",
    },
    "UNEXPECTED_INTERNAL": {
        "retryable": True,
        "problem": "An unexpected internal failure interrupted the operation.",
        "cause": "The service encountered a non-public internal error.",
        "fix": "Retry once; then inspect privacy-safe logs using the run ID.",
    },
}


def error_record(
    error_code: str,
    *,
    run_id: str | None,
    stage: str,
) -> dict[str, Any]:
    """Build an actionable envelope from controlled registry text only."""
    definition = ERROR_REGISTRY[error_code]
    return {
        "error_code": error_code,
        "run_id": run_id,
        "stage": stage,
        "retryable": definition["retryable"],
        "problem": definition["problem"],
        "cause": definition["cause"],
        "fix": definition["fix"],
    }
