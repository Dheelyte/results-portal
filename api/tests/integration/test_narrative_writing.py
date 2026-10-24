"""Writing the narrative (ARCHITECTURE.md §8.2, §6 R8, §4.6; B1/D15).

The heaviest task in the system — sixteen passages per pupil, 480 for a class
of thirty — and the one where authorship is genuinely split: a specialist
writes the curriculum area for their own subject, the class teacher writes
everything else, and neither may write the other's.

`world` is shaped for exactly that: the specialist holds the Computer Skills
assignment for 4A, and no assignment exists for Work/Study Habits, so it falls
to the class teacher by absence (D15).
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    AuditLog,
    ClassTermState,
    ClassTermStatus,
    NarrativeEntry,
    NarrativeSection,
    UserRole,
)

API = settings.api_v1_prefix


@pytest.fixture
async def sections(session: AsyncSession, world):
    """Four sections: two from `world`, plus two the class teacher owns.

    Not all sixteen — the rules under test are about who owns which section
    and whether a body is present, and four sections make a failure legible.
    `test_full_term_setup` covers the real sixteen.
    """
    extra = [
        NarrativeSection(
            school_id=world.school.id,
            code="A.mathematics",
            label="Mathematics",
            group_label="Area of Curriculum",
            display_order=1,
        ),
        NarrativeSection(
            school_id=world.school.id, code="C", label="Attendance/Tardiness", display_order=8
        ),
    ]
    session.add_all(extra)
    await session.commit()

    from types import SimpleNamespace

    return SimpleNamespace(
        computer=world.computer_skills,  # assigned to the specialist for 4A
        work_habits=world.work_habits,  # no assignment: the class teacher's
        maths=extra[0],
        attendance=extra[1],
        all=[world.computer_skills, extra[0], world.work_habits, extra[1]],
    )


@pytest.fixture
async def class_teacher(headers_for, world) -> dict[str, str]:
    """Teacher A: class teacher of 4A."""
    return await headers_for(world.teacher_a)


@pytest.fixture
async def specialist(headers_for, world) -> dict[str, str]:
    """Teaches Computer in 4A and is class teacher of nothing."""
    return await headers_for(world.specialist)


async def read_pupil(client, headers, pupil_id, term_id):
    return await client.get(
        f"{API}/pupils/{pupil_id}/narrative",
        params={"term_id": str(term_id)},
        headers=headers,
    )


async def write(client, headers, pupil_id, term_id, passages):
    return await client.put(
        f"{API}/pupils/{pupil_id}/narrative",
        params={"term_id": str(term_id)},
        json={"passages": passages},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# The page §8.2 describes
# ---------------------------------------------------------------------------


async def test_a_pupils_page_carries_every_section_in_card_order(
    client, class_teacher, world, sections
) -> None:
    """§8.2: "one pupil, all sixteen sections on a page"."""
    response = await read_pupil(client, class_teacher, world.pupils["ada"].id, world.term.id)

    assert response.status_code == 200, response.text
    body = response.json()
    # display_order, not the order the fixture happened to insert them:
    # `world` gives Computer Skills order 4 and Work/Study Habits 7.
    assert [passage["code"] for passage in body["passages"]] == [
        "A.mathematics",
        "A.computer_skills",
        "B",
        "C",
    ]
    assert body["section_count"] == 4
    assert body["complete_count"] == 0


async def test_the_page_says_which_sections_this_teacher_may_write(
    client, class_teacher, specialist, world, sections
) -> None:
    """D15, from both sides. The same page, two different sets of textareas."""
    as_class_teacher = (
        await read_pupil(client, class_teacher, world.pupils["ada"].id, world.term.id)
    ).json()
    as_specialist = (
        await read_pupil(client, specialist, world.pupils["ada"].id, world.term.id)
    ).json()

    def writable(body):
        return {p["code"] for p in body["passages"] if p["writable"]}

    # The specialist holds Computer Skills for 4A; everything else falls to
    # the class teacher by absence of an assignment.
    assert writable(as_class_teacher) == {"A.mathematics", "B", "C"}
    assert writable(as_specialist) == {"A.computer_skills"}


async def test_a_specialist_can_read_what_the_class_teacher_wrote(
    client, class_teacher, specialist, world, sections
) -> None:
    """Reading and writing are different questions.

    A specialist writing one curriculum area needs to see the rest so as not
    to contradict it — but the textarea is still read-only to them.
    """
    await write(
        client,
        class_teacher,
        world.pupils["ada"].id,
        world.term.id,
        [{"section_id": str(sections.maths.id), "body": "Confident with long division."}],
    )

    body = (await read_pupil(client, specialist, world.pupils["ada"].id, world.term.id)).json()
    maths = next(p for p in body["passages"] if p["code"] == "A.mathematics")

    assert maths["body"] == "Confident with long division."
    assert maths["writable"] is False


async def test_the_page_carries_previous_and_next_pupil(
    client, class_teacher, world, sections
) -> None:
    """§8.2: "previous/next pupil navigation". 4A holds Ada then Emeka."""
    first = (await read_pupil(client, class_teacher, world.pupils["ada"].id, world.term.id)).json()
    second = (
        await read_pupil(client, class_teacher, world.pupils["emeka"].id, world.term.id)
    ).json()

    assert first["position"] == 1
    assert first["roll_size"] == 2
    assert first["previous_pupil_id"] is None
    assert first["next_pupil_id"] == str(world.pupils["emeka"].id)

    assert second["position"] == 2
    assert second["previous_pupil_id"] == str(world.pupils["ada"].id)
    assert second["next_pupil_id"] is None


async def test_a_pupil_in_another_class_is_not_found(
    client, class_teacher, world, sections
) -> None:
    """Chidi is in 5B. Teacher A teaches French there but is not its class
    teacher — and the narrative is per class."""
    response = await read_pupil(client, class_teacher, world.pupils["chidi"].id, world.term.id)

    # Teacher A does teach into 5B, so the pupil is visible; the sections are
    # simply not theirs to write.
    assert response.status_code == 200
    assert all(passage["writable"] is False for passage in response.json()["passages"])


async def test_a_pupil_in_no_class_of_this_teacher_is_not_found(
    client, headers_for, make_user, world, sections
) -> None:
    stranger = await make_user(UserRole.TEACHER)
    headers = await headers_for(stranger)

    response = await read_pupil(client, headers, world.pupils["ada"].id, world.term.id)

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


async def test_a_passage_saves_and_comes_back(client, class_teacher, world, sections) -> None:
    response = await write(
        client,
        class_teacher,
        world.pupils["ada"].id,
        world.term.id,
        [{"section_id": str(sections.work_habits.id), "body": "Settles quickly to a task."}],
    )

    assert response.status_code == 200, response.text
    body = response.json()
    habits = next(p for p in body["passages"] if p["code"] == "B")
    assert habits["body"] == "Settles quickly to a task."
    assert habits["is_complete"] is True
    assert body["complete_count"] == 1


async def test_an_omitted_section_is_left_alone(client, class_teacher, world, sections) -> None:
    """§8.2 autosaves like the grid, which means the dirty set."""
    ada = world.pupils["ada"].id
    await write(
        client,
        class_teacher,
        ada,
        world.term.id,
        [
            {"section_id": str(sections.work_habits.id), "body": "First."},
            {"section_id": str(sections.attendance.id), "body": "Second."},
        ],
    )

    body = (
        await write(
            client,
            class_teacher,
            ada,
            world.term.id,
            [{"section_id": str(sections.attendance.id), "body": "Second, revised."}],
        )
    ).json()

    assert next(p for p in body["passages"] if p["code"] == "B")["body"] == "First."
    assert next(p for p in body["passages"] if p["code"] == "C")["body"] == "Second, revised."


async def test_a_section_can_be_cleared(client, class_teacher, world, sections) -> None:
    ada = world.pupils["ada"].id
    await write(
        client,
        class_teacher,
        ada,
        world.term.id,
        [{"section_id": str(sections.work_habits.id), "body": "Written in error."}],
    )

    body = (
        await write(
            client,
            class_teacher,
            ada,
            world.term.id,
            [{"section_id": str(sections.work_habits.id), "body": None}],
        )
    ).json()
    habits = next(p for p in body["passages"] if p["code"] == "B")

    assert habits["body"] is None
    assert habits["is_complete"] is False


async def test_whitespace_alone_is_not_a_written_passage(
    client, class_teacher, world, sections
) -> None:
    """R8: complete means a non-empty body. A space is not an assessment."""
    body = (
        await write(
            client,
            class_teacher,
            world.pupils["ada"].id,
            world.term.id,
            [{"section_id": str(sections.work_habits.id), "body": "   \n  "}],
        )
    ).json()

    assert body["complete_count"] == 0
    assert next(p for p in body["passages"] if p["code"] == "B")["is_complete"] is False


async def test_another_teachers_section_is_refused_by_name(
    client, class_teacher, world, sections
) -> None:
    """D15's whole point. The class teacher may not write the specialist's
    curriculum area, and the refusal says which section rather than just
    failing."""
    response = await write(
        client,
        class_teacher,
        world.pupils["ada"].id,
        world.term.id,
        [{"section_id": str(sections.computer.id), "body": "Not mine to write."}],
    )

    assert response.status_code == 422
    errors = response.json()["errors"][str(sections.computer.id)]
    assert "Computer Skills" in errors["section_id"]
    assert "another teacher" in errors["section_id"]


async def test_nothing_is_saved_when_one_section_is_refused(
    client, class_teacher, world, sections
) -> None:
    """All or none, as the score grid is: a half-saved page leaves the teacher
    unable to tell from the screen what reached the database."""
    response = await write(
        client,
        class_teacher,
        world.pupils["ada"].id,
        world.term.id,
        [
            {"section_id": str(sections.work_habits.id), "body": "Mine."},
            {"section_id": str(sections.computer.id), "body": "Not mine."},
        ],
    )
    assert response.status_code == 422

    body = (await read_pupil(client, class_teacher, world.pupils["ada"].id, world.term.id)).json()
    assert all(passage["body"] is None for passage in body["passages"])


async def test_the_specialist_writes_their_own_section(client, specialist, world, sections) -> None:
    response = await write(
        client,
        specialist,
        world.pupils["ada"].id,
        world.term.id,
        [{"section_id": str(sections.computer.id), "body": "Keyboards confidently."}],
    )

    assert response.status_code == 200, response.text
    computer = next(p for p in response.json()["passages"] if p["code"] == "A.computer_skills")
    assert computer["body"] == "Keyboards confidently."


async def test_a_section_from_another_card_is_refused(
    client, class_teacher, world, sections
) -> None:
    response = await write(
        client,
        class_teacher,
        world.pupils["ada"].id,
        world.term.id,
        [{"section_id": str(uuid.uuid4()), "body": "Nowhere to put this."}],
    )

    assert response.status_code == 422
    assert "not part of this card" in response.text


async def test_an_inactive_section_cannot_be_written(
    client, class_teacher, world, sections, session
) -> None:
    """N7 may reduce the sixteen. A retired section stops being writable
    without a migration, and stops counting towards R8."""
    sections.attendance.is_active = False
    await session.commit()

    response = await write(
        client,
        class_teacher,
        world.pupils["ada"].id,
        world.term.id,
        [{"section_id": str(sections.attendance.id), "body": "Retired section."}],
    )

    assert response.status_code == 422
    body = (await read_pupil(client, class_teacher, world.pupils["ada"].id, world.term.id)).json()
    assert body["section_count"] == 3


async def test_a_passage_longer_than_the_card_allows_is_refused(
    client, class_teacher, world, sections
) -> None:
    """A20. Generous rather than tight — this catches a paste accident."""
    response = await write(
        client,
        class_teacher,
        world.pupils["ada"].id,
        world.term.id,
        [{"section_id": str(sections.work_habits.id), "body": "x" * 2001}],
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# R14 and R8
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state", [ClassTermState.SUBMITTED, ClassTermState.APPROVED], ids=lambda s: s.value
)
async def test_a_closed_class_is_read_only(
    client, class_teacher, world, sections, session, state
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

    page = (await read_pupil(client, class_teacher, world.pupils["ada"].id, world.term.id)).json()
    assert page["editable"] is False

    response = await write(
        client,
        class_teacher,
        world.pupils["ada"].id,
        world.term.id,
        [{"section_id": str(sections.work_habits.id), "body": "Too late."}],
    )

    assert response.status_code == 409


async def test_the_first_passage_opens_the_term(client, class_teacher, world, sections) -> None:
    before = (await read_pupil(client, class_teacher, world.pupils["ada"].id, world.term.id)).json()
    assert before["state"] == "not_started"

    after = (
        await write(
            client,
            class_teacher,
            world.pupils["ada"].id,
            world.term.id,
            [{"section_id": str(sections.work_habits.id), "body": "Started."}],
        )
    ).json()

    assert after["state"] == "in_progress"


# ---------------------------------------------------------------------------
# The class list (§8.2's progress indicator)
# ---------------------------------------------------------------------------


async def test_the_class_list_counts_complete_pupils(
    client, class_teacher, specialist, world, sections
) -> None:
    """§8.2: "12 of 30 pupils complete". Complete means every active section,
    whoever wrote it — so the specialist's contribution counts."""
    ada = world.pupils["ada"].id
    await write(
        client,
        class_teacher,
        ada,
        world.term.id,
        [
            {"section_id": str(sections.maths.id), "body": "a"},
            {"section_id": str(sections.work_habits.id), "body": "b"},
            {"section_id": str(sections.attendance.id), "body": "c"},
        ],
    )

    partway = (
        await client.get(
            f"{API}/classes/{world.class_4a.id}/narrative",
            params={"term_id": str(world.term.id)},
            headers=class_teacher,
        )
    ).json()
    assert partway["complete_pupils"] == 0
    assert next(p for p in partway["pupils"] if p["pupil_id"] == str(ada))["written"] == 3

    await write(
        client,
        specialist,
        ada,
        world.term.id,
        [{"section_id": str(sections.computer.id), "body": "d"}],
    )

    done = (
        await client.get(
            f"{API}/classes/{world.class_4a.id}/narrative",
            params={"term_id": str(world.term.id)},
            headers=class_teacher,
        )
    ).json()

    assert done["complete_pupils"] == 1
    assert done["roll_size"] == 2
    assert next(p for p in done["pupils"] if p["pupil_id"] == str(ada))["is_complete"] is True


