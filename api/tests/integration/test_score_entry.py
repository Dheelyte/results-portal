"""Score entry over HTTP (ARCHITECTURE.md §6 R1-R4, R7, R14; §7; §8.1).

The busiest write in the system, so it is tested the way it is used: a whole
class at a time, repeatedly, with the teacher getting some of it wrong.
"""

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    AssessmentPeriod,
    AuditLog,
    ClassSubject,
    ClassTermState,
    ClassTermStatus,
    GradeBand,
    GradingScale,
    MarksObtainable,
    ResultEntry,
    Subject,
    TermHalf,
)

API = settings.api_v1_prefix

# Ten per CA test and forty for the terminal column: chosen so the arithmetic
# in the assertions is readable. N2 is open and nothing defaults these.
CA_MAX = Decimal(10)
TERMINAL_MAX = Decimal(40)


@pytest.fixture
async def sheets(session: AsyncSession, world):
    """Both halves of `world`'s term, with maxima and the card's grade scale.

    `world` stops short of assessment configuration because milestone 4 did.
    Everything added here is what an admin configures in milestone 5, so these
    tests exercise the state a real term is actually in.
    """
    from types import SimpleNamespace

    periods = {}
    for half in TermHalf:
        period = AssessmentPeriod(
            school_id=world.school.id,
            term_id=world.term.id,
            half=half,
            opens_on=dt.date(2026, 9, 14),
            closes_on=dt.date(2026, 12, 11),
        )
        session.add(period)
        periods[half] = period
    await session.flush()

    for period in periods.values():
        session.add(
            MarksObtainable(
                school_id=world.school.id,
                assessment_period_id=period.id,
                class_id=None,
                ca_test_1=CA_MAX,
                ca_test_2=CA_MAX,
                ca_test_3=CA_MAX,
                ca_test_4=CA_MAX,
                ca_test_5=CA_MAX,
                mid_term_test=TERMINAL_MAX if period.half is TermHalf.FIRST_HALF else None,
                exam=TERMINAL_MAX if period.half is TermHalf.SECOND_HALF else None,
            )
        )

    scale = GradingScale(
        school_id=world.school.id,
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
    await session.commit()

    return SimpleNamespace(
        first=periods[TermHalf.FIRST_HALF],
        second=periods[TermHalf.SECOND_HALF],
        scale=scale,
    )


@pytest.fixture
async def teacher_headers(headers_for, world) -> dict[str, str]:
    """Teacher A: class teacher of 4A and subject teacher of its Mathematics."""
    return await headers_for(world.teacher_a)


async def read_sheet(client: AsyncClient, headers, class_subject_id, period_id):
    return await client.get(
        f"{API}/class-subjects/{class_subject_id}/entries",
        params={"assessment_period_id": str(period_id)},
        headers=headers,
    )


async def save(client: AsyncClient, headers, class_subject_id, period_id, rows):
    return await client.put(
        f"{API}/class-subjects/{class_subject_id}/entries",
        json={"assessment_period_id": str(period_id), "rows": rows},
        headers=headers,
    )


def full_row(pupil_id: uuid.UUID, terminal: str = "mid_term_test") -> dict:
    return {
        "pupil_id": str(pupil_id),
        "ca_test_1": "10",
        "ca_test_2": "10",
        "ca_test_3": "10",
        "ca_test_4": "10",
        "ca_test_5": "10",
        terminal: "40",
    }


# ---------------------------------------------------------------------------
# Reading the grid
# ---------------------------------------------------------------------------


async def test_the_grid_lists_the_class_roll(client, teacher_headers, world, sheets) -> None:
    response = await read_sheet(client, teacher_headers, world.maths_4a.id, sheets.first.id)

    assert response.status_code == 200
    body = response.json()
    assert body["class_name"] == "Primary 4"
    assert body["subject_name"] == "Mathematics"
    # Ada and Emeka are in 4A; Chidi is in 5B.
    assert {row["first_name"] for row in body["rows"]} == {"Ada", "Emeka"}
    assert all(row["ca_test_1"] is None for row in body["rows"])


async def test_each_half_offers_its_own_columns(client, teacher_headers, world, sheets) -> None:
    """§8.1: five CA tests plus Mid Term Test, or five plus Exam."""
    first = await read_sheet(client, teacher_headers, world.maths_4a.id, sheets.first.id)
    second = await read_sheet(client, teacher_headers, world.maths_4a.id, sheets.second.id)

    assert first.json()["columns"][-1] == "mid_term_test"
    assert second.json()["columns"][-1] == "exam"
    assert first.json()["half"] == "first_half"
    assert len(first.json()["columns"]) == 6


async def test_the_grid_carries_the_marks_obtainable_row(
    client, teacher_headers, world, sheets
) -> None:
    """§8.1 pins it to the top of the grid, so it travels with the grid."""
    body = (await read_sheet(client, teacher_headers, world.maths_4a.id, sheets.first.id)).json()

    assert body["maxima_configured"] is True
    assert body["maxima"]["ca_test_1"] == "10.00"
    assert body["maxima"]["mid_term_test"] == "40.00"
    assert body["maxima"]["is_class_override"] is False


async def test_a_class_override_is_reported_as_one(
    client, teacher_headers, world, sheets, session
) -> None:
    session.add(
        MarksObtainable(
            school_id=world.school.id,
            assessment_period_id=sheets.first.id,
            class_id=world.class_4a.id,
            ca_test_1=Decimal(20),
            mid_term_test=Decimal(20),
        )
    )
    await session.commit()

    body = (await read_sheet(client, teacher_headers, world.maths_4a.id, sheets.first.id)).json()

    assert body["maxima"]["is_class_override"] is True
    assert body["maxima"]["ca_test_1"] == "20.00"


async def test_a_class_subject_the_teacher_does_not_teach_is_not_found(
    client, teacher_headers, world, sheets
) -> None:
    """A 404 rather than a 403: a 403 would confirm the sheet exists (§5.2)."""
    response = await read_sheet(client, teacher_headers, world.maths_5b.id, sheets.first.id)

    assert response.status_code == 404


async def test_a_period_from_another_session_is_refused(
    client, teacher_headers, world, sheets, session
) -> None:
    """Two valid ids that do not belong together."""
    from app.models import AcademicSession, Term, TermNumber

    other_session = AcademicSession(
        school_id=world.school.id,
        name="2025/2026",
        starts_on=dt.date(2025, 9, 15),
        ends_on=dt.date(2026, 7, 24),
    )
    session.add(other_session)
    await session.flush()
    other_term = Term(
        school_id=world.school.id,
        academic_session_id=other_session.id,
        number=TermNumber.FIRST,
        starts_on=dt.date(2025, 9, 15),
        ends_on=dt.date(2025, 12, 12),
    )
    session.add(other_term)
    await session.flush()
    stray = AssessmentPeriod(
        school_id=world.school.id, term_id=other_term.id, half=TermHalf.FIRST_HALF
    )
    session.add(stray)
    await session.commit()

    response = await read_sheet(client, teacher_headers, world.maths_4a.id, stray.id)

    assert response.status_code == 422
    assert "different academic session" in response.json()["detail"]


async def test_a_group_heading_offers_no_sheet(
    client, teacher_headers, world, sheets, session
) -> None:
    """R7, second line of defence.

    `services/subjects.py` refuses to offer a group heading to a class at all,
    so this row is inserted directly — the point is that even if one existed,
    no score could be entered against it.
    """
    from app.models import TeachingAssignment

    english = Subject(school_id=world.school.id, name="English", is_group=True)
    session.add(english)
    await session.flush()
    offering = ClassSubject(
        school_id=world.school.id,
        class_id=world.class_4a.id,
        subject_id=english.id,
        academic_session_id=world.academic_session.id,
    )
    session.add(offering)
    await session.flush()
    session.add(
        TeachingAssignment(
            school_id=world.school.id,
            class_subject_id=offering.id,
            teacher_user_id=world.teacher_a.id,
        )
    )
    await session.commit()

    response = await read_sheet(client, teacher_headers, offering.id, sheets.first.id)

    assert response.status_code == 422
    assert "heading on the card" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------


async def test_a_full_class_saves_and_comes_back_computed(
    client, teacher_headers, world, sheets
) -> None:
    rows = [full_row(world.pupils["ada"].id), full_row(world.pupils["emeka"].id)]

    response = await save(client, teacher_headers, world.maths_4a.id, sheets.first.id, rows)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["rows"]) == 2
    for row in body["rows"]:
        # R2 is generated by Postgres, not sent by the client.
        assert row["ca_test_total"] == "50.00"
        assert row["period_average"] == "100.00"
        assert row["grade"]["letter"] == "A+"
        assert row["grade_letter"] is None  # not snapshotted until approval


