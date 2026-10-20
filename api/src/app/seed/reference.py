"""The school's reference data, as printed on the card.

Idempotent: safe to run on every deploy. Rows are created when absent and
**left alone when present**, because the school may have edited them in the
platform and re-asserting the seeded value would silently undo that
(ARCHITECTURE.md §2.3, docs/DECISIONS.md D14).

Nothing here is read by application logic. These are starting values for rows
the admin owns — no code may branch on a subject's name or a band's letter.
"""

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GradeBand, GradingScale, NarrativeSection, Subject

# --- Subjects (§1.5, in card order) ---------------------------------------
# English is a group heading carrying no scores of its own; its five
# sub-subjects are scored (§4.3, R7).
ENGLISH_CHILDREN = (
    "Language Arts",
    "Structure",
    "Compr. & Poetry",
    "Spelling & Reading",
    "Creative Writing",
)

STANDALONE_SUBJECTS = (
    "Mathematics",
    "Cultural Studies",
    "Geography",
    "History",
    "Science",
    "Social Studies",
    "Home Economics",
    "Computer",
    "Creative Art",
    "Penmanship",
    "Yoruba",
    "French",
    "Physical/Health Education",
)

# --- Grading scale (§1.3, as printed on the card) -------------------------
# A2: this is the card's seven-band scale, which contradicts the six-band
# scale approved in September. N1 is still open. Seeded because it is what is
# printed; scales are versioned rows (§4.5) so the answer is a new scale, not
# a migration.
CARD_GRADE_BANDS = (
    ("A+", "Excellence", 90, 100),
    ("A", "Very Good", 80, 89),
    ("B+", "Good", 70, 79),
    ("B", "Fairly Good", 60, 69),
    ("C", "Average", 50, 59),
    ("D", "Below Average", 40, 49),
    ("E", "Weak", 0, 39),
)
CARD_SCALE_NAME = "Card scale (seven bands)"

# --- Narrative sections (§1.4, §4.6) --------------------------------------
# Seventeen in card order: seven curriculum areas under "Area of Curriculum",
# then B through J. N7 may reduce this; `is_active` handles that without a
# migration.
CURRICULUM_AREA = "Area of Curriculum"
CURRICULUM_AREAS = (
    ("A.english_language_arts", "English Language Arts"),
    ("A.mathematics", "Mathematics"),
    ("A.science", "Science"),
    ("A.social_studies", "Social Studies"),
    ("A.computer_skills", "Computer Skills"),
    ("A.art_and_music", "Art & Music"),
    ("A.physical_education", "Physical Education"),
)
BEHAVIOURAL_SECTIONS = (
    ("B", "Work/Study Habits"),
    ("C", "Attendance/Tardiness"),
    ("D", "Attitude"),
    ("E", "Classroom Behaviour"),
    ("F", "Outside Behaviour"),
    ("G", "Character Development"),
    ("H", "Peer Relations"),
    ("I", "Personal Development"),
    ("J", "Performance"),
)


async def seed_subjects(session: AsyncSession, school_id: uuid.UUID) -> int:
    """Create the subject tree if it is absent. Returns rows created."""
    existing = set(
        (await session.execute(select(Subject.name).where(Subject.school_id == school_id)))
        .scalars()
        .all()
    )
    created = 0
    order = 0

    english = await session.scalar(
        select(Subject).where(Subject.school_id == school_id, Subject.name == "English")
    )
    if english is None:
        english = Subject(school_id=school_id, name="English", is_group=True, display_order=order)
        session.add(english)
        await session.flush()
        created += 1
    order += 1

    for name in ENGLISH_CHILDREN:
        if name not in existing:
            session.add(
                Subject(
                    school_id=school_id,
                    name=name,
                    parent_subject_id=english.id,
                    display_order=order,
                )
            )
            created += 1
        order += 1

    for name in STANDALONE_SUBJECTS:
        if name not in existing:
            session.add(Subject(school_id=school_id, name=name, display_order=order))
            created += 1
        order += 1

    return created


async def seed_grading_scale(session: AsyncSession, school_id: uuid.UUID) -> int:
    """Create the card's scale if the school has none."""
    existing = await session.scalar(select(GradingScale).where(GradingScale.school_id == school_id))
    if existing is not None:
        return 0

    scale = GradingScale(
        school_id=school_id,
        name=CARD_SCALE_NAME,
        effective_from=dt.date(1970, 1, 1),
        is_active=True,
    )
    session.add(scale)
    await session.flush()

    for order, (letter, remark, low, high) in enumerate(CARD_GRADE_BANDS):
        session.add(
            GradeBand(
                scale_id=scale.id,
                letter=letter,
                remark=remark,
                min_score=Decimal(low),
                max_score=Decimal(high),
                sort_order=order,
            )
        )
    return 1 + len(CARD_GRADE_BANDS)


async def seed_narrative_sections(session: AsyncSession, school_id: uuid.UUID) -> int:
    """Create the seventeen sections if absent."""
    existing = set(
        (
            await session.execute(
                select(NarrativeSection.code).where(NarrativeSection.school_id == school_id)
            )
        )
        .scalars()
        .all()
    )
    created = 0
    order = 0

    for code, label in CURRICULUM_AREAS:
        if code not in existing:
            session.add(
                NarrativeSection(
                    school_id=school_id,
                    code=code,
                    label=label,
                    group_label=CURRICULUM_AREA,
                    display_order=order,
                )
            )
            created += 1
        order += 1

    for code, label in BEHAVIOURAL_SECTIONS:
        if code not in existing:
            session.add(
                NarrativeSection(school_id=school_id, code=code, label=label, display_order=order)
            )
            created += 1
        order += 1

    return created


async def seed_reference(session: AsyncSession, school_id: uuid.UUID) -> dict[str, int]:
    """Seed everything the school needs to start, idempotently."""
    counts = {
        "subjects": await seed_subjects(session, school_id),
        "grading_scale": await seed_grading_scale(session, school_id),
        "narrative_sections": await seed_narrative_sections(session, school_id),
    }
    await session.commit()
    return counts
