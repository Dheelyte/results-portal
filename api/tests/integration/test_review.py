"""Head teacher review, approval and the grade snapshot
(ARCHITECTURE.md §8.4, §4.5, §6 R4, R11, R14).

§12's criterion: "Approval writes `grade_letter` and `grading_scale_id` on
every row."

The snapshot is the only irreversible step in this system, and §4.5 says why
in as many words: "if the school later changes a boundary, last term's printed
cards must still say what was printed". So the tests that matter most here are
the ones that change the scale *after* approval and prove the card does not
move.
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
    AttendanceRecord,
    AuditLog,
    Class,
    ClassSubject,
    ClassTeacher,
    ClassTermState,
    ClassTermStatus,
    Enrollment,
    GradeBand,
    GradingScale,
    GrowthRecord,
    House,
    MarksObtainable,
    NarrativeEntry,
    NarrativeSection,
    Pupil,
    ResultEntry,
    Subject,
    TeachingAssignment,
    Term,
    TermHalf,
    TermNumber,
    TermReport,
    User,
    UserRole,
)
from tests.conftest import TEST_PASSWORD

API = settings.api_v1_prefix

OPENED = 60
CA_MAX = Decimal(20)
TERMINAL_MAX = Decimal(60)

# Two pupils with deliberately different averages, so one band change can be
# shown to move one of them and not the other.
#  Ada:   20 + 20 + 54 = 94 of 100
#  Bello: 10 + 10 + 30 = 50 of 100
SCORES = {
    "Ada": (Decimal(20), Decimal(20), Decimal(54)),
    "Bello": (Decimal(10), Decimal(10), Decimal(30)),
}


@pytest.fixture
async def submitted_class(session: AsyncSession, school, password_hash: str, request):
    """A class in `submitted`, complete, with a known grading scale.

    Parametrised by term number so the third-term promotion field can be
    tested without a second fixture: `request.param` is the TermNumber, and
    defaults to first term.
    """
    from types import SimpleNamespace

    number = getattr(request, "param", TermNumber.FIRST)

    def user(role: UserRole, name: str, email: str) -> User:
        record = User(
            school_id=school.id,
            role=role,
            full_name=name,
            email=email,
            password_hash=password_hash,
            must_change_password=False,
        )
        session.add(record)
        return record

    head = user(UserRole.HEAD_TEACHER, "The Head", "head@sshms.test")
    class_teacher = user(UserRole.TEACHER, "Mrs Class Teacher", "ct@sshms.test")
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
        number=number,
        starts_on=dt.date(2026, 9, 14),
        ends_on=dt.date(2026, 12, 11),
        times_school_opened=OPENED,
        is_current=True,
    )
    house = House(school_id=school.id, name="Blue")
    klass = Class(school_id=school.id, name="Primary 4", level_order=4)
    session.add_all([term, house, klass])
    await session.flush()

    session.add(
        ClassTeacher(
            school_id=school.id,
            class_id=klass.id,
            academic_session_id=academic_session.id,
            teacher_user_id=class_teacher.id,
        )
    )

    periods = {}
    for half in TermHalf:
        period = AssessmentPeriod(school_id=school.id, term_id=term.id, half=half)
        session.add(period)
        periods[half] = period
    await session.flush()

    for half, period in periods.items():
        session.add(
            MarksObtainable(
                school_id=school.id,
                assessment_period_id=period.id,
                class_id=None,
                ca_test_1=CA_MAX,
                ca_test_2=CA_MAX,
                mid_term_test=TERMINAL_MAX if half is TermHalf.FIRST_HALF else None,
                exam=TERMINAL_MAX if half is TermHalf.SECOND_HALF else None,
            )
        )

    # The card's seven bands (§1.3), which the snapshot tests then change.
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

    english = Subject(school_id=school.id, name="English", is_group=True, display_order=0)
    maths = Subject(school_id=school.id, name="Mathematics", display_order=1)
    session.add_all([english, maths])
    await session.flush()

    offerings = {}
    for subject in (english, maths):
        offering = ClassSubject(
            school_id=school.id,
            class_id=klass.id,
            subject_id=subject.id,
            academic_session_id=academic_session.id,
        )
        session.add(offering)
        await session.flush()
        offerings[subject.name] = offering
    session.add(
        TeachingAssignment(
            school_id=school.id,
            class_subject_id=offerings["Mathematics"].id,
            teacher_user_id=class_teacher.id,
        )
    )

    section = NarrativeSection(
        school_id=school.id, code="B", label="Work/Study Habits", display_order=0
    )
    session.add(section)
    await session.flush()

    pupils = {}
    for index, name in enumerate(SCORES, start=1):
        pupil = Pupil(
            school_id=school.id,
            admission_number=f"SSHMS/2026/{index:03d}",
            first_name=name,
            last_name="Okafor",
            house_id=house.id,
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

        ca_1, ca_2, terminal = SCORES[name]
        for half, period in periods.items():
            session.add(
                ResultEntry(
                    school_id=school.id,
                    assessment_period_id=period.id,
                    pupil_id=pupil.id,
                    class_subject_id=offerings["Mathematics"].id,
                    ca_test_1=ca_1,
                    ca_test_2=ca_2,
                    mid_term_test=terminal if half is TermHalf.FIRST_HALF else None,
                    exam=terminal if half is TermHalf.SECOND_HALF else None,
                    period_average=(ca_1 + ca_2 + terminal),  # out of 100
                )
            )
        session.add(
            NarrativeEntry(
                school_id=school.id,
                term_id=term.id,
                pupil_id=pupil.id,
                section_id=section.id,
                body="Has worked steadily this term.",
            )
        )
        session.add(
            AttendanceRecord(
                school_id=school.id,
                term_id=term.id,
                pupil_id=pupil.id,
                times_present=OPENED - 2,
                times_absent=2,
                times_late=1,
            )
        )
        session.add(
            GrowthRecord(
                school_id=school.id,
                term_id=term.id,
                pupil_id=pupil.id,
                height_start_m=Decimal("1.18"),
                height_end_m=Decimal("1.22"),
                weight_start_kg=Decimal("24.50"),
                weight_end_kg=Decimal("25.80"),
            )
        )
        session.add(
            TermReport(
                school_id=school.id,
                term_id=term.id,
                pupil_id=pupil.id,
                class_id=klass.id,
                class_teacher_comment="A purposeful term.",
                no_in_class=len(SCORES),
            )
        )
        pupils[name] = pupil

    session.add(
        ClassTermStatus(
            school_id=school.id,
            class_id=klass.id,
            term_id=term.id,
            state=ClassTermState.SUBMITTED,
            submitted_at=dt.datetime(2026, 12, 12, 9, 0, tzinfo=dt.UTC),
            submitted_by=class_teacher.id,
        )
    )

    await session.commit()

    return SimpleNamespace(
        term=term,
        klass=klass,
        head=head,
        class_teacher=class_teacher,
        pupils=pupils,
        scale=scale,
        section=section,
        periods=periods,
        maths=offerings["Mathematics"],
        english=offerings["English"],
        house=house,
    )


@pytest.fixture
async def head(client: AsyncClient, login, submitted_class) -> dict[str, str]:
    response = await login(submitted_class.head.email, TEST_PASSWORD)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def review(client, headers, submitted_class):
    response = await client.get(
        f"{API}/classes/{submitted_class.klass.id}/review",
        params={"term_id": str(submitted_class.term.id)},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def approve(client, headers, submitted_class):
    return await client.post(
        f"{API}/classes/{submitted_class.klass.id}/approve",
        params={"term_id": str(submitted_class.term.id)},
        headers=headers,
    )


def card_of(body, name: str) -> dict:
    return next(card for card in body["cards"] if card["first_name"] == name)


def maths_half(card: dict, half: str = "second_half") -> dict:
    row = next(row for row in card["subjects"] if row["subject_name"] == "Mathematics")
    return row["halves"][half]


# ---------------------------------------------------------------------------
# The queue (§8.4)
# ---------------------------------------------------------------------------


async def test_the_queue_lists_submitted_classes(client, head, submitted_class) -> None:
    response = await client.get(
        f"{API}/review/queue",
        params={"term_id": str(submitted_class.term.id)},
        headers=head,
    )

    assert response.status_code == 200, response.text
    entry = response.json()[0]
    assert entry["class_name"] == "Primary 4"
    assert entry["state"] == "submitted"
    assert entry["roll"] == len(SCORES)
    assert entry["submitted_by"] == "Mrs Class Teacher"
    assert entry["submitted_at"] is not None
    assert entry["remarks_written"] == 0


async def test_a_class_still_being_worked_on_is_not_in_the_queue(
    client, head, submitted_class, session
) -> None:
    status = (
        await session.execute(
            select(ClassTermStatus).where(ClassTermStatus.class_id == submitted_class.klass.id)
        )
    ).scalar_one()
    status.state = ClassTermState.IN_PROGRESS
    await session.commit()

    response = await client.get(
        f"{API}/review/queue",
        params={"term_id": str(submitted_class.term.id)},
        headers=head,
    )

    assert response.json() == []


# ---------------------------------------------------------------------------
# The card (§8.4)
# ---------------------------------------------------------------------------


async def test_the_card_shows_what_the_parent_will_see(client, head, submitted_class) -> None:
    """§8.4: "each pupil's card as the parent will see it"."""
    body = await review(client, head, submitted_class)

    assert body["state"] == "submitted"
    assert len(body["cards"]) == len(SCORES)

    ada = card_of(body, "Ada")
    assert ada["house_name"] == "Blue"
    assert ada["no_in_class"] == len(SCORES)
    assert ada["class_teacher_comment"] == "A purposeful term."
    assert ada["attendance"]["times_school_opened"] == OPENED
    assert ada["attendance"]["times_present"] == OPENED - 2
    assert ada["growth"]["height_end_m"] == "1.22"
    assert [p["label"] for p in ada["narrative"]] == ["Work/Study Habits"]
    assert ada["narrative"][0]["body"] == "Has worked steadily this term."


async def test_the_card_carries_both_sheets_per_subject(client, head, submitted_class) -> None:
    ada = card_of(await review(client, head, submitted_class), "Ada")
    maths = next(row for row in ada["subjects"] if row["subject_name"] == "Mathematics")

    assert set(maths["halves"]) == {"first_half", "second_half"}
    assert maths["halves"]["first_half"]["mid_term_test"] == "54.00"
    assert maths["halves"]["second_half"]["exam"] == "54.00"
    assert maths["halves"]["first_half"]["ca_test_total"] == "40.00"


async def test_a_group_heading_is_a_row_with_no_figures(client, head, submitted_class) -> None:
    """R7, as the card renders it: English spans its sub-rows and scores
    nothing of its own."""
    ada = card_of(await review(client, head, submitted_class), "Ada")
    english = next(row for row in ada["subjects"] if row["subject_name"] == "English")

    assert english["is_group"] is True
    assert english["halves"] == {}


async def test_before_approval_the_grade_is_resolved_live(client, head, submitted_class) -> None:
    """R4: "Resolved from the active scale before approval"."""
    body = await review(client, head, submitted_class)

    ada = maths_half(card_of(body, "Ada"))
    bello = maths_half(card_of(body, "Bello"))

    assert ada["period_average"] == "94.00"
    assert ada["grade_letter"] == "A+"
    assert ada["grade_remark"] == "Excellence"
    assert ada["is_snapshot"] is False

    assert bello["period_average"] == "50.00"
    assert bello["grade_letter"] == "C"
    assert bello["is_snapshot"] is False


# ---------------------------------------------------------------------------
# The snapshot (§4.5, §12's criterion)
# ---------------------------------------------------------------------------


async def test_approval_writes_a_grade_and_a_scale_on_every_row(
    client, head, submitted_class, session
) -> None:
    """Milestone 9's criterion, asserted against the rows themselves."""
    response = await approve(client, head, submitted_class)

    assert response.status_code == 200, response.text
    snapshot = response.json()["snapshot"]
    assert snapshot["grading_scale_name"] == "Card scale (seven bands)"
    assert snapshot["rows"] == len(SCORES) * 2  # two pupils, two halves
    assert snapshot["graded"] == snapshot["rows"]
    assert snapshot["ungraded"] == 0

    rows = (
        (await session.execute(select(ResultEntry).execution_options(populate_existing=True)))
        .scalars()
        .all()
    )
    assert len(rows) == len(SCORES) * 2
    assert all(row.grade_letter is not None for row in rows)
    assert all(row.grading_scale_id == submitted_class.scale.id for row in rows)


