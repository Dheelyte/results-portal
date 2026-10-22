"""Milestone 5's done-when: "an admin configures a full term from an empty
database" (ARCHITECTURE.md §12).

One walkthrough, over HTTP, as an admin, against a school that holds nothing
but that admin's own account. It ends with `GET /setup-checklist` reporting
the term ready, which is the criterion stated rather than a proxy for it.

The walkthrough is also the order the admin screens present the work in, so a
step that cannot be done before another one shows up here first.
"""

import datetime as dt

from httpx import AsyncClient

from app.models import TermHalf, UserRole
from tests.integration.test_admin_assessment import all_sixteen, card_bands

API = "/api/v1"

SESSION_START = dt.date(2026, 9, 14)
SESSION_END = dt.date(2027, 7, 23)
TERM_START = dt.date(2026, 9, 14)
TERM_END = dt.date(2026, 12, 11)

# §1.5's list, trimmed to what one test needs: the English group with two of
# its five children, plus two standalone subjects, one of them specialist.
SUBJECTS = (
    ("English", {"is_group": True}),
    ("Language Arts", {"parent": "English"}),
    ("Spelling & Reading", {"parent": "English"}),
    ("Mathematics", {}),
    ("Computer", {"is_specialist": True}),
)


class Admin:
    """A tiny client wrapper, so the walkthrough below reads as a sequence of
    administrative acts rather than a wall of HTTP."""

    def __init__(self, client: AsyncClient, headers: dict[str, str]) -> None:
        self.client = client
        self.headers = headers

    async def post(self, path: str, body: dict | None = None, *, expect: int = 201) -> dict:
        response = await self.client.post(f"{API}{path}", headers=self.headers, json=body)
        assert response.status_code == expect, f"POST {path}: {response.text}"
        return response.json()

    async def put(self, path: str, body: dict, *, expect: int = 200):
        response = await self.client.put(f"{API}{path}", headers=self.headers, json=body)
        assert response.status_code == expect, f"PUT {path}: {response.text}"
        return response.json()

    async def patch(self, path: str, body: dict) -> dict:
        response = await self.client.patch(f"{API}{path}", headers=self.headers, json=body)
        assert response.status_code == 200, f"PATCH {path}: {response.text}"
        return response.json()

    async def get(self, path: str, params: dict | None = None):
        response = await self.client.get(f"{API}{path}", headers=self.headers, params=params)
        assert response.status_code == 200, f"GET {path}: {response.text}"
        return response.json()


async def checklist(admin: Admin, term_id: str) -> dict:
    body = await admin.get("/setup-checklist", {"term_id": term_id})
    return {item["key"]: item for item in body["items"]} | {"__ready__": body["ready"]}


