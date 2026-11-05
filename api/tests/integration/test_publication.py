"""Publication, withholding, release and the post-publication edit
(ARCHITECTURE.md §6 R12, R13, §4.9).

§12's criterion: "Withheld pupil's parent sees the R12 message; every action
audited."

R12 is quoted exactly in the specification, so it is asserted exactly here —
character for character — and so is what it does **not** say. A withheld
report is invisible to the parent, not forbidden: no hint that it exists, none
that it was held back, and none of why. The school says why, in person.
"""

import datetime as dt
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    AcademicSession,
    AssessmentPeriod,
    AuditLog,
    Class,
    ClassSubject,
    ClassTeacher,
    ClassTermState,
    ClassTermStatus,
    Enrollment,
    GradeBand,
    GradingScale,
    GuardianPupil,
    MarksObtainable,
    Pupil,
    ResultEntry,
    Subject,
    Term,
    TermHalf,
    TermNumber,
    TermReport,
    User,
    UserRole,
)
from app.services.publication import UNAVAILABLE_MESSAGE
from tests.conftest import TEST_PASSWORD

API = settings.api_v1_prefix

CA_MAX = Decimal(20)
TERMINAL_MAX = Decimal(60)

# Two children of the same parent, so withholding one and releasing the other
# is observable from a single account — which is §10's multi-child case and
# the one most likely to leak.
ROLL = ["Ada", "Chidi"]


@pytest.fixture
async def approved_class(session: AsyncSession, school, password_hash: str):
    """An approved class with grades already frozen, ready to publish.

    Approval is milestone 9's, so it is set up directly here rather than
    driven through the API: what these tests are about is what happens after.
    """
    from types import SimpleNamespace

    def user(role: UserRole, name: str, email: str | None, phone: str | None = None) -> User:
        record = User(
            school_id=school.id,
            role=role,
            full_name=name,
            email=email,
            phone=phone,
            password_hash=password_hash,
            must_change_password=False,
        )
        session.add(record)
        return record

    admin = user(UserRole.ADMIN, "The Admin", "admin@sshms.test")
    head = user(UserRole.HEAD_TEACHER, "The Head", "head@sshms.test")
    teacher = user(UserRole.TEACHER, "Mrs Class Teacher", "ct@sshms.test")
    parent = user(UserRole.PARENT, "Mrs Okafor", "parent@sshms.test")
    await session.flush()

    academic_session = AcademicSession(
        school_id=school.id,
        name="2026/2027",
        starts_on=dt.date(2026, 9, 14),
        ends_on=dt.date(2027, 7, 23),
        is_current=True,
    )
    session.add(academic_session)
    await session.flush()

    term = Term(
        school_id=school.id,
        academic_session_id=academic_session.id,
        number=TermNumber.FIRST,
        starts_on=dt.date(2026, 9, 14),
        ends_on=dt.date(2026, 12, 11),
        times_school_opened=60,
        is_current=True,
    )
    later_term = Term(
        school_id=school.id,
        academic_session_id=academic_session.id,
        number=TermNumber.SECOND,
        starts_on=dt.date(2027, 1, 11),
        ends_on=dt.date(2027, 4, 2),
    )
    klass = Class(school_id=school.id, name="Primary 4", level_order=4)
    session.add_all([term, later_term, klass])
    await session.flush()

    session.add(
        ClassTeacher(
            school_id=school.id,
            class_id=klass.id,
            academic_session_id=academic_session.id,
            teacher_user_id=teacher.id,
        )
    )

    period = AssessmentPeriod(school_id=school.id, term_id=term.id, half=TermHalf.SECOND_HALF)
    session.add(period)
    await session.flush()
    session.add(
        MarksObtainable(
            school_id=school.id,
            assessment_period_id=period.id,
            class_id=None,
            ca_test_1=CA_MAX,
            ca_test_2=CA_MAX,
            exam=TERMINAL_MAX,
        )
    )

    scale = GradingScale(
        school_id=school.id,
        name="Card scale (seven bands)",
        effective_from=dt.date(2026, 9, 1),
        is_active=True,
    )
    session.add(scale)
    await session.flush()
    for order, (letter, remark, low, high) in enumerate(
        [
            ("A+", "Excellence", 90, 100),
            ("A", "Very Good", 80, 89),
            ("B+", "Good", 70, 79),
            ("B", "Fairly Good", 60, 69),
            ("C", "Average", 50, 59),
            ("D", "Below Average", 40, 49),
            ("E", "Weak", 0, 39),
        ]
    ):
        session.add(
            GradeBand(
                scale_id=scale.id,
                letter=letter,
                remark=remark,
                min_score=Decimal(low),
                max_score=Decimal(high),
                sort_order=order,
            )
        )

    maths = Subject(school_id=school.id, name="Mathematics", display_order=1)
    session.add(maths)
    await session.flush()
    offering = ClassSubject(
        school_id=school.id,
        class_id=klass.id,
        subject_id=maths.id,
        academic_session_id=academic_session.id,
    )
    session.add(offering)
    await session.flush()

    pupils = {}
    entries = {}
    for index, name in enumerate(ROLL, start=1):
        pupil = Pupil(
            school_id=school.id,
            admission_number=f"SSHMS/2026/{index:03d}",
            first_name=name,
            last_name="Okafor",
        )
        session.add(pupil)
        await session.flush()
        session.add(
            Enrollment(
                school_id=school.id,
                pupil_id=pupil.id,
                class_id=klass.id,
                academic_session_id=academic_session.id,
                joined_on=dt.date(2026, 9, 14),
            )
        )
        session.add(GuardianPupil(guardian_user_id=parent.id, pupil_id=pupil.id))

        # 20 + 20 + 54 = 94 of 100 — an A+ under the scale above.
        entry = ResultEntry(
            school_id=school.id,
            assessment_period_id=period.id,
            pupil_id=pupil.id,
            class_subject_id=offering.id,
            ca_test_1=CA_MAX,
            ca_test_2=CA_MAX,
            exam=Decimal(54),
            period_average=Decimal("94.00"),
            # Already frozen: this class has been approved.
            grade_letter="A+",
            grading_scale_id=scale.id,
        )
        session.add(entry)
        session.add(
            TermReport(
                school_id=school.id,
                term_id=term.id,
                pupil_id=pupil.id,
                class_id=klass.id,
                class_teacher_comment="A purposeful term.",
                head_teacher_remark="Well done.",
                overall_percentage=Decimal("94.00"),
                no_in_class=len(ROLL),
            )
        )
        pupils[name] = pupil
        entries[name] = entry

    session.add(
        ClassTermStatus(
            school_id=school.id,
            class_id=klass.id,
            term_id=term.id,
            state=ClassTermState.APPROVED,
        )
    )

    await session.commit()

    return SimpleNamespace(
        term=term,
        later_term=later_term,
        klass=klass,
        admin=admin,
        head=head,
        teacher=teacher,
        parent=parent,
        pupils=pupils,
        entries=entries,
        scale=scale,
        period=period,
    )