async def test_the_snapshotted_letters_are_the_right_ones(
    client, head, submitted_class, session
) -> None:
    await approve(client, head, submitted_class)

    rows = (
        await session.execute(
            select(ResultEntry, Pupil.first_name)
            .join(Pupil, Pupil.id == ResultEntry.pupil_id)
            .execution_options(populate_existing=True)
        )
    ).all()
    letters = {name: row.grade_letter for row, name in rows}

    assert letters == {"Ada": "A+", "Bello": "C"}


async def test_changing_the_scale_after_approval_does_not_move_a_printed_grade(
    client, head, submitted_class, session
) -> None:
    """§4.5's whole reason for existing, and CLAUDE.md rule 6.

    The school moves the A+ boundary from 90 to 95 — which would make Ada's
    94 an A — and activates the new scale. The card still says A+, because a
    parent is holding one that says A+.
    """
    await approve(client, head, submitted_class)

    stricter = GradingScale(
        school_id=submitted_class.klass.school_id,
        name="Stricter scale",
        effective_from=dt.date(2027, 1, 1),
        is_active=True,
    )
    session.add(stricter)
    submitted_class.scale.is_active = False
    await session.flush()
    for order, (letter, remark, low, high) in enumerate(
        [("A+", "Excellence", 95, 100), ("A", "Very Good", 0, 94)]
    ):
        session.add(
            GradeBand(
                scale_id=stricter.id,
                letter=letter,
                remark=remark,
                min_score=Decimal(low),
                max_score=Decimal(high),
                sort_order=order,
            )
        )
    await session.commit()

    body = await review(client, head, submitted_class)
    ada = maths_half(card_of(body, "Ada"))

    assert ada["grade_letter"] == "A+", "the printed grade must not move"
    assert ada["is_snapshot"] is True

    # And the row still records which scale it was frozen against, so the
    # grade can be explained years later.
    row = (
        await session.execute(
            select(ResultEntry)
            .where(ResultEntry.pupil_id == submitted_class.pupils["Ada"].id)
            .limit(1)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert row.grading_scale_id == submitted_class.scale.id
    assert row.grading_scale_id != stricter.id


async def test_approval_refuses_when_no_scale_is_active(
    client, head, submitted_class, session
) -> None:
    """Approving against no scale would freeze a class's grades as blank, and
    §4.5 gives no way to put that right."""
    submitted_class.scale.is_active = False
    await session.commit()

    response = await approve(client, head, submitted_class)

    assert response.status_code == 409
    assert "No grading scale is active" in response.json()["detail"]

    rows = (await session.execute(select(ResultEntry))).scalars().all()
    assert all(row.grade_letter is None for row in rows), "nothing was frozen"


async def test_a_failed_approval_leaves_the_class_submitted(
    client, head, submitted_class, session
) -> None:
    """The snapshot and the state change are one transaction. A class approved
    with no grades on it could only be fixed by recomputing, which is the one
    thing §4.5 forbids."""
    submitted_class.scale.is_active = False
    await session.commit()

    await approve(client, head, submitted_class)

    status = (
        await session.execute(select(ClassTermStatus).execution_options(populate_existing=True))
    ).scalar_one()
    assert status.state is ClassTermState.SUBMITTED


async def test_approval_freezes_the_overall_percentage(
    client, head, submitted_class, session
) -> None:
    """A25. R6's definition is unconfirmed, so the figure is a placeholder —
    but it is frozen at the same moment and for the same reason as the
    grades: it prints in the card's header."""
    before = card_of(await review(client, head, submitted_class), "Ada")
    assert before["overall_percentage"] is None

    await approve(client, head, submitted_class)

    after = card_of(await review(client, head, submitted_class), "Ada")
    # One scored subject, second-half average 94.
    assert after["overall_percentage"] == "94.00"


async def test_a_class_cannot_be_approved_twice(client, head, submitted_class) -> None:
    assert (await approve(client, head, submitted_class)).status_code == 200

    again = await approve(client, head, submitted_class)

    assert again.status_code == 409
    assert "submitted for review" in again.json()["detail"]


async def test_a_class_in_progress_cannot_be_approved(
    client, head, submitted_class, session
) -> None:
    status = (await session.execute(select(ClassTermStatus))).scalar_one()
    status.state = ClassTermState.IN_PROGRESS
    await session.commit()

    response = await approve(client, head, submitted_class)

    assert response.status_code == 409
    assert "in progress" in response.json()["detail"]


async def test_the_snapshot_is_audited_with_the_scale(
    client, head, submitted_class, session
) -> None:
    """ "Which scale were these grades frozen against" needs a row of its own."""
    await approve(client, head, submitted_class)

    rows = (
        (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "result_entries.grades_snapshotted")
            )
        )
        .scalars()
        .all()
    )

    assert len(rows) == 1
    assert rows[0].after["grading_scale_id"] == str(submitted_class.scale.id)
    assert rows[0].after["graded"] == len(SCORES) * 2
    assert rows[0].actor_id == submitted_class.head.id
    assert "never recomputed" in rows[0].reason
    # No score, no letter, no pupil in the payload.
    assert "A+" not in str(rows[0].after)
    assert str(submitted_class.pupils["Ada"].id) not in str(rows[0].after)