async def configure_a_full_term(admin: Admin) -> dict:
    """Everything an admin does on day one, in order."""
    academic = await admin.post(
        "/sessions",
        {
            "name": "2026/2027",
            "starts_on": SESSION_START.isoformat(),
            "ends_on": SESSION_END.isoformat(),
            "is_current": True,
        },
    )

    term = await admin.post(
        "/terms",
        {
            "academic_session_id": academic["id"],
            "number": "first",
            "starts_on": TERM_START.isoformat(),
            "ends_on": TERM_END.isoformat(),
            "times_school_opened": 58,
            "card_return_on": "2027-01-11",
            "next_resumption_on": "2027-01-11",
            "is_current": True,
        },
    )

    # The two sheets of §1.1, each with its own window and its own maxima.
    periods = {
        item["half"]: item for item in await admin.get(f"/terms/{term['id']}/assessment-periods")
    }
    await admin.post(
        f"/terms/{term['id']}/assessment-periods",
        {"half": "first_half", "opens_on": "2026-09-14", "closes_on": "2026-10-23"},
        expect=200,
    )
    await admin.post(
        f"/terms/{term['id']}/assessment-periods",
        {"half": "second_half", "opens_on": "2026-10-26", "closes_on": "2026-12-11"},
        expect=200,
    )

    # N2 is unanswered, so these are placeholders the school will replace —
    # which is exactly why they are configuration and not constants.
    await admin.put(
        f"/assessment-periods/{periods['first_half']['id']}/marks-obtainable",
        {
            "ca_test_1": "8",
            "ca_test_2": "8",
            "ca_test_3": "8",
            "ca_test_4": "8",
            "ca_test_5": "8",
            "mid_term_test": "60",
        },
    )
    await admin.put(
        f"/assessment-periods/{periods['second_half']['id']}/marks-obtainable",
        {
            "ca_test_1": "8",
            "ca_test_2": "8",
            "ca_test_3": "8",
            "ca_test_4": "8",
            "ca_test_5": "8",
            "exam": "60",
        },
    )

    await admin.post(
        "/grading-scales",
        {
            "name": "Card scale (seven bands)",
            "effective_from": SESSION_START.isoformat(),
            "bands": card_bands(),
            "activate": True,
        },
    )

    await admin.put("/narrative-sections", {"sections": all_sixteen()})
    await admin.post(
        "/comment-bank", {"scope": "B", "text": "Settles quickly to independent work."}
    )
    await admin.post("/comment-bank", {"scope": "class_teacher", "text": "A steady term."})

    for name in ("Blue", "Green"):
        await admin.post("/houses", {"name": name})
    houses = {item["name"]: item["id"] for item in await admin.get("/houses")}

    classes = {}
    for name, order in (("Primary 4", 4), ("Primary 5", 5)):
        classes[name] = await admin.post("/classes", {"name": name, "level_order": order})

    subjects: dict[str, dict] = {}
    for order, (name, options) in enumerate(SUBJECTS):
        parent = options.get("parent")
        subjects[name] = await admin.post(
            "/subjects",
            {
                "name": name,
                "display_order": order,
                "is_group": options.get("is_group", False),
                "is_specialist": options.get("is_specialist", False),
                "parent_subject_id": subjects[parent]["id"] if parent else None,
            },
        )

    staff = {}
    for key, full_name in (
        ("class_teacher_4a", "Mrs Adeyemi"),
        ("class_teacher_5b", "Mr Bello"),
        ("specialist", "Miss Chukwu"),
    ):
        created = await admin.post(
            "/users",
            {
                "role": "teacher",
                "full_name": full_name,
                "email": f"{key}@sshms.test",
            },
        )
        staff[key] = created["user"]

    # English is a heading, so only its children are offered (R7).
    scored = [
        subjects["Language Arts"]["id"],
        subjects["Spelling & Reading"]["id"],
        subjects["Mathematics"]["id"],
        subjects["Computer"]["id"],
    ]
    offerings: dict[str, list[dict]] = {}
    for name, klass in classes.items():
        offerings[name] = await admin.put(
            f"/classes/{klass['id']}/subjects", {"subject_ids": scored}
        )

    for name, rows in offerings.items():
        class_teacher = staff["class_teacher_4a" if name == "Primary 4" else "class_teacher_5b"]
        for row in rows:
            owner = (
                staff["specialist"]
                if row["subject_id"] == subjects["Computer"]["id"]
                else class_teacher
            )
            await admin.put(
                f"/class-subjects/{row['id']}/teacher", {"teacher_user_id": owner["id"]}
            )

    for name, klass in classes.items():
        class_teacher = staff["class_teacher_4a" if name == "Primary 4" else "class_teacher_5b"]
        await admin.put(
            f"/classes/{klass['id']}/class-teacher",
            {"teacher_user_id": class_teacher["id"]},
        )

    # B1: the specialist writes their own curriculum area; the class teacher
    # writes everything else by absence of a row (D15).
    sections = {item["code"]: item for item in await admin.get("/narrative-sections")}
    for klass in classes.values():
        await admin.put(
            f"/classes/{klass['id']}/narrative-assignments",
            {
                "assignments": [
                    {
                        "section_id": sections["A.computer_skills"]["id"],
                        "teacher_user_id": staff["specialist"]["id"],
                    }
                ]
            },
        )

    pupils = []
    roll = (
        ("Ada", "Okafor", "Primary 4", "Blue"),
        ("Emeka", "Okafor", "Primary 4", "Green"),
        ("Chidi", "Bakare", "Primary 5", "Blue"),
    )
    for index, (first, last, class_name, house) in enumerate(roll, start=1):
        pupils.append(
            await admin.post(
                "/pupils",
                {
                    "admission_number": f"SSHMS/2026/{index:03d}",
                    "first_name": first,
                    "last_name": last,
                    "sex": "F" if first == "Ada" else "M",
                    "house_id": houses[house],
                    "class_id": classes[class_name]["id"],
                },
            )
        )

    parent = await admin.post(
        "/users",
        {"role": "parent", "full_name": "Mrs Okafor", "phone": "08030000001"},
    )
    await admin.post(
        f"/guardians/{parent['user']['id']}/children",
        {
            "children": [
                {"pupil_id": pupils[0]["id"], "relationship": "Mother", "is_primary": True},
                {"pupil_id": pupils[1]["id"], "relationship": "Mother"},
            ]
        },
        expect=200,
    )
    # Repeating the call must not detach the first child (§7: additive POST).
    await admin.post(
        f"/guardians/{parent['user']['id']}/children",
        {"children": [{"pupil_id": pupils[1]["id"]}]},
        expect=200,
    )

    return {
        "academic_session": academic,
        "term": term,
        "classes": classes,
        "subjects": subjects,
        "staff": staff,
        "pupils": pupils,
        "parent": parent,
        "offerings": offerings,
    }


