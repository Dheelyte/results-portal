"""Grading scales, narrative sections and the phrase bank over HTTP
(§1.3, §4.5, §4.6).

The grading scale is versioned because the school's own two answers disagree
(N1), and §4.5 is explicit about the consequence: a card printed last term must
still agree with the portal. So a scale is created and activated, never edited.
"""

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditAction, AuditLog
from app.seed.reference import BEHAVIOURAL_SECTIONS, CARD_GRADE_BANDS, CURRICULUM_AREAS

SCALES = "/api/v1/grading-scales"
SECTIONS = "/api/v1/narrative-sections"
BANK = "/api/v1/comment-bank"


def card_bands() -> list[dict]:
    return [
        {"letter": letter, "remark": remark, "min_score": str(low), "max_score": str(high)}
        for letter, remark, low, high in CARD_GRADE_BANDS
    ]


async def a_scale(client: AsyncClient, headers, **payload) -> dict:
    body = {
        "name": "Card scale (seven bands)",
        "effective_from": "2026-09-14",
        "bands": card_bands(),
        "activate": True,
    } | payload
    response = await client.post(SCALES, headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Grading scales
# ---------------------------------------------------------------------------


async def test_creating_the_cards_own_scale(client: AsyncClient, admin_headers) -> None:
    body = await a_scale(client, admin_headers)

    assert body["is_active"] is True
    assert [band["letter"] for band in body["bands"]] == ["A+", "A", "B+", "B", "C", "D", "E"]


async def test_bands_print_highest_first(client: AsyncClient, admin_headers) -> None:
    """The order the card prints its key in."""
    body = await a_scale(client, admin_headers)

    assert body["bands"][0]["letter"] == "A+"
    assert float(body["bands"][0]["max_score"]) == 100.0


async def test_overlapping_bands_are_refused(client: AsyncClient, admin_headers) -> None:
    response = await client.post(
        SCALES,
        headers=admin_headers,
        json={
            "name": "Broken",
            "effective_from": "2026-09-14",
            "bands": [
                {"letter": "A", "remark": "Good", "min_score": "80", "max_score": "100"},
                {"letter": "B", "remark": "Fair", "min_score": "70", "max_score": "85"},
                {"letter": "E", "remark": "Weak", "min_score": "0", "max_score": "69"},
            ],
        },
    )

    assert response.status_code == 422
    assert "overlap" in response.json()["detail"]


async def test_a_gap_in_the_bands_is_refused(client: AsyncClient, admin_headers) -> None:
    """A mark in no band prints an empty grade cell."""
    response = await client.post(
        SCALES,
        headers=admin_headers,
        json={
            "name": "Gappy",
            "effective_from": "2026-09-14",
            "bands": [
                {"letter": "A", "remark": "Good", "min_score": "60", "max_score": "100"},
                {"letter": "E", "remark": "Weak", "min_score": "0", "max_score": "49"},
            ],
        },
    )

    assert response.status_code == 422
    assert "50-59" in response.json()["detail"]


async def test_only_one_scale_is_active_at_a_time(client: AsyncClient, admin_headers) -> None:
    """§4.5 resolves grades "from the active scale" — singular. Two would make
    the grade depend on row order."""
    first = await a_scale(client, admin_headers)
    second = await a_scale(
        client,
        admin_headers,
        name="Six bands (September requirements)",
        bands=[
            {"letter": "A", "remark": "Excellent", "min_score": "75", "max_score": "100"},
            {"letter": "B", "remark": "Very Good", "min_score": "65", "max_score": "74"},
            {"letter": "C", "remark": "Good", "min_score": "55", "max_score": "64"},
            {"letter": "D", "remark": "Pass", "min_score": "45", "max_score": "54"},
            {"letter": "E", "remark": "Weak", "min_score": "35", "max_score": "44"},
            {"letter": "F", "remark": "Fail", "min_score": "0", "max_score": "34"},
        ],
    )

    listed = (await client.get(SCALES, headers=admin_headers)).json()
    active = [item["id"] for item in listed if item["is_active"]]

    assert active == [second["id"]]
    assert first["id"] not in active


async def test_an_old_scale_can_be_reactivated(client: AsyncClient, admin_headers) -> None:
    """Answering N1 means saying "use this one from now on"."""
    first = await a_scale(client, admin_headers)
    await a_scale(client, admin_headers, name="Another scale")

    response = await client.post(f"{SCALES}/{first['id']}/activate", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["is_active"] is True


async def test_old_scales_are_kept(client: AsyncClient, admin_headers) -> None:
    """A card printed last term had its grades resolved from the scale in
    force then, and must still agree with the portal."""
    first = await a_scale(client, admin_headers)
    await a_scale(client, admin_headers, name="Another scale")

    listed = (await client.get(SCALES, headers=admin_headers)).json()

    assert first["id"] in [item["id"] for item in listed]
    assert len(listed) == 2


async def test_there_is_no_way_to_edit_a_band(client: AsyncClient, admin_headers) -> None:
    """Deliberate: §4.5 says recomputing would silently rewrite history."""
    scale = await a_scale(client, admin_headers)

    for method in (client.put, client.patch):
        response = await method(
            f"{SCALES}/{scale['id']}", headers=admin_headers, json={"name": "Renamed"}
        )
        # 404 because no such route is mounted at all, which is the point.
        assert response.status_code in (404, 405)


async def test_every_scale_change_is_audited(
    client: AsyncClient, admin_headers, session: AsyncSession
) -> None:
    """§4.9 names this one explicitly."""
    await a_scale(client, admin_headers)

    created = await session.scalar(
        select(func.count(AuditLog.id)).where(AuditLog.action == AuditAction.GRADING_SCALE_CREATED)
    )
    activated = await session.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.action == AuditAction.GRADING_SCALE_ACTIVATED
        )
    )

    assert created == 1
    assert activated == 1