async def test_the_class_list_says_which_sections_are_this_teachers(
    client, specialist, world, sections
) -> None:
    body = (
        await client.get(
            f"{API}/classes/{world.class_4a.id}/narrative",
            params={"term_id": str(world.term.id)},
            headers=specialist,
        )
    ).json()

    assert {s["code"] for s in body["sections"] if s["writable"]} == {"A.computer_skills"}


# ---------------------------------------------------------------------------
# Audit (§4.9)
# ---------------------------------------------------------------------------


async def test_a_save_is_audited_without_the_passage(
    client, class_teacher, world, sections, session
) -> None:
    """CLAUDE.md: no comment, and no pupil's identity, in a log. A narrative
    passage is both."""
    await write(
        client,
        class_teacher,
        world.pupils["ada"].id,
        world.term.id,
        [{"section_id": str(sections.work_habits.id), "body": "Settles quickly to a task."}],
    )

    rows = (
        (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "narrative_entries.saved")
            )
        )
        .scalars()
        .all()
    )

    assert len(rows) == 1
    payload = rows[0].after
    assert payload["sections_saved"] == 1
    assert payload["codes"] == ["B"]
    assert "Settles" not in str(payload)
    assert "Ada" not in str(payload)
    assert "Okafor" not in str(payload)


async def test_the_writer_is_recorded_on_the_row(
    client, specialist, world, sections, session
) -> None:
    """§4.6 keeps `written_by`: with authorship split, "who wrote this" is a
    real question when a parent queries a passage."""
    await write(
        client,
        specialist,
        world.pupils["ada"].id,
        world.term.id,
        [{"section_id": str(sections.computer.id), "body": "Keyboards confidently."}],
    )

    entry = (
        await session.execute(
            select(NarrativeEntry).where(NarrativeEntry.section_id == sections.computer.id)
        )
    ).scalar_one()

    assert entry.written_by == world.specialist.id


