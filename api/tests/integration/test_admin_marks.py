"""The Marks Obtainable row over HTTP (ARCHITECTURE.md §4.4, N2).

The row is blank on both photographed cards, so **nothing here asserts a
value** — only that the school's own numbers are stored, that a number the
sheet has no column for is refused, and that lowering a maximum cannot
silently invalidate scores already entered.
"""

import uuid
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AssessmentPeriod, AuditAction, AuditLog, ResultEntry, TermHalf
from app.services.marks import applicable_maxima
from tests.integration.test_admin_academic import make_session, make_term

TERMS = "/api/v1/terms"


def marks_url(period_id: str) -> str:
    return f"/api/v1/assessment-periods/{period_id}/marks-obtainable"


async def periods_of(client: AsyncClient, headers: dict[str, str], term_id: str) -> dict[str, str]:
    response = await client.get(f"{TERMS}/{term_id}/assessment-periods", headers=headers)
    assert response.status_code == 200, response.text
    return {item["half"]: item["id"] for item in response.json()}


async def a_term_with_periods(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[dict, dict[str, str]]:
    academic = await make_session(client, headers)
    term = await make_term(client, headers, academic["id"])
    return term, await periods_of(client, headers, term["id"])


async def test_setting_the_school_wide_maxima(client: AsyncClient, admin_headers) -> None:
    _, periods = await a_term_with_periods(client, admin_headers)

    response = await client.put(
        marks_url(periods[TermHalf.FIRST_HALF.value]),
        headers=admin_headers,
        json={
            "ca_test_1": "8",
            "ca_test_2": "8",
            "ca_test_3": "8",
            "ca_test_4": "8",
            "ca_test_5": "8",
            "mid_term_test": "60",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["class_id"] is None
    assert Decimal(body["mid_term_test"]) == Decimal(60)
    assert Decimal(body["ca_test_1"]) == Decimal(8)
    assert body["exam"] is None


async def test_the_first_half_sheet_has_no_exam_column(client: AsyncClient, admin_headers) -> None:
    """§1.2: the two sheets carry different columns. That is the point."""
    _, periods = await a_term_with_periods(client, admin_headers)

    response = await client.put(
        marks_url(periods[TermHalf.FIRST_HALF.value]),
        headers=admin_headers,
        json={"ca_test_1": "8", "exam": "60"},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "no exam column" in detail
    assert "other half of the term" in detail


async def test_the_second_half_sheet_has_no_mid_term_test_column(
    client: AsyncClient, admin_headers
) -> None:
    _, periods = await a_term_with_periods(client, admin_headers)

    response = await client.put(
        marks_url(periods[TermHalf.SECOND_HALF.value]),
        headers=admin_headers,
        json={"ca_test_1": "8", "mid_term_test": "40"},
    )

    assert response.status_code == 422
    assert "no mid_term_test column" in response.json()["detail"]


async def test_a_maximum_of_zero_is_refused(client: AsyncClient, admin_headers) -> None:
    _, periods = await a_term_with_periods(client, admin_headers)

    response = await client.put(
        marks_url(periods[TermHalf.FIRST_HALF.value]),
        headers=admin_headers,
        json={"ca_test_1": "0", "mid_term_test": "60"},
    )

    assert response.status_code == 422
    assert "greater than zero" in response.json()["detail"]


async def test_a_negative_maximum_is_refused_by_the_schema(
    client: AsyncClient, admin_headers
) -> None:
    _, periods = await a_term_with_periods(client, admin_headers)

    response = await client.put(
        marks_url(periods[TermHalf.FIRST_HALF.value]),
        headers=admin_headers,
        json={"mid_term_test": "-5"},
    )

    assert response.status_code == 422


async def test_an_empty_row_is_refused(client: AsyncClient, admin_headers) -> None:
    """A row of nulls would leave every score unvalidated while looking set."""
    _, periods = await a_term_with_periods(client, admin_headers)

    response = await client.put(
        marks_url(periods[TermHalf.FIRST_HALF.value]), headers=admin_headers, json={}
    )

    assert response.status_code == 422
    assert "at least one column" in response.json()["detail"]


async def test_saving_twice_replaces_rather_than_duplicating(
    client: AsyncClient, admin_headers, session: AsyncSession
) -> None:
    _, periods = await a_term_with_periods(client, admin_headers)
    period_id = periods[TermHalf.FIRST_HALF.value]

    await client.put(
        marks_url(period_id),
        headers=admin_headers,
        json={"ca_test_1": "8", "mid_term_test": "60"},
    )
    await client.put(
        marks_url(period_id),
        headers=admin_headers,
        json={"ca_test_1": "10", "mid_term_test": "50"},
    )

    listed = (await client.get(marks_url(period_id), headers=admin_headers)).json()

    assert len(listed) == 1
    assert Decimal(listed[0]["ca_test_1"]) == Decimal(10)
    assert Decimal(listed[0]["mid_term_test"]) == Decimal(50)


async def test_a_column_left_out_is_cleared(client: AsyncClient, admin_headers) -> None:
    """A half-updated maxima row is worse than none: the cleared column would
    keep validating against a number the admin thought they had removed."""
    _, periods = await a_term_with_periods(client, admin_headers)
    period_id = periods[TermHalf.FIRST_HALF.value]

    await client.put(
        marks_url(period_id),
        headers=admin_headers,
        json={"ca_test_1": "8", "ca_test_2": "8", "mid_term_test": "60"},
    )
    response = await client.put(
        marks_url(period_id),
        headers=admin_headers,
        json={"ca_test_1": "8", "mid_term_test": "60"},
    )

    assert response.json()["ca_test_2"] is None


async def test_a_per_class_override_sits_beside_the_school_wide_row(
    client: AsyncClient, admin_headers, world
) -> None:
    # `world` already holds a 2026/2027 session, so this one needs its own name.
    academic = await make_session(client, admin_headers, name="2027/2028")
    term = await make_term(client, admin_headers, academic["id"], number="second")
    periods = await periods_of(client, admin_headers, term["id"])
    period_id = periods[TermHalf.SECOND_HALF.value]

    await client.put(
        marks_url(period_id),
        headers=admin_headers,
        json={"ca_test_1": "8", "exam": "60"},
    )
    response = await client.put(
        marks_url(period_id),
        headers=admin_headers,
        json={"class_id": str(world.class_4a.id), "ca_test_1": "10", "exam": "50"},
    )

    assert response.status_code == 200, response.text
    listed = (await client.get(marks_url(period_id), headers=admin_headers)).json()

    assert len(listed) == 2
    # The school-wide row first, then the overrides.
    assert listed[0]["class_id"] is None
    assert listed[1]["class_id"] == str(world.class_4a.id)


async def test_an_override_for_another_schools_class_is_a_404(
    client: AsyncClient, admin_headers, session: AsyncSession
) -> None:
    from app.models import Class, School

    other_school = School(name="Another School", short_name="AS")
    session.add(other_school)
    await session.flush()
    outsider = Class(school_id=other_school.id, name="Primary 4", level_order=4)
    session.add(outsider)
    await session.commit()

    _, periods = await a_term_with_periods(client, admin_headers)

    response = await client.put(
        marks_url(periods[TermHalf.FIRST_HALF.value]),
        headers=admin_headers,
        json={"class_id": str(outsider.id), "ca_test_1": "8", "mid_term_test": "60"},
    )

    assert response.status_code == 404


async def test_lowering_a_maximum_below_an_entered_score_is_refused(
    client: AsyncClient, admin_headers, world, session: AsyncSession
) -> None:
    """§4.4 lets the school change these numbers; this stops the one change
    that silently makes stored data invalid.

    Lowering Mid Term Test to 20 when a teacher has entered 35 leaves a row
    R1 would have rejected on entry and that prints on a card as it stands.
    """
    period = AssessmentPeriod(
        school_id=world.school.id, term_id=world.term.id, half=TermHalf.FIRST_HALF
    )
    session.add(period)
    await session.flush()
    session.add(
        ResultEntry(
            school_id=world.school.id,
            assessment_period_id=period.id,
            pupil_id=world.pupils["ada"].id,
            class_subject_id=world.maths_4a.id,
            mid_term_test=Decimal(35),
        )
    )
    await session.commit()

    response = await client.put(
        marks_url(str(period.id)),
        headers=admin_headers,
        json={"ca_test_1": "8", "mid_term_test": "20"},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "1 score already entered" in detail
    # The count, never the score itself (CLAUDE.md).
    assert "35" not in detail


async def test_raising_a_maximum_above_entered_scores_is_allowed(
    client: AsyncClient, admin_headers, world, session: AsyncSession
) -> None:
    period = AssessmentPeriod(
        school_id=world.school.id, term_id=world.term.id, half=TermHalf.FIRST_HALF
    )
    session.add(period)
    await session.flush()
    session.add(
        ResultEntry(
            school_id=world.school.id,
            assessment_period_id=period.id,
            pupil_id=world.pupils["ada"].id,
            class_subject_id=world.maths_4a.id,
            mid_term_test=Decimal(35),
        )
    )
    await session.commit()

    response = await client.put(
        marks_url(str(period.id)),
        headers=admin_headers,
        json={"ca_test_1": "8", "mid_term_test": "40"},
    )

    assert response.status_code == 200, response.text


async def test_every_maxima_change_is_audited(
    client: AsyncClient, admin_headers, session: AsyncSession
) -> None:
    """§4.9 names this one explicitly. Changing a maximum changes what every
    score on the sheet means."""
    _, periods = await a_term_with_periods(client, admin_headers)

    await client.put(
        marks_url(periods[TermHalf.FIRST_HALF.value]),
        headers=admin_headers,
        json={"ca_test_1": "8", "mid_term_test": "60"},
    )

    rows = await session.scalar(
        select(func.count(AuditLog.id)).where(AuditLog.action == AuditAction.MARKS_OBTAINABLE_SAVED)
    )

    assert rows == 1


async def test_the_audit_row_records_the_old_and_new_maxima(
    client: AsyncClient, admin_headers, session: AsyncSession
) -> None:
    _, periods = await a_term_with_periods(client, admin_headers)
    period_id = periods[TermHalf.FIRST_HALF.value]

    await client.put(
        marks_url(period_id),
        headers=admin_headers,
        json={"ca_test_1": "8", "mid_term_test": "60"},
    )
    await client.put(
        marks_url(period_id),
        headers=admin_headers,
        json={"ca_test_1": "8", "mid_term_test": "50"},
    )

    row = (
        await session.execute(
            select(AuditLog)
            .where(AuditLog.action == AuditAction.MARKS_OBTAINABLE_SAVED)
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
    ).scalar_one()

    assert row.before["mid_term_test"] == "60.00"
    assert row.after["mid_term_test"] == "50.00"


async def test_per_class_overrides_alone_can_configure_a_sheet(
    client: AsyncClient, admin_headers, world
) -> None:
    """A school that marks one class out of different numbers can configure
    only the overrides and still be correctly set up.

    Until every class has one, the checklist names the classes still
    uncovered — the school-wide row is the shortcut, not the requirement.
    """
    academic = await make_session(client, admin_headers, name="2028/2029")
    term = await make_term(client, admin_headers, academic["id"], number="third")
    periods = await periods_of(client, admin_headers, term["id"])
    period_id = periods[TermHalf.FIRST_HALF.value]

    await client.put(
        marks_url(period_id),
        headers=admin_headers,
        json={"class_id": str(world.class_4a.id), "ca_test_1": "10", "mid_term_test": "50"},
    )

    checklist = await client.get(
        "/api/v1/setup-checklist", headers=admin_headers, params={"term_id": term["id"]}
    )
    item = {row["key"]: row for row in checklist.json()["items"]}["marks_obtainable"]

    assert item["done"] is False
    # Primary 4 is covered by its override; Primary 5 is named. The second
    # half has nothing at all, so it is reported as a whole sheet.
    assert item["outstanding"] == ["First Half Term — Primary 5", "Second Half Term"]

    await client.put(
        marks_url(period_id),
        headers=admin_headers,
        json={"class_id": str(world.class_5b.id), "ca_test_1": "10", "mid_term_test": "50"},
    )
    await client.put(
        marks_url(periods[TermHalf.SECOND_HALF.value]),
        headers=admin_headers,
        json={"ca_test_1": "10", "exam": "50"},
    )

    checklist = await client.get(
        "/api/v1/setup-checklist", headers=admin_headers, params={"term_id": term["id"]}
    )
    item = {row["key"]: row for row in checklist.json()["items"]}["marks_obtainable"]

    assert item["done"] is True
    assert item["outstanding"] == []


async def test_a_class_override_wins_over_the_school_wide_row(
    client: AsyncClient, admin_headers, world, session: AsyncSession
) -> None:
    """R1 resolves "per-class row if present, otherwise the school-wide row",
    and that order lives in one function so R1 cannot restate it."""
    academic = await make_session(client, admin_headers, name="2029/2030")
    term = await make_term(client, admin_headers, academic["id"], number="second")
    periods = await periods_of(client, admin_headers, term["id"])
    period_id = periods[TermHalf.SECOND_HALF.value]

    await client.put(
        marks_url(period_id),
        headers=admin_headers,
        json={"ca_test_1": "8", "exam": "60"},
    )
    await client.put(
        marks_url(period_id),
        headers=admin_headers,
        json={"class_id": str(world.class_4a.id), "ca_test_1": "10", "exam": "50"},
    )

    override = await applicable_maxima(
        session,
        world.admin,
        assessment_period_id=uuid.UUID(period_id),
        class_id=world.class_4a.id,
    )
    fallback = await applicable_maxima(
        session,
        world.admin,
        assessment_period_id=uuid.UUID(period_id),
        class_id=world.class_5b.id,
    )

    assert override.exam == Decimal("50.00")
    assert fallback.exam == Decimal("60.00")
    assert fallback.class_id is None
