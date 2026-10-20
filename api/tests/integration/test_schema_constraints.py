"""The §4 schema's constraints, proven rather than assumed.

Milestone 3's done-when is "constraints proven by tests". A constraint nobody
has tried to violate is a comment.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AcademicSession,
    AssessmentPeriod,
    AttendanceRecord,
    Class,
    ClassSubject,
    Enrollment,
    GradeBand,
    GradingScale,
    GrowthRecord,
    NarrativeEntry,
    NarrativeSection,
    Pupil,
    ResultEntry,
    School,
    Subject,
    Term,
    TermHalf,
    TermNumber,
)

TODAY = dt.date(2026, 9, 14)


# ---------------------------------------------------------------------------
# Fixtures for the structures these tests violate
# ---------------------------------------------------------------------------


@pytest.fixture
async def academic_session(session: AsyncSession, school: School) -> AcademicSession:
    record = AcademicSession(
        school_id=school.id, name="2026/2027", starts_on=TODAY, ends_on=dt.date(2027, 7, 23)
    )
    session.add(record)
    await session.commit()
    return record


@pytest.fixture
async def term(session: AsyncSession, school: School, academic_session) -> Term:
    record = Term(
        school_id=school.id,
        academic_session_id=academic_session.id,
        number=TermNumber.FIRST,
        starts_on=TODAY,
        ends_on=dt.date(2026, 12, 11),
        times_school_opened=60,
    )
    session.add(record)
    await session.commit()
    return record


@pytest.fixture
async def pupil(session: AsyncSession, school: School) -> Pupil:
    record = Pupil(
        school_id=school.id,
        admission_number="SSHMS/2026/001",
        first_name="Ada",
        last_name="Okafor",
    )
    session.add(record)
    await session.commit()
    return record


# ---------------------------------------------------------------------------
# §4.3 — the subject tree
# ---------------------------------------------------------------------------


async def test_a_group_subject_cannot_have_a_parent(session: AsyncSession, school: School) -> None:
    """English is a heading; a heading inside a heading is not a shape the
    card can print."""
    parent = Subject(school_id=school.id, name="English", is_group=True)
    session.add(parent)
    await session.commit()

    session.add(
        Subject(school_id=school.id, name="Nested", is_group=True, parent_subject_id=parent.id)
    )
    with pytest.raises(IntegrityError, match="group_has_no_parent"):
        await session.commit()


async def test_a_group_subject_cannot_be_specialist(session: AsyncSession, school: School) -> None:
    """A group holds no scores, so it has no teacher to be a specialist."""
    session.add(Subject(school_id=school.id, name="English", is_group=True, is_specialist=True))

    with pytest.raises(IntegrityError, match="group_is_not_specialist"):
        await session.commit()


async def test_subject_names_are_unique_within_a_school(
    session: AsyncSession, school: School
) -> None:
    session.add(Subject(school_id=school.id, name="Mathematics"))
    await session.commit()

    session.add(Subject(school_id=school.id, name="Mathematics"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_a_subject_may_be_nested_one_level(session: AsyncSession, school: School) -> None:
    """The shape the card actually uses: English over five scored children."""
    english = Subject(school_id=school.id, name="English", is_group=True, display_order=0)
    session.add(english)
    await session.commit()

    for order, name in enumerate(("Language Arts", "Structure"), start=1):
        session.add(
            Subject(
                school_id=school.id, name=name, parent_subject_id=english.id, display_order=order
            )
        )
    await session.commit()

    children = (
        (await session.execute(select(Subject).where(Subject.parent_subject_id == english.id)))
        .scalars()
        .all()
    )
    assert len(children) == 2
    assert all(child.is_group is False for child in children)


# ---------------------------------------------------------------------------
# §4.2 — academic structure
# ---------------------------------------------------------------------------


async def test_a_term_number_is_unique_within_a_session(
    session: AsyncSession, school: School, academic_session, term
) -> None:
    session.add(
        Term(
            school_id=school.id,
            academic_session_id=academic_session.id,
            number=TermNumber.FIRST,
            starts_on=TODAY,
            ends_on=dt.date(2026, 12, 11),
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_times_school_opened_cannot_be_negative(
    session: AsyncSession, school: School, academic_session
) -> None:
    session.add(
        Term(
            school_id=school.id,
            academic_session_id=academic_session.id,
            number=TermNumber.SECOND,
            starts_on=TODAY,
            ends_on=dt.date(2026, 12, 11),
            times_school_opened=-1,
        )
    )
    with pytest.raises(IntegrityError, match="times_school_opened_non_negative"):
        await session.commit()


async def test_a_term_has_at_most_one_sheet_per_half(
    session: AsyncSession, school: School, term
) -> None:
    """Two assessment periods per term — the structural key of the system."""
    for half in TermHalf:
        session.add(AssessmentPeriod(school_id=school.id, term_id=term.id, half=half))
    await session.commit()

    session.add(AssessmentPeriod(school_id=school.id, term_id=term.id, half=TermHalf.FIRST_HALF))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_a_pupil_enrolls_once_per_session(
    session: AsyncSession, school: School, academic_session, pupil
) -> None:
    klass = Class(school_id=school.id, name="Primary 4", level_order=4)
    other = Class(school_id=school.id, name="Primary 5", level_order=5)
    session.add_all([klass, other])
    await session.commit()

    session.add(
        Enrollment(
            school_id=school.id,
            pupil_id=pupil.id,
            class_id=klass.id,
            academic_session_id=academic_session.id,
            joined_on=TODAY,
        )
    )
    await session.commit()

    session.add(
        Enrollment(
            school_id=school.id,
            pupil_id=pupil.id,
            class_id=other.id,
            academic_session_id=academic_session.id,
            joined_on=TODAY,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_admission_numbers_are_unique(session: AsyncSession, school: School, pupil) -> None:
    """The admission number reaches every PDF object key the pupil will ever
    have (§9); a duplicate would collide them."""
    session.add(
        Pupil(
            school_id=school.id,
            admission_number=pupil.admission_number,
            first_name="Other",
            last_name="Child",
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_pupil_sex_is_constrained(session: AsyncSession, school: School) -> None:
    session.add(
        Pupil(
            school_id=school.id,
            admission_number="SSHMS/2026/999",
            first_name="A",
            last_name="B",
            sex="X",
        )
    )
    with pytest.raises(IntegrityError, match="sex_is_m_or_f"):
        await session.commit()


# ---------------------------------------------------------------------------
# §4.4 — R2, the generated CA total
# ---------------------------------------------------------------------------


@pytest.fixture
async def scored_entry_parts(session: AsyncSession, school: School, academic_session, term, pupil):
    klass = Class(school_id=school.id, name="Primary 4", level_order=4)
    subject = Subject(school_id=school.id, name="Mathematics")
    session.add_all([klass, subject])
    await session.commit()

    period = AssessmentPeriod(school_id=school.id, term_id=term.id, half=TermHalf.FIRST_HALF)
    class_subject = ClassSubject(
        school_id=school.id,
        class_id=klass.id,
        subject_id=subject.id,
        academic_session_id=academic_session.id,
    )
    session.add_all([period, class_subject])
    await session.commit()
    return period, class_subject, pupil


async def test_ca_total_is_summed_by_the_database(
    session: AsyncSession, school: School, scored_entry_parts
) -> None:
    """R2 is a stored generated column so that no code path can disagree."""
    period, class_subject, pupil = scored_entry_parts

    entry = ResultEntry(
        school_id=school.id,
        assessment_period_id=period.id,
        pupil_id=pupil.id,
        class_subject_id=class_subject.id,
        ca_test_1=Decimal("8.00"),
        ca_test_2=Decimal("7.50"),
        ca_test_3=Decimal("9.25"),
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)

    assert entry.ca_test_total == Decimal("24.75")


async def test_ca_total_is_null_only_when_every_test_is_null(
    session: AsyncSession, school: School, scored_entry_parts
) -> None:
    period, class_subject, pupil = scored_entry_parts

    empty = ResultEntry(
        school_id=school.id,
        assessment_period_id=period.id,
        pupil_id=pupil.id,
        class_subject_id=class_subject.id,
    )
    session.add(empty)
    await session.commit()
    await session.refresh(empty)

    assert empty.ca_test_total is None

    # A single score makes the total meaningful: the others count as zero.
    empty.ca_test_4 = Decimal("5.00")
    await session.commit()
    await session.refresh(empty)

    assert empty.ca_test_total == Decimal("5.00")


async def test_a_score_cannot_be_negative(
    session: AsyncSession, school: School, scored_entry_parts
) -> None:
    period, class_subject, pupil = scored_entry_parts

    session.add(
        ResultEntry(
            school_id=school.id,
            assessment_period_id=period.id,
            pupil_id=pupil.id,
            class_subject_id=class_subject.id,
            ca_test_1=Decimal("-1.00"),
        )
    )
    with pytest.raises(IntegrityError, match="ca_test_1_non_negative"):
        await session.commit()


async def test_there_is_no_upper_bound_check_on_a_score(
    session: AsyncSession, school: School, scored_entry_parts
) -> None:
    """Deliberate (§4.4): the maximum comes from marks_obtainable and the
    school can change it per sheet, so R1 validates in the service layer where
    the error can name the applicable maximum."""
    period, class_subject, pupil = scored_entry_parts

    session.add(
        ResultEntry(
            school_id=school.id,
            assessment_period_id=period.id,
            pupil_id=pupil.id,
            class_subject_id=class_subject.id,
            ca_test_1=Decimal("999.00"),
        )
    )
    await session.commit()  # accepted by the database, rejected by R1


async def test_one_entry_per_pupil_per_subject_per_period(
    session: AsyncSession, school: School, scored_entry_parts
) -> None:
    period, class_subject, pupil = scored_entry_parts

    for _ in range(2):
        session.add(
            ResultEntry(
                school_id=school.id,
                assessment_period_id=period.id,
                pupil_id=pupil.id,
                class_subject_id=class_subject.id,
            )
        )
    with pytest.raises(IntegrityError):
        await session.commit()


# ---------------------------------------------------------------------------
# §4.7 — R9, the attendance trigger
# ---------------------------------------------------------------------------


async def test_attendance_must_add_up(session: AsyncSession, school: School, term, pupil) -> None:
    """R9. Postgres cannot express a cross-table CHECK, so this is a trigger —
    and the trigger is the reason no path can write a bad row."""
    session.add(
        AttendanceRecord(
            school_id=school.id,
            term_id=term.id,
            pupil_id=pupil.id,
            times_present=50,
            times_absent=5,  # 55, but the term opened 60 times
        )
    )
    with pytest.raises(DBAPIError, match="must equal times_school_opened"):
        await session.commit()


async def test_attendance_that_adds_up_is_accepted(
    session: AsyncSession, school: School, term, pupil
) -> None:
    session.add(
        AttendanceRecord(
            school_id=school.id,
            term_id=term.id,
            pupil_id=pupil.id,
            times_present=55,
            times_absent=5,
            times_late=3,
        )
    )
    await session.commit()


async def test_times_present_cannot_exceed_times_opened(
    session: AsyncSession, school: School, term, pupil
) -> None:
    session.add(
        AttendanceRecord(
            school_id=school.id,
            term_id=term.id,
            pupil_id=pupil.id,
            times_present=61,
            times_absent=-1,
        )
    )
    with pytest.raises((DBAPIError, IntegrityError)):
        await session.commit()


async def test_attendance_is_unconstrained_until_the_term_calendar_is_set(
    session: AsyncSession, school: School, academic_session, pupil
) -> None:
    """A NULL times_school_opened means the admin has not set the calendar
    yet; there is nothing to check against."""
    undated = Term(
        school_id=school.id,
        academic_session_id=academic_session.id,
        number=TermNumber.THIRD,
        starts_on=TODAY,
        ends_on=dt.date(2026, 12, 11),
    )
    session.add(undated)
    await session.commit()

    session.add(
        AttendanceRecord(
            school_id=school.id,
            term_id=undated.id,
            pupil_id=pupil.id,
            times_present=10,
            times_absent=2,
        )
    )
    await session.commit()


async def test_changing_times_opened_cannot_orphan_attendance(
    session: AsyncSession, school: School, term, pupil
) -> None:
    """The second trigger. Without it the invariant holds only for new rows
    and rots the first time an admin corrects the term calendar."""
    session.add(
        AttendanceRecord(
            school_id=school.id,
            term_id=term.id,
            pupil_id=pupil.id,
            times_present=55,
            times_absent=5,
        )
    )
    await session.commit()

    with pytest.raises(DBAPIError, match="would no longer add up"):
        await session.execute(
            text("UPDATE terms SET times_school_opened = 70 WHERE id = :id"), {"id": term.id}
        )
    await session.rollback()


async def test_growth_measurements_must_be_positive(
    session: AsyncSession, school: School, term, pupil
) -> None:
    session.add(
        GrowthRecord(
            school_id=school.id,
            term_id=term.id,
            pupil_id=pupil.id,
            height_start_m=Decimal("0.00"),
        )
    )
    with pytest.raises(IntegrityError, match="height_start_positive"):
        await session.commit()


# ---------------------------------------------------------------------------
# §4.5 / §4.6
# ---------------------------------------------------------------------------


async def test_a_grade_band_cannot_be_inverted(session: AsyncSession, school: School) -> None:
    scale = GradingScale(school_id=school.id, name="Test", effective_from=TODAY)
    session.add(scale)
    await session.commit()

    session.add(
        GradeBand(
            scale_id=scale.id,
            letter="A",
            remark="Very Good",
            min_score=Decimal("90"),
            max_score=Decimal("80"),
        )
    )
    with pytest.raises(IntegrityError, match="min_not_above_max"):
        await session.commit()


async def test_deleting_a_scale_takes_its_bands(session: AsyncSession, school: School) -> None:
    scale = GradingScale(school_id=school.id, name="Test", effective_from=TODAY)
    session.add(scale)
    await session.commit()

    session.add(
        GradeBand(
            scale_id=scale.id,
            letter="A",
            remark="Very Good",
            min_score=Decimal("80"),
            max_score=Decimal("89"),
        )
    )
    await session.commit()

    await session.delete(scale)
    await session.commit()

    assert await session.scalar(select(GradeBand).limit(1)) is None


async def test_one_narrative_entry_per_pupil_section_and_term(
    session: AsyncSession, school: School, term, pupil
) -> None:
    """Narrative is per term, not per half term (A6)."""
    section = NarrativeSection(school_id=school.id, code="B", label="Work/Study", display_order=0)
    session.add(section)
    await session.commit()

    for _ in range(2):
        session.add(
            NarrativeEntry(
                school_id=school.id, term_id=term.id, pupil_id=pupil.id, section_id=section.id
            )
        )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_narrative_section_codes_are_unique_within_a_school(
    session: AsyncSession, school: School
) -> None:
    for _ in range(2):
        session.add(
            NarrativeSection(school_id=school.id, code="B", label="Work/Study", display_order=0)
        )
    with pytest.raises(IntegrityError):
        await session.commit()
