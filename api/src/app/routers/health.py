"""Liveness and readiness probes (ARCHITECTURE.md §11).

Both live at the root rather than under /api/v1 so a load balancer or an
orchestrator can reach them without knowing the API version.
"""

import logging

from fastapi import APIRouter, Response, status

from app.db import check_database

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/healthz", summary="Liveness probe")
async def healthz() -> dict[str, str]:
    """The process is up.  Touches no dependency, so it never fails on a slow
    database and so cannot get the container needlessly restarted."""
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness probe")
async def readyz(response: Response) -> dict[str, str]:
    """The process is up *and* the database is reachable.

    The failure body names no host, DSN, driver or exception text — a readiness
    endpoint is typically unauthenticated (docs/DECISIONS.md, D9).  The detail
    is logged instead.
    """
    if await check_database():
        return {"status": "ready", "database": "ok"}

    logger.warning("readiness check failed: database unreachable", extra={"probe": "readyz"})
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "not_ready", "database": "unreachable"}