@pytest.fixture
async def admin(client: AsyncClient, login, approved_class) -> dict[str, str]:
    response = await login(approved_class.admin.email, TEST_PASSWORD)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
async def parent(client: AsyncClient, login, approved_class) -> dict[str, str]:
    response = await login(approved_class.parent.email, TEST_PASSWORD)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def publish(client, admin, approved_class, *, withhold=(), reason=None):
    return await client.post(
        f"{API}/classes/{approved_class.klass.id}/publish",
        params={"term_id": str(approved_class.term.id)},
        json={"withhold_pupil_ids": [str(pupil) for pupil in withhold], "reason": reason},
        headers=admin,
    )


async def publication_state(client, admin, approved_class):
    response = await client.get(
        f"{API}/classes/{approved_class.klass.id}/publication",
        params={"term_id": str(approved_class.term.id)},
        headers=admin,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def childs_reports(client, parent, pupil_id):
    response = await client.get(f"{API}/my/children/{pupil_id}/reports", headers=parent)
    assert response.status_code == 200, response.text
    return response.json()


def report_of(body, name: str) -> dict:
    return next(r for r in body["reports"] if r["name"].endswith(name))


# ---------------------------------------------------------------------------
# R12 — publishing a class
# ---------------------------------------------------------------------------


async def test_publishing_a_class_makes_every_report_available(
    client, admin, parent, approved_class
) -> None:
    before = await childs_reports(client, parent, approved_class.pupils["Ada"].id)
    assert all(term["available"] is False for term in before["terms"])

    response = await publish(client, admin, approved_class)

    assert response.status_code == 200, response.text
    assert len(response.json()["published"]) == len(ROLL)
    assert response.json()["withheld"] == []

    after = childs_reports(client, parent, approved_class.pupils["Ada"].id)
    first = next(t for t in (await after)["terms"] if t["term_label"] == "First Term")
    assert first["available"] is True
    assert first["message"] is None
    assert first["published_at"] is not None


async def test_an_unapproved_class_cannot_be_published(
    client, admin, approved_class, session
) -> None:
    """§1.6: the head teacher approves, then the admin publishes. Publishing
    first would put an unchecked card in front of a parent, with grades that
    were never frozen."""
    status = (await session.execute(select(ClassTermStatus))).scalar_one()
    status.state = ClassTermState.SUBMITTED
    await session.commit()

    response = await publish(client, admin, approved_class)

    assert response.status_code == 409
    assert "Only an approved class can be published" in response.json()["detail"]
    assert "head teacher approves it first" in response.json()["detail"]


async def test_publishing_twice_is_harmless(client, admin, approved_class) -> None:
    """The admin will do this: publish, notice something, correct it, publish
    again. A second run must not refuse the class or re-stamp its dates."""
    first = await publish(client, admin, approved_class)
    stamped = (await publication_state(client, admin, approved_class))["reports"][0]["published_at"]

    second = await publish(client, admin, approved_class)

    assert second.status_code == 200
    assert second.json()["published"] == []
    assert len(second.json()["already_published"]) == len(ROLL)
    assert first.status_code == 200
    assert (await publication_state(client, admin, approved_class))["reports"][0][
        "published_at"
    ] == stamped


# ---------------------------------------------------------------------------
# R12 — withholding, and what the parent is told
# ---------------------------------------------------------------------------


async def test_a_withheld_pupils_parent_sees_exactly_the_r12_message(
    client, admin, parent, approved_class
) -> None:
    """§12's criterion, and the message is quoted in §6 so it is asserted
    character for character."""
    response = await publish(
        client,
        admin,
        approved_class,
        withhold=[approved_class.pupils["Ada"].id],
        reason="Fees outstanding.",
    )
    assert response.status_code == 200, response.text

    body = await childs_reports(client, parent, approved_class.pupils["Ada"].id)
    first = next(t for t in body["terms"] if t["term_label"] == "First Term")

    assert first["available"] is False
    assert first["message"] == "Result not yet available. Please contact the school."
    assert first["message"] == UNAVAILABLE_MESSAGE


async def test_the_direct_url_says_the_same_thing(client, admin, parent, approved_class) -> None:
    """A parent who kept last term's link will use it. A 200 with the message,
    not a 404: "not yet available" is a normal answer, and a 403 would confirm
    the report exists."""
    await publish(
        client,
        admin,
        approved_class,
        withhold=[approved_class.pupils["Ada"].id],
        reason="Fees outstanding.",
    )

    response = await client.get(
        f"{API}/my/children/{approved_class.pupils['Ada'].id}/reports/{approved_class.term.id}",
        headers=parent,
    )

    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["message"] == UNAVAILABLE_MESSAGE


async def test_the_parent_is_told_nothing_about_why(client, admin, parent, approved_class) -> None:
    """R12 gives one sentence and no detail. A parent held back over fees must
    not learn that from a screen with somebody else in the room — and nothing
    may hint that the report exists at all.
    """
    await publish(
        client,
        admin,
        approved_class,
        withhold=[approved_class.pupils["Ada"].id],
        reason="Fees outstanding for two terms.",
    )

    listing = await client.get(
        f"{API}/my/children/{approved_class.pupils['Ada'].id}/reports", headers=parent
    )
    direct = await client.get(
        f"{API}/my/children/{approved_class.pupils['Ada'].id}/reports/{approved_class.term.id}",
        headers=parent,
    )

    for response in (listing, direct):
        text = response.text
        assert "Fees" not in text
        assert "withheld" not in text.lower()
        assert "withhold" not in text.lower()


async def test_withholding_one_child_does_not_affect_the_other(
    client, admin, parent, approved_class
) -> None:
    """R12's whole shape: "a disciplinary matter holds one child back; it must
    not block the other twenty-nine" — here, their own sibling."""
    await publish(
        client,
        admin,
        approved_class,
        withhold=[approved_class.pupils["Ada"].id],
        reason="Fees outstanding.",
    )

    held = await childs_reports(client, parent, approved_class.pupils["Ada"].id)
    released = await childs_reports(client, parent, approved_class.pupils["Chidi"].id)

    assert next(t for t in held["terms"] if t["term_label"] == "First Term")["available"] is False
    assert (
        next(t for t in released["terms"] if t["term_label"] == "First Term")["available"] is True
    )


async def test_withholding_needs_a_reason(client, admin, approved_class) -> None:
    """Somebody has to be able to answer the parent who rings up."""
    response = await publish(
        client, admin, approved_class, withhold=[approved_class.pupils["Ada"].id]
    )

    assert response.status_code == 422
    assert "Give a reason" in response.json()["detail"]


async def test_publishing_with_nothing_held_back_needs_no_reason(
    client, admin, approved_class
) -> None:
    assert (await publish(client, admin, approved_class)).status_code == 200


async def test_a_pupil_from_another_class_cannot_be_held_back(
    client, admin, approved_class, session
) -> None:
    stranger = Pupil(
        school_id=approved_class.klass.school_id,
        admission_number="SSHMS/2026/999",
        first_name="Stranger",
        last_name="Elsewhere",
    )
    session.add(stranger)
    await session.commit()

    response = await publish(
        client, admin, approved_class, withhold=[stranger.id], reason="A mistake."
    )

    assert response.status_code == 422
    assert "not in this class" in response.json()["detail"]


# ---------------------------------------------------------------------------
# R12 — release, and withholding after the fact
# ---------------------------------------------------------------------------


async def test_a_withheld_report_can_be_released_individually(
    client, admin, parent, approved_class
) -> None:
    """R12: "Withheld pupils may be released individually later"."""
    await publish(
        client,
        admin,
        approved_class,
        withhold=[approved_class.pupils["Ada"].id],
        reason="Fees outstanding.",
    )
    state = await publication_state(client, admin, approved_class)
    held = report_of(state, "Ada")
    assert held["state"] == "withheld"
    assert held["withheld_reason"] == "Fees outstanding."

    response = await client.post(f"{API}/reports/{held['report_id']}/release", headers=admin)

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "published"
    assert response.json()["withheld_reason"] is None

    body = await childs_reports(client, parent, approved_class.pupils["Ada"].id)
    assert next(t for t in body["terms"] if t["term_label"] == "First Term")["available"] is True


async def test_a_published_report_can_be_pulled_back(client, admin, parent, approved_class) -> None:
    await publish(client, admin, approved_class)
    state = await publication_state(client, admin, approved_class)
    report = report_of(state, "Ada")

    response = await client.post(
        f"{API}/reports/{report['report_id']}/withhold",
        json={"reason": "Printed in error."},
        headers=admin,
    )

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "withheld"

    body = await childs_reports(client, parent, approved_class.pupils["Ada"].id)
    first = next(t for t in body["terms"] if t["term_label"] == "First Term")
    assert first["available"] is False
    assert first["message"] == UNAVAILABLE_MESSAGE


async def test_pulling_a_report_back_needs_a_reason(client, admin, approved_class) -> None:
    await publish(client, admin, approved_class)
    report = report_of(await publication_state(client, admin, approved_class), "Ada")

    response = await client.post(
        f"{API}/reports/{report['report_id']}/withhold",
        json={"reason": "   "},
        headers=admin,
    )

    assert response.status_code == 422


async def test_releasing_an_already_published_report_is_refused(
    client, admin, approved_class
) -> None:
    await publish(client, admin, approved_class)
    report = report_of(await publication_state(client, admin, approved_class), "Ada")

    response = await client.post(f"{API}/reports/{report['report_id']}/release", headers=admin)

    assert response.status_code == 409
    assert "already published" in response.json()["detail"]


# ---------------------------------------------------------------------------
# What the parent sees of a term that was never published
# ---------------------------------------------------------------------------


async def test_a_term_nobody_has_published_is_listed_as_unavailable(
    client, parent, approved_class
) -> None:
    """Listed rather than hidden: a parent looking for a result needs to see
    that the term exists and the result is not there yet."""
    body = await childs_reports(client, parent, approved_class.pupils["Ada"].id)

    labels = {term["term_label"] for term in body["terms"]}
    assert labels == {"First Term", "Second Term"}
    assert all(term["available"] is False for term in body["terms"])
    assert all(term["message"] == UNAVAILABLE_MESSAGE for term in body["terms"])


async def test_a_parent_cannot_reach_another_familys_child(
    client, headers_for, approved_class, session, password_hash
) -> None:
    other = User(
        school_id=approved_class.klass.school_id,
        role=UserRole.PARENT,
        full_name="Another Parent",
        email="other@sshms.test",
        password_hash=password_hash,
        must_change_password=False,
    )
    session.add(other)
    await session.commit()
    headers = await headers_for(other)

    response = await client.get(
        f"{API}/my/children/{approved_class.pupils['Ada'].id}/reports", headers=headers
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# R13 — the post-publication edit
# ---------------------------------------------------------------------------


async def test_a_correction_needs_a_reason(client, admin, approved_class) -> None:
    """§4.9: "A post-publication edit **requires** a non-empty `reason`;
    reject the request without one"."""
    response = await client.patch(
        f"{API}/entries/{approved_class.entries['Ada'].id}",
        json={"ca_test_1": "18"},
        headers=admin,
    )

    assert response.status_code == 422


async def test_a_blank_reason_is_refused(client, admin, approved_class) -> None:
    response = await client.patch(
        f"{API}/entries/{approved_class.entries['Ada'].id}",
        json={"reason": "   ", "ca_test_1": "18"},
        headers=admin,
    )

    assert response.status_code == 422


async def test_a_correction_updates_the_score_and_the_average(
    client, admin, approved_class, session
) -> None:
    response = await client.patch(
        f"{API}/entries/{approved_class.entries['Ada'].id}",
        json={"reason": "Transposed digits on the mark sheet.", "exam": "40"},
        headers=admin,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["before"]["exam"] == "54.00"
    assert body["after"]["exam"] == "40.00"
    # 20 + 20 + 40 = 80 of 100.
    assert body["after"]["period_average"] == "80.00"


async def test_a_correction_regrades_against_the_snapshotted_scale(
    client, admin, approved_class, session
) -> None:
    """CLAUDE.md rule 6 and §4.5, at the one place a grade may legitimately
    move after approval.

    The school has since tightened the scale. The correction must be graded
    the way the rest of that card was — against the frozen scale — or one line
    of a printed card becomes unexplainable.
    """
    stricter = GradingScale(
        school_id=approved_class.klass.school_id,
        name="Stricter scale",
        effective_from=dt.date(2027, 1, 1),
        is_active=True,
    )
    approved_class.scale.is_active = False
    session.add(stricter)
    await session.flush()
    # Under this scale 80 would be a C, not an A.
    for order, (letter, low, high) in enumerate([("A", 95, 100), ("C", 0, 94)]):
        session.add(
            GradeBand(
                scale_id=stricter.id,
                letter=letter,
                remark="x",
                min_score=Decimal(low),
                max_score=Decimal(high),
                sort_order=order,
            )
        )
    await session.commit()

    response = await client.patch(
        f"{API}/entries/{approved_class.entries['Ada'].id}",
        json={"reason": "Transposed digits.", "exam": "40"},
        headers=admin,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # 80 under the card's seven bands is an A, not the stricter scale's C.
    assert body["after"]["grade_letter"] == "A"
    assert body["regraded_against"] == "Card scale (seven bands)"
    assert body["grade_changed"] is True

    row = (
        await session.execute(
            select(ResultEntry)
            .where(ResultEntry.id == approved_class.entries["Ada"].id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert row.grading_scale_id == approved_class.scale.id


async def test_a_correction_that_does_not_move_the_grade_says_so(
    client, admin, approved_class
) -> None:
    """Whether the card has to be reprinted is the question the admin is
    actually asking."""
    response = await client.patch(
        f"{API}/entries/{approved_class.entries['Ada'].id}",
        json={"reason": "One mark adrift.", "exam": "53"},
        headers=admin,
    )

    body = response.json()
    assert body["after"]["grade_letter"] == "A+"
    assert body["grade_changed"] is False


async def test_a_correction_still_obeys_r1(client, admin, approved_class) -> None:
    """A correction is still a score, and still has to fit the sheet."""
    over = await client.patch(
        f"{API}/entries/{approved_class.entries['Ada'].id}",
        json={"reason": "Trying it on.", "exam": "90"},
        headers=admin,
    )
    assert over.status_code == 422
    assert "between 0 and 60" in over.json()["detail"]

    wrong_column = await client.patch(
        f"{API}/entries/{approved_class.entries['Ada'].id}",
        json={"reason": "Wrong sheet.", "mid_term_test": "30"},
        headers=admin,
    )
    assert wrong_column.status_code == 422
    assert "no mid_term_test column" in wrong_column.json()["detail"]


async def test_a_correction_is_audited_with_before_and_after(
    client, admin, approved_class, session
) -> None:
    """§4.9 asks for before/after values on a post-publication edit — the one
    audited action whose payload carries scores, because "what did this card
    say before?" cannot be answered without them."""
    await client.patch(
        f"{API}/entries/{approved_class.entries['Ada'].id}",
        json={"reason": "Transposed digits on the mark sheet.", "exam": "40"},
        headers=admin,
    )

    rows = (
        (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "result_entries.edited_after_publication")
            )
        )
        .scalars()
        .all()
    )

    assert len(rows) == 1
    assert rows[0].reason == "Transposed digits on the mark sheet."
    assert rows[0].before["exam"] == "54.00"
    assert rows[0].after["exam"] == "40.00"
    assert rows[0].before["grade_letter"] == "A+"
    assert rows[0].actor_id == approved_class.admin.id


# ---------------------------------------------------------------------------
# §4.9 — every action audited
# ---------------------------------------------------------------------------


async def test_publishing_and_withholding_are_audited(
    client, admin, approved_class, session
) -> None:
    """§4.9: "every publish, withhold and release"."""
    await publish(
        client,
        admin,
        approved_class,
        withhold=[approved_class.pupils["Ada"].id],
        reason="Fees outstanding.",
    )

    actions = [
        row.action
        for row in (await session.execute(select(AuditLog).order_by(AuditLog.created_at)))
        .scalars()
        .all()
    ]

    assert "class.published" in actions
    assert "term_report.withheld" in actions


async def test_a_release_is_audited_with_the_reason_it_was_held_for(
    client, admin, approved_class, session
) -> None:
    """ "Why was this held back" survives the release, which is when somebody
    asks."""
    await publish(
        client,
        admin,
        approved_class,
        withhold=[approved_class.pupils["Ada"].id],
        reason="Fees outstanding.",
    )
    report = report_of(await publication_state(client, admin, approved_class), "Ada")
    await client.post(f"{API}/reports/{report['report_id']}/release", headers=admin)

    row = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "term_report.released")))
        .scalars()
        .one()
    )

    assert row.before["state"] == "withheld"
    assert row.after["state"] == "published"
    assert row.reason == "Fees outstanding."


async def test_the_audit_log_reads_back_newest_first(client, admin, approved_class) -> None:
    await publish(client, admin, approved_class)
    await client.patch(
        f"{API}/entries/{approved_class.entries['Ada'].id}",
        json={"reason": "A correction.", "exam": "50"},
        headers=admin,
    )

    response = await client.get(f"{API}/audit", headers=admin)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 2
    assert body["entries"][0]["action"] == "result_entries.edited_after_publication"
    assert body["entries"][0]["actor_name"] == "The Admin"
    assert body["entries"][0]["reason"] == "A correction."


async def test_the_audit_log_filters_by_entity(client, admin, approved_class) -> None:
    """§4.9's own index is `(entity_type, entity_id, created_at DESC)`, and §7
    exposes exactly those two filters: "what has happened to this report"."""
    await publish(
        client,
        admin,
        approved_class,
        withhold=[approved_class.pupils["Ada"].id],
        reason="Fees outstanding.",
    )
    report = report_of(await publication_state(client, admin, approved_class), "Ada")

    response = await client.get(
        f"{API}/audit",
        params={"entity_type": "term_report", "entity_id": report["report_id"]},
        headers=admin,
    )

    assert response.status_code == 200
    entries = response.json()["entries"]
    assert entries
    assert all(entry["entity_type"] == "term_report" for entry in entries)
    assert all(entry["entity_id"] == report["report_id"] for entry in entries)


async def test_the_audit_log_pages(client, admin, approved_class) -> None:
    await publish(client, admin, approved_class)

    page = await client.get(f"{API}/audit", params={"limit": 1}, headers=admin)

    assert page.status_code == 200
    assert len(page.json()["entries"]) == 1
    assert page.json()["total"] > 1
    assert page.json()["limit"] == 1


async def test_the_head_teacher_reads_the_log_but_cannot_act_on_it(
    client, admin, login, approved_class
) -> None:
    """§5.2 marks their access read-only. In a GET-only resource that is the
    same rows; what makes it read-only is that there is no verb to write one,
    and `services/audit.py` is the only writer in the codebase."""
    await publish(client, admin, approved_class)
    signed_in = await login(approved_class.head.email, TEST_PASSWORD)
    head = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}

    readable = await client.get(f"{API}/audit", headers=head)
    assert readable.status_code == 200
    assert readable.json()["total"] > 0

    # And they may not publish, which is the other half of §1.6.
    refused = await client.post(
        f"{API}/classes/{approved_class.klass.id}/publish",
        params={"term_id": str(approved_class.term.id)},
        json={"withhold_pupil_ids": [], "reason": None},
        headers=head,
    )
    assert refused.status_code == 403