# ---------------------------------------------------------------------------
# The remark, the position and the promotion (§8.4, R11)
# ---------------------------------------------------------------------------


async def test_the_head_teacher_writes_a_remark_and_a_position(
    client, head, submitted_class
) -> None:
    response = await client.put(
        f"{API}/classes/{submitted_class.klass.id}/remarks",
        params={"term_id": str(submitted_class.term.id)},
        json={
            "rows": [
                {
                    "pupil_id": str(submitted_class.pupils["Ada"].id),
                    "head_teacher_remark": "An excellent term. Keep it up.",
                    "position_text": "Upper band",
                }
            ]
        },
        headers=head,
    )

    assert response.status_code == 200, response.text
    ada = card_of(response.json(), "Ada")
    assert ada["head_teacher_remark"] == "An excellent term. Keep it up."
    assert ada["position_text"] == "Upper band"


async def test_the_position_is_free_text_and_never_a_rank(client, head, submitted_class) -> None:
    """R11: "Never computed. `position_text` is free text the head teacher may
    optionally enter. There is no ranking query anywhere in this codebase."

    Ada's average is higher than Bello's. Nothing offers to turn that into
    "1st of 2", and the field accepts whatever the school means by position —
    here a band, which is what the card's "Position (In grades)" suggests.
    """
    body = await review(client, head, submitted_class)
    assert all(card["position_text"] is None for card in body["cards"])

    response = await client.put(
        f"{API}/classes/{submitted_class.klass.id}/remarks",
        params={"term_id": str(submitted_class.term.id)},
        json={
            "rows": [
                {"pupil_id": str(submitted_class.pupils["Bello"].id), "position_text": "Middle"}
            ]
        },
        headers=head,
    )

    assert card_of(response.json(), "Bello")["position_text"] == "Middle"