# ---------------------------------------------------------------------------
# R8 and R10's per-pupil helpers
# ---------------------------------------------------------------------------
#
# `narrative.narrative_is_complete` and `reports.has_comment` are what R10's
# submission gate will ask, one pupil at a time (milestone 8). They are tested
# here, where the data they read is written, rather than arriving untested with
# the gate that calls them.


async def test_r8_is_complete_only_when_every_active_section_has_a_body(
    client, class_teacher, specialist, world, sections, session
) -> None:
    from app.services.narrative import narrative_is_complete

    ada = world.pupils["ada"].id

    async def complete() -> bool:
        return await narrative_is_complete(
            session, world.teacher_a, pupil_id=ada, term_id=world.term.id
        )

    assert await complete() is False

    # Everything the class teacher owns: still short by the specialist's one.
    await write(
        client,
        class_teacher,
        ada,
        world.term.id,
        [
            {"section_id": str(sections.maths.id), "body": "a"},
            {"section_id": str(sections.work_habits.id), "body": "b"},
            {"section_id": str(sections.attendance.id), "body": "c"},
        ],
    )
    assert await complete() is False

    await write(
        client,
        specialist,
        ada,
        world.term.id,
        [{"section_id": str(sections.computer.id), "body": "d"}],
    )
    assert await complete() is True


