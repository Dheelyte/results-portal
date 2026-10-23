"""Grade band validation (ARCHITECTURE.md §1.3, §4.5).

Pure: no database. Every rule exists because of a specific way a report card
goes wrong, and each test names that way.
"""

from decimal import Decimal

import pytest

from app.seed.reference import CARD_GRADE_BANDS
from app.services.errors import Invalid
from app.services.grading import BandInput, validate_bands


def band(letter: str, low: int | str, high: int | str, remark: str = "Remark") -> BandInput:
    return BandInput(
        letter=letter, remark=remark, min_score=Decimal(str(low)), max_score=Decimal(str(high))
    )


def card_scale() -> list[BandInput]:
    """The seven bands as printed on the card (§1.3)."""
    return [band(letter, low, high, remark) for letter, remark, low, high in CARD_GRADE_BANDS]


def test_the_cards_own_scale_is_valid() -> None:
    """The scale the school actually prints must pass, or the rules are wrong."""
    assert len(validate_bands(card_scale())) == 7


def test_bands_come_back_highest_first() -> None:
    """The card prints its key with A+ at the top."""
    letters = [item.letter for item in validate_bands(card_scale())]

    assert letters == ["A+", "A", "B+", "B", "C", "D", "E"]
    assert validate_bands(card_scale())[0].max_score == Decimal(100)


def test_an_empty_scale_is_refused() -> None:
    with pytest.raises(Invalid, match="at least one band"):
        validate_bands([])


def test_overlapping_bands_are_refused() -> None:
    """Two bands containing 85 makes the printed grade depend on row order."""
    bands = [band("A", 80, 90), band("B+", 85, 95), band("E", 0, 79)]

    with pytest.raises(Invalid, match="overlap"):
        validate_bands(bands)


def test_a_gap_is_refused() -> None:
    """A mark in no band prints an empty grade cell."""
    bands = [band("A", 60, 100), band("E", 0, 49)]

    with pytest.raises(Invalid, match="50-59"):
        validate_bands(bands)


def test_the_gap_message_collapses_runs() -> None:
    """One unreadable list of ninety numbers is worse than no message."""
    with pytest.raises(Invalid) as caught:
        validate_bands([band("A", 95, 100)])

    assert "0-94" in str(caught.value)


def test_a_band_above_one_hundred_is_refused() -> None:
    with pytest.raises(Invalid, match="outside 0 to 100"):
        validate_bands([band("A", 90, 110), band("E", 0, 89)])


def test_a_band_that_starts_above_its_end_is_refused() -> None:
    with pytest.raises(Invalid, match="starts above where it ends"):
        validate_bands([band("A", 90, 10)])


def test_a_repeated_letter_is_refused() -> None:
    """Two rows both printing "A" cannot be told apart on the card."""
    with pytest.raises(Invalid, match="appears twice"):
        validate_bands([band("A", 50, 100), band("A", 0, 49)])


def test_a_band_needs_a_remark() -> None:
    """The remark prints beside the grade in the card's key."""
    with pytest.raises(Invalid, match="needs a remark"):
        validate_bands([band("A", 0, 100, remark="  ")])


def test_a_band_needs_a_letter() -> None:
    with pytest.raises(Invalid, match="needs a grade letter"):
        validate_bands([band("   ", 0, 100)])


def test_a_single_band_covering_everything_is_valid() -> None:
    """Degenerate but coherent: the rules check coverage, not taste."""
    assert len(validate_bands([band("P", 0, 100)])) == 1


def test_fractional_coverage_is_not_claimed() -> None:
    """A deliberate, documented limit.

    The card's bands run 0-39, 40-49 and so on, so 39.5 — which numeric(5,2)
    permits and R1's one decimal place allows — sits between two bands and
    `validate_bands` does **not** reject it. Whether averages are rounded
    before banding is part of the unanswered N3.

    This test pins the current behaviour so that answering N3 is a deliberate
    change with a failing test, rather than a surprise discovered on results
    night.

    Milestone 6 closed the gap at the *lookup* site rather than here:
    `grading.banded_value` rounds half up before a band is read, so 39.5
    resolves to a D (§14 A17, `test_period_average.py`). `validate_bands`
    still makes no claim about fractional coverage, which is what this
    asserts — the two are the same decision seen from opposite ends, and
    answering N3 should move both.
    """
    bands = validate_bands(card_scale())
    fractional = Decimal("39.5")

    assert not any(item.min_score <= fractional <= item.max_score for item in bands)
