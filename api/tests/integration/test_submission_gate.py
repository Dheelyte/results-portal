"""R10, the submission gate (ARCHITECTURE.md §6 R10, §8.3, §7, R14).

§12's criterion: "Submission blocked with an accurate missing-items list,
allowed when complete."

**Accurate** is the word these tests are built around. R10 says what a plain
refusal costs: "'Cannot submit' with no explanation generates support calls
every term." So most of what follows is not "does it refuse" but "does it say
the right thing" — and, just as important, does it stop saying it once the
work is done.

The fixture builds a class that is one step from ready, and each test knocks
out exactly one requirement.
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
    GrowthRecord,
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
CA_MAX = Decimal(8)
TERMINAL_MAX = Decimal(60)
ROLL = ["Adeyemi", "Bello"]


@pytest.fixture
async def ready_class(session: AsyncSession, school, password_hash: str):
    """A class that satisfies R10 completely. Each test breaks one thing.

    Two pupils rather than thirty: R10 is a conjunction, and two is enough to
    show that the list names the right child.
    """
    from types import SimpleNamespace

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

    class_teacher = user(UserRole.TEACHER, "Mrs Class Teacher", "ct@sshms.test")
    other_teacher = user(UserRole.TEACHER, "Mr Other", "other@sshms.test")
    head = user(UserRole.HEAD_TEACHER, "The Head", "head@sshms.test")
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
        times_school_opened=OPENED,
        is_current=True,
    )
    klass = Class(school_id=school.id, name="Primary 4", level_order=4)
    session.add_all([term, klass])
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

    # Two scored subjects and a group heading, which R7 excludes from the gate.
    maths = Subject(school_id=school.id, name="Mathematics", display_order=1)
    english = Subject(school_id=school.id, name="English", is_group=True, display_order=0)
    session.add_all([maths, english])
    await session.flush()

    offerings = {}
    for subject, teacher in ((maths, other_teacher), (english, None)):
        offering = ClassSubject(
            school_id=school.id,
            class_id=klass.id,
            subject_id=subject.id,
            academic_session_id=academic_session.id,
        )
        session.add(offering)
        await session.flush()
        if teacher is not None:
            session.add(
                TeachingAssignment(
                    school_id=school.id,
                    class_subject_id=offering.id,
                    teacher_user_id=teacher.id,
                )
            )
        offerings[subject.name] = offering

    # Two narrative sections, both the class teacher's by absence of an
    # assignment (D15).
    sections = [
        NarrativeSection(school_id=school.id, code="B", label="Work/Study Habits", display_order=0),
        NarrativeSection(school_id=school.id, code="C", label="Attitude", display_order=1),
    ]
    session.add_all(sections)
    await session.flush()

    pupils = []
    for index, surname in enumerate(ROLL, start=1):
        pupil = Pupil(
            school_id=school.id,
            admission_number=f"SSHMS/2026/{index:03d}",
            first_name="Pupil",
            last_name=surname,
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
        pupils.append(pupil)

    # Everything R10 asks for, for every pupil.
    for pupil in pupils:
        for half, period in periods.items():
            session.add(
                ResultEntry(
                    school_id=school.id,
                    assessment_period_id=period.id,
                    pupil_id=pupil.id,
                    class_subject_id=offerings["Mathematics"].id,
                    ca_test_1=Decimal(7),
                    ca_test_2=Decimal(6),
                    mid_term_test=Decimal(50) if half is TermHalf.FIRST_HALF else None,
                    exam=Decimal(52) if half is TermHalf.SECOND_HALF else None,
                )
            )
        for section in sections:
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
            )
        )
        session.add(
            GrowthRecord(
                school_id=school.id,
                term_id=term.id,
                pupil_id=pupil.id,
                height_start_m=Decimal("1.18"),
                weight_start_kg=Decimal("24.50"),
            )
        )
        session.add(
            TermReport(
                school_id=school.id,
                term_id=term.id,
                pupil_id=pupil.id,
                class_id=klass.id,
                class_teacher_comment="A purposeful term.",
            )
        )

    session.add(
        ClassTermStatus(
            school_id=school.id,
            class_id=klass.id,
            term_id=term.id,
            state=ClassTermState.IN_PROGRESS,
        )
    )

    await session.commit()

    return SimpleNamespace(
        term=term,
        klass=klass,
        class_teacher=class_teacher,
        other_teacher=other_teacher,
        head=head,
        pupils=pupils,
        sections=sections,
        periods=periods,
        maths=offerings["Mathematics"],
        english=offerings["English"],
    )


@pytest.fixture
async def teacher(client: AsyncClient, login, ready_class) -> dict[str, str]:
    response = await login(ready_class.class_teacher.email, TEST_PASSWORD)
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def progress(client, headers, ready_class):
    response = await client.get(
        f"{API}/classes/{ready_class.klass.id}/progress",
        params={"term_id": str(ready_class.term.id)},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def submit(client, headers, ready_class):
    return await client.post(
        f"{API}/classes/{ready_class.klass.id}/submit",
        params={"term_id": str(ready_class.term.id)},
        headers=headers,
    )


def kinds(body) -> set[str]:
    return {item["kind"] for item in body["outstanding"]}


def whats(body) -> str:
    return " | ".join(item["what"] for item in body["outstanding"])


# ---------------------------------------------------------------------------
# The happy path, first — so the fixture is known good
# ---------------------------------------------------------------------------


async def test_a_complete_class_is_ready_and_submits(client, teacher, ready_class) -> None:
    body = await progress(client, teacher, ready_class)

    assert body["outstanding"] == [], whats(body)
    assert body["ready"] is True
    assert body["may_submit"] is True
    assert body["state"] == "in_progress"

    response = await submit(client, teacher, ready_class)

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "submitted"


async def test_the_progress_page_lists_every_subject_and_its_owner(
    client, teacher, ready_class
) -> None:
    """§8.3: "every subject with its state and owner, for both assessment
    periods"."""
    body = await progress(client, teacher, ready_class)

    # One row per scored subject per half. The English heading is excluded by
    # R7 — a heading carries no scores, so it cannot be incomplete.
    assert len(body["sheets"]) == 2
    assert {sheet["subject_name"] for sheet in body["sheets"]} == {"Mathematics"}
    assert {sheet["half"] for sheet in body["sheets"]} == {"first_half", "second_half"}
    assert all(sheet["teacher_name"] == "Mr Other" for sheet in body["sheets"])
    assert all(sheet["is_complete"] for sheet in body["sheets"])
    assert all(sheet["roll"] == len(ROLL) for sheet in body["sheets"])


