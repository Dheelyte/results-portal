"""The §5.2 matrix, role by role — every cell, allow or deny.

Milestone 4's done-when. These are pure: `policy.can` reads a role and an
active flag and nothing else, so no database is involved. The *scoped* half of
the matrix — "may this teacher, for that class" — needs real rows and lives in
tests/integration/test_authz_matrix.py.

§12 puts this milestone before any admin endpoint on purpose:

> "Milestone 4 before 5 is deliberate — retrofitting authorization onto built
> endpoints is how school portals leak results."
"""

import uuid

import pytest

from app.authz import policy
from app.authz.policy import Action
from app.models import User, UserRole

# §5.2, transcribed. The key is the action; the set is every role the table
# marks. A cell absent from this map is a deny.
EXPECTED_ROLE_GRANTS: dict[Action, set[UserRole]] = {
    Action.MANAGE_ACADEMIC_STRUCTURE: {UserRole.ADMIN},
    Action.MANAGE_USERS: {UserRole.ADMIN},
    Action.MANAGE_ASSESSMENT_CONFIG: {UserRole.ADMIN},
    # D123: a head teacher or an admin can be assigned to teach. The grants
    # are scoped, so without an assignment row none of these lets them act.
    Action.ENTER_SCORES: {UserRole.TEACHER, UserRole.HEAD_TEACHER, UserRole.ADMIN},
    Action.WRITE_NARRATIVE: {UserRole.TEACHER, UserRole.HEAD_TEACHER, UserRole.ADMIN},
    Action.RECORD_ATTENDANCE_AND_GROWTH: {
        UserRole.TEACHER,
        UserRole.HEAD_TEACHER,
        UserRole.ADMIN,
    },
    Action.SUBMIT_CLASS: {UserRole.TEACHER, UserRole.HEAD_TEACHER, UserRole.ADMIN},
    # D125: scoped to one's own class as class teacher.
    Action.PROPOSE_PUPIL: {UserRole.TEACHER, UserRole.HEAD_TEACHER, UserRole.ADMIN},
    # The admin reviews only a class a head teacher teaches in (D123).
    Action.REVIEW_CLASS: {UserRole.HEAD_TEACHER, UserRole.ADMIN},
    Action.SET_HEAD_TEACHER_REMARK: {UserRole.HEAD_TEACHER},
    Action.PUBLISH: {UserRole.ADMIN},
    Action.EDIT_AFTER_PUBLICATION: {UserRole.ADMIN},
    Action.VIEW_OWN_CHILDREN_REPORTS: {UserRole.PARENT},
    Action.ACKNOWLEDGE_REPORT: {UserRole.PARENT},
    Action.VIEW_AUDIT_LOG: {UserRole.ADMIN, UserRole.HEAD_TEACHER},
    # Not a row of §5.2 as printed. The table's "comment bank — admin" is
    # about managing it; §4.6 and §8.2 require every member of staff to read
    # it, and no parent ever does (docs/DECISIONS.md D55).
    Action.USE_COMMENT_BANK: {UserRole.ADMIN, UserRole.HEAD_TEACHER, UserRole.TEACHER},
}


def make_user(role: UserRole, *, is_active: bool = True) -> User:
    """A detached User. `policy.can` touches only role and is_active."""
    return User(
        id=uuid.uuid4(),
        school_id=uuid.uuid4(),
        role=role,
        full_name="Test Person",
        email="test@sshms.test",
        password_hash="unused",
        is_active=is_active,
    )


@pytest.mark.parametrize("action", list(Action))
@pytest.mark.parametrize("role", list(UserRole))
def test_every_cell_of_the_matrix(action: Action, role: UserRole) -> None:
    """One assertion per cell: every role against every action."""
    expected = role in EXPECTED_ROLE_GRANTS[action]

    assert policy.can(make_user(role), action) is expected, (
        f"{role.value} should {'be allowed' if expected else 'be denied'} {action.value}"
    )


def test_the_matrix_covers_every_action() -> None:
    """A new Action without a row here would silently never be asserted."""
    assert set(EXPECTED_ROLE_GRANTS) == set(Action)


def test_every_action_is_reachable_by_someone() -> None:
    granted = {action for actions in policy.ROLE_ACTIONS.values() for action in actions}

    assert granted == set(Action)


def test_every_role_has_a_row_in_the_table() -> None:
    assert set(policy.ROLE_ACTIONS) == set(UserRole)


@pytest.mark.parametrize("role", list(UserRole))
def test_an_inactive_user_can_do_nothing(role: UserRole) -> None:
    """Deactivation is the lever an admin pulls when an account is
    compromised. It must close every door at once, not merely stop new
    sign-ins."""
    user = make_user(role, is_active=False)

    assert not any(policy.can(user, action) for action in Action)


def test_the_head_teacher_sees_the_audit_log_read_only() -> None:
    head = make_user(UserRole.HEAD_TEACHER)

    assert policy.can(head, Action.VIEW_AUDIT_LOG)
    assert policy.audit_log_is_read_only(head) is True
    assert policy.audit_log_is_read_only(make_user(UserRole.ADMIN)) is False


def test_approve_and_publish_stay_in_different_hands() -> None:
    """B2 confirmed the head teacher and the admin are two people. The
    separation is what gives §4.9's audit trail two signatures.

    D123 narrowed it, as a product decision: an admin now holds the review
    grant, but `policy.review_refusal` lets them use it only on a class a head
    teacher teaches in, the one class the head teacher can't approve. Every
    other class still needs both people. The head teacher never publishes."""
    admin = make_user(UserRole.ADMIN)
    head = make_user(UserRole.HEAD_TEACHER)

    assert policy.can(head, Action.REVIEW_CLASS)
    assert not policy.can(head, Action.PUBLISH)

    assert policy.can(admin, Action.PUBLISH)
    assert policy.can(admin, Action.REVIEW_CLASS)  # scoped by review_refusal


def test_no_staff_role_can_act_as_a_parent() -> None:
    """§5.2: staff cannot read parent endpoints."""
    parent_actions = {Action.VIEW_OWN_CHILDREN_REPORTS, Action.ACKNOWLEDGE_REPORT}

    for role in (UserRole.ADMIN, UserRole.HEAD_TEACHER, UserRole.TEACHER):
        user = make_user(role)
        assert not any(policy.can(user, action) for action in parent_actions)


def test_a_parent_can_reach_no_staff_action() -> None:
    """§5.2: parents cannot read any staff endpoint."""
    parent = make_user(UserRole.PARENT)
    staff_actions = set(Action) - {
        Action.VIEW_OWN_CHILDREN_REPORTS,
        Action.ACKNOWLEDGE_REPORT,
    }

    assert not any(policy.can(parent, action) for action in staff_actions)


def test_every_scoped_action_is_granted_to_someone_by_role() -> None:
    """A scoped action whose role grant was dropped would be unreachable, and
    the scoped check below it would never run."""
    for action in policy.SCOPED_ACTIONS:
        assert EXPECTED_ROLE_GRANTS[action], action
