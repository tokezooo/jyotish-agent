"""Jyotish Agent.

Deterministic Vedic-astrology calculation service (PyJHora facade) exposed to a
Pi agent harness as typed tools. Calculations live in Python; interpretation
lives in the agent and must cite only returned facts.

MVP posture: LOCAL-ONLY. PyJHora is AGPL-3.0 — see PLAN.md before distributing.
"""

__version__ = "0.1.0"
ENGINE = "PyJHora"
ENGINE_VERSION = "4.8.6"
