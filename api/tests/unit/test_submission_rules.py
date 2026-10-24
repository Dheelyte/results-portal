"""R10's and R14's pure parts (ARCHITECTURE.md §6 R10, R14).

Two things are testable without a database and worth testing that way: what
"every column filled" means for one row, and whether R14's transition table is
the state machine the specification draws.

The gate itself needs real data and lives in
`tests/integration/test_submission_gate.py`.
"""

import uuid

import pytest

from app.models import ClassTermState, ResultEntry
from app.services.submission import columns_filled
from app.services.workflow import LEGAL_PREDECESSORS, TEACHER_EDITABLE

FIRST_HALF = ("ca_test_1", "ca_test_2", "mid_term_test")


def entry(**scores: int | None) -> ResultEntry:
    """A detached row. `columns_filled` reads nothing but these columns."""
    return ResultEntry(id=uuid.uuid4(), **scores)


# ---------------------------------------------------------------------------
# A23 — what "complete" means for one row
# ---------------------------------------------------------------------------


def test_every_column_present_is_complete() -> None:
    assert columns_filled(entry(ca_test_1=7, ca_test_2=6, mid_term_test=50), FIRST_HALF)


def test_a_missing_column_is_not_complete() -> None:
    """A23, and the reason it matters: R2 coalesces a blank to zero, so this
    row still produces an average and a grade. The gap only surfaces when a
    parent compares the card with the paper sheet."""
    assert not columns_filled(entry(ca_test_1=7, ca_test_2=None, mid_term_test=50), FIRST_HALF)


def test_a_zero_is_a_score() -> None:
    """A pupil who missed a test is marked 0, exactly as on paper. Treating
    zero as "not entered" would make an absent pupil unsubmittable."""
    assert columns_filled(entry(ca_test_1=0, ca_test_2=0, mid_term_test=0), FIRST_HALF)


def test_no_row_at_all_is_not_complete() -> None:
    assert not columns_filled(None, FIRST_HALF)


def test_columns_the_sheet_does_not_carry_are_not_required() -> None:
    """The school decides which columns exist by setting their maxima (N2).
    A school using two CA tests must not be blocked for the other three."""
    row = entry(ca_test_1=7, ca_test_2=6, mid_term_test=50)

    assert columns_filled(row, ("ca_test_1",))
    assert columns_filled(row, FIRST_HALF)
    # CA test 3 has no maximum, so it is not on the sheet and not checked.
    assert row.ca_test_3 is None


def test_a_sheet_with_no_columns_is_vacuously_complete() -> None:
    """Deliberate, and safe: a sheet with no configured columns is reported as
    `not_configured`, which is its own outstanding item. Without that, this
    would be the hole in R10."""
    assert columns_filled(entry(), ())


def test_the_other_halfs_column_is_not_consulted() -> None:
    """A first-half row has no exam mark, and must not be asked for one."""
    row = entry(ca_test_1=7, ca_test_2=6, mid_term_test=50)

    assert columns_filled(row, FIRST_HALF)
    assert not columns_filled(row, ("ca_test_1", "exam"))


# ---------------------------------------------------------------------------
# R14 — the state machine as the specification draws it
# ---------------------------------------------------------------------------
#
#     not_started -> in_progress -> submitted -> approved
#                         ^             |
#                         +-- returned <+


@pytest.mark.parametrize(
    ("to", "from_"),
    [
        (ClassTermState.IN_PROGRESS, ClassTermState.NOT_STARTED),
        (ClassTermState.SUBMITTED, ClassTermState.IN_PROGRESS),
        (ClassTermState.RETURNED, ClassTermState.SUBMITTED),
        (ClassTermState.APPROVED, ClassTermState.SUBMITTED),
        (ClassTermState.SUBMITTED, ClassTermState.RETURNED),
    ],
)
def test_every_arrow_in_the_diagram_is_legal(to: ClassTermState, from_: ClassTermState) -> None:
    assert from_ in LEGAL_PREDECESSORS[to]


@pytest.mark.parametrize(
    ("to", "from_"),
    [
        # Approval is the head teacher's, after review — never straight from
        # the class teacher's desk.
        (ClassTermState.APPROVED, ClassTermState.IN_PROGRESS),
        (ClassTermState.APPROVED, ClassTermState.NOT_STARTED),
        (ClassTermState.APPROVED, ClassTermState.RETURNED),
        # Nothing reopens an approved class except the admin's post-publication
        # edit (R13), which is not a state change.
        (ClassTermState.RETURNED, ClassTermState.APPROVED),
        (ClassTermState.SUBMITTED, ClassTermState.APPROVED),
        (ClassTermState.IN_PROGRESS, ClassTermState.SUBMITTED),
        (ClassTermState.IN_PROGRESS, ClassTermState.APPROVED),
        # A class nobody has touched cannot be returned.
        (ClassTermState.RETURNED, ClassTermState.NOT_STARTED),
        (ClassTermState.RETURNED, ClassTermState.IN_PROGRESS),
    ],
)
def test_every_other_move_is_refused(to: ClassTermState, from_: ClassTermState) -> None:
    assert from_ not in LEGAL_PREDECESSORS[to]


def test_submitting_an_untouched_class_is_left_to_r10() -> None:
    """`not_started -> submitted` is permitted by the table on purpose.

    R10 refuses it anyway — a class nobody has touched is missing everything —
    and a 422 that lists what is missing is more use than a 409 that can only
    say the move was illegal.
    """
    assert ClassTermState.NOT_STARTED in LEGAL_PREDECESSORS[ClassTermState.SUBMITTED]


def test_every_state_but_the_first_can_be_arrived_at() -> None:
    """A state nothing transitions to would be unreachable, and a target
    missing from the table would raise a KeyError at the call site."""
    reachable = set(LEGAL_PREDECESSORS)

    assert reachable == set(ClassTermState) - {ClassTermState.NOT_STARTED}


def test_submission_closes_the_class_to_teachers() -> None:
    """R14: "Scores and narrative become read-only for teachers on
    `submitted`". The two tables have to agree about that."""
    assert ClassTermState.SUBMITTED not in TEACHER_EDITABLE
    assert ClassTermState.APPROVED not in TEACHER_EDITABLE
    # And a returned class reopens, or returning it would achieve nothing.
    assert ClassTermState.RETURNED in TEACHER_EDITABLE
