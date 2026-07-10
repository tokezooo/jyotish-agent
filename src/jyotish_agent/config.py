"""Calculation configuration and PyJHora global-state control.

Two PyJHora traps this module guards against:

1. **Wrong default ayanamsa.** PyJHora ships ``const._DEFAULT_AYANAMSA_MODE =
   "TRUE_PUSHYA"``. The product mandates **Lahiri** for parity (see PRD/PLAN), so
   the ayanamsa must be set explicitly before every computation rather than relying
   on the library default.

2. **Global mutation (NOT concurrency-safe).** ``drik.set_ayanamsa_mode`` mutates
   process-global state in two places: the Python global ``const._DEFAULT_AYANAMSA_MODE``
   and the pyswisseph C-level sidereal mode. ``rasi_chart`` reads that global at
   compute time, not from a per-call argument. So apply-then-compute is a single
   critical section: a second thread/request that calls ``apply_config`` between
   another caller's apply and compute will silently change its ayanamsa and produce
   a wrong chart with NO error. ``apply_config`` alone cannot fix this — the
   apply+compute pair must be serialized. ``ENGINE_LOCK`` is provided for the
   facade (Phase 2/3) to hold across the whole pair; true parallelism requires a
   process-per-request or subprocess pool. See PLAN.md Risks: "global config mutation".

Ephemeris precision is surfaced here for provenance: PyJHora wheels ship no ``.se1``
files, so pyswisseph falls back to its built-in Moshier ephemeris. A consequence:
**star-based ayanamsas** (TRUE_CITRA / TRUE_REVATI / TRUE_PUSHYA and friends — which
includes PyJHora's own default) need the Swiss ephemeris to locate a reference star
and crash under Moshier. Rather than maintain a denylist of every crashing mode,
``apply_config`` uses an **allowlist** of formula/precession-based modes empirically
verified to work under Moshier (``MOSHIER_SAFE_AYANAMSAS``) and rejects everything
else when no .se1 is installed. The product default LAHIRI is in the safe set.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# Product default ayanamsa. Must be a key in const.available_ayanamsa_modes.
DEFAULT_AYANAMSA = "LAHIRI"
# PyJHora's own (undesired) default, asserted in tests so a library change is caught.
PYJHORA_DEFAULT_AYANAMSA = "TRUE_PUSHYA"
# Formula/precession-based ayanamsas verified to compute under the Moshier fallback
# (no .se1 files). Allowlist, not denylist: anything outside this set is rejected on
# Moshier because we have not verified it is safe. Add a mode here only with a test.
MOSHIER_SAFE_AYANAMSAS = frozenset({"LAHIRI", "RAMAN", "KP", "FAGAN"})

# Supported divisional (varga) charts -> PyJHora divisional_chart_factor. D1 is always
# computed (it carries the ascendant); the rest are opt-in via CalculationConfig.charts.
# This is the common, high-signal subset of the classical 16 vargas, chosen for the
# MVP; the domain note is what an interpreter typically reads each chart for.
DIVISIONAL_FACTORS: dict[str, int] = {
    "D1": 1,    # Rasi — overall life, body, self
    "D2": 2,    # Hora — wealth
    "D3": 3,    # Drekkana — siblings, courage
    "D7": 7,    # Saptamsa — children, progeny
    "D9": 9,    # Navamsa — marriage, dharma, planetary strength
    "D10": 10,  # Dasamsa — career, profession, status
    "D12": 12,  # Dvadasamsa — parents
}
DEFAULT_CHARTS: tuple[str, ...] = ("D1", "D9")

# Opt-in fact modules (Milestone 3). Default OFF: always-on would ~2.5x the citation
# atoms, grow the ENGINE_LOCK hold (engine yoga scan measured at ~0.7s), and churn the
# default golden fixtures. The agent requests modules per question via config.modules.
KNOWN_MODULES: frozenset[str] = frozenset(
    {"shadbala", "ashtakavarga", "transits", "yogas_engine", "varshaphal"}
)
# Modules with a facade implementation. A known-but-unimplemented module is a 422
# (never a silent 200-with-nothing — the agent would loop on the missing facts).
# Grows one entry per Milestone-3 phase.
IMPLEMENTED_MODULES: frozenset[str] = frozenset({"shadbala"})

# Held by the facade across apply_config()+compute to serialize PyJHora global state.
# apply_config does NOT acquire it (callers compose apply+compute under one hold).
ENGINE_LOCK = threading.Lock()


class ConfigError(ValueError):
    """A calculation parameter (ayanamsa / node mode) was rejected. Subclasses
    ValueError for back-compat, but is distinct so callers (e.g. the API) can map
    *only* these to a 4xx and never confuse them with internal ValueErrors whose
    messages may carry user-derived data."""


@dataclass(frozen=True)
class CalculationConfig:
    """Explicit, serializable calculation settings.

    These values must appear in every chart response's ``calculation_config`` so an
    answer can never hide which ayanamsa / node mode produced a placement.
    """

    ayanamsa: str = DEFAULT_AYANAMSA
    rahu_ketu: str = "true_nodes"  # vs "mean_nodes"; applied via const.set_node_mode
    # Divisional charts to compute. D1 is always included (carries the ascendant).
    charts: tuple[str, ...] = DEFAULT_CHARTS
    # Rahu/Ketu drishti: "standard" = 7th only; "jupiter_like" = 5th/7th/9th (some
    # schools). Affects only the nodes' aspects.
    node_aspects: str = "standard"
    # Opt-in fact modules (see KNOWN_MODULES). Empty by default.
    modules: tuple[str, ...] = ()

    def resolved_modules(self) -> frozenset[str]:
        """Validated, deduplicated module set. Raises ConfigError on unknown names and
        on known-but-not-yet-implemented modules (silent absence would mislead)."""
        requested = {m.lower() for m in self.modules}
        unknown = requested - KNOWN_MODULES
        if unknown:
            raise ConfigError(
                f"unknown modules {sorted(unknown)}; supported: {sorted(IMPLEMENTED_MODULES)}"
            )
        pending = requested - IMPLEMENTED_MODULES
        if pending:
            raise ConfigError(
                f"modules {sorted(pending)} are not implemented yet; "
                f"available: {sorted(IMPLEMENTED_MODULES)}"
            )
        return frozenset(requested)

    def resolved_charts(self) -> dict[str, int]:
        """Validated {chart_name: factor}, always including D1, order-stable.
        Raises ConfigError on an unknown chart."""
        names = ["D1", *[c.upper() for c in self.charts]]
        resolved: dict[str, int] = {}
        for name in names:
            if name not in DIVISIONAL_FACTORS:
                raise ConfigError(
                    f"unknown chart {name!r}; supported: {sorted(DIVISIONAL_FACTORS)}"
                )
            resolved[name] = DIVISIONAL_FACTORS[name]
        return resolved


def apply_config(config: CalculationConfig | None = None) -> CalculationConfig:
    """Apply config to PyJHora global state. Call immediately before each computation.

    NOT concurrency-safe on its own — see module docstring; hold ``ENGINE_LOCK``
    across apply_config()+compute. Returns the config applied for provenance echo.
    """
    config = config or CalculationConfig()

    from jhora import const
    from jhora.panchanga import drik

    mode = config.ayanamsa.upper()
    available = {m.upper() for m in const.available_ayanamsa_modes}
    if mode not in available:
        raise ConfigError(
            f"unknown ayanamsa {config.ayanamsa!r}; available: {sorted(available)}"
        )
    if ephemeris_mode() == "moshier" and mode not in MOSHIER_SAFE_AYANAMSAS:
        raise ConfigError(
            f"ayanamsa {mode!r} is not in the Moshier-verified safe set "
            f"{sorted(MOSHIER_SAFE_AYANAMSAS)}; no .se1 files are installed "
            f"(Moshier fallback active). Star-based modes crash and others are "
            f"unverified. Use a safe mode (e.g. LAHIRI) or install ephemeris files."
        )

    if config.rahu_ketu not in ("true_nodes", "mean_nodes"):
        raise ConfigError(
            f"unknown rahu_ketu {config.rahu_ketu!r}; expected "
            f"'true_nodes' or 'mean_nodes'"
        )

    if config.node_aspects not in ("standard", "jupiter_like"):
        raise ConfigError(
            f"unknown node_aspects {config.node_aspects!r}; expected "
            f"'standard' or 'jupiter_like'"
        )

    drik.set_ayanamsa_mode(mode)
    # Wire node mode so provenance never claims a setting that wasn't applied.
    const.set_node_mode(config.rahu_ketu == "true_nodes")
    return config


@lru_cache(maxsize=1)
def ephemeris_mode() -> str:
    """Return 'swiss' if .se1 files are installed, else 'moshier' (fallback).

    Cached: ephemeris install layout cannot change within a process. Tests that
    simulate the other mode must monkeypatch this function, not the filesystem.
    """
    import jhora

    ephe = Path(jhora.__file__).resolve().parent / "data" / "ephe"
    has_se1 = ephe.is_dir() and any(ephe.glob("*.se1"))
    return "swiss" if has_se1 else "moshier"
