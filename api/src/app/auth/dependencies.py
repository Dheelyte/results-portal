"""FastAPI dependencies for the authenticated caller.

Authorization *scopes* — which rows a user may touch — are milestone 4 and live
in `authz/scope.py` (CLAUDE.md rule 4). This module only answers "who is
calling", which is a prerequisite for that.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import TokenError, decode_access_token
from app.db import get_session
from app.models import User

DbSession = Annotated[AsyncSession, Depends(get_session)]

# auto_error=False so a missing header produces our 401 with a WWW-Authenticate
# challenge rather than FastAPI's bare 403.
_bearer = HTTPBearer(auto_error=False)

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """The authenticated user, or 401.

    The token is verified first and the row loaded second, so that a revoked or
    deactivated account cannot keep working until its access token expires.
    """
    if credentials is None:
        raise _UNAUTHENTICATED

    try:
        claims = decode_access_token(credentials.credentials)
    except TokenError:
        raise _UNAUTHENTICATED from None

    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise _UNAUTHENTICATED

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_active_user(user: CurrentUser) -> User:
    """The authenticated user, refusing one who still owes a password change.

    §5.1 gives new accounts a temporary password and `must_change_password`.
    This is the gate that makes it mean something. `/auth/change-password`
    depends on `CurrentUser` instead, or there would be no way out.

    409 rather than 403: nothing is forbidden, the account is in a state the
    user can resolve themselves.
    """
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You must change your password before continuing.",
        )
    return user


ActiveUser = Annotated[User, Depends(get_active_user)]


def client_ip(request: Request) -> str | None:
    """The caller's IP, for the audit log.

    Caddy sits in front, so request.client is the proxy. X-Forwarded-For is
    trusted only because nothing but our own Caddy can reach the API — in
    production the container publishes no port (docs/DECISIONS.md, D8).
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


@dataclass(frozen=True)
class RequestContext:
    """Who and where, for the audit log (§4.9).

    Bundled into one dependency because every audited endpoint needs both and
    threading two keyword arguments through each signature is how one of them
    ends up missing.
    """

    ip_address: str | None
    user_agent: str | None


def request_context(request: Request) -> RequestContext:
    return RequestContext(
        ip_address=client_ip(request),
        user_agent=(request.headers.get("user-agent") or None),
    )


Context = Annotated[RequestContext, Depends(request_context)]