async def test_the_log_stays_inside_one_school(
    client, admin, headers_for, approved_class, session, password_hash
) -> None:
    """§2.2. An audit log that crossed schools would be the worst possible
    leak: it carries before/after scores."""
    from app.models import School

    other_school = School(name="Another School", short_name="AS")
    session.add(other_school)
    await session.flush()
    intruder = User(
        school_id=other_school.id,
        role=UserRole.ADMIN,
        full_name="Elsewhere",
        email="admin@other.test",
        password_hash=password_hash,
        must_change_password=False,
    )
    session.add(intruder)
    await session.commit()

    await publish(client, admin, approved_class)

    headers = await headers_for(intruder)
    response = await client.get(f"{API}/audit", headers=headers)

    assert response.status_code == 200
    entries = response.json()["entries"]
    # Not zero: their own sign-in is audited, and that row is theirs. What
    # must not be there is anything belonging to the other school.
    assert entries
    assert all(entry["action"].startswith("login") for entry in entries)
    assert all(entry["actor_id"] == str(intruder.id) for entry in entries)
    assert str(approved_class.klass.id) not in response.text


# ---------------------------------------------------------------------------
# Reaching R13's verb at all (D75)
# ---------------------------------------------------------------------------


async def test_the_admin_can_find_the_entry_to_correct(client, admin, approved_class) -> None:
    """§7 lists `PATCH /entries/{id}` and no admin route that yields an id:
    the grid is teacher-only (§5.2) and the review payload is the head
    teacher's. Without this the verb is unreachable."""
    response = await client.get(
        f"{API}/pupils/{approved_class.pupils['Ada'].id}/entries",
        params={"term_id": str(approved_class.term.id)},
        headers=admin,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["first_name"] == "Ada"
    row = body["rows"][0]
    assert row["entry_id"] == str(approved_class.entries["Ada"].id)
    assert row["subject_name"] == "Mathematics"
    assert row["half"] == "second_half"
    assert row["exam"] == "54.00"
    assert row["grade_letter"] == "A+"
    assert row["is_snapshot"] is True
    assert row["columns"][-1] == "exam"


async def test_the_lookup_and_the_correction_fit_together(client, admin, approved_class) -> None:
    """The point of the lookup: its output is the PATCH's input."""
    listing = await client.get(
        f"{API}/pupils/{approved_class.pupils['Ada'].id}/entries",
        params={"term_id": str(approved_class.term.id)},
        headers=admin,
    )
    row = listing.json()["rows"][0]

    corrected = await client.patch(
        f"{API}/entries/{row['entry_id']}",
        json={"reason": "Transposed digits.", "exam": "40"},
        headers=admin,
    )

    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["after"]["exam"] == "40.00"


async def test_a_pupil_in_another_school_is_not_found(
    client, headers_for, approved_class, session, password_hash
) -> None:
    from app.models import School

    other_school = School(name="Another School", short_name="AS")
    session.add(other_school)
    await session.flush()
    intruder = User(
        school_id=other_school.id,
        role=UserRole.ADMIN,
        full_name="Elsewhere",
        email="admin2@other.test",
        password_hash=password_hash,
        must_change_password=False,
    )
    session.add(intruder)
    await session.commit()
    headers = await headers_for(intruder)

    response = await client.get(
        f"{API}/pupils/{approved_class.pupils['Ada'].id}/entries",
        params={"term_id": str(approved_class.term.id)},
        headers=headers,
    )

    assert response.status_code == 404
