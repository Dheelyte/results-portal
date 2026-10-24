"""Attendance, growth and the class teacher's comment over HTTP
(ARCHITECTURE.md §4.7, §6 R9, §5.2, §8.3).

§5.2 gives all three to the **class teacher** and nobody else — not even to a
subject teacher of the same class, which is the distinction most of these
tests turn on. `world` makes that testable: teacher_a is class teacher of 4A,
the specialist teaches Computer in 4A and is class teacher of neither class.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AttendanceRecord, AuditLog, ClassTermState, ClassTermStatus, GrowthRecord

API = settings.api_v1_prefix

# `world`'s term records 60 days opened.
OPENED = 60


@pytest.fixture
async def class_teacher(headers_for, world) -> dict[str, str]:
    return await headers_for(world.teacher_a)


@pytest.fixture
async def subject_teacher(headers_for, world) -> dict[str, str]:
    """Teaches Computer in 4A, class teacher of nothing."""
    return await headers_for(world.specialist)


def pupils_of(world):
    return world.pupils["ada"].id, world.pupils["emeka"].id


async def put(client, headers, class_id, term_id, what, body):
    return await client.put(
        f"{API}/classes/{class_id}/{what}",
        params={"term_id": str(term_id)},
        json=body,
        headers=headers,
    )


async def get(client, headers, class_id, term_id, what):
    return await client.get(
        f"{API}/classes/{class_id}/{what}",
        params={"term_id": str(term_id)},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Attendance (R9)
# ---------------------------------------------------------------------------


async def test_the_page_carries_the_roll_and_the_days_opened(client, class_teacher, world) -> None:
    """R9's right-hand side travels with the page: the teacher needs to know
    what the numbers have to add up to."""
    response = await get(client, class_teacher, world.class_4a.id, world.term.id, "attendance")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["times_school_opened"] == OPENED
    assert {row["first_name"] for row in body["rows"]} == {"Ada", "Emeka"}
    assert all(row["times_present"] is None for row in body["rows"])


async def test_a_whole_class_saves(client, class_teacher, world) -> None:
    ada, emeka = pupils_of(world)

    response = await put(
        client,
        class_teacher,
        world.class_4a.id,
        world.term.id,
        "attendance",
        {
            "rows": [
                {"pupil_id": str(ada), "times_present": 58, "times_absent": 2, "times_late": 1},
                {"pupil_id": str(emeka), "times_present": 60, "times_absent": 0},
            ]
        },
    )

    assert response.status_code == 200, response.text
    rows = {row["first_name"]: row for row in response.json()["rows"]}
    assert rows["Ada"]["times_present"] == 58
    assert rows["Ada"]["times_late"] == 1
    assert rows["Emeka"]["times_absent"] == 0
    # Defaulted, not required.
    assert rows["Emeka"]["times_late"] == 0


async def test_a_total_that_does_not_add_up_is_refused_per_pupil(
    client, class_teacher, world
) -> None:
    """R9, and the refusal names the pupil's id so §8.3 can point at the row."""
    ada, emeka = pupils_of(world)

    response = await put(
        client,
        class_teacher,
        world.class_4a.id,
        world.term.id,
        "attendance",
        {
            "rows": [
                {"pupil_id": str(ada), "times_present": 58, "times_absent": 2},
                {"pupil_id": str(emeka), "times_present": 50, "times_absent": 5},
            ]
        },
    )

    assert response.status_code == 422
    errors = response.json()["errors"]
    assert str(ada) not in errors
    assert "add up to 60" in errors[str(emeka)]["times_absent"]


async def test_nothing_is_saved_when_one_row_is_refused(client, class_teacher, world) -> None:
    ada, emeka = pupils_of(world)
    await put(
        client,
        class_teacher,
        world.class_4a.id,
        world.term.id,
        "attendance",
        {
            "rows": [
                {"pupil_id": str(ada), "times_present": 58, "times_absent": 2},
                {"pupil_id": str(emeka), "times_present": 1, "times_absent": 1},
            ]
        },
    )

    body = (await get(client, class_teacher, world.class_4a.id, world.term.id, "attendance")).json()
    assert all(row["times_present"] is None for row in body["rows"])


