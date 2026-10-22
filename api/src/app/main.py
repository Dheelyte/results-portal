"""FastAPI application factory.

Mounts the /api/v1 surface of ARCHITECTURE.md §7 and maps the service layer's
domain errors onto status codes — once, here, so no router repeats a
try/except and no two routers disagree about what a broken rule means.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.config import settings
from app.db import engine
from app.logging import configure_logging
from app.routers import academic, assessment, auth, health, people, setup, structure
from app.services.errors import ServiceError

configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("api starting", extra={"env": settings.app_env, "version": __version__})
    yield
    await engine.dispose()
    logger.info("api stopped")


async def _service_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render a service-layer refusal as its status code and message.

    The service layer owns the rules, so it owns the refusals. Mapping them
    here means a router never decides what a broken rule means, and a rule
    reached from two endpoints cannot answer differently.

    Every `ServiceError` message is written to be read by the person who
    caused it — the admin who just typed something — and obeys the standing
    rule in CLAUDE.md: no score, no comment, no token, no hash, no pupil's
    identity. `services/errors.py` is where that is documented and kept.
    """
    assert isinstance(exc, ServiceError)  # registered only for this type
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


def create_app() -> FastAPI:
    # The OpenAPI surface is closed in production.  Caddyfile.prod also declines
    # to route it, so it is shut at both layers (docs/DECISIONS.md, D8).
    docs_enabled = not settings.is_production

    app = FastAPI(
        title="School Results Portal API",
        description=(
            "Results portal for Self-Starters House Montessori School. Built by HSD Technologies."
        ),
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    # The API is on its own hostname (docs/DECISIONS.md, D13), so browser
    # calls from the web app are cross-origin and need this.
    #
    # One explicit origin, never "*": allow_credentials and a wildcard origin
    # are incompatible by specification, and the refresh cookie travels with
    # credentials. Browsers reject the combination rather than warn.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.public_web_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )

    app.add_exception_handler(ServiceError, _service_error_handler)

    app.include_router(health.router)
    app.include_router(auth.router, prefix=settings.api_v1_prefix)

    # The admin setup surface of §7. Each router declares the §5.2 capability
    # it needs in its route signatures; none of them is open to a teacher or a
    # parent.
    for admin_router in (academic, structure, people, assessment, setup):
        app.include_router(admin_router.router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