async def test_the_grade_follows_the_average(client, teacher_headers, world, sheets) -> None:
    rows = [
        {"pupil_id": str(world.pupils["ada"].id), "ca_test_1": "5", "mid_term_test": "20"},
    ]

    body = (await save(client, teacher_headers, world.maths_4a.id, sheets.first.id, rows)).json()
    ada = next(row for row in body["rows"] if row["first_name"] == "Ada")

    # 25 of 90.
    assert ada["period_average"] == "27.78"
    assert ada["grade"]["letter"] == "E"
    assert ada["grade"]["remark"] == "Weak"


async def test_an_omitted_column_is_left_alone(client, teacher_headers, world, sheets) -> None:
    """The grid autosaves the dirty set, not the whole row (§8.1)."""
    ada = str(world.pupils["ada"].id)
    await save(
        client,
        teacher_headers,
        world.maths_4a.id,
        sheets.first.id,
        [{"pupil_id": ada, "ca_test_1": "8", "ca_test_2": "7"}],
    )

    body = (
        await save(
            client,
            teacher_headers,
            world.maths_4a.id,
            sheets.first.id,
            [{"pupil_id": ada, "ca_test_2": "9"}],
        )
    ).json()
    row = next(r for r in body["rows"] if r["pupil_id"] == ada)

    assert row["ca_test_1"] == "8.00"
    assert row["ca_test_2"] == "9.00"


