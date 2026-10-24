"""Milestone 7's criterion, asserted end to end.

§12: "A class teacher completes one pupil's sixteen sections and moves to the
next."

So this walks a real class the way a teacher does: open the first pupil, write
every section that is theirs, follow `next_pupil_id`, repeat — then the
specialist does the same for the one curriculum area that belongs to them, and
the class teacher fills in attendance, height and weight, and the comment.

The sixteen sections come from `app.seed.reference`, not from a list in this
file: the point is that the school's own card is completable, and a test
inventing four tidy sections would not show that.
"""

import datetime as dt

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    AcademicSession,
    Class,
    ClassSubject,
    ClassTeacher,
    Enrollment,
    NarrativeSection,
    NarrativeSectionAssignment,
    Pupil,
    Subject,
    TeachingAssignment,
    Term,
    TermNumber,
    User,
    UserRole,
)
from app.seed.reference import seed_narrative_sections
from tests.conftest import TEST_PASSWORD

API = settings.api_v1_prefix

ROLL = ["Adeyemi", "Bello", "Chukwu", "Danjuma", "Eze"]
OPENED = 58


class Teacher:
    """A signed-in teacher, so the walk below reads like the screen."""

    def __init__(self, client: AsyncClient, headers: dict[str, str], term_id: str) -> None:
        self.client = client
        self.headers = headers
        self.term = term_id

    async def get(self, path: str):
        response = await self.client.get(f"{API}{path}", headers=self.headers)
        assert response.status_code == 200, f"GET {path}: {response.text}"
        return response.json()

    async def put(self, path: str, body: dict):
        response = await self.client.put(f"{API}{path}", json=body, headers=self.headers)
        assert response.status_code == 200, f"PUT {path}: {response.text}"
        return response.json()

    async def pupil(self, pupil_id: str):
        return await self.get(f"/pupils/{pupil_id}/narrative?term_id={self.term}")

    async def write_my_sections(self, pupil_id: str) -> int:
        """Write every section on this pupil's page that is mine. Returns how
        many, so the caller can assert the split rather than assume it."""
        page = await self.pupil(pupil_id)
        mine = [p for p in page["passages"] if p["writable"]]
        if not mine:
            return 0
        await self.put(
            f"/pupils/{pupil_id}/narrative?term_id={self.term}",
            {
                "passages": [
                    {
                        "section_id": passage["section_id"],
                        "body": (
                            f"Has worked steadily in {passage['label'].lower()} "
                            "this term and shows growing confidence."
                        ),
                    }
                    for passage in mine
                ]
            },
        )
        return len(mine)


