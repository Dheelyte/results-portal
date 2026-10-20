"""R11: position is never computed.

> "Never computed. `position_text` is free text the head teacher may
> optionally enter. There is no ranking query anywhere in this codebase."

The school does not rank pupils (CLAUDE.md rule 5). That is a product
decision, not a technical one, and the kind of thing a well-meaning future
change reintroduces without noticing — so it is asserted rather than left to
convention.
"""

import pathlib
import re

from app.models import TermReport

SOURCE_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src"

# SQL window functions that produce a rank, plus the obvious Python spellings.
RANKING_CONSTRUCTS = re.compile(
    r"\b(dense_rank|percent_rank|row_number\s*\(|rank\s*\(\s*\)|\.rank\b)",
    re.IGNORECASE,
)

# This file names them in order to forbid them.
EXEMPT = {"test_no_ranking.py"}


def test_no_ranking_construct_appears_in_the_source() -> None:
    offenders = []
    for path in SOURCE_ROOT.rglob("*.py"):
        if path.name in EXEMPT:
            continue
        match = RANKING_CONSTRUCTS.search(path.read_text(encoding="utf-8"))
        if match:
            offenders.append(f"{path.relative_to(SOURCE_ROOT)}: {match.group(0)!r}")

    assert offenders == [], "ranking constructs found:\n  " + "\n  ".join(offenders)


def test_no_order_by_on_a_score_column() -> None:
    """Sorting pupils by a score is ranking by another name."""
    suspicious = re.compile(
        r"order_by\([^)]*\b(period_average|overall_percentage|ca_test_total)\b", re.IGNORECASE
    )

    offenders = [
        str(path.relative_to(SOURCE_ROOT))
        for path in SOURCE_ROOT.rglob("*.py")
        if suspicious.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == [], f"pupils sorted by score in: {offenders}"


def test_position_text_is_nullable_free_text() -> None:
    """N4 suggests "Position (In grades)" is a band rather than a rank. Either
    way it is text a head teacher types, never a value the system derives."""
    column = TermReport.__table__.columns["position_text"]

    assert column.nullable
    assert column.computed is None
    assert column.server_default is None
    assert column.type.python_type is str


def test_no_position_column_is_numeric() -> None:
    """A numeric position would be a rank, whatever it were called."""
    for name, column in TermReport.__table__.columns.items():
        if "position" in name:
            assert column.type.python_type is str, f"{name} is not text"