async def test_an_explicit_null_clears_a_cell(client, teacher_headers, world, sheets) -> None:
    """A teacher must be able to undo a mistyped score, not only overwrite it."""
    ada = str(world.pupils["ada"].id)
    await save(
        client,
        teacher_headers,
        world.maths_4a.id,
        sheets.first.id,
        [{"pupil_id": ada, "ca_test_1": "8"}],
    )

    body = (
        await save(
            client,
            teacher_headers,
            world.maths_4a.id,
            sheets.first.id,
            [{"pupil_id": ada, "ca_test_1": None}],
        )
    ).json()
    row = next(r for r in body["rows"] if r["pupil_id"] == ada)

    assert row["ca_test_1"] is None
    # R2: null only when all five CA columns are null.
    assert row["ca_test_total"] is None
    assert row["period_average"] is None


# ---------------------------------------------------------------------------
# R1 — validation
# ---------------------------------------------------------------------------


async def test_a_score_above_the_maximum_is_refused_and_names_it(
    client, teacher_headers, world, sheets
) -> None:
    ada = str(world.pupils["ada"].id)

    response = await save(
        client,
        teacher_headers,
        world.maths_4a.id,
        sheets.first.id,
        [{"pupil_id": ada, "ca_test_3": "11"}],
    )

    assert response.status_code == 422
    errors = response.json()["errors"]
    assert errors[ada]["ca_test_3"] == "CA Test 3 is out of 10."


