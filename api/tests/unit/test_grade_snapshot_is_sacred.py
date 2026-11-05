"""CLAUDE.md rule 6, as a scan: "Never recompute a grade on a published
result. Grades are snapshotted at approval."

§4.5 explains what is at stake:

    If the school later changes a boundary, last term's printed cards must
    still say what was printed. Recomputing would silently rewrite history,
    and a parent holding a printed card would find it disagrees with the
    portal.

`tests/integration/test_review.py` proves the rule holds today — it moves a
band after approval and checks the card does not follow. This proves the rule
*cannot be broken by accident*: exactly one function in the codebase assigns
`grade_letter`, and if a second one appears, this fails the day it lands.

The same discipline as `test_no_raw_tenant_queries.py`, and for the same
reason: a convention nobody checks is a convention that lasts until the first
busy afternoon.
"""

import ast
import pathlib

import pytest

SOURCE_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "app"

# The snapshot's own fields. `grading_scale_id` is here too: a row whose scale
# was overwritten could no longer explain the letter beside it.
SNAPSHOT_FIELDS = frozenset({"grade_letter", "grading_scale_id"})

# The only functions permitted to write them.
#
# `review._snapshot_grades` is approval: §4.5's one moment, where a grade is
# decided from the active scale.
#
# `publication._regrade_against_snapshot` is R13's post-publication edit. It
# is permitted for a specific reason, and the reason is the condition of its
# being permitted: it re-resolves against **the scale already on the row**,
# never against today's active scale. The rest of that card was graded against
# the snapshot, so a corrected row graded any other way would leave one line
# of a printed card unexplainable. A test below pins that behaviour.
#
# Adding a third entry should be a deliberate act with this comment in front
# of whoever does it — not a silent extra assignment in a router.
PERMITTED = {
    ("services/review.py", "_snapshot_grades"),
    ("services/publication.py", "_regrade_against_snapshot"),
}


def source_files() -> list[pathlib.Path]:
    return sorted(
        path
        for path in SOURCE_ROOT.rglob("*.py")
        # Alembic revisions and the models themselves declare the columns;
        # they do not assign them at runtime.
        if "alembic" not in path.parts and path.parent.name != "models"
    )


def enclosing_function(tree: ast.AST, target: ast.AST) -> str | None:
    """The name of the function a node sits inside, or None at module level."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for child in ast.walk(node):
                if child is target:
                    return node.name
    return None


def snapshot_writes(path: pathlib.Path) -> set[tuple[str, str]]:
    """Every `<something>.grade_letter = ...` in the file, with its function."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[tuple[str, str]] = set()

    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            targets = [node.target]

        for target in targets:
            if isinstance(target, ast.Attribute) and target.attr in SNAPSHOT_FIELDS:
                found.add((target.attr, enclosing_function(tree, node) or "<module>"))

        # `setattr(row, "grade_letter", ...)`, which the scan above would miss.
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "setattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in SNAPSHOT_FIELDS
        ):
            found.add((node.args[1].value, enclosing_function(tree, node) or "<module>"))

    return found


def test_there_are_source_files_to_check() -> None:
    """Guards against the scan passing because it found nothing."""
    assert len(source_files()) > 20


@pytest.mark.parametrize("path", source_files(), ids=lambda p: str(p.name))
def test_only_approval_writes_a_grade(path: pathlib.Path) -> None:
    relative = path.relative_to(SOURCE_ROOT).as_posix()

    for field, function in sorted(snapshot_writes(path)):
        assert (relative, function) in PERMITTED, (
            f"{relative}::{function} assigns {field}. A grade is decided once, at "
            "approval, and never recomputed (CLAUDE.md rule 6, ARCHITECTURE.md §4.5). "
            "If this is deliberate, add it to PERMITTED in this file and say why."
        )


def test_the_permitted_writers_really_do_write_it() -> None:
    """Otherwise this scan would pass by watching the wrong function — and a
    rename would turn the guard off without failing anything."""
    approval = snapshot_writes(SOURCE_ROOT / "services" / "review.py")
    assert "_snapshot_grades" in {function for _, function in approval}
    assert SNAPSHOT_FIELDS <= {field for field, _ in approval}

    correction = snapshot_writes(SOURCE_ROOT / "services" / "publication.py")
    assert "_regrade_against_snapshot" in {function for _, function in correction}


def test_the_post_publication_edit_regrades_against_the_row_not_the_present() -> None:
    """R13's permission is conditional on this (§4.5, CLAUDE.md rule 6).

    `publication._regrade_against_snapshot` may write a grade **because** it
    reads the scale from `entry.grading_scale_id`. If it ever called
    `active_scale` instead, a correction made after the school changed a band
    would grade one line of a printed card differently from the rest of it.
    """
    source = (SOURCE_ROOT / "services" / "publication.py").read_text(encoding="utf-8")
    start = source.index("async def _regrade_against_snapshot")
    body = source[start:]

    assert "entry.grading_scale_id" in body
    assert "active_scale" not in body


def test_the_recompute_command_skips_snapshotted_rows() -> None:
    """`python -m app.recompute_averages` rewrites `period_average`, which a
    grade was resolved from. It must leave an approved row alone, or the
    figure printed beside a frozen letter would stop matching it."""
    source = (SOURCE_ROOT / "recompute_averages.py").read_text(encoding="utf-8")

    assert "grade_letter is not None" in source
    assert "skipped_approved" in source