async def test_a_group_heading_is_never_a_blocker(client, teacher, ready_class) -> None:
    """R7. English is offered to the class and has no scores at all, and the
    class is still ready."""
    body = await progress(client, teacher, ready_class)

    assert str(ready_class.english.id) not in str(body["sheets"])
    assert body["ready"] is True


# ---------------------------------------------------------------------------
# One requirement at a time
# ---------------------------------------------------------------------------


async def test_a_missing_score_blocks_and_names_the_pupil(
    client, teacher, ready_class, session
) -> None:
    """R10's first condition, and the list has to be specific enough to act on."""
    await session.execute(
        ResultEntry.__table__.delete().where(
            ResultEntry.pupil_id == ready_class.pupils[0].id,
            ResultEntry.assessment_period_id == ready_class.periods[TermHalf.FIRST_HALF].id,
        )
    )
    await session.commit()

    body = await progress(client, teacher, ready_class)

    assert body["ready"] is False
    assert "scores" in kinds(body)
    item = next(i for i in body["outstanding"] if i["kind"] == "scores")
    assert "Mathematics" in item["what"]
    assert "First Half Term" in item["what"]
    assert "1 of 2" in item["what"]
    # Who to chase, and whose sheet it is.
    assert "Adeyemi" in item["detail"]
    assert item["teacher"] == "Mr Other"

    response = await submit(client, teacher, ready_class)
    assert response.status_code == 422
    assert response.json()["outstanding"] == body["outstanding"]


