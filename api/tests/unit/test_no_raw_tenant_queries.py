"""§5.2: "No router composes a raw `select(Model)` against tenant data."

A convention nobody checks is a convention that lasts until the first busy
afternoon. This asserts it, because the failure mode — one router that forgets
`school_id` — is exactly how a school portal leaks another family's results.

The rule is about *routers*. Services and the scope layer compose raw queries
by design; the scope layer is where the filter lives.
"""

import ast
import pathlib

import pytest

SOURCE_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "app"
ROUTERS = SOURCE_ROOT / "routers"

# Models carrying tenant data. A router must reach these through
# app.authz.scope, never through a select() of its own.
TENANT_MODELS = frozenset(
    {
        "AcademicSession",
        "AssessmentPeriod",
        "AttendanceRecord",
        "AuditLog",
        "Class",
        "ClassSubject",
        "ClassTeacher",
        "ClassTermStatus",
        "CommentBank",
        "Enrollment",
        "GradeBand",
        "GradingScale",
        "GrowthRecord",
        "GuardianPupil",
        "House",
        "MarksObtainable",
        "NarrativeEntry",
        "NarrativeSection",
        "NarrativeSectionAssignment",
        "Pupil",
        "ResultEntry",
        "Subject",
        "TeachingAssignment",
        "Term",
        "TermReport",
    }
)


def router_files() -> list[pathlib.Path]:
    return sorted(path for path in ROUTERS.rglob("*.py") if path.name != "__init__.py")


def selected_models(tree: ast.AST) -> set[str]:
    """Every model name passed to a bare select(...) call."""
    found: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name != "select":
            continue

        for argument in node.args:
            if isinstance(argument, ast.Name):
                found.add(argument.id)
            elif isinstance(argument, ast.Attribute):
                # select(Pupil.id)
                value = argument.value
                if isinstance(value, ast.Name):
                    found.add(value.id)

    return found


def test_there_is_at_least_one_router_to_check() -> None:
    """Guards against the scan silently passing because it found nothing."""
    assert router_files()


@pytest.mark.parametrize("path", router_files(), ids=lambda p: p.name)
def test_no_router_selects_tenant_data_directly(path: pathlib.Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    offenders = selected_models(tree) & TENANT_MODELS

    assert not offenders, (
        f"{path.name} builds a raw select() against {sorted(offenders)}. "
        "Build the query from app.authz.scope instead (ARCHITECTURE.md §5.2)."
    )


def test_the_tenant_model_list_is_complete() -> None:
    """If a model is added without being listed here, the scan above would
    quietly stop covering it."""
    from app.models import Base

    # Tables that are not tenant-scoped, and why.
    exempt = {
        "schools",  # the tenant itself
        "users",  # scoped by the auth layer, not by a row filter
        "refresh_tokens",  # reachable only through the presenting cookie
    }

    tenant_tables = set(Base.metadata.tables) - exempt
    covered = set()

    for mapper in Base.registry.mappers:
        if mapper.class_.__name__ in TENANT_MODELS:
            covered.add(mapper.local_table.name)

    missing = tenant_tables - covered
    assert not missing, f"tenant tables not covered by the router scan: {sorted(missing)}"
