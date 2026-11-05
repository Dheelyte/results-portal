"""The report card PDF (ARCHITECTURE.md §9).

§12's criterion: "Golden-file tests pass; a guessed key 403s."

The golden files in `tests/golden/` are the **extracted text** of a fixed
fixture pupil's card, one per layout, committed and compared. §9 asks for
exactly that, and text rather than bytes is the right comparison for a reason
worth stating: a diff in a golden text file is readable in a review, so a
change to the card is something a person can see and approve rather than a
binary blob that only says "different".

Regenerate them deliberately, never automatically:

    docker compose exec -T api pytest tests/integration/test_report_card.py \\
        --golden-update
"""

import datetime as dt
import io
import pathlib
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    AcademicSession,
    AssessmentPeriod,
    AttendanceRecord,
    Class,
    ClassSubject,
    ClassTermState,
    ClassTermStatus,
    Enrollment,
    GradeBand,
    GradingScale,
    GrowthRecord,
    GuardianPupil,
    House,
    MarksObtainable,
    NarrativeEntry,
    NarrativeSection,
    PublicationState,
    Pupil,
    ResultEntry,
    Subject,
    Term,
    TermHalf,
    TermNumber,
    TermReport,
    User,
    UserRole,
)
from app.pdf import links, render
from app.seed.reference import seed_narrative_sections
from app.services import cards, reportcard
from tests.conftest import TEST_PASSWORD

API = settings.api_v1_prefix
GOLDEN = pathlib.Path(__file__).resolve().parents[1] / "golden"

CA_MAX = Decimal(8)
TERMINAL_MAX = Decimal(60)


def extract(pdf: bytes) -> str:
    """The PDF's text, normalised enough to diff but not enough to hide a bug.

    Trailing whitespace goes, because it is invisible in a diff and varies
    with layout rounding. Nothing else is touched: a word order change, a
    missing figure or an extra column all show.
    """
    from pypdf import PdfReader

    pages = PdfReader(io.BytesIO(pdf)).pages
    text = "\n--- page ---\n".join(page.extract_text() for page in pages)
    return "\n".join(line.rstrip() for line in text.splitlines()).strip() + "\n"


def compare_golden(name: str, actual: str, *, update: bool) -> None:
    path = GOLDEN / name
    if update:
        path.write_text(actual, encoding="utf-8")
        pytest.skip(f"golden file {name} rewritten")
    assert path.is_file(), (
        f"{name} is missing. Generate it deliberately with --golden-update "
        "and read the diff before committing it."
    )
    assert actual == path.read_text(encoding="utf-8"), (
        f"the card's text no longer matches {name}. If the change is intended, "
        "rerun with --golden-update and review the diff."
    )


