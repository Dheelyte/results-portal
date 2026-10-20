"""Demo data for development and tests (ARCHITECTURE.md §10).

A fictional school: two classes of ten pupils, the full subject tree with
English grouped, three teachers, one head teacher, one admin, eight parents —
**one with two children in different classes**, and **one pupil who joined in
second term**. Those last two exist because they catch most multi-child and
cumulative-average bugs, and §10 names them for that reason.

Never run this against a real deployment. `python -m app.seed` refuses unless
the database holds no pupils.
"""

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import hash_password
from app.models import (
    AcademicSession,
    AssessmentPeriod,
    Class,
    ClassSubject,
    ClassTeacher,
    Enrollment,
    GuardianPupil,
    House,
    Pupil,
    School,
    Subject,
    TeachingAssignment,
    Term,
    TermHalf,
    TermNumber,
    User,
    UserRole,
)
from app.seed.reference import seed_reference

DEMO_PASSWORD = "demo-password-change-me"
SESSION_NAME = "2026/2027"
HOUSES = ("Blue", "Gold", "Green", "Red")

# Taught by specialists rather than the class teacher. A starting point the
# admin edits — which subjects are specialist is the school's call (§2.3), and
# the B1 follow-up is still open.
SPECIALIST_SUBJECTS = ("Computer", "Creative Art", "Physical/Health Education", "French")

TERM_DATES = {
    TermNumber.FIRST: (dt.date(2026, 9, 14), dt.date(2026, 12, 11), 61),
    TermNumber.SECOND: (dt.date(2027, 1, 11), dt.date(2027, 4, 2), 58),
    TermNumber.THIRD: (dt.date(2027, 4, 26), dt.date(2027, 7, 23), 62),
}

FIRST_NAMES = (
    "Adaeze",
    "Chidi",
    "Emeka",
    "Folake",
    "Ibrahim",
    "Kemi",
    "Ngozi",
    "Obinna",
    "Simi",
    "Tunde",
    "Yemi",
    "Zainab",
    "Amara",
    "Bisi",
    "Chinelo",
    "Damilola",
    "Efe",
    "Funmi",
    "Gbenga",
    "Halima",
)
SURNAMES = (
    "Adebayo",
    "Okafor",
    "Balogun",
    "Eze",
    "Lawal",
    "Nwosu",
    "Oyelaran",
    "Suleiman",
    "Uche",
    "Williams",
)


async def _make_user(
    session: AsyncSession,
    school_id: uuid.UUID,
    role: UserRole,
    full_name: str,
    email: str,
    password_hash: str,
    phone: str | None = None,
) -> User:
    user = User(
        school_id=school_id,
        role=role,
        full_name=full_name,
        email=email,
        phone=phone,
        password_hash=password_hash,
        # Demo accounts are meant to be signed into directly.
        must_change_password=False,
    )
    session.add(user)
    return user