async def test_a_half_entered_row_is_not_complete(client, teacher, ready_class, session) -> None:
    """A23: every column with a maximum, not merely "has an average".

    R2 treats a blank as zero, so a row missing one CA test still produces a
    figure — and nobody notices until a parent compares the card with the
    paper sheet.
    """
    entry = (
        await session.execute(
            select(ResultEntry).where(
                ResultEntry.pupil_id == ready_class.pupils[0].id,
                ResultEntry.assessment_period_id == ready_class.periods[TermHalf.FIRST_HALF].id,
            )
        )
    ).scalar_one()
    entry.ca_test_2 = None
    await session.commit()

    body = await progress(client, teacher, ready_class)

    assert body["ready"] is False
    assert "1 of 2 pupils incomplete" in whats(body)


async def test_a_column_with_no_maximum_is_not_required(
    client, teacher, ready_class, session
) -> None:
    """The other side of A23: the school decides which columns exist.

    A school using two CA tests sets two maxima, and nobody is blocked for
    leaving CA tests 3 to 5 empty.
    """
    body = await progress(client, teacher, ready_class)

    first = next(s for s in body["sheets"] if s["half"] == "first_half")
    assert first["columns"] == ["ca_test_1", "ca_test_2", "mid_term_test"]
    assert body["ready"] is True


async def test_a_missing_narrative_section_blocks_and_names_it(
    client, teacher, ready_class, session
) -> None:
    """R8 through R10, and the list names the section, not just the pupil."""
    await session.execute(
        NarrativeEntry.__table__.delete().where(
            NarrativeEntry.pupil_id == ready_class.pupils[1].id,
            NarrativeEntry.section_id == ready_class.sections[1].id,
        )
    )
    await session.commit()

    body = await progress(client, teacher, ready_class)

    assert body["ready"] is False
    item = next(i for i in body["outstanding"] if i["kind"] == "pupil")
    assert "Bello" in item["what"]
    assert "Attitude" in item["what"]
    assert item["pupil_id"] == str(ready_class.pupils[1].id)


async def test_an_empty_narrative_body_does_not_count(
    client, teacher, ready_class, session
) -> None:
    """R8: complete means a non-empty body. Whitespace is not an assessment."""
    entry = (
        await session.execute(
            select(NarrativeEntry).where(
                NarrativeEntry.pupil_id == ready_class.pupils[0].id,
                NarrativeEntry.section_id == ready_class.sections[0].id,
            )
        )
    ).scalar_one()
    entry.body = "   \n "
    await session.commit()

    body = await progress(client, teacher, ready_class)

    assert body["ready"] is False
    assert "Work/Study Habits" in whats(body)


async def test_a_missing_comment_blocks(client, teacher, ready_class, session) -> None:
    report = (
        await session.execute(
            select(TermReport).where(TermReport.pupil_id == ready_class.pupils[0].id)
        )
    ).scalar_one()
    report.class_teacher_comment = None
    await session.commit()

    body = await progress(client, teacher, ready_class)

    assert body["ready"] is False
    assert "class teacher's comment" in whats(body)


async def test_a_missing_attendance_record_blocks(client, teacher, ready_class, session) -> None:
    await session.execute(
        AttendanceRecord.__table__.delete().where(
            AttendanceRecord.pupil_id == ready_class.pupils[1].id
        )
    )
    await session.commit()

    body = await progress(client, teacher, ready_class)

    assert body["ready"] is False
    assert "attendance" in whats(body)
    assert "Bello" in whats(body)


async def test_a_missing_growth_record_blocks(client, teacher, ready_class, session) -> None:
    await session.execute(
        GrowthRecord.__table__.delete().where(GrowthRecord.pupil_id == ready_class.pupils[0].id)
    )
    await session.commit()

    body = await progress(client, teacher, ready_class)

    assert body["ready"] is False
    assert "height and weight" in whats(body)


async def test_an_unset_times_school_opened_blocks(client, teacher, ready_class, session) -> None:
    """R10 lists this separately from attendance, and so does the list: it is
    the administrator's job, not the teacher's."""
    await session.execute(
        AttendanceRecord.__table__.delete()
    )  # the trigger refuses the term change otherwise
    ready_class.term.times_school_opened = None
    await session.commit()

    body = await progress(client, teacher, ready_class)

    assert "term" in kinds(body)
    item = next(i for i in body["outstanding"] if i["kind"] == "term")
    assert "administrator" in item["detail"]