@pytest.fixture
async def card_world(session: AsyncSession, school, password_hash: str):
    """One pupil with a complete, approved, published card.

    Fixed values throughout — fixed dates, fixed scores, fixed passages — so
    the rendered text is a function of this fixture alone. A golden file that
    depended on `date.today()` would fail every midnight.
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

    admin = user(UserRole.ADMIN, "The Admin", "admin@sshms.test")
    parent = user(UserRole.PARENT, "Mrs Okafor", "parent@sshms.test")
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
        times_school_opened=58,
        is_current=True,
    )
    house = House(school_id=school.id, name="Blue")
    klass = Class(school_id=school.id, name="Primary 4", level_order=4)
    session.add_all([term, house, klass])
    await session.flush()

    periods = {}
    for half in TermHalf:
        period = AssessmentPeriod(school_id=school.id, term_id=term.id, half=half)
        session.add(period)
        periods[half] = period
    await session.flush()

    for half, period in periods.items():
        session.add(
            MarksObtainable(
                school_id=school.id,
                assessment_period_id=period.id,
                class_id=None,
                ca_test_1=CA_MAX,
                ca_test_2=CA_MAX,
                mid_term_test=TERMINAL_MAX if half is TermHalf.FIRST_HALF else None,
                exam=TERMINAL_MAX if half is TermHalf.SECOND_HALF else None,
            )
        )

    scale = GradingScale(
        school_id=school.id,
        name="Card scale (seven bands)",
        effective_from=dt.date(2026, 9, 1),
        is_active=True,
    )
    session.add(scale)
    await session.flush()
    for order, (letter, remark, low, high) in enumerate(
        [
            ("A+", "Excellence", 90, 100),
            ("A", "Very Good", 80, 89),
            ("B+", "Good", 70, 79),
            ("B", "Fairly Good", 60, 69),
            ("C", "Average", 50, 59),
            ("D", "Below Average", 40, 49),
            ("E", "Weak", 0, 39),
        ]
    ):
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

    # English as a heading over two of its sub-subjects, plus Mathematics —
    # enough to exercise §9's spanning row without a golden file nobody reads.
    english = Subject(school_id=school.id, name="English", is_group=True, display_order=0)
    session.add(english)
    await session.flush()
    language_arts = Subject(
        school_id=school.id,
        name="Language Arts",
        parent_subject_id=english.id,
        display_order=1,
    )
    structure = Subject(
        school_id=school.id, name="Structure", parent_subject_id=english.id, display_order=2
    )
    maths = Subject(school_id=school.id, name="Mathematics", display_order=3)
    session.add_all([language_arts, structure, maths])
    await session.flush()

    offerings = {}
    for subject in (language_arts, structure, maths):
        offering = ClassSubject(
            school_id=school.id,
            class_id=klass.id,
            subject_id=subject.id,
            academic_session_id=academic_session.id,
        )
        session.add(offering)
        await session.flush()
        offerings[subject.name] = offering

    await seed_narrative_sections(session, school.id)
    await session.flush()
    sections = (
        await session.execute(
            NarrativeSection.__table__.select().where(NarrativeSection.school_id == school.id)
        )
    ).all()

    pupil = Pupil(
        school_id=school.id,
        admission_number="SSHMS/2026/001",
        first_name="Ada",
        middle_name="Ngozi",
        last_name="Okafor",
        house_id=house.id,
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
    session.add(GuardianPupil(guardian_user_id=parent.id, pupil_id=pupil.id))

    # Fixed scores per subject, so every figure on the card is predictable.
    marks_by_subject = {
        "Language Arts": (Decimal(7), Decimal(8), Decimal(50)),
        "Structure": (Decimal(6), Decimal(7), Decimal(44)),
        "Mathematics": (Decimal(8), Decimal(8), Decimal(55)),
    }
    for name, (ca_1, ca_2, terminal) in marks_by_subject.items():
        for half, period in periods.items():
            session.add(
                ResultEntry(
                    school_id=school.id,
                    assessment_period_id=period.id,
                    pupil_id=pupil.id,
                    class_subject_id=offerings[name].id,
                    ca_test_1=ca_1,
                    ca_test_2=ca_2,
                    mid_term_test=terminal if half is TermHalf.FIRST_HALF else None,
                    exam=terminal if half is TermHalf.SECOND_HALF else None,
                    period_average=(ca_1 + ca_2 + terminal) * Decimal("1.25"),
                    grade_letter="A" if terminal > Decimal(45) else "B",
                    grading_scale_id=scale.id,
                )
            )

    for row in sections:
        session.add(
            NarrativeEntry(
                school_id=school.id,
                term_id=term.id,
                pupil_id=pupil.id,
                section_id=row.id,
                body=f"Has worked steadily on {row.label.lower()} this term.",
            )
        )

    session.add(
        AttendanceRecord(
            school_id=school.id,
            term_id=term.id,
            pupil_id=pupil.id,
            times_present=56,
            times_absent=2,
            times_late=1,
        )
    )
    session.add(
        GrowthRecord(
            school_id=school.id,
            term_id=term.id,
            pupil_id=pupil.id,
            height_start_m=Decimal("1.18"),
            height_end_m=Decimal("1.22"),
            weight_start_kg=Decimal("24.50"),
            weight_end_kg=Decimal("25.80"),
        )
    )
    session.add(
        TermReport(
            school_id=school.id,
            term_id=term.id,
            pupil_id=pupil.id,
            class_id=klass.id,
            class_teacher_comment="A purposeful and settled term.",
            head_teacher_remark="Well done. Keep it up.",
            position_text="Upper band",
            overall_percentage=Decimal("88.75"),
            no_in_class=1,
            state=PublicationState.PUBLISHED,
            published_at=dt.datetime(2026, 12, 12, 9, 0, tzinfo=dt.UTC),
            published_by=admin.id,
        )
    )
    session.add(
        ClassTermStatus(
            school_id=school.id,
            class_id=klass.id,
            term_id=term.id,
            state=ClassTermState.APPROVED,
        )
    )

    await session.commit()

    return SimpleNamespace(
        admin=admin,
        parent=parent,
        pupil=pupil,
        term=term,
        klass=klass,
        periods=periods,
        scale=scale,
    )


# ---------------------------------------------------------------------------
# §12's criterion: the golden files
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("half", "name"),
    [
        (TermHalf.FIRST_HALF, "card-first-half.txt"),
        (TermHalf.SECOND_HALF, "card-second-half.txt"),
    ],
    ids=["first-half", "second-half"],
)
async def test_the_card_renders_to_its_golden_text(
    session, card_world, half, name, request
) -> None:
    """§9: "a fixed fixture pupil renders to a PDF whose extracted text
    matches a committed expected output, for both the first-half and
    second-half layouts"."""
    card = await reportcard.build(
        session,
        card_world.admin,
        pupil_id=card_world.pupil.id,
        term_id=card_world.term.id,
        half=half,
    )

    compare_golden(
        name,
        extract(render.render_pdf(card)),
        update=request.config.getoption("--golden-update"),
    )


