"""FastAPI application factory.

Milestone 1 mounts only the health routers.  Milestone 2 adds the /api/v1
surface of ARCHITECTURE.md §7.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.config import settings
from app.db import engine
from app.logging import configure_logging
from app.routers import health

configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("api starting", extra={"env": settings.app_env, "version": __version__})
    yield
    await engine.dispose()
    logger.info("api stopped")


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

    app.include_router(health.router)

    return app


app = create_app()
