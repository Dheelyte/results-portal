"""Walking the mounted routes, for the authorization guards.

Shared by the setup and entry authorization suites. Both need to know which
routes exist and whether each one declares a capability, and the coverage test
needs the union of their tables — a route covered by neither is the hole these
guards exist to find.
"""

import uuid

from fastapi.routing import APIRoute
from httpx import AsyncClient

from app.config import settings
from app.main import app

# A syntactically valid id that matches nothing. Every table below uses it, so
# a request reaches the handler and is refused on authorization rather than
# bouncing off path validation.
ANY_ID = str(uuid.uuid4())

# (method, path, body) — the shape both authorization tables use.
Case = tuple[str, str, dict | None]


def capability_gated(route: APIRoute) -> bool:
    """Whether a capability dependency guards this route.

    Looks for the closure `authz.dependencies.requires` returns, anywhere in
    the route's dependency tree.
    """
    seen = [route.dependant]
    while seen:
        dependant = seen.pop()
        call_target = getattr(dependant, "call", None)
        qualname = getattr(call_target, "__qualname__", "")
        if qualname.startswith("requires.") and qualname.endswith("guard"):
            return True
        seen.extend(dependant.dependencies)
    return False


def mounted_routes(routes: object = None, prefix: str = "") -> list[tuple[str, APIRoute]]:
    """Every API route with its full path.

    `app.routes` holds `_IncludedRouter` wrappers rather than the routes
    themselves in this FastAPI version, and the mount prefix lives on the
    wrapper — so the path has to be reassembled while descending.
    """
    found: list[tuple[str, APIRoute]] = []
    for item in app.routes if routes is None else routes:
        if isinstance(item, APIRoute):
            found.append((prefix + item.path, item))
        elif hasattr(item, "original_router"):
            context = getattr(item, "include_context", None)
            found.extend(
                mounted_routes(
                    item.original_router.routes,
                    prefix + (getattr(context, "prefix", "") or ""),
                )
            )
    return found


def guarded_routes() -> list[tuple[str, APIRoute]]:
    """Every /api/v1 route that is not an authentication route.

    The auth routes are deliberately open — a login endpoint that required
    being logged in would be a closed system.
    """
    return [
        (path, route)
        for path, route in mounted_routes()
        if path.startswith(settings.api_v1_prefix)
        and not path.startswith(f"{settings.api_v1_prefix}/auth")
    ]


def normalise(path: str) -> str:
    """A path with every id — placeholder or literal — reduced to `{id}`."""
    parts = path.removeprefix(settings.api_v1_prefix).lstrip("/").split("?")[0].split("/")
    return "/" + "/".join(
        "{id}" if part.startswith("{") or part == ANY_ID else part for part in parts
    )


def ids_for(case: Case) -> str:
    return f"{case[0]} {case[1].split('?')[0]}"


async def call(client: AsyncClient, case: Case, headers: dict[str, str] | None):
    method, path, body = case
    return await client.request(
        method, f"{settings.api_v1_prefix}{path}", headers=headers, json=body
    )