async def test_both_layouts_carry_their_own_columns(session, card_world) -> None:
    """The two sheets differ in exactly the way the photographs show."""
    first = await reportcard.build(
        session,
        card_world.admin,
        pupil_id=card_world.pupil.id,
        term_id=card_world.term.id,
        half=TermHalf.FIRST_HALF,
    )
    second = await reportcard.build(
        session,
        card_world.admin,
        pupil_id=card_world.pupil.id,
        term_id=card_world.term.id,
        half=TermHalf.SECOND_HALF,
    )

    assert first.subtitle == "FIRST HALF TERM"
    assert second.subtitle == "SECOND HALF TERM"
    assert [label for _, label in first.columns][-2:] == [
        "MID TERM TEST",
        "MID TERM AVE.",
    ]
    assert [label for _, label in second.columns][-2:] == [
        "EXAM",
        "TOTAL WEIGHTED AVERAGE",
    ]


async def test_the_card_is_deterministic(session, card_world) -> None:
    """§9: "same data renders byte-identically, so regeneration is
    verifiable". Measured, not assumed — WeasyPrint could start stamping a
    timestamp in a future version and this is what would notice."""
    card = await reportcard.build(
        session,
        card_world.admin,
        pupil_id=card_world.pupil.id,
        term_id=card_world.term.id,
        half=TermHalf.FIRST_HALF,
    )

    assert render.render_pdf(card) == render.render_pdf(card)


async def test_the_card_is_under_the_size_budget(session, card_world) -> None:
    """§9: "Under 300 KB per file"."""
    card = await reportcard.build(
        session,
        card_world.admin,
        pupil_id=card_world.pupil.id,
        term_id=card_world.term.id,
        half=TermHalf.SECOND_HALF,
    )

    assert len(render.render_pdf(card)) < cards.SIZE_BUDGET_BYTES


# ---------------------------------------------------------------------------
# What the card prints (§9's structure)
# ---------------------------------------------------------------------------


async def test_the_heading_is_the_cards_own_wording(session, card_world) -> None:
    """The photographs are the specification: "CONTINUOUS ASSESSMENT FOR
    FIRST TERM" over "FIRST HALF TERM"."""
    card = await reportcard.build(
        session,
        card_world.admin,
        pupil_id=card_world.pupil.id,
        term_id=card_world.term.id,
        half=TermHalf.FIRST_HALF,
    )
    text = extract(render.render_pdf(card))

    assert "CONTINUOUS ASSESSMENT FOR FIRST TERM" in text
    assert "FIRST HALF TERM" in text


async def test_english_spans_its_sub_rows(session, card_world) -> None:
    """§9: "English as a spanning group heading over its five sub-rows".

    R7 keeps the heading out of `class_subjects`, so it is drawn from its
    children — and the paper prints it as upright stacked letters, which is
    what the extracted text shows.
    """
    card = await reportcard.build(
        session,
        card_world.admin,
        pupil_id=card_world.pupil.id,
        term_id=card_world.term.id,
        half=TermHalf.FIRST_HALF,
    )

    english = [line for line in card.lines if line.in_group]
    assert len(english) == 2
    assert english[0].group_name == "ENGLISH"
    assert english[0].group_size == 2
    assert english[1].group_name is None, "only the first row opens the span"

    assert "\nE\nN\nG\nL\nI\nS\nH\n" in extract(render.render_pdf(card))


