# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# base — Python plus uv, no project code
#
# WeasyPrint's native libraries (pango, cairo, gdk-pixbuf) are deliberately not
# installed: the PDF arrives in milestone 11 and an unused 200MB of shared
# objects in every image until then is waste.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS base

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# ---------------------------------------------------------------------------
# deps — resolve from the lockfile alone, so a source edit does not reinstall
# ---------------------------------------------------------------------------
FROM base AS deps

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --all-groups

# ---------------------------------------------------------------------------
# dev — reload server, test and lint tooling present
#
# The compose file bind-mounts src/, tests/ and alembic/ over the copies below.
# The virtualenv sits at /opt/venv, outside the mount, so it survives.
# ---------------------------------------------------------------------------
FROM deps AS dev

COPY . .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-groups

ENV PYTHONPATH=/app/src

EXPOSE 8000

CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--reload", "--reload-dir", "/app/src"]

# ---------------------------------------------------------------------------
# prod — runtime dependencies only, unprivileged user
# ---------------------------------------------------------------------------
FROM base AS prod

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV PYTHONPATH=/app/src

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Migrations are an explicit deploy step and are never run here
# (ARCHITECTURE.md §11).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