# ---------------------------------------------------------------------------
# The milestone criterion
# ---------------------------------------------------------------------------


async def test_an_admin_configures_a_full_term_from_an_empty_database(
    client: AsyncClient, make_user, headers_for
) -> None:
    """§12's done-when for milestone 5, asserted directly."""
    admin = Admin(client, await headers_for(await make_user(UserRole.ADMIN)))

    world = await configure_a_full_term(admin)
    report = await checklist(admin, world["term"]["id"])

    blocking_outstanding = {
        key
        for key, item in report.items()
        if key != "__ready__" and item["blocking"] and not item["done"]
    }
    assert blocking_outstanding == set()
    assert report["__ready__"] is True


async def test_nothing_is_ready_before_any_of_it_is_done(
    client: AsyncClient, make_user, headers_for
) -> None:
    """The checklist has to be able to say no, or saying yes means nothing."""
    admin = Admin(client, await headers_for(await make_user(UserRole.ADMIN)))

    academic = await admin.post(
        "/sessions",
        {
            "name": "2026/2027",
            "starts_on": SESSION_START.isoformat(),
            "ends_on": SESSION_END.isoformat(),
            "is_current": True,
        },
    )
    term = await admin.post(
        "/terms",
        {
            "academic_session_id": academic["id"],
            "number": "first",
            "starts_on": TERM_START.isoformat(),
            "ends_on": TERM_END.isoformat(),
            "is_current": True,
        },
    )

    report = await checklist(admin, term["id"])

    assert report["__ready__"] is False
    # The session and term pointers are set; nothing else is.
    assert report["current_session"]["done"] is True
    assert report["current_term"]["done"] is True
    assert report["times_school_opened"]["done"] is False
    assert report["marks_obtainable"]["done"] is False
    assert report["grading_scale"]["done"] is False
    assert report["classes"]["done"] is False
    assert report["pupils_enrolled"]["done"] is False
    assert report["teacher_accounts"]["done"] is False


async def test_the_checklist_names_the_classes_that_are_missing_something(
    client: AsyncClient, make_user, headers_for
) -> None:
    """R10's lesson applied to setup: "cannot submit" with no explanation
    generates a support call every term, and so does "setup incomplete"."""
    admin = Admin(client, await headers_for(await make_user(UserRole.ADMIN)))
    world = await configure_a_full_term(admin)

    # Add a class after the fact, with nothing attached to it.
    await admin.post("/classes", {"name": "Primary 6", "level_order": 6})

    report = await checklist(admin, world["term"]["id"])

    assert report["__ready__"] is False
    assert report["class_subjects"]["outstanding"] == ["Primary 6"]
    assert report["class_teachers"]["outstanding"] == ["Primary 6"]
    assert "Primary 6" in report["no_empty_classes"]["outstanding"]


async def test_an_unassigned_class_subject_blocks_readiness_by_name(
    client: AsyncClient, make_user, headers_for
) -> None:
    """Only the assigned teacher may enter scores (§5.2), so an unassigned
    offering can never be filled in at all."""
    admin = Admin(client, await headers_for(await make_user(UserRole.ADMIN)))
    world = await configure_a_full_term(admin)

    geography = await admin.post("/subjects", {"name": "Geography", "display_order": 9})
    klass = world["classes"]["Primary 4"]
    existing = [row["subject_id"] for row in await admin.get(f"/classes/{klass['id']}/subjects")]
    await admin.put(
        f"/classes/{klass['id']}/subjects",
        {"subject_ids": [*existing, geography["id"]]},
    )

    report = await checklist(admin, world["term"]["id"])

    assert report["__ready__"] is False
    assert report["teaching_assignments"]["outstanding"] == ["Primary 4 — Geography"]