# ---------------------------------------------------------------------------
# Narrative sections
# ---------------------------------------------------------------------------


def all_sixteen() -> list[dict]:
    """The card's sixteen sections: seven curriculum areas, then B to J (D27)."""
    sections = [
        {
            "code": code,
            "label": label,
            "group_label": "Area of Curriculum",
            "display_order": order,
        }
        for order, (code, label) in enumerate(CURRICULUM_AREAS)
    ]
    sections += [
        {"code": code, "label": label, "display_order": len(CURRICULUM_AREAS) + order}
        for order, (code, label) in enumerate(BEHAVIOURAL_SECTIONS)
    ]
    return sections


async def test_the_sixteen_sections_round_trip(client: AsyncClient, admin_headers) -> None:
    """Sixteen, not seventeen: 7 + 9, which the photographs confirm (D27)."""
    sections = all_sixteen()
    assert len(sections) == 16

    response = await client.put(SECTIONS, headers=admin_headers, json={"sections": sections})

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 16
    assert body[0]["code"] == "A.english_language_arts"
    assert body[0]["group_label"] == "Area of Curriculum"
    assert body[-1]["code"] == "J"


async def test_sections_are_upserted_by_code(client: AsyncClient, admin_headers) -> None:
    """Reordering is the common edit, and an order only means anything
    relative to the others."""
    await client.put(SECTIONS, headers=admin_headers, json={"sections": all_sixteen()})

    response = await client.put(
        SECTIONS,
        headers=admin_headers,
        json={"sections": [{"code": "J", "label": "Overall Performance", "display_order": 0}]},
    )

    assert response.status_code == 200
    body = {item["code"]: item for item in response.json()}
    assert len(body) == 16  # nothing was replaced wholesale
    assert body["J"]["label"] == "Overall Performance"
    assert body["J"]["display_order"] == 0


async def test_a_section_is_retired_rather_than_deleted(client: AsyncClient, admin_headers) -> None:
    """N7 may reduce the sixteen; a term's written passages point at them."""
    await client.put(SECTIONS, headers=admin_headers, json={"sections": all_sixteen()})

    await client.put(
        SECTIONS,
        headers=admin_headers,
        json={
            "sections": [
                {
                    "code": "F",
                    "label": "Outside Behaviour",
                    "display_order": 11,
                    "is_active": False,
                }
            ]
        },
    )

    active = (
        await client.get(SECTIONS, headers=admin_headers, params={"include_inactive": False})
    ).json()
    everything = (await client.get(SECTIONS, headers=admin_headers)).json()

    assert len(active) == 15
    assert len(everything) == 16