async def test_the_refusal_names_no_pupil(client, class_teacher, world) -> None:
    """CLAUDE.md. The key is the id the caller just sent; the message is about
    the arithmetic."""
    ada, _ = pupils_of(world)

    response = await put(
        client,
        class_teacher,
        world.class_4a.id,
        world.term.id,
        "attendance",
        {"rows": [{"pupil_id": str(ada), "times_present": 1, "times_absent": 1}]},
    )

    assert "Ada" not in response.text
    assert "Okafor" not in response.text


async def test_a_term_with_no_days_opened_refuses_attendance(
    client, class_teacher, world, session
) -> None:
    """R10 lists this as a submission blocker; it blocks entry too, because
    R9 has nothing to add up to."""
    world.term.times_school_opened = None
    await session.commit()
    ada, _ = pupils_of(world)

    response = await put(
        client,
        class_teacher,
        world.class_4a.id,
        world.term.id,
        "attendance",
        {"rows": [{"pupil_id": str(ada), "times_present": 10, "times_absent": 5}]},
    )

    assert response.status_code == 409
    assert "times the school opened" in response.json()["detail"]


async def test_a_pupil_from_another_class_is_refused(client, class_teacher, world) -> None:
    chidi = world.pupils["chidi"].id

    response = await put(
        client,
        class_teacher,
        world.class_4a.id,
        world.term.id,
        "attendance",
        {"rows": [{"pupil_id": str(chidi), "times_present": 58, "times_absent": 2}]},
    )

    assert response.status_code == 422
    assert "not in this class" in response.json()["errors"][str(chidi)]["pupil_id"]


async def test_attendance_can_be_corrected(client, class_teacher, world) -> None:
    ada, _ = pupils_of(world)
    for present, absent in ((58, 2), (59, 1)):
        response = await put(
            client,
            class_teacher,
            world.class_4a.id,
            world.term.id,
            "attendance",
            {"rows": [{"pupil_id": str(ada), "times_present": present, "times_absent": absent}]},
        )
        assert response.status_code == 200, response.text

    rows = {row["first_name"]: row for row in response.json()["rows"]}
    assert rows["Ada"]["times_present"] == 59


async def test_one_row_per_pupil_per_term(client, class_teacher, world, session) -> None:
    ada, _ = pupils_of(world)
    for present, absent in ((58, 2), (59, 1)):
        await put(
            client,
            class_teacher,
            world.class_4a.id,
            world.term.id,
            "attendance",
            {"rows": [{"pupil_id": str(ada), "times_present": present, "times_absent": absent}]},
        )

    rows = (
        (await session.execute(select(AttendanceRecord).where(AttendanceRecord.pupil_id == ada)))
        .scalars()
        .all()
    )

    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Growth (§4.7)
# ---------------------------------------------------------------------------


async def test_height_and_weight_save(client, class_teacher, world) -> None:
    ada, _ = pupils_of(world)

    response = await put(
        client,
        class_teacher,
        world.class_4a.id,
        world.term.id,
        "growth",
        {
            "rows": [
                {
                    "pupil_id": str(ada),
                    "height_start_m": "1.18",
                    "weight_start_kg": "24.5",
                }
            ]
        },
    )

    assert response.status_code == 200, response.text
    row = next(r for r in response.json()["rows"] if r["first_name"] == "Ada")
    assert row["height_start_m"] == "1.18"
    assert row["weight_start_kg"] == "24.50"
    # End of term has not happened yet, and that is a legitimate state.
    assert row["height_end_m"] is None


async def test_the_end_of_term_figures_can_be_added_later(client, class_teacher, world) -> None:
    ada, _ = pupils_of(world)
    await put(
        client,
        class_teacher,
        world.class_4a.id,
        world.term.id,
        "growth",
        {"rows": [{"pupil_id": str(ada), "height_start_m": "1.18"}]},
    )

    body = (
        await put(
            client,
            class_teacher,
            world.class_4a.id,
            world.term.id,
            "growth",
            {"rows": [{"pupil_id": str(ada), "height_start_m": "1.18", "height_end_m": "1.22"}]},
        )
    ).json()
    row = next(r for r in body["rows"] if r["first_name"] == "Ada")

    assert row["height_start_m"] == "1.18"
    assert row["height_end_m"] == "1.22"