async def test_nothing_is_saved_when_one_row_is_rejected(
    client, teacher_headers, world, sheets
) -> None:
    """All or none (§7). A partial save leaves the teacher unable to tell from
    the screen which cells reached the database."""
    good = full_row(world.pupils["ada"].id)
    bad = {"pupil_id": str(world.pupils["emeka"].id), "ca_test_1": "99"}

    response = await save(client, teacher_headers, world.maths_4a.id, sheets.first.id, [good, bad])
    assert response.status_code == 422

    body = (await read_sheet(client, teacher_headers, world.maths_4a.id, sheets.first.id)).json()
    assert all(row["ca_test_1"] is None for row in body["rows"])


async def test_every_bad_cell_is_reported_not_just_the_first(
    client, teacher_headers, world, sheets
) -> None:
    """A teacher who mistyped three cells should be told about three."""
    ada = str(world.pupils["ada"].id)

    response = await save(
        client,
        teacher_headers,
        world.maths_4a.id,
        sheets.first.id,
        [{"pupil_id": ada, "ca_test_1": "11", "ca_test_2": "12", "mid_term_test": "41"}],
    )

    assert set(response.json()["errors"][ada]) == {"ca_test_1", "ca_test_2", "mid_term_test"}


async def test_the_refusal_names_no_pupil_and_no_score(
    client, teacher_headers, world, sheets
) -> None:
    """CLAUDE.md: no score and no pupil's identity in an error message.

    The keys are pupil ids, which the caller just sent. The maximum is the
    school's configuration, not a child's mark.
    """
    response = await save(
        client,
        teacher_headers,
        world.maths_4a.id,
        sheets.first.id,
        [{"pupil_id": str(world.pupils["ada"].id), "ca_test_1": "11"}],
    )

    text = response.text
    assert "Ada" not in text
    assert "Okafor" not in text
    assert "11" not in text


async def test_a_column_the_sheet_does_not_have_is_refused(
    client, teacher_headers, world, sheets
) -> None:
    ada = str(world.pupils["ada"].id)

    response = await save(
        client,
        teacher_headers,
        world.maths_4a.id,
        sheets.first.id,
        [{"pupil_id": ada, "exam": "30"}],
    )

    assert response.status_code == 422
    assert "no Exam column" in response.json()["errors"][ada]["exam"]


async def test_a_pupil_from_another_class_is_refused(
    client, teacher_headers, world, sheets
) -> None:
    chidi = str(world.pupils["chidi"].id)

    response = await save(
        client,
        teacher_headers,
        world.maths_4a.id,
        sheets.first.id,
        [{"pupil_id": chidi, "ca_test_1": "5"}],
    )

    assert response.status_code == 422
    assert "not in this class" in response.json()["errors"][chidi]["pupil_id"]


async def test_a_score_with_two_decimal_places_is_refused(
    client, teacher_headers, world, sheets
) -> None:
    """R1: "One decimal place." The column is numeric(5,2) because
    `period_average` shares the type, so this is a rule, not a constraint."""
    ada = str(world.pupils["ada"].id)

    response = await save(
        client,
        teacher_headers,
        world.maths_4a.id,
        sheets.first.id,
        [{"pupil_id": ada, "ca_test_1": "7.25"}],
    )

    assert response.status_code == 422
    assert "one decimal place" in response.json()["errors"][ada]["ca_test_1"]


async def test_a_maximum_echoed_back_is_accepted(client, teacher_headers, world, sheets) -> None:
    """The API returns maxima as "10.00", so it must accept "10.00".

    R1 bounds the value, not its representation. Refusing a figure the server
    had just handed out would break any client that offered "full marks" as a
    shortcut — and it broke a walkthrough script before it was fixed.
    """
    sheet = (await read_sheet(client, teacher_headers, world.maths_4a.id, sheets.first.id)).json()
    maximum = sheet["maxima"]["ca_test_1"]
    assert maximum == "10.00"

    response = await save(
        client,
        teacher_headers,
        world.maths_4a.id,
        sheets.first.id,
        [{"pupil_id": str(world.pupils["ada"].id), "ca_test_1": maximum}],
    )

    assert response.status_code == 200, response.text
    assert response.json()["rows"][0]["ca_test_1"] == "10.00"