async def test_an_unconfigured_sheet_blocks_and_blames_the_administrator(
    client, teacher, ready_class, session
) -> None:
    """A teacher cannot fix this one, so the list says who can."""
    await session.execute(
        MarksObtainable.__table__.delete().where(
            MarksObtainable.assessment_period_id == ready_class.periods[TermHalf.SECOND_HALF].id
        )
    )
    await session.commit()

    body = await progress(client, teacher, ready_class)

    assert body["ready"] is False
    item = next(i for i in body["outstanding"] if i["kind"] == "sheet")
    assert "Marks Obtainable" in item["what"]
    assert "administrator" in item["detail"]


async def test_a_missing_assessment_period_blocks(client, teacher, ready_class, session) -> None:
    """D36 creates both halves with the term, so this needs forcing — but a
    term whose second half was deleted must not submit half a card."""
    await session.execute(
        ResultEntry.__table__.delete().where(
            ResultEntry.assessment_period_id == ready_class.periods[TermHalf.SECOND_HALF].id
        )
    )
    await session.execute(
        AssessmentPeriod.__table__.delete().where(
            AssessmentPeriod.id == ready_class.periods[TermHalf.SECOND_HALF].id
        )
    )
    await session.commit()

    body = await progress(client, teacher, ready_class)

    assert body["ready"] is False
    assert "no assessment period" in whats(body)


async def test_a_class_with_no_pupils_cannot_be_submitted(
    client, teacher, ready_class, session
) -> None:
    """Zero of zero is not "done" — an empty class would otherwise sail
    through every condition R10 lists."""
    await session.execute(Enrollment.__table__.delete())
    await session.commit()

    body = await progress(client, teacher, ready_class)

    assert body["ready"] is False
    assert "class" in kinds(body)
    assert (await submit(client, teacher, ready_class)).status_code == 422


async def test_every_outstanding_item_is_reported_not_just_the_first(
    client, teacher, ready_class, session
) -> None:
    """A teacher should be able to fix everything in one pass."""
    await session.execute(GrowthRecord.__table__.delete())
    await session.execute(NarrativeEntry.__table__.delete())
    await session.commit()

    body = await progress(client, teacher, ready_class)

    # Both pupils, and both of their problems named in each line.
    assert len(body["outstanding"]) == 2
    assert all("narrative" in item["what"] for item in body["outstanding"])
    assert all("height and weight" in item["what"] for item in body["outstanding"])


async def test_fixing_the_last_item_makes_it_ready(client, teacher, ready_class, session) -> None:
    """The half of the criterion that is easy to forget: the gate has to stop
    refusing."""
    await session.execute(
        GrowthRecord.__table__.delete().where(GrowthRecord.pupil_id == ready_class.pupils[0].id)
    )
    await session.commit()
    assert (await progress(client, teacher, ready_class))["ready"] is False

    response = await client.put(
        f"{API}/classes/{ready_class.klass.id}/growth",
        params={"term_id": str(ready_class.term.id)},
        json={"rows": [{"pupil_id": str(ready_class.pupils[0].id), "height_start_m": "1.20"}]},
        headers=teacher,
    )
    assert response.status_code == 200, response.text

    assert (await progress(client, teacher, ready_class))["ready"] is True
    assert (await submit(client, teacher, ready_class)).status_code == 200


# ---------------------------------------------------------------------------
# §5.2 and R14
# ---------------------------------------------------------------------------


async def test_a_subject_teacher_sees_the_page_but_cannot_submit(
    client, login, ready_class
) -> None:
    """§8.3 shows every subject's state so a subject teacher can see theirs is
    the one holding the class up; §5.2 gives the button to the class teacher."""
    response = await login(ready_class.other_teacher.email, TEST_PASSWORD)
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    body = await progress(client, headers, ready_class)
    assert body["ready"] is True
    assert body["may_submit"] is False

    refused = await submit(client, headers, ready_class)
    assert refused.status_code == 403
    assert "class teacher" in refused.json()["detail"]


async def test_a_class_cannot_be_submitted_twice(client, teacher, ready_class) -> None:
    assert (await submit(client, teacher, ready_class)).status_code == 200

    again = await submit(client, teacher, ready_class)

    assert again.status_code == 409
    assert "already been submitted" in again.json()["detail"]


