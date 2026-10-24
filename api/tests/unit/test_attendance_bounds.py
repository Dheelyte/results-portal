"""R9, and the growth bounds beside it (ARCHITECTURE.md §6 R9, §4.7).

Pure: `check_attendance` and `check_growth` take a row and a number and
return the refusals. The trigger in migration 0003 enforces R9 as well, and
`tests/integration/test_schema_constraints.py` proves that half — this is the
half that can say *which* pupil and *which* field, which is what §8.3 needs
to show a teacher where to look.
"""

import uuid
from decimal import Decimal

import pytest

from app.services.wellbeing import (
    MAX_HEIGHT_M,
    MAX_WEIGHT_KG,
    MIN_HEIGHT_M,
    MIN_WEIGHT_KG,
    AttendanceInput,
    GrowthInput,
    check_attendance,
    check_growth,
)

PUPIL = uuid.uuid4()
OPENED = 60


def attendance(present: int, absent: int, late: int = 0) -> AttendanceInput:
    return AttendanceInput(
        pupil_id=PUPIL, times_present=present, times_absent=absent, times_late=late
    )


# ---------------------------------------------------------------------------
# R9
# ---------------------------------------------------------------------------


def test_present_plus_absent_equal_to_times_opened_is_accepted() -> None:
    assert check_attendance(attendance(58, 2), times_school_opened=OPENED) == {}


def test_a_pupil_present_every_day_is_accepted() -> None:
    assert check_attendance(attendance(60, 0), times_school_opened=OPENED) == {}


def test_a_pupil_absent_all_term_is_accepted() -> None:
    """Sad, but not a validation error."""
    assert check_attendance(attendance(0, 60), times_school_opened=OPENED) == {}


def test_a_total_that_does_not_add_up_is_refused() -> None:
    errors = check_attendance(attendance(50, 5), times_school_opened=OPENED)

    assert "times_absent" in errors
    # The message names both numbers, so the teacher can see the gap without
    # doing the arithmetic themselves.
    assert "60" in errors["times_absent"]
    assert "55" in errors["times_absent"]


def test_present_more_often_than_the_school_opened_is_refused() -> None:
    errors = check_attendance(attendance(61, 0), times_school_opened=OPENED)

    assert "times_present" in errors
    assert "60" in errors["times_present"]


def test_the_present_check_comes_before_the_sum_check() -> None:
    """61 present and -1 absent adds to 60, which must not be accepted.

    Reporting the sum first would make the real mistake — more days present
    than the school opened — invisible.
    """
    errors = check_attendance(attendance(61, 0), times_school_opened=OPENED)

    assert set(errors) == {"times_present"}


@pytest.mark.parametrize("field", ["times_present", "times_absent", "times_late"])
def test_a_negative_count_is_refused(field: str) -> None:
    counts = {"present": 58, "absent": 2, "late": 0}
    counts[field.removeprefix("times_")] = -1
    errors = check_attendance(
        attendance(counts["present"], counts["absent"], counts["late"]),
        times_school_opened=OPENED,
    )

    assert field in errors


def test_a_negative_count_is_reported_before_the_arithmetic() -> None:
    """Otherwise the teacher is told the total is wrong, which is a
    consequence of the real error rather than the error."""
    errors = check_attendance(attendance(-1, 61), times_school_opened=OPENED)

    assert set(errors) == {"times_present"}


def test_collected_late_more_often_than_the_school_opened_is_refused() -> None:
    errors = check_attendance(attendance(58, 2, late=61), times_school_opened=OPENED)

    assert "times_late" in errors


def test_collected_late_may_exceed_days_absent() -> None:
    """Late is counted independently of present and absent: a pupil who
    attended every day can still have been collected late every day."""
    assert check_attendance(attendance(60, 0, late=60), times_school_opened=OPENED) == {}


def test_a_term_with_no_days_accepts_only_zeros() -> None:
    """Defence in depth. The service refuses to validate at all when
    `times_school_opened` is unset, so this is the degenerate case of 0."""
    assert check_attendance(attendance(0, 0), times_school_opened=0) == {}
    assert check_attendance(attendance(1, 0), times_school_opened=0) != {}


# ---------------------------------------------------------------------------
# Growth (§4.7)
# ---------------------------------------------------------------------------


def growth(**values: str) -> GrowthInput:
    return GrowthInput(PUPIL, **{key: Decimal(value) for key, value in values.items()})


def test_a_plausible_pupil_is_accepted() -> None:
    assert (
        check_growth(
            growth(
                height_start_m="1.18",
                height_end_m="1.22",
                weight_start_kg="24.5",
                weight_end_kg="25.8",
            )
        )
        == {}
    )


def test_an_empty_row_is_accepted() -> None:
    """The end-of-term figures do not exist until the end of term, which is
    why §4.7 makes every column nullable."""
    assert check_growth(GrowthInput(PUPIL)) == {}


def test_centimetres_in_the_metres_column_are_refused() -> None:
    """The mistake that actually happens: 118 instead of 1.18.

    §4.7's CHECK only requires a positive number, so without this the card
    prints a pupil 118 metres tall.
    """
    errors = check_growth(growth(height_start_m="118"))

    assert "height_start_m" in errors
    assert "Height at the beginning of term" in errors["height_start_m"]


def test_a_height_of_a_centimetre_is_refused() -> None:
    errors = check_growth(growth(height_end_m="0.01"))

    assert "height_end_m" in errors


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("height_start_m", MIN_HEIGHT_M),
        ("height_end_m", MAX_HEIGHT_M),
        ("weight_start_kg", MIN_WEIGHT_KG),
        ("weight_end_kg", MAX_WEIGHT_KG),
    ],
)
def test_the_bounds_themselves_are_accepted(field: str, value: Decimal) -> None:
    """Inclusive, so a child exactly on a boundary is not refused."""
    assert check_growth(GrowthInput(PUPIL, **{field: value})) == {}


def test_every_measurement_is_checked_not_just_the_first() -> None:
    errors = check_growth(growth(height_start_m="300", weight_start_kg="900"))

    assert set(errors) == {"height_start_m", "weight_start_kg"}


def test_the_bounds_are_wide_enough_for_a_whole_primary_school() -> None:
    """A three-year-old and a tall twelve-year-old both fit. The bounds exist
    to stop nonsense printing on a card, not to tell a school what a child may
    weigh (§14 A21).
    """
    assert check_growth(growth(height_start_m="0.85", weight_start_kg="11")) == {}
    assert check_growth(growth(height_end_m="1.75", weight_end_kg="80")) == {}
