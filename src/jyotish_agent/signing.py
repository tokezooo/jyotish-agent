"""HMAC signing of computed facts — binds answer validation to real compute output.

Without this, ``/answers/validate`` would check an answer's citations against a
``facts`` block supplied by the *caller*, so an agent could forge both the citation
and the facts it is checked against and self-certify an invented reading. Instead,
``/charts/compute`` returns a ``facts_token`` = HMAC(secret, canonical(facts)), and
``/answers/validate`` recomputes the HMAC over the facts it was given and rejects any
mismatch. The agent cannot produce a valid token for facts the service didn't compute.

The secret comes from ``$JYOTISH_SIGNING_KEY`` if set; otherwise a random per-process
key is generated (fine for a single-process local MVP). Multi-process or
cross-restart deployments MUST set ``JYOTISH_SIGNING_KEY`` so tokens verify across
workers.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from copy import deepcopy
from collections import OrderedDict

_env_key = os.environ.get("JYOTISH_SIGNING_KEY", "")
_SIGNING_KEY: bytes = _env_key.encode("utf-8") if _env_key else secrets.token_bytes(32)


def _canonical(facts: dict) -> bytes:
    return json.dumps(facts, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def sign_facts(facts: dict) -> str:
    """Return an HMAC-SHA256 token over the canonical facts JSON."""
    return hmac.new(_SIGNING_KEY, _canonical(facts), hashlib.sha256).hexdigest()


def verify_facts(facts: dict, token: str) -> bool:
    """Constant-time check that ``token`` was produced by this service for ``facts``."""
    expected = sign_facts(facts)
    return hmac.compare_digest(expected, token)


# Server-side facts cache, keyed by token. The agent cannot faithfully echo the full
# 14 KB facts JSON back through an LLM context (it rounds/drops fields), so requiring
# that for /answers/validate caused every integrity check to fail and the agent to
# loop. Instead /charts/compute caches facts here under the token, and
# /answers/validate looks them up — the agent only passes the token. Process-local
# (single uvicorn worker for the local MVP); bounded LRU.
_FACTS_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_CACHE_MAX = 256


def cache_facts(facts: dict) -> str:
    """Sign + cache facts; return the token. Called by /charts/compute."""
    token = sign_facts(facts)
    _FACTS_CACHE[token] = facts
    _FACTS_CACHE.move_to_end(token)
    while len(_FACTS_CACHE) > _CACHE_MAX:
        _FACTS_CACHE.popitem(last=False)
    return token


def get_cached_facts(token: str) -> dict | None:
    """Return server-held facts for a token, or None if not cached (e.g. after a
    restart or eviction). Refreshes LRU recency."""
    facts = _FACTS_CACHE.get(token)
    if facts is not None:
        _FACTS_CACHE.move_to_end(token)
    return facts


# Domain artifacts bind more than a facts dictionary: replay must preserve the
# normalized anchor, effective profile/configuration, governed rule/source packs,
# and engine provenance.  Keep this cache separate from the legacy natal facts
# cache so the existing ``facts_token`` behavior and eviction budget do not change.
_DOMAIN_ARTIFACT_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_DOMAIN_ARTIFACT_CACHE_MAX = 256


def _domain_unsigned(payload: dict) -> dict:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"artifact_id", "artifact_sha256", "artifact_token"}
    }


def cache_domain_artifact(payload: dict) -> dict:
    """Seal and defensively cache a deterministic signed domain artifact."""
    unsigned = deepcopy(_domain_unsigned(payload))
    digest = hashlib.sha256(_canonical(unsigned)).hexdigest()
    token = hmac.new(_SIGNING_KEY, _canonical(unsigned), hashlib.sha256).hexdigest()
    artifact = {
        **unsigned,
        "artifact_id": f"jya_{digest[:24]}",
        "artifact_sha256": digest,
        "artifact_token": token,
    }
    _DOMAIN_ARTIFACT_CACHE[token] = deepcopy(artifact)
    _DOMAIN_ARTIFACT_CACHE.move_to_end(token)
    while len(_DOMAIN_ARTIFACT_CACHE) > _DOMAIN_ARTIFACT_CACHE_MAX:
        _DOMAIN_ARTIFACT_CACHE.popitem(last=False)
    return deepcopy(artifact)


def verify_domain_artifact(artifact: dict) -> bool:
    """Verify the artifact identity, digest, and HMAC in constant time."""
    try:
        unsigned = _domain_unsigned(artifact)
        digest = hashlib.sha256(_canonical(unsigned)).hexdigest()
        token = hmac.new(_SIGNING_KEY, _canonical(unsigned), hashlib.sha256).hexdigest()
        expected_id = f"jya_{digest[:24]}"
        return (
            hmac.compare_digest(str(artifact["artifact_sha256"]), digest)
            and hmac.compare_digest(str(artifact["artifact_token"]), token)
            and hmac.compare_digest(str(artifact["artifact_id"]), expected_id)
        )
    except (KeyError, TypeError, ValueError):
        return False


def get_cached_domain_artifact(token: str) -> dict | None:
    """Return a defensive copy of a server-held signed domain artifact."""
    artifact = _DOMAIN_ARTIFACT_CACHE.get(token)
    if artifact is None:
        return None
    _DOMAIN_ARTIFACT_CACHE.move_to_end(token)
    return deepcopy(artifact)
