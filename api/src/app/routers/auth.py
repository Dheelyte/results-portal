"""Authentication endpoints (ARCHITECTURE.md §7).

Translation only: HTTP in, service call, HTTP out. Every rule is in
`services/auth.py` (CLAUDE.md rule 2).
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status

from app.auth.dependencies import CurrentUser, DbSession, client_ip
from app.config import settings
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    MessageResponse,
    TokenResponse,
    UserRead,
)
from app.services import auth as auth_service
from app.services.auth import AccountLocked, AuthError, InvalidCredentials, IssuedTokens

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"

# Scoped to the auth routes: the cookie is only ever presented to /refresh and
# /logout, so no other endpoint can be induced to act on it.
REFRESH_COOKIE_PATH = f"{settings.api_v1_prefix}/auth"


def _set_refresh_cookie(response: Response, tokens: IssuedTokens) -> None:
    """Attach the refresh token as an httpOnly cookie (§5.1).

    Host-only — no `domain` — so it stays on the API's own hostname rather than
    being sent to every sibling subdomain (docs/DECISIONS.md, D13).

    SameSite=Lax is sufficient because the web app and the API share a
    registrable domain, which makes their requests same-site. That is the
    constraint D13 records; break it and this must become SameSite=None with
    explicit CSRF tokens.
    """
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=tokens.refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def _token_response(tokens: IssuedTokens) -> TokenResponse:
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=settings.access_token_minutes * 60,
        user=UserRead.model_validate(tokens.user),
    )


@router.post("/login", response_model=TokenResponse, summary="Sign in")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: DbSession,
) -> TokenResponse:
    """Sign in with an email address or a phone number (§5.1, A7)."""
    try:
        tokens = await auth_service.authenticate(
            session,
            identifier=payload.identifier,
            password=payload.password,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except AccountLocked as exc:
        # 423 Locked says precisely what happened without revealing whether
        # the password was right.
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail=str(exc)) from None
    except InvalidCredentials as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from None

    _set_refresh_cookie(response, tokens)
    return _token_response(tokens)


@router.post("/refresh", response_model=TokenResponse, summary="Rotate the session")
async def refresh(
    request: Request,
    response: Response,
    session: DbSession,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> TokenResponse:
    """Exchange the refresh cookie for a new token pair.

    Presenting an already-used token revokes the whole family and returns 401,
    exactly as an unknown token does — an attacker learns nothing from the
    difference.
    """
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")

    try:
        tokens = await auth_service.refresh(
            session,
            refresh_token=refresh_token,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except InvalidCredentials:
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired. Please sign in."
        ) from None

    _set_refresh_cookie(response, tokens)
    return _token_response(tokens)


@router.post("/logout", response_model=MessageResponse, summary="Sign out")
async def logout(
    request: Request,
    response: Response,
    session: DbSession,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> MessageResponse:
    """End the session, revoking every token descended from that login.

    Always succeeds. A logout that finds nothing to revoke has still achieved
    what the caller asked for.
    """
    await auth_service.logout(
        session,
        refresh_token=refresh_token,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    _clear_refresh_cookie(response)
    return MessageResponse(detail="Signed out.")


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change your own password",
)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    session: DbSession,
    user: CurrentUser,
) -> MessageResponse:
    """Change the signed-in user's password.

    Depends on `CurrentUser`, not `ActiveUser`: a user who must change their
    password has to be able to reach this endpoint, and only this one.

    Every existing session is revoked, so the caller signs in again.
    """
    try:
        await auth_service.change_password(
            session,
            user=user,
            current_password=payload.current_password,
            new_password=payload.new_password,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except InvalidCredentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect."
        ) from None
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from None

    _clear_refresh_cookie(response)
    return MessageResponse(detail="Password changed. Please sign in again.")


@router.get("/me", response_model=UserRead, summary="The signed-in user")
async def me(user: CurrentUser) -> UserRead:
    """Who the bearer token belongs to.

    Not in §7's list, but the client needs it after a page reload to restore
    the session from the refresh cookie without a second round trip.
    """
    return UserRead.model_validate(user)
