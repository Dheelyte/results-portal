"""R14's state machine, as a pure question (ARCHITECTURE.md §6 R14).

The integration tests prove the 409 arrives. This proves the table behind it
is complete — a state added later cannot quietly default to writable.
"""

import pytest

from app.models import ClassTermState
from app.services.errors import Conflict
from app.services.workflow import (
    LOCKED_MESSAGE,
    TEACHER_EDITABLE,
    refuse_if_locked,
    teacher_may_edit,
)

EDITABLE = [
    ClassTermState.NOT_STARTED,
    ClassTermState.IN_PROGRESS,
    ClassTermState.RETURNED,
]
LOCKED = [ClassTermState.SUBMITTED, ClassTermState.APPROVED]


@pytest.mark.parametrize("state", EDITABLE, ids=lambda state: state.value)
def test_a_teacher_may_write_before_submission(state: ClassTermState) -> None:
    assert teacher_may_edit(state)
    refuse_if_locked(state)  # does not raise


@pytest.mark.parametrize("state", LOCKED, ids=lambda state: state.value)
def test_a_teacher_may_not_write_after_submission(state: ClassTermState) -> None:
    assert not teacher_may_edit(state)
    with pytest.raises(Conflict):
        refuse_if_locked(state)


def test_a_returned_class_is_writable_again() -> None:
    """The head teacher sent it back so it could be corrected. If `returned`
    were read-only, returning a class would be indistinguishable from
    approving it."""
    assert ClassTermState.RETURNED in TEACHER_EDITABLE


def test_every_state_is_decided() -> None:
    """A state added in a later milestone must be classified deliberately.

    Without this, a new member of the enum would fall outside
    `TEACHER_EDITABLE` and silently become read-only — or, worse, a future
    edit to the set would make it writable without anyone deciding so.
    """
    assert set(EDITABLE) | set(LOCKED) == set(ClassTermState)


@pytest.mark.parametrize("state", LOCKED, ids=lambda state: state.value)
def test_the_refusal_says_what_to_do_next(state: ClassTermState) -> None:
    """ "Cannot submit" with no explanation generates support calls every term
    (R10), and a grid that stops saving is no different."""
    message = LOCKED_MESSAGE[state]

    assert "head teacher" in message or "administrator" in message
