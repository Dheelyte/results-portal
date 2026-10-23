"""Fixtures for tests that touch the database.

Real PostgreSQL 16, never SQLite (ARCHITECTURE.md §10): generated columns,
enums, citext and triggers all behave differently, and a suite that passes
against a database you do not run is worth nothing.

State is reset by truncating between tests rather than by wrapping each test
in a rolled-back transaction. The auth rules commit deliberately — a failed
login must persist its attempt counter even though the request fails — and a
harness that swallowed commits would hide exactly that.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from alembic import command
from httpx import ASGITransport, AsyncClient
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import settings
from app.db import SessionLocal, engine
from app.main import app
from app.models import Base, School, User, UserRole
from tests.alembic_support import alembic_config, run_alembic
from tests.conftest import TEST_PASSWORD

# Children before parents, derived from the model metadata rather than
# hand-listed, so a table added in a later milestone is cleaned without anyone
# remembering to add it here.
DELETE_ORDER = tuple(table.name for table in reversed(Base.metadata.sorted_tables))


@pytest.fixture(scope="session")
async def migrated_database() -> None:
    """Create the suite's database if it is absent, and bring it to head.

    The suite owns this database outright (`tests/conftest.py` redirects to
    it), so it can be built here rather than by hand. That also makes the
    schema under test the migration chain's output rather than
    `metadata.create_all`, which would let a model and its migration disagree
    without any test noticing — CLAUDE.md rule 3.
    """
    url = make_url(settings.dsn)
    admin = create_async_engine(url.set(database="postgres").render_as_string(hide_password=False))
    try:
        async with admin.connect() as connection:
            await connection.execution_options(isolation_level="AUTOCOMMIT")
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
            )
            if not exists:
                await connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        await admin.dispose()

    await run_alembic(alembic_config(settings.dsn), command.upgrade, "head")


@pytest.fixture(autouse=True)
async def clean_database(migrated_database: None) -> AsyncIterator[None]:
    """Empty every table before each test.

    DELETE rather than TRUNCATE, which is counter-intuitive but measured:
    TRUNCATE rewrites each table's file and fsyncs, costing ~650ms across this
    schema, against ~19ms for DELETE over the same (nearly always empty)
    tables. On a suite this size that is the difference between three minutes
    and one.

    Deleting rather than rolling back a transaction is deliberate: the auth
    rules commit on purpose — a failed login must persist its attempt counter
    even though the request fails — and a harness that swallowed commits would
    hide exactly that behaviour (docs/DECISIONS.md D26).

    This empties the suite's own database, never the application's — see the
    redirection in `tests/conftest.py` (docs/DECISIONS.md D46).
    """
    async with engine.begin() as connection:
        for table in DELETE_ORDER:
            await connection.execute(text(f'DELETE FROM "{table}"'))
    yield


@pytest.fixture
async def session(clean_database: None) -> AsyncIterator[AsyncSession]:
    """A session for test setup.

    Depends on `clean_database` explicitly even though that fixture is
    autouse. Autouse ordering against a requested fixture chain is not
    guaranteed in every case, and when it lost the race the wipe landed
    *between* a user being committed and that user logging in — which
    presented as an intermittent 401 in fixture setup rather than as anything
    resembling its cause. Naming the dependency makes the order a fact.
    """
    async with SessionLocal() as db_session:
        yield db_session


@pytest.fixture
async def school(session: AsyncSession) -> School:
    record = School(name="Self-Starters House Montessori School", short_name="SSHMS")
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


@pytest.fixture
async def make_user(session: AsyncSession, school: School, password_hash: str):
    """Factory for a user of any role."""

    async def _make(
        role: UserRole = UserRole.TEACHER,
        *,
        email: str | None = None,
        phone: str | None = None,
        must_change_password: bool = False,
        is_active: bool = True,
        full_name: str = "Test Person",
    ) -> User:
        if email is None and phone is None:
            email = f"{role.value}-{uuid.uuid4().hex[:8]}@sshms.test"

        user = User(
            school_id=school.id,
            role=role,
            email=email,
            phone=phone,
            full_name=full_name,
            password_hash=password_hash,
            must_change_password=must_change_password,
            is_active=is_active,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    return _make


@pytest.fixture
async def users(make_user) -> dict[UserRole, User]:
    """One user per role — the §5.2 cast, for the four-role assertions."""
    return {role: await make_user(role) for role in UserRole}


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """An HTTP client bound directly to the ASGI app.

    No lifespan manager is needed: app.db builds the engine at import time, so
    the database is reachable without starting the application's lifespan.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://api.test") as http_client:
        yield http_client