async def test_one_decimal_place_is_accepted(client, teacher_headers, world, sheets) -> None:
    response = await save(
        client,
        teacher_headers,
        world.maths_4a.id,
        sheets.first.id,
        [{"pupil_id": str(world.pupils["ada"].id), "ca_test_1": "7.5"}],
    )

    assert response.status_code == 200
    assert response.json()["rows"][0]["ca_test_1"] == "7.50"


async def test_a_negative_score_is_refused(client, teacher_headers, world, sheets) -> None:
    response = await save(
        client,
        teacher_headers,
        world.maths_4a.id,
        sheets.first.id,
        [{"pupil_id": str(world.pupils["ada"].id), "ca_test_1": "-1"}],
    )

    assert response.status_code == 422


async def test_a_sheet_with_no_maxima_refuses_scores(
    client, teacher_headers, world, sheets, session
) -> None:
    """R1 has nothing to validate against, so the grid must not pretend."""
    await session.execute(
        MarksObtainable.__table__.delete().where(
            MarksObtainable.assessment_period_id == sheets.first.id
        )
    )
    await session.commit()

    response = await save(
        client,
        teacher_headers,
        world.maths_4a.id,
        sheets.first.id,
        [full_row(world.pupils["ada"].id)],
    )

    assert response.status_code == 409
    assert "Marks Obtainable" in response.json()["detail"]


# ---------------------------------------------------------------------------
# R14 — the state machine
# ---------------------------------------------------------------------------


async def test_the_first_save_opens_the_term(
    client, teacher_headers, world, sheets, session
) -> None:
    before = (await read_sheet(client, teacher_headers, world.maths_4a.id, sheets.first.id)).json()
    assert before["state"] == "not_started"

    after = (
        await save(
            client,
            teacher_headers,
            world.maths_4a.id,
            sheets.first.id,
            [full_row(world.pupils["ada"].id)],
        )
    ).json()

    assert after["state"] == "in_progress"
    assert after["editable"] is True


@pytest.mark.parametrize(
    ("state", "phrase"),
    [
        (ClassTermState.SUBMITTED, "submitted for review"),
        (ClassTermState.APPROVED, "approved"),
    ],
)
async def test_a_closed_class_is_read_only(
    client, teacher_headers, world, sheets, session, state, phrase
) -> None:
    session.add(
        ClassTermStatus(
            school_id=world.school.id,
            class_id=world.class_4a.id,
            term_id=world.term.id,
            state=state,
        )
    )
    await session.commit()

    sheet = (await read_sheet(client, teacher_headers, world.maths_4a.id, sheets.first.id)).json()
    assert sheet["editable"] is False

    response = await save(
        client,
        teacher_headers,
        world.maths_4a.id,
        sheets.first.id,
        [full_row(world.pupils["ada"].id)],
    )

    assert response.status_code == 409
    assert phrase in response.json()["detail"]


async def test_a_returned_class_reopens(client, teacher_headers, world, sheets, session) -> None:
    """R14: the head teacher sent it back precisely so it could be corrected."""
    session.add(
        ClassTermStatus(
            school_id=world.school.id,
            class_id=world.class_4a.id,
            term_id=world.term.id,
            state=ClassTermState.RETURNED,
        )
    )
    await session.commit()

    response = await save(
        client,
        teacher_headers,
        world.maths_4a.id,
        sheets.first.id,
        [full_row(world.pupils["ada"].id)],
    )

    assert response.status_code == 200
    # Still returned: correcting a returned class does not resubmit it.
    assert response.json()["state"] == "returned"


# ---------------------------------------------------------------------------
# The snapshot boundary (CLAUDE.md rule 6)
# ---------------------------------------------------------------------------


