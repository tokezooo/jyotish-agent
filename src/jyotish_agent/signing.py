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