async def test_the_key_comes_from_the_snapshotted_scale(session, card_world) -> None:
    """§9 item 6: "printed from the snapshotted scale, not the current one".

    The school tightens its bands and activates a new scale. A card already
    issued keeps the key it was graded against, or the letters on it stop
    being explicable (§4.5).
    """
    stricter = GradingScale(
        school_id=card_world.klass.school_id,
        name="Stricter scale",
        effective_from=dt.date(2027, 1, 1),
        is_active=True,
    )
    card_world.scale.is_active = False
    session.add(stricter)
    await session.flush()
    session.add(
        GradeBand(
            scale_id=stricter.id,
            letter="Z",
            remark="Nonsense",
            min_score=Decimal(0),
            max_score=Decimal(100),
            sort_order=0,
        )
    )
    await session.commit()

    card = await reportcard.build(
        session,
        card_world.admin,
        pupil_id=card_world.pupil.id,
        term_id=card_world.term.id,
        half=TermHalf.FIRST_HALF,
    )

    letters = [letter for letter, _, _ in card.key]
    assert letters == ["A+", "A", "B+", "B", "C", "D", "E"]
    assert "Z" not in letters


async def test_a_first_term_card_carries_no_cumulative_columns(session, card_world) -> None:
    """§9: "none in first term". Never an empty or zero-filled column."""
    card = await reportcard.build(
        session,
        card_world.admin,
        pupil_id=card_world.pupil.id,
        term_id=card_world.term.id,
        half=TermHalf.SECOND_HALF,
    )

    assert card.cumulative_columns == []
    assert "1ST TERM AVE." not in extract(render.render_pdf(card))


async def test_a_second_term_card_carries_one(session, card_world) -> None:
    """§9: "one in second". The first term's figures exist, so its column
    appears — and the annual average does not, because one term is not a
    year."""
    second_term = Term(
        school_id=card_world.klass.school_id,
        academic_session_id=card_world.term.academic_session_id,
        number=TermNumber.SECOND,
        starts_on=dt.date(2027, 1, 11),
        ends_on=dt.date(2027, 4, 2),
        times_school_opened=60,
    )
    session.add(second_term)
    await session.flush()
    period = AssessmentPeriod(
        school_id=card_world.klass.school_id,
        term_id=second_term.id,
        half=TermHalf.SECOND_HALF,
    )
    session.add(period)
    await session.flush()
    session.add(
        MarksObtainable(
            school_id=card_world.klass.school_id,
            assessment_period_id=period.id,
            class_id=None,
            ca_test_1=CA_MAX,
            exam=TERMINAL_MAX,
        )
    )
    session.add(
        TermReport(
            school_id=card_world.klass.school_id,
            term_id=second_term.id,
            pupil_id=card_world.pupil.id,
            class_id=card_world.klass.id,
            state=PublicationState.PUBLISHED,
        )
    )
    offering = (await session.execute(ClassSubject.__table__.select().limit(1))).one()
    session.add(
        ResultEntry(
            school_id=card_world.klass.school_id,
            assessment_period_id=period.id,
            pupil_id=card_world.pupil.id,
            class_subject_id=offering.id,
            ca_test_1=Decimal(7),
            exam=Decimal(50),
            period_average=Decimal("71.25"),
        )
    )
    await session.commit()

    card = await reportcard.build(
        session,
        card_world.admin,
        pupil_id=card_world.pupil.id,
        term_id=second_term.id,
        half=TermHalf.SECOND_HALF,
    )

    assert card.cumulative_columns == ["1ST TERM AVE."]
    assert "ANNUAL SCORES (AVE.)" not in card.cumulative_columns


# ---------------------------------------------------------------------------
# §12's other criterion: a guessed key is refused
# ---------------------------------------------------------------------------