async def test_a_repeated_code_is_refused(client: AsyncClient, admin_headers) -> None:
    response = await client.put(
        SECTIONS,
        headers=admin_headers,
        json={
            "sections": [
                {"code": "B", "label": "One", "display_order": 0},
                {"code": "B", "label": "Two", "display_order": 1},
            ]
        },
    )

    assert response.status_code == 422
    assert "appears twice" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Who writes which section — B1 / D15
# ---------------------------------------------------------------------------


async def test_assigning_a_section_to_a_specialist(
    client: AsyncClient, admin_headers, world
) -> None:
    response = await client.put(
        f"/api/v1/classes/{world.class_5b.id}/narrative-assignments",
        headers=admin_headers,
        json={
            "assignments": [
                {
                    "section_id": str(world.computer_skills.id),
                    "teacher_user_id": str(world.specialist.id),
                }
            ]
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()[0]["teacher_user_id"] == str(world.specialist.id)


async def test_clearing_an_assignment_hands_it_back_to_the_class_teacher(
    client: AsyncClient, admin_headers, world
) -> None:
    """D15: absence of a row means the class teacher writes it. That is the
    default, not nobody — so clearing has to be expressible."""
    url = f"/api/v1/classes/{world.class_4a.id}/narrative-assignments"
    listed = (await client.get(url, headers=admin_headers)).json()
    assert len(listed) == 1  # the specialist holds Computer Skills in 4A

    response = await client.put(
        url,
        headers=admin_headers,
        json={
            "assignments": [{"section_id": str(world.computer_skills.id), "teacher_user_id": None}]
        },
    )

    assert response.status_code == 200
    assert response.json() == []


async def test_a_parent_cannot_be_given_a_section_to_write(
    client: AsyncClient, admin_headers, world
) -> None:
    response = await client.put(
        f"/api/v1/classes/{world.class_5b.id}/narrative-assignments",
        headers=admin_headers,
        json={
            "assignments": [
                {
                    "section_id": str(world.work_habits.id),
                    "teacher_user_id": str(world.parent.id),
                }
            ]
        },
    )

    assert response.status_code == 422
    assert "not a teacher" in response.json()["detail"]


# ---------------------------------------------------------------------------
# The phrase bank
# ---------------------------------------------------------------------------


async def test_adding_a_phrase_scoped_to_a_section(client: AsyncClient, admin_headers) -> None:
    await client.put(SECTIONS, headers=admin_headers, json={"sections": all_sixteen()})

    response = await client.post(
        BANK,
        headers=admin_headers,
        json={"scope": "B", "text": "Settles quickly to independent work."},
    )

    assert response.status_code == 201, response.text
    assert response.json()["scope"] == "B"


async def test_the_footer_comment_scopes_are_accepted(client: AsyncClient, admin_headers) -> None:
    for scope in ("class_teacher", "head_teacher"):
        response = await client.post(
            BANK, headers=admin_headers, json={"scope": scope, "text": "A steady term."}
        )
        assert response.status_code == 201, response.text


async def test_an_unknown_scope_is_refused(client: AsyncClient, admin_headers) -> None:
    """§4.6: "scope its entries to each section so the suggestions are
    relevant". A bank of generic phrases is a bank nobody scrolls through."""
    response = await client.post(
        BANK, headers=admin_headers, json={"scope": "Z", "text": "Anything."}
    )

    assert response.status_code == 422
    assert "not a narrative section code" in response.json()["detail"]


async def test_phrases_can_be_filtered_by_scope(client: AsyncClient, admin_headers) -> None:
    await client.put(SECTIONS, headers=admin_headers, json={"sections": all_sixteen()})
    await client.post(BANK, headers=admin_headers, json={"scope": "B", "text": "First."})
    await client.post(BANK, headers=admin_headers, json={"scope": "C", "text": "Second."})

    listed = (await client.get(BANK, headers=admin_headers, params={"scope": "B"})).json()

    assert [item["text"] for item in listed] == ["First."]