@pytest.fixture
async def school_year(session: AsyncSession, school, password_hash: str):
    """One class of five, the real sixteen sections, and two teachers.

    The specialist holds "Art & Music", which is the section §4.6 singles out
    as having no scored subject to hang off — so the one case the card makes
    awkward is the one this test uses.
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
    specialist = user(UserRole.TEACHER, "Mr Specialist", "spec@sshms.test")
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

    # The specialist teaches something, because §5.2's narrative row for a
    # specialist reads "own class-subjects" — the assignment below is what
    # actually grants the section, but a specialist with no teaching at all
    # would be an odd shape to test against.
    music = Subject(school_id=school.id, name="Creative Art")
    session.add(music)
    await session.flush()
    offering = ClassSubject(
        school_id=school.id,
        class_id=klass.id,
        subject_id=music.id,
        academic_session_id=academic_session.id,
    )
    session.add(offering)
    await session.flush()
    session.add(
        TeachingAssignment(
            school_id=school.id,
            class_subject_id=offering.id,
            teacher_user_id=specialist.id,
        )
    )

    # The school's real sixteen (§1.4), through the seed the deploy runs.
    await seed_narrative_sections(session, school.id)
    await session.flush()

    # §4.6 singles this one out: "Art & Music" is the curriculum area with no
    # scored counterpart, so it is the section the school is most likely to
    # hand to a specialist.
    art_and_music = await session.scalar(
        select(NarrativeSection).where(
            NarrativeSection.school_id == school.id,
            NarrativeSection.code == "A.art_and_music",
        )
    )
    assert art_and_music is not None, "the seed should create the sixteen sections"
    session.add(
        NarrativeSectionAssignment(
            school_id=school.id,
            class_id=klass.id,
            section_id=art_and_music.id,
            academic_session_id=academic_session.id,
            teacher_user_id=specialist.id,
        )
    )

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

    await session.commit()

    return SimpleNamespace(
        term=term,
        klass=klass,
        class_teacher=class_teacher,
        specialist=specialist,
        pupils=pupils,
        art_and_music=art_and_music,
    )


@pytest.fixture
async def walkers(client: AsyncClient, login, school_year):
    """Both teachers, signed in through the real login endpoint."""

    async def signed_in(user: User) -> Teacher:
        response = await login(user.email, TEST_PASSWORD)
        assert response.status_code == 200, response.text
        token = response.json()["access_token"]
        return Teacher(client, {"Authorization": f"Bearer {token}"}, str(school_year.term.id))

    return (
        await signed_in(school_year.class_teacher),
        await signed_in(school_year.specialist),
    )


async def test_a_class_teacher_completes_a_pupil_and_moves_to_the_next(
    walkers, school_year
) -> None:
    """Milestone 7's criterion, as one walk through a class of five."""
    class_teacher, specialist = walkers
    class_id = str(school_year.klass.id)
    term_id = str(school_year.term.id)

    listing = await class_teacher.get(f"/classes/{class_id}/narrative?term_id={term_id}")
    assert len(listing["sections"]) == 16, "the school's card has sixteen sections"
    assert listing["roll_size"] == len(ROLL)
    assert listing["complete_pupils"] == 0

    # D15: fifteen are the class teacher's, one is the specialist's.
    assert sum(1 for s in listing["sections"] if s["writable"]) == 15

    # The walk. Start at the first pupil and follow next_pupil_id, which is
    # exactly what §8.2's "next pupil" button does.
    visited: list[str] = []
    pupil_id = listing["pupils"][0]["pupil_id"]
    while pupil_id:
        written = await class_teacher.write_my_sections(pupil_id)
        assert written == 15

        page = await class_teacher.pupil(pupil_id)
        assert page["complete_count"] == 15, "fifteen written, one still the specialist's"
        assert page["position"] == len(visited) + 1
        assert page["roll_size"] == len(ROLL)

        visited.append(pupil_id)
        pupil_id = page["next_pupil_id"]

    assert len(visited) == len(ROLL), "the walk reached every pupil exactly once"

    # Nobody is complete yet, because one section on each page is not the
    # class teacher's to write. R8 counts every active section.
    listing = await class_teacher.get(f"/classes/{class_id}/narrative?term_id={term_id}")
    assert listing["complete_pupils"] == 0

    # The specialist walks the same roll for their one section.
    for pupil in visited:
        assert await specialist.write_my_sections(pupil) == 1

    listing = await class_teacher.get(f"/classes/{class_id}/narrative?term_id={term_id}")
    assert listing["complete_pupils"] == len(ROLL)
    assert all(pupil["written"] == 16 for pupil in listing["pupils"])
    assert all(pupil["is_complete"] for pupil in listing["pupils"])


async def test_the_class_teachers_other_three_tasks(walkers, school_year) -> None:
    """§8.3's remaining columns: attendance, height and weight, the comment."""
    class_teacher, _ = walkers
    class_id = str(school_year.klass.id)
    term_id = str(school_year.term.id)
    ids = [str(pupil.id) for pupil in school_year.pupils]

    attendance = await class_teacher.put(
        f"/classes/{class_id}/attendance?term_id={term_id}",
        {
            "rows": [
                {
                    "pupil_id": pupil_id,
                    "times_present": OPENED - index,
                    "times_absent": index,
                    "times_late": index % 2,
                }
                for index, pupil_id in enumerate(ids)
            ]
        },
    )
    assert all(row["times_present"] is not None for row in attendance["rows"])
    assert attendance["times_school_opened"] == OPENED

    growth = await class_teacher.put(
        f"/classes/{class_id}/growth?term_id={term_id}",
        {
            "rows": [
                {
                    "pupil_id": pupil_id,
                    "height_start_m": "1.18",
                    "height_end_m": "1.22",
                    "weight_start_kg": "24.50",
                    "weight_end_kg": "25.80",
                }
                for pupil_id in ids
            ]
        },
    )
    assert all(row["height_end_m"] == "1.22" for row in growth["rows"])

    comments = await class_teacher.put(
        f"/classes/{class_id}/comments?term_id={term_id}",
        {
            "rows": [
                {"pupil_id": pupil_id, "comment": "A purposeful and settled term."}
                for pupil_id in ids
            ]
        },
    )
    assert all(row["comment"] for row in comments["rows"])

    # Writing anything at all opens the term (R14), and it stays open until
    # the class is submitted — which is milestone 8.
    assert comments["state"] == "in_progress"
    assert comments["editable"] is True
