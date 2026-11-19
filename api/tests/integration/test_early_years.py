"""The early-years progress report, end to end (docs/DECISIONS.md D128).

Primary 5 in the shared `world` is turned into an early-years class: it keeps
its subjects, which must then stop mattering, and Chidi (the parent's child
in it) goes from an empty form to a published progress report.
"""

import io

import pytest
from httpx import AsyncClient

from app.config import settings
from app.services import early_years

API = settings.api_v1_prefix


@pytest.fixture
async def early(client: AsyncClient, world, headers_for):
    """Primary 5 set to early years by the admin."""
    admin = await headers_for(world.admin)
    response = await client.patch(
        f"{API}/classes/{world.class_5b.id}", json={"report_type": "early_years"}, headers=admin
    )
    assert response.status_code == 200, response.text
    assert response.json()["report_type"] == "early_years"
    return admin


def term(world) -> dict[str, str]:
    return {"term_id": str(world.term.id)}


async def write_everything(client, world, teacher) -> None:
    sections = (
        await client.get(
            f"{API}/classes/{world.class_5b.id}/narrative", params=term(world), headers=teacher
        )
    ).json()["sections"]
    response = await client.put(
        f"{API}/pupils/{world.pupils['chidi'].id}/narrative",
        params=term(world),
        json={
            "passages": [
                {"section_id": section["section_id"], "body": f"Answer to {section['label']}"}
                for section in sections
            ]
        },
        headers=teacher,
    )
    assert response.status_code == 200, response.text
    response = await client.put(
        f"{API}/classes/{world.class_5b.id}/early-years-details",
        params=term(world),
        json={
            "rows": [
                {
                    "pupil_id": str(world.pupils["chidi"].id),
                    "dominance": "left",
                    "years_in_school": "2",
                }
            ]
        },
        headers=teacher,
    )
    assert response.status_code == 200, response.text


async def test_setting_a_class_to_early_years_creates_the_forms_sections(
    client: AsyncClient, world, early
) -> None:
    response = await client.get(
        f"{API}/narrative-sections", params={"report_type": "early_years"}, headers=early
    )

    assert response.status_code == 200
    sections = response.json()
    assert len(sections) == len(early_years.STANDARD_SECTIONS)
    assert sections[0]["group_label"] == "I. Learning Style"
    assert sections[-1]["label"] == "Strengths"
    # The primary card's own sections are untouched and listed separately.
    primary = (await client.get(f"{API}/narrative-sections", headers=early)).json()
    assert {section["code"] for section in primary} == {"A.computer_skills", "B"}


async def test_a_second_early_years_class_does_not_duplicate_them(
    client: AsyncClient, world, early
) -> None:
    await client.patch(
        f"{API}/classes/{world.class_4a.id}", json={"report_type": "early_years"}, headers=early
    )

    sections = (
        await client.get(
            f"{API}/narrative-sections", params={"report_type": "early_years"}, headers=early
        )
    ).json()
    assert len(sections) == len(early_years.STANDARD_SECTIONS)


async def test_the_class_writes_only_the_early_years_form(
    client: AsyncClient, world, early, headers_for
) -> None:
    teacher = await headers_for(world.teacher_b)

    body = (
        await client.get(
            f"{API}/classes/{world.class_5b.id}/narrative", params=term(world), headers=teacher
        )
    ).json()

    assert body["report_type"] == "early_years"
    assert len(body["sections"]) == len(early_years.STANDARD_SECTIONS)
    assert all(section["code"].startswith("EY.") for section in body["sections"])


async def test_a_primary_section_is_refused_for_an_early_years_pupil(
    client: AsyncClient, world, early, headers_for
) -> None:
    teacher = await headers_for(world.teacher_b)

    response = await client.put(
        f"{API}/pupils/{world.pupils['chidi'].id}/narrative",
        params=term(world),
        json={"passages": [{"section_id": str(world.work_habits.id), "body": "Hello"}]},
        headers=teacher,
    )

    assert response.status_code == 422


async def test_progress_asks_for_the_form_not_scores_or_attendance(
    client: AsyncClient, world, early, headers_for
) -> None:
    teacher = await headers_for(world.teacher_b)

    body = (
        await client.get(
            f"{API}/classes/{world.class_5b.id}/progress", params=term(world), headers=teacher
        )
    ).json()

    assert body["report_type"] == "early_years"
    assert body["sheets"] == []
    [chidi] = body["pupils"]
    assert chidi["early_years"] is True
    [item] = body["outstanding"]
    assert "dominance and years in school" in item["what"]
    assert "attendance" not in item["what"]
    assert "comment" not in item["what"]