async def test_remarks_can_be_written_after_approval(client, head, submitted_class) -> None:
    """D67. The remark is the head teacher's own, and a class is often
    approved before every remark is typed — R14's lock is on teachers."""
    await approve(client, head, submitted_class)

    response = await client.put(
        f"{API}/classes/{submitted_class.klass.id}/remarks",
        params={"term_id": str(submitted_class.term.id)},
        json={
            "rows": [
                {
                    "pupil_id": str(submitted_class.pupils["Ada"].id),
                    "head_teacher_remark": "Added after approval.",
                }
            ]
        },
        headers=head,
    )

    assert response.status_code == 200, response.text
    assert card_of(response.json(), "Ada")["head_teacher_remark"] == "Added after approval."


async def test_remarks_cannot_be_written_before_submission(
    client, head, submitted_class, session
) -> None:
    status = (await session.execute(select(ClassTermStatus))).scalar_one()
    status.state = ClassTermState.IN_PROGRESS
    await session.commit()

    response = await client.put(
        f"{API}/classes/{submitted_class.klass.id}/remarks",
        params={"term_id": str(submitted_class.term.id)},
        json={
            "rows": [
                {
                    "pupil_id": str(submitted_class.pupils["Ada"].id),
                    "head_teacher_remark": "Too early.",
                }
            ]
        },
        headers=head,
    )

    assert response.status_code == 409
    assert "nothing to remark on" in response.json()["detail"]


