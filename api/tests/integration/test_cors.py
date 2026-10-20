"""Cross-origin access control.

The API lives on its own hostname (docs/DECISIONS.md, D13), so every browser
call from the web app is cross-origin. These assertions are the difference
between "the portal works" and "the portal works until someone opens it".
"""

from httpx import AsyncClient

from app.config import settings

LOGIN = "/api/v1/auth/login"
ALLOWED = settings.public_web_origin
UNLISTED = "https://evil.example"


async def test_preflight_from_the_web_app_is_allowed(client: AsyncClient) -> None:
    response = await client.options(
        LOGIN,
        headers={
            "Origin": ALLOWED,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert response.headers["access-control-allow-credentials"] == "true"


async def test_preflight_from_an_unlisted_origin_gets_no_grant(client: AsyncClient) -> None:
    """The absent Allow-Origin header is what stops the browser, not the
    status code."""
    response = await client.options(
        LOGIN,
        headers={"Origin": UNLISTED, "Access-Control-Request-Method": "POST"},
    )

    assert "access-control-allow-origin" not in response.headers


async def test_a_simple_request_from_an_unlisted_origin_gets_no_grant(
    client: AsyncClient, make_user, login
) -> None:
    """The request itself still executes — CORS is a browser control, not a
    server-side authorisation. What matters is that the response is not
    readable cross-origin."""
    user = await make_user()

    response = await client.post(
        LOGIN,
        json={"identifier": user.email, "password": "irrelevant"},
        headers={"Origin": UNLISTED},
    )

    assert "access-control-allow-origin" not in response.headers


async def test_the_allowed_origin_is_never_a_wildcard() -> None:
    """A wildcard origin and allow_credentials are incompatible by
    specification, and the refresh cookie travels with credentials."""
    assert settings.public_web_origin != "*"
    assert settings.public_web_origin.startswith(("http://", "https://"))


async def test_credentialed_responses_name_one_exact_origin(client: AsyncClient, make_user) -> None:
    user = await make_user()

    response = await client.post(
        LOGIN,
        json={"identifier": user.email, "password": "correct-horse-battery"},
        headers={"Origin": ALLOWED},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert response.headers["access-control-allow-origin"] != "*"
