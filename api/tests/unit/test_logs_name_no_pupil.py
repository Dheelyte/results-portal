"""No log line may name a pupil.

CLAUDE.md: "Never log or expose scores, comments, tokens, password hashes, or
a pupil's identity in logs or error messages."

A name is the obvious breach, but so is a `pupil_id`: a support engineer
reading the log has the database beside them, and the id is a join away from
the child. The ids that *are* safe to log identify a row rather than a person
— `report_id`, `class_id`, `entry_id` — and those are what the services use.

This is a static scan rather than a caplog assertion, because the breach that
matters is the log line nobody thought to test: an `extra=` dictionary grown
one field at a time until it carries a child.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

SOURCE_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "app"

#: Keys that point at a child rather than at a row.
FORBIDDEN_KEYS = frozenset(
    {
        "pupil",
        "pupil_id",
        "pupil_name",
        "first_name",
        "middle_name",
        "last_name",
        "admission_number",
        "guardian",
        "guardian_id",
        "guardian_user_id",
        "parent_id",
        # Not a pupil, but the same sentence of CLAUDE.md.
        "score",
        "scores",
        "comment",
        "remark",
        "narrative",
        "token",
        "password",
        "password_hash",
    }
)

LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical"})


def _log_calls() -> list[tuple[pathlib.Path, ast.Call]]:
    found: list[tuple[pathlib.Path, ast.Call]] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr not in LOG_METHODS:
                continue
            # `logger.info(...)`, `log.warning(...)`, `self.logger.error(...)`.
            target = func.value
            name = getattr(target, "id", None) or getattr(target, "attr", None)
            if name in {"logger", "log", "logging"}:
                found.append((path, node))
    return found


LOG_CALLS = _log_calls()


def test_the_scan_finds_the_log_calls_it_is_meant_to_police() -> None:
    """A floor, so an import rename cannot quietly empty the scan."""
    assert len(LOG_CALLS) >= 5


@pytest.mark.parametrize(
    "case",
    LOG_CALLS,
    ids=lambda case: f"{case[0].relative_to(SOURCE_ROOT)}:{case[1].lineno}",
)
def test_logs_name_no_pupil(case: tuple[pathlib.Path, ast.Call]) -> None:
    path, call = case
    where = f"{path.relative_to(SOURCE_ROOT)}:{call.lineno}"

    keys: list[str] = []
    for keyword in call.keywords:
        if keyword.arg != "extra":
            continue
        if isinstance(keyword.value, ast.Dict):
            keys += [k.value for k in keyword.value.keys if isinstance(k, ast.Constant)]

    offending = sorted(set(keys) & FORBIDDEN_KEYS)
    assert not offending, (
        f"{where} logs {offending}. CLAUDE.md forbids a pupil's identity, a "
        "score, a comment or a token in a log line. Log the row's own id "
        "instead — report_id, class_id, entry_id."
    )