async def test_a_promotion_decision_is_refused_outside_third_term(
    client, head, submitted_class
) -> None:
    """§8.4 puts it in third term only. Refused rather than ignored: silently
    dropping it would have the head teacher believe it was recorded."""
    response = await client.put(
        f"{API}/classes/{submitted_class.klass.id}/remarks",
        params={"term_id": str(submitted_class.term.id)},
        json={
            "rows": [
                {
                    "pupil_id": str(submitted_class.pupils["Ada"].id),
                    "promotion_decision": "Promoted to Primary 5",
                }
            ]
        },
        headers=head,
    )

    assert response.status_code == 422
    errors = response.json()["errors"][str(submitted_class.pupils["Ada"].id)]
    assert "third term only" in errors["promotion_decision"]


@pytest.mark.parametrize("submitted_class", [TermNumber.THIRD], indirect=True)
async def test_a_promotion_decision_is_accepted_in_third_term(
    client, head, submitted_class
) -> None:
    assert (await review(client, head, submitted_class))["promotion_applies"] is True

    response = await client.put(
        f"{API}/classes/{submitted_class.klass.id}/remarks",
        params={"term_id": str(submitted_class.term.id)},
        json={
            "rows": [
                {
                    "pupil_id": str(submitted_class.pupils["Ada"].id),
                    "promotion_decision": "Promoted to Primary 5",
                }
            ]
        },
        headers=head,
    )

    assert response.status_code == 200, response.text
    assert card_of(response.json(), "Ada")["promotion_decision"] == "Promoted to Primary 5"