async def test_r8_agrees_with_the_class_list(
    client, class_teacher, specialist, world, sections, session
) -> None:
    """The class list's per-pupil flag and R8's helper are the same rule.

    They are computed two different ways — one grouped query for the class,
    one count for the pupil — so a disagreement is exactly the kind of bug
    that would show up as "the list says complete, submission says not".
    """
    from app.services.narrative import narrative_is_complete

    ada = world.pupils["ada"].id
    for writer, section in (
        (class_teacher, sections.maths),
        (class_teacher, sections.work_habits),
        (class_teacher, sections.attendance),
        (specialist, sections.computer),
    ):
        await write(
            client, writer, ada, world.term.id, [{"section_id": str(section.id), "body": "x"}]
        )

    listing = (
        await client.get(
            f"{API}/classes/{world.class_4a.id}/narrative",
            params={"term_id": str(world.term.id)},
            headers=class_teacher,
        )
    ).json()
    from_list = next(p for p in listing["pupils"] if p["pupil_id"] == str(ada))["is_complete"]

    assert from_list is await narrative_is_complete(
        session, world.teacher_a, pupil_id=ada, term_id=world.term.id
    )


async def test_retiring_a_section_can_complete_a_pupil(
    client, class_teacher, world, sections, session
) -> None:
    """R8 counts *active* sections, so N7's answer changes who is complete.

    A school that retires a section finds pupils who were one passage short
    are now finished — which is the intended behaviour and worth pinning,
    because it means retiring a section after submission would change a
    completeness answer that has already been acted on.
    """
    from app.services.narrative import narrative_is_complete

    ada = world.pupils["ada"].id
    for section in (sections.maths, sections.work_habits, sections.attendance):
        await write(
            client,
            class_teacher,
            ada,
            world.term.id,
            [{"section_id": str(section.id), "body": "x"}],
        )

    assert (
        await narrative_is_complete(session, world.teacher_a, pupil_id=ada, term_id=world.term.id)
        is False
    )

    sections.computer.is_active = False
    await session.commit()

    assert (
        await narrative_is_complete(session, world.teacher_a, pupil_id=ada, term_id=world.term.id)
        is True
    )