async def test_an_approved_row_keeps_its_snapshotted_grade(
    client, teacher_headers, world, sheets, session
) -> None:
    """A printed card must keep saying what was printed (§4.5).

    The row below carries an average that today's bands would call an A+, and
    a snapshot that says B. The portal shows B.
    """
    session.add(
        ResultEntry(
            school_id=world.school.id,
            assessment_period_id=sheets.first.id,
            pupil_id=world.pupils["ada"].id,
            class_subject_id=world.maths_4a.id,
            ca_test_1=Decimal(10),
            period_average=Decimal("95.00"),
            grade_letter="B",
            grading_scale_id=sheets.scale.id,
        )
    )
    await session.commit()

    body = (await read_sheet(client, teacher_headers, world.maths_4a.id, sheets.first.id)).json()
    ada = next(row for row in body["rows"] if row["first_name"] == "Ada")

    assert ada["grade_letter"] == "B"
    assert ada["grade"] is None  # nothing recomputed over the snapshot


# ---------------------------------------------------------------------------
# Audit (§4.9)
# ---------------------------------------------------------------------------


async def test_a_save_is_audited_with_counts_and_no_scores(
    client, teacher_headers, world, sheets, session
) -> None:
    await save(
        client,
        teacher_headers,
        world.maths_4a.id,
        sheets.first.id,
        [full_row(world.pupils["ada"].id), full_row(world.pupils["emeka"].id)],
    )

    rows = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "result_entries.saved")))
        .scalars()
        .all()
    )

    assert len(rows) == 1
    payload = rows[0].after
    assert payload["rows_saved"] == 2
    assert payload["rows_created"] == 2
    assert "ca_test_1" in payload["columns"]
    # No value of any score, and no pupil id, reaches the log.
    assert "10" not in str(payload["columns"])
    assert str(world.pupils["ada"].id) not in str(payload)


async def test_opening_a_term_is_audited_once(
    client, teacher_headers, world, sheets, session
) -> None:
    for _ in range(2):
        await save(
            client,
            teacher_headers,
            world.maths_4a.id,
            sheets.first.id,
            [full_row(world.pupils["ada"].id)],
        )

    rows = (
        (await session.execute(select(AuditLog).where(AuditLog.action == "class_term.started")))
        .scalars()
        .all()
    )

    assert len(rows) == 1


# ---------------------------------------------------------------------------
# A teacher's own list (§7 GET /my/assignments)
# ---------------------------------------------------------------------------


async def test_the_workload_names_the_term_and_both_sheets(
    client, teacher_headers, world, sheets
) -> None:
    """D51: §5.2 gives the calendar to the admin alone, so the teacher's own
    endpoint has to carry the ids their grid needs."""
    body = (
        await client.get(
            f"{API}/my/assignments", params={"term_id": str(world.term.id)}, headers=teacher_headers
        )
    ).json()

    assert body["term"]["academic_session_name"] == "2026/2027"
    assert body["term"]["times_school_opened"] == 60
    assert [period["half"] for period in body["periods"]] == ["first_half", "second_half"]


async def test_the_workload_names_the_classes_this_teacher_leads(
    client, teacher_headers, world, sheets
) -> None:
    """The narrative, attendance, growth and the comment belong to the class
    teacher of a class, not to a subject. Without this list a class teacher
    has no route to that work at all."""
    body = (
        await client.get(
            f"{API}/my/assignments", params={"term_id": str(world.term.id)}, headers=teacher_headers
        )
    ).json()

    # Teacher A leads 4A and teaches French in 5B, which is not the same job.
    assert [klass["class_name"] for klass in body["class_teacher_of"]] == ["Primary 4"]


async def test_a_subject_teacher_leads_no_class(client, headers_for, world, sheets) -> None:
    """The specialist teaches Computer in both classes and leads neither."""
    headers = await headers_for(world.specialist)

    body = (await client.get(f"{API}/my/assignments", headers=headers)).json()

    assert body["class_teacher_of"] == []
    assert len(body["assignments"]) == 2


async def test_the_current_term_is_the_default(client, teacher_headers, world, sheets) -> None:
    """§2.3 sets the current term in the platform; a teacher should not have
    to know its id to start work."""
    response = await client.get(f"{API}/my/assignments", headers=teacher_headers)

    assert response.status_code == 200
    assert response.json()["term"]["id"] == str(world.term.id)


