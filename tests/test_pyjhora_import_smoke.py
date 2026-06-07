"""Headless import smoke test.

The calculation service must import PyJHora calculation modules WITHOUT pulling in
PyQt UI modules. If a server process imports ``jhora.ui.*`` it can break headless
installs and add a heavy GUI dependency to a backend.
"""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("jhora", reason="PyJHora not installed; run `uv sync`")


def test_calculation_modules_import_headless():
    # The modules the facade will actually call.
    import jhora.horoscope.chart.charts  # noqa: F401
    import jhora.horoscope.dhasa.graha.vimsottari  # noqa: F401
    import jhora.panchanga  # noqa: F401


def test_no_pyqt_ui_module_loaded_by_calculation_imports():
    # Importing calculation modules must not transitively load the UI layer.
    leaked = [name for name in sys.modules if name.startswith("jhora.ui")]
    assert not leaked, f"UI modules leaked into headless import: {leaked}"


def test_engine_version_matches_installed_pyjhora():
    # Provenance (ENGINE_VERSION) is hand-written; if it drifts from the installed
    # wheel, chart responses would report a false engine version. Catch the drift.
    from importlib.metadata import version

    from jyotish_agent import ENGINE_VERSION

    assert ENGINE_VERSION == version("PyJHora")