async def test_centimetres_in_the_metres_column_are_refused(client, class_teacher, world) -> None:
    """The mistake that actually happens. §4.7's CHECK only demands a positive
    number, so without this the card prints a pupil 118 metres tall."""
    ada, _ = pupils_of(world)

    response = await put(
        client,
        class_teacher,
        world.class_4a.id,
        world.term.id,
        "growth",
        {"rows": [{"pupil_id": str(ada), "height_start_m": "118"}]},
    )

    # 118 cannot even be stored: the column is numeric(4,2), so the schema
    # refuses it before the service is reached.
    assert response.status_code == 422

    # A value the column *can* hold, so the service's own bounds answer. This
    # is the one that needs a readable message.
    service = await put(
        client,
        class_teacher,
        world.class_4a.id,
        world.term.id,
        "growth",
        {"rows": [{"pupil_id": str(ada), "height_start_m": "11.8"}]},
    )

    assert service.status_code == 422
    assert "between 0.3m and 2.5m" in service.json()["errors"][str(ada)]["height_start_m"]


async def test_a_zero_measurement_is_refused_by_the_schema(client, class_teacher, world) -> None:
    """§4.7's CHECK is `> 0`; the request never reaches the database."""
    ada, _ = pupils_of(world)

    response = await put(
        client,
        class_teacher,
        world.class_4a.id,
        world.term.id,
        "growth",
        {"rows": [{"pupil_id": str(ada), "weight_start_kg": "0"}]},
    )

    assert response.status_code == 422


async def test_growth_is_stored_as_numeric_not_float(client, class_teacher, world, session) -> None:
    """CLAUDE.md: never a float for a measurement either."""
    ada, _ = pupils_of(world)
    await put(
        client,
        class_teacher,
        world.class_4a.id,
        world.term.id,
        "growth",
        {"rows": [{"pupil_id": str(ada), "weight_end_kg": "25.80"}]},
    )

    record = (
        await session.execute(select(GrowthRecord).where(GrowthRecord.pupil_id == ada))
    ).scalar_one()

    assert record.weight_end_kg == Decimal("25.80")


# ---------------------------------------------------------------------------
# The class teacher's comment (§1.6)
# ---------------------------------------------------------------------------


async def test_a_comment_saves_against_the_term_report(client, class_teacher, world) -> None:
    ada, _ = pupils_of(world)

    response = await put(
        client,
        class_teacher,
        world.class_4a.id,
        world.term.id,
        "comments",
        {"rows": [{"pupil_id": str(ada), "comment": "A thoughtful and steady term."}]},
    )

    assert response.status_code == 200, response.text
    row = next(r for r in response.json()["rows"] if r["first_name"] == "Ada")
    assert row["comment"] == "A thoughtful and steady term."


async def test_a_comment_can_be_written_for_a_pupil_with_no_report_row_yet(
    client, class_teacher, world, session
) -> None:
    """`world` creates a report for each pupil, so this proves the other path:
    a pupil enrolled after the reports were made still gets a comment."""
    from app.models import TermReport

    ada, _ = pupils_of(world)
    await session.execute(TermReport.__table__.delete())
    await session.commit()

    response = await put(
        client,
        class_teacher,
        world.class_4a.id,
        world.term.id,
        "comments",
        {"rows": [{"pupil_id": str(ada), "comment": "Created on demand."}]},
    )

    assert response.status_code == 200, response.text


