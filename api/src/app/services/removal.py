"""Deleting safely (docs/DECISIONS.md D121).

One rule for everything an admin can create: **delete only what nothing
depends on yet.** A class made by mistake a minute ago goes; a class with a
term of scores behind it does not, because last term's cards still have to
say what they said. For those, the answer is to retire or deactivate, which
every such record already supports.

The database enforces this too. Its foreign keys refuse a delete that would
orphan a row, and `integrity_guard` turns that refusal into a `Conflict`. The
checks here come first because they can say *what* is in the way, in counts:
"it has 312 scores". The foreign key can only say that something is.

Counts and nouns only, never names. The standing rule in CLAUDE.md keeps a
pupil's identity out of every error message.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.errors import Conflict


@dataclass(frozen=True)
class Dependent:
    """One kind of row that would stop a delete.

    `count` is a `select(func.count())…` statement that counts them.
    """

    singular: str
    plural: str
    count: Select

    def describe(self, n: int) -> str:
        return f"{n} {self.singular if n == 1 else self.plural}"


async def refuse_if_in_use(
    db: AsyncSession,
    *,
    thing: str,
    dependents: Sequence[Dependent],
    instead: str | None = None,
) -> None:
    """Raise a `Conflict` naming what depends on `thing`, if anything does.

    `thing` begins the sentence ("This class"). `instead` is the advice to
    follow it with, such as "Deactivate it instead.".
    """
    found: list[str] = []
    for dependent in dependents:
        n = await db.scalar(dependent.count) or 0
        if n:
            found.append(dependent.describe(n))
    if not found:
        return

    listed = found[0] if len(found) == 1 else f"{', '.join(found[:-1])} and {found[-1]}"
    message = f"{thing} can't be deleted: it has {listed}."
    if instead:
        message = f"{message} {instead}"
    raise Conflict(message)