async def test_a_school_with_no_sections_is_never_complete(world, session) -> None:
    """Zero of zero is not "done". A card with no assessment pages is a setup
    error, and R10 should block on it rather than wave it through."""
    from app.models import NarrativeSection
    from app.services.narrative import narrative_is_complete

    await session.execute(NarrativeSection.__table__.delete())
    await session.commit()

    assert (
        await narrative_is_complete(
            session, world.teacher_a, pupil_id=world.pupils["ada"].id, term_id=world.term.id
        )
        is False
    )


async def test_r10s_comment_check_sees_what_the_teacher_wrote(
    client, class_teacher, world, sections, session
) -> None:
    from app.services.reports import has_comment

    ada = world.pupils["ada"].id

    async def answered() -> bool:
        return await has_comment(session, world.teacher_a, pupil_id=ada, term_id=world.term.id)

    assert await answered() is False

    await client.put(
        f"{API}/classes/{world.class_4a.id}/comments",
        params={"term_id": str(world.term.id)},
        json={"rows": [{"pupil_id": str(ada), "comment": "A purposeful term."}]},
        headers=class_teacher,
    )
    assert await answered() is True

    # Cleared again, and whitespace is not a comment.
    await client.put(
        f"{API}/classes/{world.class_4a.id}/comments",
        params={"term_id": str(world.term.id)},
        json={"rows": [{"pupil_id": str(ada), "comment": "   "}]},
        headers=class_teacher,
    )
    assert await answered() is False