@pytest.fixture
async def login(client: AsyncClient):
    """Sign a user in, returning the raw response."""

    async def _login(identifier: str, password: str = TEST_PASSWORD):
        return await client.post(
            "/api/v1/auth/login",
            json={"identifier": identifier, "password": password},
        )

    return _login


# ---------------------------------------------------------------------------
# A small but complete school, for the §5.2 authorization matrix
# ---------------------------------------------------------------------------


@pytest.fixture
async def world(session: AsyncSession, school, password_hash: str):
    """Two classes, two teachers, a specialist, a parent with two children.

    Deliberately shaped to make the §5.2 invariants testable:

    - `teacher_a` is class teacher of 4A **and** subject teacher of French in
      5B — the union case the matrix calls out by name.
    - `teacher_b` is class teacher of 5B and teaches nothing in 4A.
    - `specialist` teaches Computer in both classes and is class teacher of
      neither, and holds the narrative assignment for Computer Skills in 4A.
    - `parent` has one child in each class; `other_parent` has neither.
    """
    import datetime as dt
    from types import SimpleNamespace

    from app.models import (
        AcademicSession,
        Class,
        ClassSubject,
        ClassTeacher,
        Enrollment,
        GuardianPupil,
        NarrativeSection,
        NarrativeSectionAssignment,
        Pupil,
        Subject,
        TeachingAssignment,
        Term,
        TermNumber,
        TermReport,
        User,
        UserRole,
    )

    def user(role: UserRole, name: str) -> User:
        record = User(
            school_id=school.id,
            role=role,
            full_name=name,
            email=f"{name.lower().replace(' ', '.')}@sshms.test",
            password_hash=password_hash,
            must_change_password=False,
        )
        session.add(record)
        return record

    admin = user(UserRole.ADMIN, "The Admin")
    head = user(UserRole.HEAD_TEACHER, "The Head")
    teacher_a = user(UserRole.TEACHER, "Teacher A")
    teacher_b = user(UserRole.TEACHER, "Teacher B")
    specialist = user(UserRole.TEACHER, "The Specialist")
    parent = user(UserRole.PARENT, "A Parent")
    other_parent = user(UserRole.PARENT, "Other Parent")
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
        times_school_opened=60,
        is_current=True,
    )
    class_4a = Class(school_id=school.id, name="Primary 4", level_order=4)
    class_5b = Class(school_id=school.id, name="Primary 5", level_order=5)
    french = Subject(school_id=school.id, name="French")
    maths = Subject(school_id=school.id, name="Mathematics")
    computer = Subject(school_id=school.id, name="Computer", is_specialist=True)
    session.add_all([term, class_4a, class_5b, french, maths, computer])
    await session.flush()

    session.add_all(
        [
            ClassTeacher(
                school_id=school.id,
                class_id=class_4a.id,
                academic_session_id=academic_session.id,
                teacher_user_id=teacher_a.id,
            ),
            ClassTeacher(
                school_id=school.id,
                class_id=class_5b.id,
                academic_session_id=academic_session.id,
                teacher_user_id=teacher_b.id,
            ),
        ]
    )

    def offer(klass: Class, subject: Subject, teacher: User) -> ClassSubject:
        class_subject = ClassSubject(
            school_id=school.id,
            class_id=klass.id,
            subject_id=subject.id,
            academic_session_id=academic_session.id,
        )
        session.add(class_subject)
        return class_subject

    maths_4a = offer(class_4a, maths, teacher_a)
    french_4a = offer(class_4a, french, teacher_a)
    maths_5b = offer(class_5b, maths, teacher_b)
    french_5b = offer(class_5b, french, teacher_a)  # the union case
    computer_4a = offer(class_4a, computer, specialist)
    computer_5b = offer(class_5b, computer, specialist)
    await session.flush()

    for class_subject, teacher in (
        (maths_4a, teacher_a),
        (french_4a, teacher_a),
        (maths_5b, teacher_b),
        (french_5b, teacher_a),
        (computer_4a, specialist),
        (computer_5b, specialist),
    ):
        session.add(
            TeachingAssignment(
                school_id=school.id,
                class_subject_id=class_subject.id,
                teacher_user_id=teacher.id,
            )
        )

    computer_skills = NarrativeSection(
        school_id=school.id,
        code="A.computer_skills",
        label="Computer Skills",
        group_label="Area of Curriculum",
        display_order=4,
    )
    work_habits = NarrativeSection(
        school_id=school.id, code="B", label="Work/Study Habits", display_order=7
    )
    session.add_all([computer_skills, work_habits])
    await session.flush()

    # The specialist writes Computer Skills for 4A; everything else falls to
    # the class teacher by absence of an assignment (D15).
    session.add(
        NarrativeSectionAssignment(
            school_id=school.id,
            class_id=class_4a.id,
            section_id=computer_skills.id,
            academic_session_id=academic_session.id,
            teacher_user_id=specialist.id,
        )
    )

    pupils = {}
    for index, (name, klass) in enumerate(
        (("Ada", class_4a), ("Chidi", class_5b), ("Emeka", class_4a))
    ):
        pupil = Pupil(
            school_id=school.id,
            admission_number=f"SSHMS/2026/{index + 1:03d}",
            first_name=name,
            last_name="Okafor",
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
        pupils[name.lower()] = pupil

    # The parent's two children are in *different* classes (§10).
    session.add_all(
        [
            GuardianPupil(guardian_user_id=parent.id, pupil_id=pupils["ada"].id),
            GuardianPupil(guardian_user_id=parent.id, pupil_id=pupils["chidi"].id),
        ]
    )

    reports = {}
    for key, pupil, klass in (
        ("ada", pupils["ada"], class_4a),
        ("chidi", pupils["chidi"], class_5b),
        ("emeka", pupils["emeka"], class_4a),
    ):
        report = TermReport(
            school_id=school.id, term_id=term.id, pupil_id=pupil.id, class_id=klass.id
        )
        session.add(report)
        reports[key] = report

    await session.commit()

    return SimpleNamespace(
        school=school,
        academic_session=academic_session,
        term=term,
        admin=admin,
        head=head,
        teacher_a=teacher_a,
        teacher_b=teacher_b,
        specialist=specialist,
        parent=parent,
        other_parent=other_parent,
        class_4a=class_4a,
        class_5b=class_5b,
        maths_4a=maths_4a,
        french_4a=french_4a,
        maths_5b=maths_5b,
        french_5b=french_5b,
        computer_4a=computer_4a,
        computer_5b=computer_5b,
        computer_skills=computer_skills,
        work_habits=work_habits,
        pupils=pupils,
        reports=reports,
    )


@pytest.fixture
async def headers_for(login):
    """Sign a user in and return their Authorization header.

    Goes through the real login endpoint rather than minting a token directly,
    so every authorization test also exercises the path a browser takes.
    """

    async def _headers(user: User, password: str = TEST_PASSWORD) -> dict[str, str]:
        response = await login(user.email or user.phone, password)
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _headers


@pytest.fixture
async def admin_headers(make_user, headers_for) -> dict[str, str]:
    """An admin's Authorization header, against an otherwise empty school."""
    admin = await make_user(UserRole.ADMIN)
    return await headers_for(admin)