async def seed_demo(session: AsyncSession) -> dict[str, int]:
    """Create the demo school. Returns a count of what was made."""
    if await session.scalar(select(Pupil).limit(1)) is not None:
        raise RuntimeError(
            "refusing to seed: this database already holds pupils. "
            "Demo data is for an empty development database only."
        )

    school = await session.scalar(select(School).limit(1))
    if school is None:
        school = School(
            name="Self-Starters House Montessori School",
            short_name="SSHMS",
            address="Lagos, Nigeria",
        )
        session.add(school)
        await session.flush()

    await seed_reference(session, school.id)

    # Hash once: Argon2id is deliberately slow and every demo account shares
    # the same password.
    password_hash = hash_password(DEMO_PASSWORD)

    houses = [House(school_id=school.id, name=name) for name in HOUSES]
    session.add_all(houses)

    admin = await _make_user(
        session, school.id, UserRole.ADMIN, "Admin User", "admin@sshms.test", password_hash
    )
    head = await _make_user(
        session, school.id, UserRole.HEAD_TEACHER, "Head Teacher", "head@sshms.test", password_hash
    )
    teachers = [
        await _make_user(
            session,
            school.id,
            UserRole.TEACHER,
            name,
            f"teacher{index + 1}@sshms.test",
            password_hash,
        )
        for index, name in enumerate(("Mrs Adeyemi", "Mr Okonkwo", "Miss Bello"))
    ]
    await session.flush()

    academic_session = AcademicSession(
        school_id=school.id,
        name=SESSION_NAME,
        starts_on=dt.date(2026, 9, 14),
        ends_on=dt.date(2027, 7, 23),
        is_current=True,
    )
    session.add(academic_session)
    await session.flush()

    terms: dict[TermNumber, Term] = {}
    for number, (starts, ends, opened) in TERM_DATES.items():
        term = Term(
            school_id=school.id,
            academic_session_id=academic_session.id,
            number=number,
            starts_on=starts,
            ends_on=ends,
            times_school_opened=opened,
            # The active term is set in the platform, never derived (§2.3).
            is_current=number is TermNumber.THIRD,
        )
        session.add(term)
        terms[number] = term
    await session.flush()

    # Two assessment periods per term — the structural key of the system.
    for term in terms.values():
        for half in TermHalf:
            session.add(AssessmentPeriod(school_id=school.id, term_id=term.id, half=half))

    classes = [
        Class(school_id=school.id, name=name, level_order=order)
        for order, name in enumerate(("Primary 4", "Primary 5"), start=4)
    ]
    session.add_all(classes)
    await session.flush()

    for index, klass in enumerate(classes):
        session.add(
            ClassTeacher(
                school_id=school.id,
                class_id=klass.id,
                academic_session_id=academic_session.id,
                teacher_user_id=teachers[index].id,
            )
        )

    # Every scored subject is offered to both classes. Group headings are
    # excluded: a group holds no scores and must never appear here (R7).
    scored = (
        (
            await session.execute(
                select(Subject)
                .where(Subject.school_id == school.id, Subject.is_group.is_(False))
                .order_by(Subject.display_order)
            )
        )
        .scalars()
        .all()
    )
    for subject in scored:
        if subject.name in SPECIALIST_SUBJECTS:
            subject.is_specialist = True

    for klass in classes:
        for subject in scored:
            class_subject = ClassSubject(
                school_id=school.id,
                class_id=klass.id,
                subject_id=subject.id,
                academic_session_id=academic_session.id,
                display_order=subject.display_order,
            )
            session.add(class_subject)
            await session.flush()

            # Specialists teach their subject across both classes; everything
            # else falls to the class teacher. This is what makes the §5.2
            # union case ("class teacher of 4A and French teacher in 5B") real
            # in the demo data.
            if subject.is_specialist:
                teacher = teachers[2]
            else:
                teacher = teachers[classes.index(klass)]

            session.add(
                TeachingAssignment(
                    school_id=school.id,
                    class_subject_id=class_subject.id,
                    teacher_user_id=teacher.id,
                )
            )

    pupils: list[Pupil] = []
    for class_index, klass in enumerate(classes):
        for pupil_index in range(10):
            ordinal = class_index * 10 + pupil_index
            pupil = Pupil(
                school_id=school.id,
                admission_number=f"SSHMS/2026/{ordinal + 1:03d}",
                first_name=FIRST_NAMES[ordinal],
                last_name=SURNAMES[ordinal % len(SURNAMES)],
                sex="F" if ordinal % 2 == 0 else "M",
                date_of_birth=dt.date(2016, 1 + (ordinal % 12), 1 + (ordinal % 28)),
                house_id=houses[ordinal % len(houses)].id,
            )
            session.add(pupil)
            await session.flush()
            pupils.append(pupil)

            # §10: one pupil joined in second term. R5's cumulative averages
            # must count the terms they were present for, not three.
            joined = (
                TERM_DATES[TermNumber.SECOND][0]
                if ordinal == 15
                else TERM_DATES[TermNumber.FIRST][0]
            )
            session.add(
                Enrollment(
                    school_id=school.id,
                    pupil_id=pupil.id,
                    class_id=klass.id,
                    academic_session_id=academic_session.id,
                    joined_on=joined,
                )
            )

    # Eight parents. The first has two children in *different* classes (§10),
    # which is what the multi-child parent view must handle.
    parents = [
        await _make_user(
            session,
            school.id,
            UserRole.PARENT,
            f"Parent {index + 1}",
            f"parent{index + 1}@sshms.test",
            password_hash,
            phone=f"+23480000000{index + 1:02d}",
        )
        for index in range(8)
    ]
    await session.flush()

    session.add(
        GuardianPupil(guardian_user_id=parents[0].id, pupil_id=pupils[0].id, is_primary=True)
    )
    session.add(
        GuardianPupil(guardian_user_id=parents[0].id, pupil_id=pupils[10].id, is_primary=True)
    )
    for index, parent in enumerate(parents[1:], start=1):
        session.add(
            GuardianPupil(guardian_user_id=parent.id, pupil_id=pupils[index].id, is_primary=True)
        )

    await session.commit()

    return {
        "schools": 1,
        "users": 2 + len(teachers) + len(parents),
        "classes": len(classes),
        "pupils": len(pupils),
        "subjects": len(scored),
        "terms": len(terms),
        "assessment_periods": len(terms) * 2,
        "admin_id_exists": int(admin.id is not None and head.id is not None),
    }