@pytest.fixture
async def parent_headers(client: AsyncClient, login, card_world) -> dict[str, str]:
    response = await login(card_world.parent.email, TEST_PASSWORD)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_a_parent_gets_a_redirect_to_a_signed_url(client, parent_headers, card_world) -> None:
    """§7: "302 → signed URL, 5 min TTL"."""
    response = await client.get(
        f"{API}/my/children/{card_world.pupil.id}/reports/{card_world.term.id}/pdf",
        params={"half": "first_half"},
        headers=parent_headers,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("/reports/download/")


async def test_the_signed_url_serves_the_pdf(client, parent_headers, card_world) -> None:
    redirect = await client.get(
        f"{API}/my/children/{card_world.pupil.id}/reports/{card_world.term.id}/pdf",
        params={"half": "first_half"},
        headers=parent_headers,
    )

    # No Authorization header: the token is the authority, which is what
    # makes the link usable by a download manager or a print dialog.
    response = await client.get(redirect.headers["location"])

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content[:5] == b"%PDF-"
    assert response.headers["cache-control"] == "private, no-store"


async def test_a_guessed_key_is_refused(client) -> None:
    """§12's criterion. Nothing about the response tells an attacker whether
    the key exists, because without the secret no signature can be made for
    any key."""
    forged = links._encode(b"reports/2026-2027/first-half/SSHMS-2026-001-1.pdf")

    response = await client.get(f"/reports/download/{forged}.9999999999.AAAA")

    assert response.status_code == 403


async def test_a_tampered_expiry_is_refused(client, parent_headers, card_world) -> None:
    """The signature covers the key **and** the expiry, so neither can be
    edited without invalidating the other."""
    redirect = await client.get(
        f"{API}/my/children/{card_world.pupil.id}/reports/{card_world.term.id}/pdf",
        params={"half": "first_half"},
        headers=parent_headers,
    )
    key, _, signature = redirect.headers["location"].rsplit("/", 1)[1].split(".")

    response = await client.get(f"/reports/download/{key}.9999999999.{signature}")

    assert response.status_code == 403


async def test_an_expired_token_is_refused(client, card_world) -> None:
    """§7 puts the TTL at five minutes: long enough to click a link, short
    enough that a URL pasted into a group chat stops working."""
    import time

    token = links.sign("reports/x/y-1.pdf", ttl_seconds=1, now=int(time.time()) - 10)

    response = await client.get(f"/reports/download/{token}")

    assert response.status_code == 403


async def test_a_swapped_key_is_refused(client) -> None:
    """A valid signature for one key must not open another — otherwise a
    parent with one card could read the whole school's."""
    token = links.sign("reports/2026-2027/first-half/SSHMS-2026-001-1.pdf")
    encoded, expiry, signature = token.split(".")
    other = links._encode(b"reports/2026-2027/first-half/SSHMS-2026-002-1.pdf")

    response = await client.get(f"/reports/download/{other}.{expiry}.{signature}")

    assert response.status_code == 403


async def test_a_parent_cannot_ask_for_another_familys_card(
    client, headers_for, card_world, session, password_hash
) -> None:
    other = User(
        school_id=card_world.klass.school_id,
        role=UserRole.PARENT,
        full_name="Another Parent",
        email="other@sshms.test",
        password_hash=password_hash,
        must_change_password=False,
    )
    session.add(other)
    await session.commit()
    headers = await headers_for(other)

    response = await client.get(
        f"{API}/my/children/{card_world.pupil.id}/reports/{card_world.term.id}/pdf",
        headers=headers,
    )

    assert response.status_code == 404


async def test_an_unpublished_card_is_not_served_to_a_parent(
    client, parent_headers, card_world, session
) -> None:
    """R12 again, at the PDF: a withheld card is invisible, not forbidden."""
    report = (
        await session.execute(
            TermReport.__table__.select().where(TermReport.pupil_id == card_world.pupil.id)
        )
    ).first()
    await session.execute(
        TermReport.__table__.update()
        .where(TermReport.id == report.id)
        .values(state=PublicationState.WITHHELD)
    )
    await session.commit()

    response = await client.get(
        f"{API}/my/children/{card_world.pupil.id}/reports/{card_world.term.id}/pdf",
        headers=parent_headers,
    )

    assert response.status_code == 404


async def test_the_card_is_cached_rather_than_rerendered(session, card_world) -> None:
    """§2.1: "Generate on demand, cache the artifact"."""
    first = await cards.card_pdf(
        session,
        card_world.admin,
        pupil_id=card_world.pupil.id,
        term_id=card_world.term.id,
        half=TermHalf.FIRST_HALF,
    )
    second = await cards.card_pdf(
        session,
        card_world.admin,
        pupil_id=card_world.pupil.id,
        term_id=card_world.term.id,
        half=TermHalf.FIRST_HALF,
    )

    assert first.generated is True
    assert second.generated is False
    assert first.key == second.key
    assert first.content == second.content


async def test_the_object_key_is_the_one_section_nine_specifies(session, card_world) -> None:
    """reports/{session}/{term}/{admission_number}-{version}.pdf — and the
    admission number is flattened, because "SSHMS/2026/001" would otherwise
    create directories."""
    stored = await cards.card_pdf(
        session,
        card_world.admin,
        pupil_id=card_world.pupil.id,
        term_id=card_world.term.id,
        half=TermHalf.FIRST_HALF,
    )

    assert stored.key.startswith("reports/2026-2027/")
    assert stored.key.endswith("SSHMS-2026-001-1.pdf")
    assert "first-half" in stored.key
