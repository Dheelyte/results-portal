"""Capability gates as FastAPI dependencies (ARCHITECTURE.md §5.2).

`policy.can` answers "may this role do this at all". This turns that answer
into a dependency, so a route declares the capability it needs in its
signature and cannot be mounted without one.

Two layers, both required, and they answer different questions:

- **Capability** — this module. May an admin manage subjects?
- **Visibility** — `authz/scope.py`. Which rows may *this* admin see?

The capability gate alone would let an admin of one school edit another's
subjects. The scope filter alone would let a teacher edit their own class's
subject list. Neither is sufficient; every setup endpoint carries both.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.auth.dependencies import ActiveUser
from app.authz.policy import Action, can
from app.models import User


def requires(action: Action) -> Callable[[User], Awaitable[User]]:
    """A dependency admitting only callers whose role permits `action`.

    Depends on `ActiveUser`, so a caller who still owes a password change is
    stopped before the capability question is even asked (§5.1).
    """

    async def guard(user: ActiveUser) -> User:
        if not can(user, action):
            # Names the action, not the data. An admin-only endpoint is
            # admin-only whether or not anything exists behind it, so there is
            # nothing here to conceal.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your role does not permit this action.",
            )
        return user

    return guard


# The three admin capabilities of §5.2's first three rows. Named aliases
# rather than inline `Depends(requires(...))`, so a route's signature reads as
# the matrix row it implements.
AcademicStructureAdmin = Annotated[User, Depends(requires(Action.MANAGE_ACADEMIC_STRUCTURE))]
UserAdmin = Annotated[User, Depends(requires(Action.MANAGE_USERS))]
AssessmentConfigAdmin = Annotated[User, Depends(requires(Action.MANAGE_ASSESSMENT_CONFIG))]

# §5.2's teaching rows. The capability is the role half of the question — a
# head teacher and an admin are refused here, because neither enters scores.
# *Which* class-subjects a teacher may write to is the other half, and
# `authz/scope.py` answers it: a sheet outside their assignments is a 404,
# never a 403, because a 403 would confirm it exists (CLAUDE.md rule 4).
ScoreEntrant = Annotated[User, Depends(requires(Action.ENTER_SCORES))]