async def test_remarks_are_audited_without_their_text(
    client, head, submitted_class, session
) -> None:
    """A remark is written about a named child."""
    await client.put(
        f"{API}/classes/{submitted_class.klass.id}/remarks",
        params={"term_id": str(submitted_class.term.id)},
        json={
            "rows": [
                {
                    "pupil_id": str(submitted_class.pupils["Ada"].id),
                    "head_teacher_remark": "An excellent term.",
                }
            ]
        },
        headers=head,
    )

    rows = (
        (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "term_reports.head_teacher_remarks_saved")
            )
        )
        .scalars()
        .all()
    )

    assert len(rows) == 1
    assert rows[0].after["pupils"] == 1
    assert rows[0].after["fields"] == ["head_teacher_remark"]
    assert "excellent" not in str(rows[0].after)
    assert str(submitted_class.pupils["Ada"].id) not in str(rows[0].after)


# ---------------------------------------------------------------------------
# Return (§8.4, R14)
# ---------------------------------------------------------------------------


async def test_returning_a_class_reopens_it_with_the_note(client, head, submitted_class) -> None:
    response = await client.post(
        f"{API}/classes/{submitted_class.klass.id}/return",
        params={"term_id": str(submitted_class.term.id)},
        json={"note": "Bello's Mathematics looks transposed. Please check."},
        headers=head,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "returned"
    assert body["return_note"] == "Bello's Mathematics looks transposed. Please check."


async def test_a_return_needs_a_note(client, head, submitted_class) -> None:
    """R10's lesson: a class back with no explanation is a phone call, and the
    teacher has thirty cards to guess among."""
    blank = await client.post(
        f"{API}/classes/{submitted_class.klass.id}/return",
        params={"term_id": str(submitted_class.term.id)},
        json={"note": "   "},
        headers=head,
    )
    assert blank.status_code == 409
    assert "Say what needs changing" in blank.json()["detail"]

    missing = await client.post(
        f"{API}/classes/{submitted_class.klass.id}/return",
        params={"term_id": str(submitted_class.term.id)},
        json={},
        headers=head,
    )
    assert missing.status_code == 422


async def test_returning_does_not_snapshot_anything(client, head, submitted_class, session) -> None:
    """Only approval freezes a grade. A returned class is going back to be
    changed, and a frozen grade would make the change invisible."""
    await client.post(
        f"{API}/classes/{submitted_class.klass.id}/return",
        params={"term_id": str(submitted_class.term.id)},
        json={"note": "Please check Mathematics."},
        headers=head,
    )

    rows = (
        (await session.execute(select(ResultEntry).execution_options(populate_existing=True)))
        .scalars()
        .all()
    )

    assert all(row.grade_letter is None for row in rows)
    assert all(row.grading_scale_id is None for row in rows)


async def test_a_returned_class_is_writable_by_its_teacher_again(
    client, head, login, submitted_class
) -> None:
    """R14's loop, end to end: returned reopens the class for the teacher."""
    await client.post(
        f"{API}/classes/{submitted_class.klass.id}/return",
        params={"term_id": str(submitted_class.term.id)},
        json={"note": "Please check Mathematics."},
        headers=head,
    )

    signed_in = await login(submitted_class.class_teacher.email, TEST_PASSWORD)
    teacher = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}

    response = await client.put(
        f"{API}/classes/{submitted_class.klass.id}/comments",
        params={"term_id": str(submitted_class.term.id)},
        json={
            "rows": [
                {
                    "pupil_id": str(submitted_class.pupils["Ada"].id),
                    "comment": "Revised after the return.",
                }
            ]
        },
        headers=teacher,
    )

    assert response.status_code == 200, response.text


