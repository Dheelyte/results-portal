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

# Both of §5.2's narrative rows. Which *sections* this caller may write for a
# given class is the other half, and `policy.writable_narrative_sections`
# answers it per section — a specialist writing one curriculum area and the
# class teacher writing the rest both arrive here (D15).
NarrativeWriter = Annotated[User, Depends(requires(Action.WRITE_NARRATIVE))]

# §5.2: "Attendance, growth records — own class", and only as class teacher. A
# subject teacher who happens to teach the class does not record its
# attendance; `policy.can_record_attendance_and_growth` enforces that half.
WellbeingRecorder = Annotated[User, Depends(requires(Action.RECORD_ATTENDANCE_AND_GROWTH))]

# Reading the phrase bank, which every member of staff does and no parent does
# (§4.6, §8.2, docs/DECISIONS.md D55). Editing it stays `AssessmentConfigAdmin`.
CommentBankReader = Annotated[User, Depends(requires(Action.USE_COMMENT_BANK))]

# §5.2's "Submit class for review — own class". The capability covers reading
# the progress page as well as pressing the button: §8.3 shows every subject's
# state, which a subject teacher needs in order to see that theirs is the one
# holding the class up. *Who may press it* is the narrower question, and
# `policy.can_submit_class` answers it — the page reports the answer as
# `may_submit` rather than hiding the page.
ClassSubmitter = Annotated[User, Depends(requires(Action.SUBMIT_CLASS))]
