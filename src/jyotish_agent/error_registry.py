"""Stable, privacy-safe operator error records."""

from __future__ import annotations

from typing import Any


ERROR_REGISTRY: dict[str, dict[str, Any]] = {
    "EVENT_TIME_REQUIRED": {
        "retryable": False,
        "problem": "An explicit timezone-aware event time is required.",
        "cause": "The event anchor is missing a time, timezone, or both.",
        "fix": "Confirm an explicit event instant and timezone.",
        "next_action": "confirm_anchor",
    },
    "EVENT_PLACE_REQUIRED": {
        "retryable": False,
        "problem": "An event place is required.",
        "cause": "The request has no validated event latitude and longitude.",
        "fix": "Provide the event place before calculating the chart.",
        "next_action": "provide_event_place",
    },
    "ANCHOR_MISMATCH": {
        "retryable": False,
        "problem": "The follow-up does not match the stored event anchor.",
        "cause": "The supplied anchor identity differs from the active question anchor.",
        "fix": "Create a new anchor for this question.",
        "next_action": "create_new_anchor",
    },
    "SEARCH_RANGE_TOO_LARGE": {
        "retryable": False,
        "problem": "The requested search range exceeds the supported maximum.",
        "cause": "The bounded search cannot evaluate this many calendar candidates.",
        "fix": "Narrow the requested search range to a supported value.",
        "next_action": "narrow_search_range",
    },
    "RULE_PROFILE_UNSUPPORTED": {
        "retryable": False,
        "problem": "The requested rule profile is unsupported.",
        "cause": "No exact versioned profile matches the supplied identifier.",
        "fix": "Select one of the explicitly supported rule profiles.",
        "next_action": "select_supported_rule_profile",
    },
    "ENGINE_CROSSCHECK_FAILED": {
        "retryable": True,
        "problem": "A calculation invariant or independent cross-check failed.",
        "cause": "The affected facts could not be verified consistently.",
        "fix": "Retry once, then inspect private diagnostics using the request ID.",
        "next_action": "retry_calculation",
    },
    "BIRTH_TIME_RANGE_REQUIRED": {
        "retryable": False,
        "problem": "A bounded approximate birth-time range is required.",
        "cause": "The range is missing, reversed, or exceeds 120 minutes.",
        "fix": "Provide earliest and latest times no more than 120 minutes apart.",
        "next_action": "provide_birth_range",
    },
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
    "UNSUPPORTED_CONTRACT_VERSION": {
        "retryable": False,
        "problem": "The requested answer contract version is unsupported.",
        "cause": "This service owns and supports AnswerContract version 2.0 only.",
        "fix": "Omit contract_version or submit contract_version '2.0'.",
    },
    "INPUT_INVALID": {
        "retryable": False,
        "problem": "The run operation payload is invalid or incomplete.",
        "cause": "One or more required operation fields failed schema validation.",
        "fix": "Correct the payload for this run stage and resubmit it.",
    },
    "UNSUPPORTED_SCHEMA_VERSION": {
        "retryable": False,
        "problem": "The requested AnswerContract major version is unsupported.",
        "cause": "This endpoint accepts AnswerContract major version 2 only.",
        "fix": "Submit schema_version '2.0'.",
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
    request_id: str | None = None,
    mode: str | None = None,
    invalid_fields: list[str] | None = None,
    supported_values: list[str] | None = None,
    next_action: str | None = None,
) -> dict[str, Any]:
    """Build an actionable envelope from controlled registry text only."""
    definition = ERROR_REGISTRY[error_code]
    record = {
        "error_code": error_code,
        "run_id": run_id,
        "stage": stage,
        "retryable": definition["retryable"],
        "problem": definition["problem"],
        "cause": definition["cause"],
        "fix": definition["fix"],
    }
    optional = {
        "request_id": request_id,
        "mode": mode,
        "invalid_fields": invalid_fields,
        "supported_values": supported_values,
        "next_action": next_action or definition.get("next_action"),
    }
    record.update({key: value for key, value in optional.items() if value is not None})
    return record