async def test_an_approved_class_cannot_be_submitted(client, teacher, ready_class, session) -> None:
    status = (
        await session.execute(
            select(ClassTermStatus).where(ClassTermStatus.class_id == ready_class.klass.id)
        )
    ).scalar_one()
    status.state = ClassTermState.APPROVED
    await session.commit()

    response = await submit(client, teacher, ready_class)

    assert response.status_code == 409
    # R14 names the illegal move rather than the destination: approved is not
    # "already submitted", it is past it.
    assert response.json()["detail"] == "A class that is approved cannot be submitted."


async def test_submission_closes_the_class_to_further_editing(client, teacher, ready_class) -> None:
    """R14: "Scores and narrative become read-only for teachers on
    `submitted`"."""
    await submit(client, teacher, ready_class)

    response = await client.put(
        f"{API}/classes/{ready_class.klass.id}/comments",
        params={"term_id": str(ready_class.term.id)},
        json={"rows": [{"pupil_id": str(ready_class.pupils[0].id), "comment": "Changed."}]},
        headers=teacher,
    )

    assert response.status_code == 409
    assert "submitted for review" in response.json()["detail"]


async def test_a_returned_class_can_be_resubmitted(client, teacher, ready_class, session) -> None:
    """R14's loop. The note is cleared, because the class teacher has acted on
    it and the head teacher is looking at a fresh submission."""
    status = (
        await session.execute(
            select(ClassTermStatus).where(ClassTermStatus.class_id == ready_class.klass.id)
        )
    ).scalar_one()
    status.state = ClassTermState.RETURNED
    status.return_note = "Mathematics looks wrong for Bello."
    await session.commit()

    body = await progress(client, teacher, ready_class)
    assert body["state"] == "returned"
    assert body["return_note"] == "Mathematics looks wrong for Bello."

    response = await submit(client, teacher, ready_class)

    assert response.status_code == 200
    assert response.json()["state"] == "submitted"
    assert response.json()["return_note"] is None


# ---------------------------------------------------------------------------
# What submission writes
# ---------------------------------------------------------------------------


async def test_submission_records_who_and_when(client, teacher, ready_class, session) -> None:
    await submit(client, teacher, ready_class)

    status = (
        await session.execute(
            select(ClassTermStatus)
            .where(ClassTermStatus.class_id == ready_class.klass.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()

    assert status.submitted_by == ready_class.class_teacher.id
    assert status.submitted_at is not None


async def test_submission_is_audited(client, teacher, ready_class, session) -> None:
    await submit(client, teacher, ready_class)

    rows = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "class_term.submitted")))
        .scalars()
        .all()
    )

    assert len(rows) == 1
    assert rows[0].before["state"] == "in_progress"
    assert rows[0].after["state"] == "submitted"
    assert rows[0].actor_id == ready_class.class_teacher.id


async def test_submission_gives_every_pupil_a_report_row(
    client, teacher, ready_class, session
) -> None:
    """A24. Publication acts on these rows (R12) and the head teacher's remark
    hangs off them, so the set has to be complete before review begins — and
    `no_in_class` prints on the card beside the pupil's own figures."""
    await session.execute(TermReport.__table__.update().values(class_teacher_comment="x"))
    await session.execute(
        TermReport.__table__.delete().where(TermReport.pupil_id == ready_class.pupils[1].id)
    )
    await session.commit()

    # The deleted row's comment went with it, so put it back the way a teacher
    # would, which also recreates the report.
    await client.put(
        f"{API}/classes/{ready_class.klass.id}/comments",
        params={"term_id": str(ready_class.term.id)},
        json={"rows": [{"pupil_id": str(ready_class.pupils[1].id), "comment": "A good term."}]},
        headers=teacher,
    )
    assert (await submit(client, teacher, ready_class)).status_code == 200

    reports = (
        (
            await session.execute(
                select(TermReport)
                .where(TermReport.term_id == ready_class.term.id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )

    assert len(reports) == len(ROLL)
    assert all(report.no_in_class == len(ROLL) for report in reports)
    # R11: nothing computes a position, at submission or ever.
    assert all(report.position_text is None for report in reports)