async def test_an_approved_class_cannot_be_returned(client, head, submitted_class) -> None:
    """Nothing reopens an approved class. R13's post-publication edit is the
    admin's, needs a reason, and is not a state change."""
    await approve(client, head, submitted_class)

    response = await client.post(
        f"{API}/classes/{submitted_class.klass.id}/return",
        params={"term_id": str(submitted_class.term.id)},
        json={"note": "Changed my mind."},
        headers=head,
    )

    assert response.status_code == 409


async def test_a_return_is_audited_with_its_note(client, head, submitted_class, session) -> None:
    """The note is about a class, not a child, and "why was this returned" is
    asked three weeks later."""
    await client.post(
        f"{API}/classes/{submitted_class.klass.id}/return",
        params={"term_id": str(submitted_class.term.id)},
        json={"note": "Mathematics looks transposed."},
        headers=head,
    )

    rows = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "class_term.returned")))
        .scalars()
        .all()
    )

    assert len(rows) == 1
    assert rows[0].after["note"] == "Mathematics looks transposed."
    assert rows[0].before["state"] == "submitted"


async def test_the_resubmitted_class_can_then_be_approved(
    client, head, login, submitted_class, session
) -> None:
    """The full loop: submitted → returned → submitted → approved, with the
    grades frozen only at the end."""
    await client.post(
        f"{API}/classes/{submitted_class.klass.id}/return",
        params={"term_id": str(submitted_class.term.id)},
        json={"note": "Please check Mathematics."},
        headers=head,
    )

    signed_in = await login(submitted_class.class_teacher.email, TEST_PASSWORD)
    teacher = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}
    resubmitted = await client.post(
        f"{API}/classes/{submitted_class.klass.id}/submit",
        params={"term_id": str(submitted_class.term.id)},
        headers=teacher,
    )
    assert resubmitted.status_code == 200, resubmitted.text

    approved = await approve(client, head, submitted_class)

    assert approved.status_code == 200, approved.text
    assert approved.json()["review"]["state"] == "approved"
    assert approved.json()["snapshot"]["graded"] == len(SCORES) * 2


async def test_the_queue_defaults_to_the_current_term(client, head, submitted_class) -> None:
    """D51's reasoning again: §5.2 gives `/terms` to the admin alone, so the
    head teacher has no id to pass."""
    response = await client.get(f"{API}/review/queue", headers=head)

    assert response.status_code == 200, response.text
    entry = response.json()[0]
    assert entry["term_id"] == str(submitted_class.term.id)
    assert entry["term_label"] == "First Term, 2026/2027"


async def test_with_no_current_term_the_queue_says_so(
    client, head, submitted_class, session
) -> None:
    submitted_class.term.is_current = False
    await session.commit()

    response = await client.get(f"{API}/review/queue", headers=head)

    assert response.status_code == 409
    assert "current one" in response.json()["detail"]


async def test_a_sub_subject_carries_its_heading_name(
    client, head, submitted_class, session
) -> None:
    """§9 prints "English as a spanning group heading over its five sub-rows".

    R7 keeps the heading out of `class_subjects` — it carries no scores, so it
    is never offered to a class — which means the card has nothing to put in
    that spanning row unless the name travels on the children.
    """
    from app.models import Subject

    english = (await session.execute(select(Subject).where(Subject.name == "English"))).scalar_one()
    language_arts = Subject(
        school_id=submitted_class.klass.school_id,
        name="Language Arts",
        parent_subject_id=english.id,
        display_order=2,
    )
    session.add(language_arts)
    await session.flush()
    session.add(
        ClassSubject(
            school_id=submitted_class.klass.school_id,
            class_id=submitted_class.klass.id,
            subject_id=language_arts.id,
            academic_session_id=submitted_class.term.academic_session_id,
        )
    )
    await session.commit()

    ada = card_of(await review(client, head, submitted_class), "Ada")
    row = next(r for r in ada["subjects"] if r["subject_name"] == "Language Arts")

    assert row["parent_subject_id"] == str(english.id)
    assert row["parent_subject_name"] == "English"
    assert row["is_group"] is False
