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

# The one function permitted to write them, and the one command permitted to
# read-and-skip them.
#
# `review._snapshot_grades` is approval. Milestone 10's post-publication edit
# (R13) will need a second entry here, and adding it should be a deliberate
# act with this comment in front of whoever does it — not a silent extra
# assignment somewhere in a router.
PERMITTED = {
    ("services/review.py", "_snapshot_grades"),
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


def test_the_permitted_writer_really_does_write_it() -> None:
    """Otherwise this scan would pass by watching the wrong function — and a
    rename would turn the guard off without failing anything."""
    writes = snapshot_writes(SOURCE_ROOT / "services" / "review.py")
    functions = {function for _, function in writes}

    assert "_snapshot_grades" in functions
    assert SNAPSHOT_FIELDS <= {field for field, _ in writes}


def test_the_recompute_command_skips_snapshotted_rows() -> None:
    """`python -m app.recompute_averages` rewrites `period_average`, which a
    grade was resolved from. It must leave an approved row alone, or the
    figure printed beside a frozen letter would stop matching it."""
    source = (SOURCE_ROOT / "recompute_averages.py").read_text(encoding="utf-8")

    assert "grade_letter is not None" in source
    assert "skipped_approved" in source
