"""Small helpers shared by the service layer.

Nothing here is a business rule. These exist so the rules in the modules
beside them are not buried in lookup boilerplate.
"""

import contextlib
from collections.abc import AsyncIterator, Sequence
from typing import Any, TypeVar

from sqlalchemy import Select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.errors import Conflict, NotFound

T = TypeVar("T")


async def one_or_404(db: AsyncSession, stmt: Select, what: str) -> Any:
    """The single row the statement selects, or `NotFound`.

    The statement is expected to come from `authz/scope.py`, already filtered.
    That is what makes one error correct for both "no such row" and "not
    yours": a scoped query cannot see another school's row, so the two cases
    are indistinguishable by construction rather than by a router remembering
    to conflate them (§5.2).
    """
    row = await db.scalar(stmt)
    if row is None:
        raise NotFound(f"No such {what}.")
    return row


async def all_of(db: AsyncSession, stmt: Select) -> Sequence[Any]:
    return (await db.execute(stmt)).scalars().all()


async def rows_of(db: AsyncSession, stmt: Select) -> Sequence[Any]:
    """Every row of a multi-column select, as tuples.

    Separate from `all_of` rather than a flag on it: `scalars()` silently
    returns only the first column, so a select that grew a second one would
    keep working and start lying.
    """
    return (await db.execute(stmt)).all()


@contextlib.asynccontextmanager
async def integrity_guard(db: AsyncSession, message: str) -> AsyncIterator[None]:
    """Turn a constraint violation into a `Conflict` with a readable message.

    The services below check for collisions before writing, because a checked
    error can say something useful. This is the backstop for the race between
    that check and the insert — two admins adding "Primary 4" at once — where
    the only honest answer is that somebody got there first.

    The session is rolled back before raising. A Postgres transaction is
    aborted by a failed statement, so without this every later query on the
    same session would fail with `InFailedSQLTransaction` and the real cause
    would be two frames further away.
    """
    try:
        yield
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict(message) from exc
