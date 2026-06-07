"""Index-convention guards for names.py.

The Phase 2 review found three off-by-one mislabels: nakshatra, yoga, and karana are
1-based in PyJHora but were indexed 0-based. These tests pin the 1-based contract and
the table boundaries so the bug class cannot silently return."""

from __future__ import annotations

from jyotish_agent import names


def test_table_counts():
    assert len(names.PLANETS) == 9
    assert len(names.SIGNS) == 12
    assert len(names.NAKSHATRAS) == 27
    assert len(names.WEEKDAYS) == 7
    assert len(names.TITHIS) == 30
    assert len(names.YOGAS) == 27
    assert len(names.KARANAS_60) == 60


def test_nakshatra_1based():
    assert names.nakshatra_name(1) == "Ashwini"
    assert names.nakshatra_name(24) == "Shatabhisha"  # the value in the golden fixture
    assert names.nakshatra_name(27) == "Revati"
    assert names.nakshatra_name(0) is None
    assert names.nakshatra_name(28) is None


def test_yoga_1based():
    assert names.yoga_name(1) == "Vishkambha"
    assert names.yoga_name(16) == "Siddhi"  # golden-fixture value
    assert names.yoga_name(27) == "Vaidhriti"
    assert names.yoga_name(0) is None
    assert names.yoga_name(28) is None


def test_karana_1based_60():
    assert names.karana_name(1) == "Kimstughna"
    assert names.karana_name(2) == "Bava"
    assert names.karana_name(9) == "Bava"  # golden-fixture value (2nd movable cycle)
    assert names.karana_name(58) == "Shakuni"
    assert names.karana_name(59) == "Chatushpada"
    assert names.karana_name(60) == "Naga"
    assert names.karana_name(0) is None
    assert names.karana_name(61) is None


def test_tithi_1based():
    assert names.tithi_name(1) == "Shukla Pratipada"
    assert names.tithi_name(5) == "Shukla Panchami"
    assert names.tithi_name(15) == "Purnima"
    assert names.tithi_name(16) == "Krishna Pratipada"
    assert names.tithi_name(30) == "Amavasya"
    assert names.tithi_name(0) is None
    assert names.tithi_name(31) is None


def test_weekday_0based():
    assert names.weekday_name(0) == "Sunday"
    assert names.weekday_name(1) == "Monday"
    assert names.weekday_name(6) == "Saturday"
    assert names.weekday_name(7) is None


def test_sign_lords():
    # Aries->Mars, Leo->Sun, Sagittarius->Jupiter, Capricorn->Saturn.
    assert names.planet_name(names.sign_lord_index(0)) == "Mars"
    assert names.planet_name(names.sign_lord_index(4)) == "Sun"
    assert names.planet_name(names.sign_lord_index(8)) == "Jupiter"
    assert names.planet_name(names.sign_lord_index(9)) == "Saturn"
    assert names.sign_lord_index(12) is None
    assert len(names.SIGN_LORDS) == 12