async def test_details_are_refused_for_a_primary_class(
    client: AsyncClient, world, early, headers_for
) -> None:
    teacher = await headers_for(world.teacher_a)

    response = await client.get(
        f"{API}/classes/{world.class_4a.id}/early-years-details",
        params=term(world),
        headers=teacher,
    )

    assert response.status_code == 422


async def test_only_the_class_teacher_records_the_details(
    client: AsyncClient, world, early, headers_for
) -> None:
    # Teacher A teaches French in Primary 5 but is not its class teacher.
    teacher = await headers_for(world.teacher_a)

    response = await client.put(
        f"{API}/classes/{world.class_5b.id}/early-years-details",
        params=term(world),
        json={"rows": [{"pupil_id": str(world.pupils["chidi"].id), "dominance": "right"}]},
        headers=teacher,
    )

    assert response.status_code == 403


async def test_the_form_goes_from_empty_to_a_parents_published_report(
    client: AsyncClient, world, early, headers_for
) -> None:
    teacher = await headers_for(world.teacher_b)
    await write_everything(client, world, teacher)

    submitted = await client.post(
        f"{API}/classes/{world.class_5b.id}/submit", params=term(world), headers=teacher
    )
    assert submitted.status_code == 200, submitted.text

    head = await headers_for(world.head)
    review = (
        await client.get(
            f"{API}/classes/{world.class_5b.id}/review", params=term(world), headers=head
        )
    ).json()
    assert review["report_type"] == "early_years"
    [card] = review["cards"]
    assert card["dominance"] == "left"
    assert card["years_in_school"] == "2"
    assert len(card["narrative"]) == len(early_years.STANDARD_SECTIONS)

    approved = await client.post(
        f"{API}/classes/{world.class_5b.id}/approve", params=term(world), headers=head
    )
    assert approved.status_code == 200, approved.text

    published = await client.post(
        f"{API}/classes/{world.class_5b.id}/publish",
        params=term(world),
        json={"withhold_pupil_ids": [], "reason": None},
        headers=early,
    )
    assert published.status_code == 200, published.text

    parent = await headers_for(world.parent)
    body = (
        await client.get(
            f"{API}/my/children/{world.pupils['chidi'].id}/reports/{world.term.id}",
            headers=parent,
        )
    ).json()
    assert body["available"] is True
    assert body["card"] is None
    report = body["progress_report"]
    assert report["dominance"] == "Left"
    assert report["years_in_school"] == "2"
    assert report["teachers"] == "Teacher B"
    assert [section["heading"] for section in report["sections"]] == [
        "I. Learning Style",
        "II. Social Behaviour",
        "III. Curriculum Areas",
        "IV. What Are Key Issues in This Child's Development",
        "V. What Are His/Her Strengths",
    ]
    learning = report["sections"][0]["blocks"][0]["items"]
    assert learning[0]["marker"] == "1."
    sensorial = report["sections"][2]["blocks"][2]
    assert sensorial["heading"] == "3. Sensorial"
    assert [item["marker"] for item in sensorial["items"]] == ["a.", "b.", "c."]

    redirect = await client.get(
        f"{API}/my/children/{world.pupils['chidi'].id}/reports/{world.term.id}/pdf",
        headers=parent,
    )
    pdf = await client.get(redirect.headers["location"])
    assert pdf.status_code == 200
    text = _text(pdf.content)
    assert "NURSERY PROGRESS REPORT FORM" in text
    assert "Answer to Parallel play" in text
    # Both signature lines (the extractor sometimes splits "T eacher").
    assert text.count("Signature") == 2


async def test_the_report_type_cannot_change_once_submitted(
    client: AsyncClient, world, early, headers_for
) -> None:
    teacher = await headers_for(world.teacher_b)
    await write_everything(client, world, teacher)
    await client.post(
        f"{API}/classes/{world.class_5b.id}/submit", params=term(world), headers=teacher
    )

    response = await client.patch(
        f"{API}/classes/{world.class_5b.id}", json={"report_type": "primary"}, headers=early
    )

    assert response.status_code == 409


async def test_an_admin_adds_a_question_under_an_existing_heading(
    client: AsyncClient, world, early
) -> None:
    response = await client.post(
        f"{API}/narrative-sections",
        json={
            "label": "Musical interest",
            "group_label": "III. Curriculum Areas — 6. Art",
            "report_type": "early_years",
        },
        headers=early,
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["report_type"] == "early_years"
    assert created["code"].startswith("EY.")

    sections = (
        await client.get(
            f"{API}/narrative-sections", params={"report_type": "early_years"}, headers=early
        )
    ).json()
    art = [s["label"] for s in sections if s["group_label"] == "III. Curriculum Areas — 6. Art"]
    assert art[-1] == "Musical interest"


def _text(pdf: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)