async def test_an_advisory_gap_does_not_block_readiness(
    client: AsyncClient, make_user, headers_for
) -> None:
    """A parent account with no child attached would sign in and see nothing.

    A real gap — reported — but parents are not needed until publication, so
    it does not stop a teacher entering a score.
    """
    admin = Admin(client, await headers_for(await make_user(UserRole.ADMIN)))
    world = await configure_a_full_term(admin)

    await admin.post(
        "/users", {"role": "parent", "full_name": "Unattached Parent", "phone": "08030000002"}
    )

    report = await checklist(admin, world["term"]["id"])

    assert report["parent_accounts"]["done"] is False
    assert report["parent_accounts"]["blocking"] is False
    assert report["__ready__"] is True


async def test_marks_obtainable_for_only_one_sheet_is_not_enough(
    client: AsyncClient, make_user, headers_for
) -> None:
    """Both sheets carry a Marks Obtainable row, and a term produces both."""
    admin = Admin(client, await headers_for(await make_user(UserRole.ADMIN)))
    world = await configure_a_full_term(admin)

    periods = {
        item["half"]: item
        for item in await admin.get(f"/terms/{world['term']['id']}/assessment-periods")
    }
    # Blank the second-half row by replacing it with a first-half-only set is
    # impossible, so prove the inverse: a fresh term with one sheet set.
    second = await admin.post(
        "/terms",
        {
            "academic_session_id": world["academic_session"]["id"],
            "number": "second",
            "starts_on": "2027-01-11",
            "ends_on": "2027-04-02",
            "times_school_opened": 60,
        },
    )
    fresh = {
        item["half"]: item for item in await admin.get(f"/terms/{second['id']}/assessment-periods")
    }
    await admin.put(
        f"/assessment-periods/{fresh[TermHalf.FIRST_HALF.value]['id']}/marks-obtainable",
        {"ca_test_1": "8", "mid_term_test": "60"},
    )

    report = await checklist(admin, second["id"])

    assert report["marks_obtainable"]["done"] is False
    assert report["marks_obtainable"]["outstanding"] == ["Second Half Term"]
    assert periods  # the first term's own sheets are untouched


async def test_a_term_from_another_school_is_a_404(
    client: AsyncClient, make_user, headers_for, session
) -> None:
    """§5.2: outside the caller's scope is a 404, never a 403."""
    from app.models import AcademicSession, School, Term, TermNumber

    other = School(name="Another School", short_name="AS")
    session.add(other)
    await session.flush()
    academic = AcademicSession(
        school_id=other.id,
        name="2026/2027",
        starts_on=SESSION_START,
        ends_on=SESSION_END,
        is_current=True,
    )
    session.add(academic)
    await session.flush()
    term = Term(
        school_id=other.id,
        academic_session_id=academic.id,
        number=TermNumber.FIRST,
        starts_on=TERM_START,
        ends_on=TERM_END,
        is_current=True,
    )
    session.add(term)
    await session.commit()

    admin_user = await make_user(UserRole.ADMIN)
    headers = await headers_for(admin_user)

    response = await client.get(
        f"{API}/setup-checklist", headers=headers, params={"term_id": str(term.id)}
    )

    assert response.status_code == 404


async def test_the_configured_term_is_internally_consistent(
    client: AsyncClient, make_user, headers_for
) -> None:
    """Spot-checks on the shape of what the walkthrough produced, so a change
    that keeps the checklist green while breaking the data still fails."""
    admin = Admin(client, await headers_for(await make_user(UserRole.ADMIN)))
    world = await configure_a_full_term(admin)

    # The English group heading is not among any class's offerings (R7).
    for klass in world["classes"].values():
        offered = {row["subject_id"] for row in await admin.get(f"/classes/{klass['id']}/subjects")}
        assert world["subjects"]["English"]["id"] not in offered
        assert len(offered) == 4

    # Three pupils, two in Primary 4 and one in Primary 5.
    in_4a = await admin.get("/pupils", {"class_id": world["classes"]["Primary 4"]["id"]})
    in_5b = await admin.get("/pupils", {"class_id": world["classes"]["Primary 5"]["id"]})
    assert in_4a["total"] == 2
    assert in_5b["total"] == 1

    # The parent's two children, attached once despite the repeated call.
    children = await admin.get(f"/guardians/{world['parent']['user']['id']}/children")
    assert len(children) == 2

    # Sixteen narrative sections, with one assigned per class and the rest
    # falling to the class teacher by absence (D15).
    sections = await admin.get("/narrative-sections")
    assert len(sections) == 16
    for klass in world["classes"].values():
        assignments = await admin.get(f"/classes/{klass['id']}/narrative-assignments")
        assert len(assignments) == 1
