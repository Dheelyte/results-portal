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


class NotPermitted(ServiceError):
    """The caller's role does not permit this action at all.

    Distinct from `NotFound`: this one is about capability, where there is
    nothing to hide — an admin-only endpoint is admin-only whether or not any
    rows exist behind it.
    """

    status_code = 403