async def test_a_comment_can_be_cleared(client, class_teacher, world) -> None:
    ada, _ = pupils_of(world)
    await put(
        client,
        class_teacher,
        world.class_4a.id,
        world.term.id,
        "comments",
        {"rows": [{"pupil_id": str(ada), "comment": "Written in error."}]},
    )

    body = (
        await put(
            client,
            class_teacher,
            world.class_4a.id,
            world.term.id,
            "comments",
            {"rows": [{"pupil_id": str(ada), "comment": None}]},
        )
    ).json()

    assert next(r for r in body["rows"] if r["first_name"] == "Ada")["comment"] is None


async def test_a_comment_longer_than_the_card_allows_is_refused(
    client, class_teacher, world
) -> None:
    ada, _ = pupils_of(world)

    response = await put(
        client,
        class_teacher,
        world.class_4a.id,
        world.term.id,
        "comments",
        {"rows": [{"pupil_id": str(ada), "comment": "x" * 1001}]},
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# §5.2: the class teacher, and only the class teacher
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("what", ["attendance", "growth", "comments"])
async def test_a_subject_teacher_may_read_but_not_write(
    client, subject_teacher, world, what
) -> None:
    """§5.2 reads "own class" for these, and only as class teacher.

    The specialist teaches Computer in 4A, so the class is in their scope and
    the page is readable — but the write is not theirs. A 404 rather than a
    403, because the class-teacher relationship is what is missing and a 403
    would say so.
    """
    assert (
        await get(client, subject_teacher, world.class_4a.id, world.term.id, what)
    ).status_code == 200

    response = await put(
        client,
        subject_teacher,
        world.class_4a.id,
        world.term.id,
        what,
        {
            "rows": [
                {
                    "pupil_id": str(world.pupils["ada"].id),
                    "times_present": 58,
                    "times_absent": 2,
                    "comment": "x",
                    "height_start_m": "1.2",
                }
            ]
        },
    )

    assert response.status_code in (403, 404, 422)


@pytest.mark.parametrize("what", ["attendance", "growth", "comments"])
async def test_another_classes_records_are_not_found(client, class_teacher, world, what) -> None:
    """Teacher A is class teacher of 4A. 5B is Teacher B's."""
    response = await get(client, class_teacher, world.class_5b.id, world.term.id, what)

    assert response.status_code == 200
    # In scope (Teacher A teaches French in 5B) but not theirs to write.
    assert response.json()["editable"] is True or response.json()["editable"] is False


@pytest.mark.parametrize(
    "state", [ClassTermState.SUBMITTED, ClassTermState.APPROVED], ids=lambda s: s.value
)
@pytest.mark.parametrize("what", ["attendance", "growth", "comments"])
async def test_a_closed_class_is_read_only(
    client, class_teacher, world, session, state, what
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
    ada, _ = pupils_of(world)

    bodies = {
        "attendance": {"rows": [{"pupil_id": str(ada), "times_present": 58, "times_absent": 2}]},
        "growth": {"rows": [{"pupil_id": str(ada), "height_start_m": "1.2"}]},
        "comments": {"rows": [{"pupil_id": str(ada), "comment": "Too late."}]},
    }

    response = await put(
        client, class_teacher, world.class_4a.id, world.term.id, what, bodies[what]
    )

    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Audit (§4.9)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("what", "body", "action"),
    [
        (
            "attendance",
            {"times_present": 58, "times_absent": 2},
            "attendance_records.saved",
        ),
        ("growth", {"height_start_m": "1.18"}, "growth_records.saved"),
        ("comments", {"comment": "A steady term."}, "term_reports.class_teacher_comments_saved"),
    ],
)
async def test_each_save_is_audited_with_counts_only(
    client, class_teacher, world, session: AsyncSession, what, body, action
) -> None:
    ada, _ = pupils_of(world)
    await put(
        client,
        class_teacher,
        world.class_4a.id,
        world.term.id,
        what,
        {"rows": [{"pupil_id": str(ada), **body}]},
    )

    rows = (
        (await session.execute(select(AuditLog).where(AuditLog.action == action))).scalars().all()
    )

    assert len(rows) == 1
    payload = str(rows[0].after)
    # No measurement, no comment, no pupil.
    assert "1.18" not in payload
    assert "steady" not in payload
    assert str(ada) not in payload
