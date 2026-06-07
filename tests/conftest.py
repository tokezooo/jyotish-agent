"""Test isolation for PyJHora's process-global ayanamsa state.

PyJHora keeps the active ayanamsa in module-level globals that ``set_ayanamsa_mode``
mutates and never auto-restores. Without isolation, one test's ayanamsa leaks into
the next, making the suite order-dependent (e.g. an assertion that PyJHora's default
is TRUE_PUSHYA only holds if no earlier test set LAHIRI first). The autouse fixture
below snapshots and restores that global around every test so order never matters.
"""

from __future__ import annotations

import pytest

# Capture PyJHora's pristine default ONCE at collection time, before any test calls
# apply_config / set_ayanamsa_mode. Tests assert against this instead of a hardcoded
# literal, so a future library default change surfaces in one place.
try:
    from jhora import const as _const

    PYJHORA_PRISTINE_AYANAMSA = _const._DEFAULT_AYANAMSA_MODE
except ImportError:  # PyJHora not installed; jhora-dependent tests importorskip out.
    PYJHORA_PRISTINE_AYANAMSA = None


@pytest.fixture(autouse=True)
def _restore_pyjhora_ayanamsa():
    """Snapshot the global ayanamsa before each test and restore it after, so no test
    leaks calculation state into another."""
    try:
        from jhora import const
        from jhora.panchanga import drik
    except ImportError:
        yield
        return

    saved_ayanamsa = const._DEFAULT_AYANAMSA_MODE
    saved_true_nodes = const._use_true_nodes_for_rahu_ketu
    try:
        yield
    finally:
        drik.set_ayanamsa_mode(saved_ayanamsa)
        const.set_node_mode(saved_true_nodes)