async def test_with_no_current_term_the_teacher_is_told_so(
    client, teacher_headers, world, sheets, session
) -> None:
    world.term.is_current = False
    await session.commit()

    response = await client.get(f"{API}/my/assignments", headers=teacher_headers)

    assert response.status_code == 409
    assert "current one" in response.json()["detail"]


async def test_a_teacher_sees_only_their_own_sheets(client, teacher_headers, world, sheets) -> None:
    """Teacher A teaches Maths and French in 4A, and French in 5B — the union
    case §5.2 calls out by name. Not 5B Mathematics, which is Teacher B's."""
    response = await client.get(
        f"{API}/my/assignments", params={"term_id": str(world.term.id)}, headers=teacher_headers
    )

    assert response.status_code == 200
    got = {(row["class_name"], row["subject_name"]) for row in response.json()["assignments"]}
    assert got == {
        ("Primary 4", "Mathematics"),
        ("Primary 4", "French"),
        ("Primary 5", "French"),
    }


async def test_the_assignment_list_counts_progress(client, teacher_headers, world, sheets) -> None:
    await save(
        client,
        teacher_headers,
        world.maths_4a.id,
        sheets.first.id,
        [full_row(world.pupils["ada"].id)],
    )

    body = (
        await client.get(
            f"{API}/my/assignments",
            params={"term_id": str(world.term.id)},
            headers=teacher_headers,
        )
    ).json()
    maths = next(row for row in body["assignments"] if row["subject_name"] == "Mathematics")

    assert maths["pupil_count"] == 2
    assert maths["entered_count"]["first_half"] == 1
    assert maths["entered_count"]["second_half"] == 0
    assert maths["state"] == "in_progress"


async def test_a_teacher_with_no_assignments_gets_an_empty_list(
    client, headers_for, make_user, world, sheets
) -> None:
    """An empty list, not an error: the screen says so rather than breaking."""
    from app.models import UserRole

    stranger = await make_user(UserRole.TEACHER)
    headers = await headers_for(stranger)

    response = await client.get(
        f"{API}/my/assignments", params={"term_id": str(world.term.id)}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["assignments"] == []
    # The term still comes back, so the screen can say which term is empty.
    assert response.json()["term"]["number"] == "first"


# ---------------------------------------------------------------------------
# Both layouts, end to end
# ---------------------------------------------------------------------------


async def test_the_second_half_sheet_takes_an_exam_mark(
    client, teacher_headers, world, sheets
) -> None:
    rows = [full_row(world.pupils["ada"].id, terminal="exam")]

    response = await save(client, teacher_headers, world.maths_4a.id, sheets.second.id, rows)

    assert response.status_code == 200, response.text
    ada = response.json()["rows"][0]
    assert ada["exam"] == "40.00"
    assert ada["mid_term_test"] is None
    assert ada["period_average"] == "100.00"


async def test_the_two_halves_are_separate_rows(client, teacher_headers, world, sheets) -> None:
    """One `result_entries` row per pupil per period per class-subject."""
    ada = world.pupils["ada"].id
    await save(
        client,
        teacher_headers,
        world.maths_4a.id,
        sheets.first.id,
        [{"pupil_id": str(ada), "ca_test_1": "5"}],
    )
    await save(
        client,
        teacher_headers,
        world.maths_4a.id,
        sheets.second.id,
        [{"pupil_id": str(ada), "ca_test_1": "9"}],
    )

    first = (await read_sheet(client, teacher_headers, world.maths_4a.id, sheets.first.id)).json()
    second = (await read_sheet(client, teacher_headers, world.maths_4a.id, sheets.second.id)).json()

    assert next(r for r in first["rows"] if r["pupil_id"] == str(ada))["ca_test_1"] == "5.00"
    assert next(r for r in second["rows"] if r["pupil_id"] == str(ada))["ca_test_1"] == "9.00"
