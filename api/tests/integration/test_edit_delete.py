"""Editing and deleting what setup created (docs/DECISIONS.md D121).

One rule, tested for each kind of record: **a delete goes through only while
nothing depends on the record**, and is otherwise refused with a 409 that says
what is in the way. Each test that deletes has a twin that is refused, using
the `world` fixture, where every class, pupil, term and teacher has history.
"""

import datetime as dt
import uuid

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditAction, AuditLog, CommentBank, RefreshToken, UserRole
from tests.integration.test_admin_academic import make_session
from tests.integration.test_admin_structure import a_class, a_subject

API = "/api/v1"


async def created(client: AsyncClient, headers, path: str, body: dict) -> dict:
    response = await client.post(f"{API}{path}", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def audited(session: AsyncSession, action: str) -> int:
    return (
        await session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == action)
        )
        or 0
    )


def refused(response, *words: str) -> None:
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    for word in words:
        assert word in detail, detail


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


async def test_an_account_can_be_corrected(client: AsyncClient, admin_headers, make_user) -> None:
    teacher = await make_user(UserRole.TEACHER)

    response = await client.patch(
        f"{API}/users/{teacher.id}",
        headers=admin_headers,
        json={"full_name": "  Mrs Adaeze Okafor ", "phone": "08030000000"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["full_name"] == "Mrs Adaeze Okafor"
    assert response.json()["phone"] == "08030000000"
    assert response.json()["role"] == "teacher"


async def test_an_account_cannot_lose_both_ways_to_sign_in(
    client: AsyncClient, admin_headers, make_user
) -> None:
    teacher = await make_user(UserRole.TEACHER)

    response = await client.patch(
        f"{API}/users/{teacher.id}", headers=admin_headers, json={"email": " "}
    )

    assert response.status_code == 422
    assert "email address or a phone number" in response.json()["detail"]


async def test_the_role_is_not_editable(client: AsyncClient, admin_headers, make_user) -> None:
    """Changing it would leave a parent holding a teacher's assignments."""
    teacher = await make_user(UserRole.TEACHER)

    response = await client.patch(
        f"{API}/users/{teacher.id}", headers=admin_headers, json={"role": "parent"}
    )

    assert response.status_code == 200
    assert response.json()["role"] == "teacher"


async def test_deactivating_signs_the_person_out_everywhere(
    client: AsyncClient, admin_headers, make_user, login, session: AsyncSession
) -> None:
    teacher = await make_user(UserRole.TEACHER)
    await login(teacher.email)

    response = await client.patch(
        f"{API}/users/{teacher.id}", headers=admin_headers, json={"is_active": False}
    )

    assert response.status_code == 200
    live = await session.scalar(
        select(func.count())
        .select_from(RefreshToken)
        .where(RefreshToken.user_id == teacher.id, RefreshToken.revoked_at.is_(None))
    )
    assert live == 0


async def test_an_admin_cannot_deactivate_or_delete_themselves(
    client: AsyncClient, make_user, headers_for
) -> None:
    admin = await make_user(UserRole.ADMIN)
    await make_user(UserRole.ADMIN)  # not the last one: the self rule alone applies
    headers = await headers_for(admin)

    deactivate = await client.patch(
        f"{API}/users/{admin.id}", headers=headers, json={"is_active": False}
    )
    remove = await client.delete(f"{API}/users/{admin.id}", headers=headers)

    assert deactivate.status_code == 422
    assert remove.status_code == 422


async def test_an_unused_account_is_deleted(
    client: AsyncClient, admin_headers, make_user, session: AsyncSession
) -> None:
    """A typo'd account that was never signed in to."""
    mistake = await make_user(UserRole.PARENT)

    response = await client.delete(f"{API}/users/{mistake.id}", headers=admin_headers)

    assert response.status_code == 204
    listed = (await client.get(f"{API}/users", headers=admin_headers)).json()
    assert str(mistake.id) not in {account["id"] for account in listed}
    assert await audited(session, AuditAction.USER_DELETED) == 1


async def test_an_account_that_has_signed_in_is_kept(
    client: AsyncClient, admin_headers, make_user, login
) -> None:
    """Every sign-in is an audit row in that person's name."""
    teacher = await make_user(UserRole.TEACHER)
    await login(teacher.email)

    response = await client.delete(f"{API}/users/{teacher.id}", headers=admin_headers)

    refused(response, "recorded action", "Deactivate the account instead.")


async def test_a_teacher_with_classes_is_kept(client: AsyncClient, world, headers_for) -> None:
    headers = await headers_for(world.admin)

    response = await client.delete(f"{API}/users/{world.teacher_a.id}", headers=headers)

    refused(response, "1 class they lead", "they teach")


# ---------------------------------------------------------------------------
# Pupils
# ---------------------------------------------------------------------------


async def a_pupil(client: AsyncClient, headers, **payload) -> dict:
    body = {"admission_number": "SSHMS/26/001", "first_name": "Ada", "last_name": "Obi"}
    return await created(client, headers, "/pupils", body | payload)


async def test_a_pupil_can_be_corrected(client: AsyncClient, admin_headers) -> None:
    pupil = await a_pupil(client, admin_headers)
    house = await created(client, admin_headers, "/houses", {"name": "Blue"})

    response = await client.patch(
        f"{API}/pupils/{pupil['id']}",
        headers=admin_headers,
        json={"first_name": "Adaora", "house_id": house["id"], "sex": "F"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["first_name"], body["house_id"], body["sex"]) == ("Adaora", house["id"], "F")

    cleared = await client.patch(
        f"{API}/pupils/{pupil['id']}", headers=admin_headers, json={"house_id": None}
    )
    assert cleared.json()["house_id"] is None


async def test_a_pupils_audit_row_names_fields_not_values(
    client: AsyncClient, admin_headers, session: AsyncSession
) -> None:
    """CLAUDE.md: no pupil's identity in the log."""
    pupil = await a_pupil(client, admin_headers)
    await client.patch(
        f"{API}/pupils/{pupil['id']}", headers=admin_headers, json={"first_name": "Adaora"}
    )

    row = await session.scalar(select(AuditLog).where(AuditLog.action == AuditAction.PUPIL_UPDATED))
    assert row.after["changed"] == ["first_name"]
    assert "Adaora" not in str(row.after) and "Adaora" not in str(row.before)


async def test_a_duplicate_admission_number_is_refused_on_edit(
    client: AsyncClient, admin_headers
) -> None:
    await a_pupil(client, admin_headers)
    other = await a_pupil(client, admin_headers, admission_number="SSHMS/26/002")

    response = await client.patch(
        f"{API}/pupils/{other['id']}",
        headers=admin_headers,
        json={"admission_number": "SSHMS/26/001"},
    )

    assert response.status_code == 409


async def test_a_pupil_with_no_records_is_deleted_with_their_enrolment(
    client: AsyncClient, admin_headers
) -> None:
    await make_session(client, admin_headers)
    klass = await a_class(client, admin_headers)
    pupil = await a_pupil(client, admin_headers, class_id=klass["id"])

    response = await client.delete(f"{API}/pupils/{pupil['id']}", headers=admin_headers)

    assert response.status_code == 204
    # The class is now empty, so it can go too.
    assert (
        await client.delete(f"{API}/classes/{klass['id']}", headers=admin_headers)
    ).status_code == 204


async def test_a_pupil_with_a_report_card_is_kept(client: AsyncClient, world, headers_for) -> None:
    headers = await headers_for(world.admin)

    response = await client.delete(
        f"{API}/pupils/{next(iter(world.pupils.values())).id}", headers=headers
    )

    refused(response, "report card", "Deactivate the pupil instead.")


# ---------------------------------------------------------------------------
# Classes and houses
# ---------------------------------------------------------------------------


async def test_a_class_can_be_renamed_and_deactivated(client: AsyncClient, admin_headers) -> None:
    klass = await a_class(client, admin_headers)

    response = await client.patch(
        f"{API}/classes/{klass['id']}",
        headers=admin_headers,
        json={"name": "Primary 4 Gold", "is_active": False},
    )

    assert response.status_code == 200
    assert (response.json()["name"], response.json()["is_active"]) == ("Primary 4 Gold", False)


async def test_an_unused_class_is_deleted_with_its_setup(
    client: AsyncClient, admin_headers, make_user
) -> None:
    """Its subject list and teachers are its own setup and go with it."""
    await make_session(client, admin_headers)
    klass = await a_class(client, admin_headers)
    maths = await a_subject(client, admin_headers, name="Mathematics")
    offerings = (
        await client.put(
            f"{API}/classes/{klass['id']}/subjects",
            headers=admin_headers,
            json={"subject_ids": [maths["id"]]},
        )
    ).json()
    teacher = await make_user(UserRole.TEACHER)
    await client.put(
        f"{API}/class-subjects/{offerings[0]['id']}/teacher",
        headers=admin_headers,
        json={"teacher_user_id": str(teacher.id)},
    )
    await client.put(
        f"{API}/classes/{klass['id']}/class-teacher",
        headers=admin_headers,
        json={"teacher_user_id": str(teacher.id)},
    )

    response = await client.delete(f"{API}/classes/{klass['id']}", headers=admin_headers)

    assert response.status_code == 204, response.text
    # And the subject is no longer taught anywhere, so it can go as well.
    assert (
        await client.delete(f"{API}/subjects/{maths['id']}", headers=admin_headers)
    ).status_code == 204


async def test_a_class_with_pupils_is_kept(client: AsyncClient, world, headers_for) -> None:
    headers = await headers_for(world.admin)

    response = await client.delete(f"{API}/classes/{world.class_4a.id}", headers=headers)

    refused(response, "enrolled pupil", "Deactivate it instead.")


async def test_a_house_is_renamed_and_an_empty_one_deleted(
    client: AsyncClient, admin_headers
) -> None:
    house = await created(client, admin_headers, "/houses", {"name": "Blu"})

    renamed = await client.patch(
        f"{API}/houses/{house['id']}", headers=admin_headers, json={"name": "Blue"}
    )
    removed = await client.delete(f"{API}/houses/{house['id']}", headers=admin_headers)

    assert renamed.json()["name"] == "Blue"
    assert removed.status_code == 204


async def test_a_house_with_pupils_is_kept(client: AsyncClient, admin_headers) -> None:
    house = await created(client, admin_headers, "/houses", {"name": "Blue"})
    await a_pupil(client, admin_headers, house_id=house["id"])

    response = await client.delete(f"{API}/houses/{house['id']}", headers=admin_headers)

    refused(response, "1 pupil", "Move its pupils")


# ---------------------------------------------------------------------------
# Sessions and terms
# ---------------------------------------------------------------------------


async def test_a_session_can_be_renamed(client: AsyncClient, admin_headers) -> None:
    academic = await make_session(client, admin_headers, name="2026-2027")

    response = await client.patch(
        f"{API}/sessions/{academic['id']}", headers=admin_headers, json={"name": "2026/2027"}
    )

    assert response.json()["name"] == "2026/2027"


async def test_a_sessions_dates_cannot_shut_out_its_terms(
    client: AsyncClient, world, headers_for
) -> None:
    headers = await headers_for(world.admin)

    response = await client.patch(
        f"{API}/sessions/{world.academic_session.id}",
        headers=headers,
        json={"starts_on": world.term.ends_on.isoformat(), "ends_on": "2099-01-01"},
    )

    assert response.status_code == 422
    assert "term outside the session" in response.json()["detail"]


async def test_an_unused_session_and_term_are_deleted(client: AsyncClient, admin_headers) -> None:
    await make_session(client, admin_headers)  # the current one
    spare = await make_session(
        client,
        admin_headers,
        name="2027/2028",
        is_current=False,
        starts_on=dt.date(2027, 9, 13),
        ends_on=dt.date(2028, 7, 21),
    )
    term = await created(
        client,
        admin_headers,
        "/terms",
        {
            "academic_session_id": spare["id"],
            "number": "first",
            "starts_on": "2027-09-13",
            "ends_on": "2027-12-10",
        },
    )

    blocked = await client.delete(f"{API}/sessions/{spare['id']}", headers=admin_headers)
    term_gone = await client.delete(f"{API}/terms/{term['id']}", headers=admin_headers)
    session_gone = await client.delete(f"{API}/sessions/{spare['id']}", headers=admin_headers)

    refused(blocked, "1 term")
    assert term_gone.status_code == 204, term_gone.text
    assert session_gone.status_code == 204


async def test_the_current_session_and_term_are_kept(
    client: AsyncClient, world, headers_for
) -> None:
    headers = await headers_for(world.admin)

    session_response = await client.delete(
        f"{API}/sessions/{world.academic_session.id}", headers=headers
    )
    term_response = await client.delete(f"{API}/terms/{world.term.id}", headers=headers)

    refused(session_response, "current session")
    refused(term_response, "current term")


async def test_a_term_with_report_cards_is_kept(
    client: AsyncClient, world, headers_for, session: AsyncSession
) -> None:
    world.term.is_current = False
    await session.commit()
    headers = await headers_for(world.admin)

    response = await client.delete(f"{API}/terms/{world.term.id}", headers=headers)

    refused(response, "report card", "cards must stay as they were")


# ---------------------------------------------------------------------------
# Subjects, scales, sections, phrases
# ---------------------------------------------------------------------------


async def test_a_subject_taught_to_a_class_is_kept(client: AsyncClient, world, headers_for) -> None:
    headers = await headers_for(world.admin)
    subject_id = world.maths_4a.subject_id

    response = await client.delete(f"{API}/subjects/{subject_id}", headers=headers)

    refused(response, "classes taught it", "Retire it instead")


async def test_a_group_heading_with_subjects_under_it_is_kept(
    client: AsyncClient, admin_headers
) -> None:
    english = await a_subject(client, admin_headers, name="English", is_group=True)
    await a_subject(client, admin_headers, name="Spelling", parent_subject_id=english["id"])

    response = await client.delete(f"{API}/subjects/{english['id']}", headers=admin_headers)

    refused(response, "subject under it")


async def scale(client: AsyncClient, headers, *, activate: bool) -> dict:
    return await created(
        client,
        headers,
        "/grading-scales",
        {
            "name": f"Scale {uuid.uuid4().hex[:6]}",
            "effective_from": "2026-09-14",
            "bands": [{"letter": "A", "remark": "Good", "min_score": "0", "max_score": "100"}],
            "activate": activate,
        },
    )


async def test_an_unused_scale_version_is_deleted_but_the_active_one_kept(
    client: AsyncClient, admin_headers
) -> None:
    active = await scale(client, admin_headers, activate=True)
    mistake = await scale(client, admin_headers, activate=False)

    kept = await client.delete(f"{API}/grading-scales/{active['id']}", headers=admin_headers)
    gone = await client.delete(f"{API}/grading-scales/{mistake['id']}", headers=admin_headers)

    refused(kept, "active scale")
    assert gone.status_code == 204


async def test_an_unwritten_section_is_deleted_with_its_phrases(
    client: AsyncClient, admin_headers, session: AsyncSession
) -> None:
    section = await created(client, admin_headers, "/narrative-sections", {"label": "Music"})
    await created(
        client, admin_headers, "/comment-bank", {"scope": section["code"], "text": "Sings well."}
    )

    response = await client.delete(
        f"{API}/narrative-sections/{section['id']}", headers=admin_headers
    )

    assert response.status_code == 204, response.text
    assert await session.scalar(select(func.count()).select_from(CommentBank)) == 0


async def test_a_section_with_written_passages_is_kept(
    client: AsyncClient, world, headers_for, session: AsyncSession
) -> None:
    from app.models import NarrativeEntry

    session.add(
        NarrativeEntry(
            school_id=world.school.id,
            term_id=world.term.id,
            pupil_id=next(iter(world.pupils.values())).id,
            section_id=world.work_habits.id,
            body="Works steadily.",
        )
    )
    await session.commit()
    headers = await headers_for(world.admin)

    response = await client.delete(
        f"{API}/narrative-sections/{world.work_habits.id}", headers=headers
    )

    refused(response, "1 written passage", "Retire it instead")


async def test_a_phrase_is_reworded_and_deleted(client: AsyncClient, admin_headers) -> None:
    phrase = await created(
        client, admin_headers, "/comment-bank", {"scope": "class_teacher", "text": "Steady"}
    )

    reworded = await client.patch(
        f"{API}/comment-bank/{phrase['id']}",
        headers=admin_headers,
        json={"text": "A steady, careful worker."},
    )
    removed = await client.delete(f"{API}/comment-bank/{phrase['id']}", headers=admin_headers)

    assert reworded.json()["text"] == "A steady, careful worker."
    assert removed.status_code == 204


async def test_deleting_what_is_not_there_is_a_404(client: AsyncClient, admin_headers) -> None:
    missing = uuid.uuid4()
    for path in (
        "users",
        "pupils",
        "classes",
        "houses",
        "sessions",
        "terms",
        "subjects",
        "grading-scales",
        "narrative-sections",
        "comment-bank",
    ):
        response = await client.delete(f"{API}/{path}/{missing}", headers=admin_headers)
        assert response.status_code == 404, path


# ---------------------------------------------------------------------------
# Admission numbers are optional (D124)
# ---------------------------------------------------------------------------


async def test_pupils_need_no_admission_number(client: AsyncClient, admin_headers) -> None:
    """Two pupils without one never collide; a blank is the same as none."""
    first = await created(
        client, admin_headers, "/pupils", {"first_name": "Ada", "last_name": "Obi"}
    )
    second = await created(
        client,
        admin_headers,
        "/pupils",
        {"admission_number": "  ", "first_name": "Ada", "last_name": "Eze"},
    )

    assert first["admission_number"] is None
    assert second["admission_number"] is None


async def test_a_given_admission_number_is_still_unique(client: AsyncClient, admin_headers) -> None:
    await a_pupil(client, admin_headers, admission_number="SSHMS/26/009")

    response = await client.post(
        f"{API}/pupils",
        headers=admin_headers,
        json={"admission_number": "SSHMS/26/009", "first_name": "B", "last_name": "C"},
    )

    assert response.status_code == 409


async def test_an_admission_number_can_be_cleared(client: AsyncClient, admin_headers) -> None:
    pupil = await a_pupil(client, admin_headers)

    response = await client.patch(
        f"{API}/pupils/{pupil['id']}", headers=admin_headers, json={"admission_number": None}
    )

    assert response.status_code == 200, response.text
    assert response.json()["admission_number"] is None
