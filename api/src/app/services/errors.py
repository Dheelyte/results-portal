"""Domain errors raised by the service layer.

Services own the rules, so they own the refusals. A router does not decide
what a broken rule means — it is mapped to a status code once, by the handlers
registered in `main.py`.

Every message here reaches a user, so every message obeys the standing rule in
CLAUDE.md: no score, no comment, no token, no hash, and no pupil's identity.
Note what that forbids in practice — "pupil SSHMS/2026/004 already exists"
names a child, so the conflicts below describe the *field* and leave the value
to the admin who just typed it.
"""


class ServiceError(Exception):
    """Base class. The message is safe to return verbatim to a client."""

    status_code = 422

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(ServiceError):
    """The row does not exist, or is outside the caller's scope.

    Those two cases are deliberately the same error. §5.2 requires a subject
    teacher reaching another class's data to get a 404, not a 403: a 403
    confirms the row exists, which is itself a leak.
    """

    status_code = 404


class Conflict(ServiceError):
    """The request collides with existing data, or with the current state."""

    status_code = 409


class Invalid(ServiceError):
    """The request is coherent as JSON but breaks a business rule."""

    status_code = 422


class RowErrors(ServiceError):
    """A bulk write where individual rows broke a rule.

    The score grid writes a whole class at once and applies all or none (§7).
    A single message would tell the teacher that *something* is out of range
    without saying which cell, so this carries the refusals keyed by pupil, in
    the shape the grid needs to paint them red (§8.1).

    The keys are pupil ids, which the caller already holds — it just sent
    them. No name and no score appears in the payload.
    """

    status_code = 422

    def __init__(self, message: str, errors: dict[str, dict[str, str]]) -> None:
        super().__init__(message)
        self.errors = errors


class Blocked(ServiceError):
    """A request refused because prerequisites are outstanding.

    R10's submission gate is the case this exists for, and §6 is explicit
    about why a plain message will not do: "Return a structured list of what
    is missing, by subject, by pupil and by section. 'Cannot submit' with no
    explanation generates support calls every term."

    `outstanding` carries that list in the shape the screen renders. It names
    subjects, sections and pupils, because a class teacher being told what to
    go and do needs to know which child — this is the one place a pupil's name
    legitimately travels in a refusal, and it travels to the teacher who
    already has the register in front of them.
    """

    status_code = 422

    def __init__(self, message: str, outstanding: list[dict[str, object]]) -> None:
        super().__init__(message)
        self.outstanding = outstanding


class NotPermitted(ServiceError):
    """The caller's role does not permit this action at all.

    Distinct from `NotFound`: this one is about capability, where there is
    nothing to hide — an admin-only endpoint is admin-only whether or not any
    rows exist behind it.
    """

    status_code = 403
