"""Admin setup over HTTP: sessions, terms, half terms and column maxima
(ARCHITECTURE.md §7, §4.2, §4.4).

Every test here goes through the real endpoint with a real token, because the
rules being checked are only worth anything if the route enforces them.
"""

import datetime as dt

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AssessmentPeriod, AuditAction, AuditLog, TermHalf

SESSIONS = "/api/v1/sessions"
TERMS = "/api/v1/terms"

SESSION_START = dt.date(2026, 9, 14)
SESSION_END = dt.date(2027, 7, 23)
TERM_START = dt.date(2026, 9, 14)
TERM_END = dt.date(2026, 12, 11)


async def make_session(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str = "2026/2027",
    is_current: bool = True,
    starts_on: dt.date = SESSION_START,
    ends_on: dt.date = SESSION_END,
) -> dict:
    response = await client.post(
        SESSIONS,
        headers=headers,
        json={
            "name": name,
            "starts_on": starts_on.isoformat(),
            "ends_on": ends_on.isoformat(),
            "is_current": is_current,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def make_term(
    client: AsyncClient,
    headers: dict[str, str],
    session_id: str,
    *,
    number: str = "first",
    is_current: bool = True,
    starts_on: dt.date = TERM_START,
    ends_on: dt.date = TERM_END,
    times_school_opened: int | None = 60,
) -> dict:
    response = await client.post(
        TERMS,
        headers=headers,
        json={
            "academic_session_id": session_id,
            "number": number,
            "starts_on": starts_on.isoformat(),
            "ends_on": ends_on.isoformat(),
            "times_school_opened": times_school_opened,
            "is_current": is_current,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


async def test_an_admin_creates_a_session(client: AsyncClient, admin_headers) -> None:
    body = await make_session(client, admin_headers)

    assert body["name"] == "2026/2027"
    assert body["is_current"] is True


async def test_a_session_must_start_before_it_ends(client: AsyncClient, admin_headers) -> None:
    response = await client.post(
        SESSIONS,
        headers=admin_headers,
        json={"name": "Backwards", "starts_on": "2027-07-23", "ends_on": "2026-09-14"},
    )

    assert response.status_code == 422
    assert "start before it ends" in response.json()["detail"]


async def test_a_duplicate_session_name_is_a_conflict(client: AsyncClient, admin_headers) -> None:
    await make_session(client, admin_headers)

    response = await client.post(
        SESSIONS,
        headers=admin_headers,
        json={
            "name": "2026/2027",
            "starts_on": SESSION_START.isoformat(),
            "ends_on": SESSION_END.isoformat(),
        },
    )

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


async def test_only_one_session_is_ever_current(client: AsyncClient, admin_headers) -> None:
    """`scope.current_session_id` resolves with LIMIT 1.

    Two current sessions would not fail — they would silently pick one, and
    half the portal would scope itself to last year.
    """
    first = await make_session(
        client,
        admin_headers,
        name="2025/2026",
        starts_on=dt.date(2025, 9, 15),
        ends_on=dt.date(2026, 7, 24),
    )
    second = await make_session(
        client,
        admin_headers,
        name="2026/2027",
        starts_on=dt.date(2027, 9, 13),
        ends_on=dt.date(2028, 7, 21),
    )

    listed = (await client.get(SESSIONS, headers=admin_headers)).json()
    current = [item["id"] for item in listed if item["is_current"]]

    assert current == [second["id"]]
    assert first["id"] not in current


async def test_making_an_old_session_current_again_demotes_the_other(
    client: AsyncClient, admin_headers
) -> None:
    first = await make_session(
        client,
        admin_headers,
        name="2025/2026",
        starts_on=dt.date(2025, 9, 15),
        ends_on=dt.date(2026, 7, 24),
    )
    await make_session(
        client,
        admin_headers,
        name="2026/2027",
        starts_on=dt.date(2027, 9, 13),
        ends_on=dt.date(2028, 7, 21),
    )

    response = await client.post(f"{SESSIONS}/{first['id']}/current", headers=admin_headers)

    assert response.status_code == 200
    listed = (await client.get(SESSIONS, headers=admin_headers)).json()
    assert [item["id"] for item in listed if item["is_current"]] == [first["id"]]


# ---------------------------------------------------------------------------
# Terms
# ---------------------------------------------------------------------------


async def test_creating_a_term_creates_both_half_terms(
    client: AsyncClient, admin_headers, session: AsyncSession
) -> None:
    """§1.1 states the two halves as a fact, not an option.

    A term that exists with nowhere to enter scores is a term a teacher is
    locked out of, so the rows arrive with the term.
    """
    academic = await make_session(client, admin_headers)
    term = await make_term(client, admin_headers, academic["id"])

    response = await client.get(f"{TERMS}/{term['id']}/assessment-periods", headers=admin_headers)

    assert response.status_code == 200
    halves = [item["half"] for item in response.json()]
    assert halves == [TermHalf.FIRST_HALF.value, TermHalf.SECOND_HALF.value]

    stored = await session.scalar(
        select(func.count(AssessmentPeriod.id)).where(AssessmentPeriod.term_id == term["id"])
    )
    assert stored == 2


async def test_a_term_must_fall_inside_its_session(client: AsyncClient, admin_headers) -> None:
    academic = await make_session(client, admin_headers)

    response = await client.post(
        TERMS,
        headers=admin_headers,
        json={
            "academic_session_id": academic["id"],
            "number": "first",
            "starts_on": "2026-08-01",
            "ends_on": "2026-12-11",
        },
    )

    assert response.status_code == 422
    assert "inside its session" in response.json()["detail"]


async def test_the_same_term_cannot_exist_twice_in_a_session(
    client: AsyncClient, admin_headers
) -> None:
    academic = await make_session(client, admin_headers)
    await make_term(client, admin_headers, academic["id"])

    response = await client.post(
        TERMS,
        headers=admin_headers,
        json={
            "academic_session_id": academic["id"],
            "number": "first",
            "starts_on": TERM_START.isoformat(),
            "ends_on": TERM_END.isoformat(),
        },
    )

    assert response.status_code == 409


async def test_terms_list_in_chronological_order(client: AsyncClient, admin_headers) -> None:
    """The enum's own alphabetical order puts "first" after "second"."""
    academic = await make_session(client, admin_headers)
    await make_term(
        client,
        admin_headers,
        academic["id"],
        number="third",
        is_current=False,
        starts_on=dt.date(2027, 4, 19),
        ends_on=dt.date(2027, 7, 23),
    )
    await make_term(client, admin_headers, academic["id"], number="first", is_current=False)
    await make_term(
        client,
        admin_headers,
        academic["id"],
        number="second",
        is_current=False,
        starts_on=dt.date(2027, 1, 11),
        ends_on=dt.date(2027, 4, 2),
    )

    listed = (
        await client.get(
            TERMS, headers=admin_headers, params={"academic_session_id": academic["id"]}
        )
    ).json()

    assert [item["number"] for item in listed] == ["first", "second", "third"]


async def test_times_school_opened_can_be_filled_in_later(
    client: AsyncClient, admin_headers
) -> None:
    """R9's denominator is rarely known on the day the term is created."""
    academic = await make_session(client, admin_headers)
    term = await make_term(client, admin_headers, academic["id"], times_school_opened=None)
    assert term["times_school_opened"] is None

    response = await client.patch(
        f"{TERMS}/{term['id']}", headers=admin_headers, json={"times_school_opened": 58}
    )

    assert response.status_code == 200
    assert response.json()["times_school_opened"] == 58


async def test_only_one_term_is_ever_current(client: AsyncClient, admin_headers) -> None:
    academic = await make_session(client, admin_headers)
    first = await make_term(client, admin_headers, academic["id"], number="first")
    second = await make_term(
        client,
        admin_headers,
        academic["id"],
        number="second",
        starts_on=dt.date(2027, 1, 11),
        ends_on=dt.date(2027, 4, 2),
    )

    listed = (await client.get(TERMS, headers=admin_headers)).json()

    assert [item["id"] for item in listed if item["is_current"]] == [second["id"]]
    assert first["id"] not in [item["id"] for item in listed if item["is_current"]]


async def test_a_term_outside_the_current_session_cannot_be_made_current(
    client: AsyncClient, admin_headers
) -> None:
    """Two pointers, two deliberate acts.

    Moving the school into another year changes which classes, enrolments and
    assignments resolve, so it is not a side effect of picking a term.
    """
    old = await make_session(
        client,
        admin_headers,
        name="2025/2026",
        is_current=False,
        starts_on=dt.date(2025, 9, 15),
        ends_on=dt.date(2026, 7, 24),
    )
    await make_session(
        client,
        admin_headers,
        name="2026/2027",
        starts_on=dt.date(2027, 9, 13),
        ends_on=dt.date(2028, 7, 21),
    )
    stale_term = await make_term(
        client,
        admin_headers,
        old["id"],
        is_current=False,
        starts_on=dt.date(2025, 9, 15),
        ends_on=dt.date(2025, 12, 12),
    )

    response = await client.post(f"{TERMS}/{stale_term['id']}/current", headers=admin_headers)

    assert response.status_code == 409
    assert "not the current session" in response.json()["detail"]


async def test_changing_the_current_session_demotes_a_term_elsewhere(
    client: AsyncClient, admin_headers
) -> None:
    """Otherwise the two pointers disagree and the portal scopes to neither."""
    first_year = await make_session(
        client,
        admin_headers,
        name="2025/2026",
        starts_on=dt.date(2025, 9, 15),
        ends_on=dt.date(2026, 7, 24),
    )
    term = await make_term(
        client,
        admin_headers,
        first_year["id"],
        starts_on=dt.date(2025, 9, 15),
        ends_on=dt.date(2025, 12, 12),
    )
    assert term["is_current"] is True

    await make_session(
        client,
        admin_headers,
        name="2026/2027",
        starts_on=dt.date(2027, 9, 13),
        ends_on=dt.date(2028, 7, 21),
    )

    listed = (await client.get(TERMS, headers=admin_headers)).json()
    assert [item["is_current"] for item in listed] == [False]


# ---------------------------------------------------------------------------
# Assessment periods
# ---------------------------------------------------------------------------


async def test_setting_a_half_terms_window(client: AsyncClient, admin_headers) -> None:
    academic = await make_session(client, admin_headers)
    term = await make_term(client, admin_headers, academic["id"])

    response = await client.post(
        f"{TERMS}/{term['id']}/assessment-periods",
        headers=admin_headers,
        json={"half": "first_half", "opens_on": "2026-09-14", "closes_on": "2026-10-23"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["opens_on"] == "2026-09-14"
    assert body["closes_on"] == "2026-10-23"


async def test_a_half_terms_window_must_sit_inside_the_term(
    client: AsyncClient, admin_headers
) -> None:
    academic = await make_session(client, admin_headers)
    term = await make_term(client, admin_headers, academic["id"])

    response = await client.post(
        f"{TERMS}/{term['id']}/assessment-periods",
        headers=admin_headers,
        json={"half": "first_half", "opens_on": "2026-09-14", "closes_on": "2027-02-01"},
    )

    assert response.status_code == 422
    assert "inside the term" in response.json()["detail"]


async def test_a_half_term_must_open_before_it_closes(client: AsyncClient, admin_headers) -> None:
    academic = await make_session(client, admin_headers)
    term = await make_term(client, admin_headers, academic["id"])

    response = await client.post(
        f"{TERMS}/{term['id']}/assessment-periods",
        headers=admin_headers,
        json={"half": "first_half", "opens_on": "2026-10-23", "closes_on": "2026-09-14"},
    )

    assert response.status_code == 422
    assert "open before it closes" in response.json()["detail"]


async def test_term_dates_cannot_orphan_a_configured_half_term(
    client: AsyncClient, admin_headers
) -> None:
    """Shrinking a term must not leave a half term's window outside it."""
    academic = await make_session(client, admin_headers)
    term = await make_term(client, admin_headers, academic["id"])
    await client.post(
        f"{TERMS}/{term['id']}/assessment-periods",
        headers=admin_headers,
        json={"half": "second_half", "opens_on": "2026-11-01", "closes_on": "2026-12-11"},
    )

    response = await client.patch(
        f"{TERMS}/{term['id']}", headers=admin_headers, json={"ends_on": "2026-10-31"}
    )

    assert response.status_code == 422
    assert "outside the term" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    [
        AuditAction.SESSION_CREATED,
        AuditAction.SESSION_MADE_CURRENT,
        AuditAction.TERM_CREATED,
        AuditAction.ASSESSMENT_PERIOD_SAVED,
    ],
)
async def test_setup_changes_are_audited(
    client: AsyncClient, admin_headers, session: AsyncSession, action: str
) -> None:
    """ "Who changed the current term" is the first question asked when a
    class of results goes missing (D40)."""
    academic = await make_session(client, admin_headers)
    term = await make_term(client, admin_headers, academic["id"])
    await client.post(
        f"{TERMS}/{term['id']}/assessment-periods",
        headers=admin_headers,
        json={"half": "first_half", "opens_on": "2026-09-14", "closes_on": "2026-10-23"},
    )

    rows = await session.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == action))

    assert rows and rows >= 1
