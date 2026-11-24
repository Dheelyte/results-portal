"""Which columns each sheet carries, and when its maxima are usable
(ARCHITECTURE.md §1.2, §4.4).

Pure: these read a `MarksObtainable` instance's attributes and touch no
database.
"""

from decimal import Decimal

from app.models import MarksObtainable, TermHalf
from app.services.marks import ALL_COLUMNS, CA_COLUMNS, COLUMNS_BY_HALF, is_configured


def row(**values: object) -> MarksObtainable:
    """An unsaved row; `is_configured` only reads attributes."""
    return MarksObtainable(**values)


def test_the_first_half_sheet_ends_in_mid_term_test() -> None:
    assert COLUMNS_BY_HALF[TermHalf.FIRST_HALF] == (*CA_COLUMNS, "mid_term_test")


def test_the_second_half_sheet_carries_the_mid_term_and_ends_in_exam() -> None:
    """D129: the first half's Mid Term Test is carried over and counted."""
    assert COLUMNS_BY_HALF[TermHalf.SECOND_HALF] == (*CA_COLUMNS, "mid_term_test", "exam")


def test_the_first_half_never_carries_the_exam() -> None:
    assert "exam" not in COLUMNS_BY_HALF[TermHalf.FIRST_HALF]


def test_three_ca_tests() -> None:
    """D129: CA Test 4 retired, as CA Test 5 was (D127)."""
    assert CA_COLUMNS == ("ca_test_1", "ca_test_2", "ca_test_3")


def test_every_column_is_covered_by_one_sheet_or_the_other() -> None:
    """Guards against a column being added to the model and configured
    nowhere."""
    covered = set(COLUMNS_BY_HALF[TermHalf.FIRST_HALF]) | set(COLUMNS_BY_HALF[TermHalf.SECOND_HALF])

    assert covered == set(ALL_COLUMNS)


def test_a_missing_row_is_not_configured() -> None:
    assert is_configured(None, TermHalf.FIRST_HALF) is False


def test_a_row_without_the_terminal_column_is_not_configured() -> None:
    """Five CA tests and no Mid Term Test leaves the last column unvalidated."""
    assert is_configured(row(ca_test_1=Decimal(8)), TermHalf.FIRST_HALF) is False


def test_a_row_with_no_ca_column_is_not_configured() -> None:
    assert is_configured(row(mid_term_test=Decimal(40)), TermHalf.FIRST_HALF) is False


def test_one_ca_column_and_the_terminal_one_is_enough() -> None:
    """Not all five, deliberately.

    N2 is open and the school may use fewer than five CA tests in a given
    half, so demanding all five would block a term on a number nobody has.
    """
    configured = row(ca_test_1=Decimal(8), mid_term_test=Decimal(40))

    assert is_configured(configured, TermHalf.FIRST_HALF) is True


def test_the_other_halfs_column_does_not_count() -> None:
    """An exam maximum on a first-half sheet configures nothing."""
    assert is_configured(row(ca_test_1=Decimal(8), exam=Decimal(60)), TermHalf.FIRST_HALF) is False
