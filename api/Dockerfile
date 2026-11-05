# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# base — Python, uv, and WeasyPrint's native libraries
#
# WeasyPrint renders through Pango and HarfBuzz rather than a browser engine,
# so the text layout happens in these shared objects and not in Python. Cairo
# is **not** needed: WeasyPrint 53 replaced it with its own PDF writer.
#
# The fonts are pinned for a reason. §9 requires deterministic output — "same
# data renders byte-identically, so regeneration is verifiable" — and a PDF's
# text layout depends on the exact font metrics available to the renderer. A
# machine with a different font set would produce a different file from the
# same data, and the golden-file test would fail for reasons nobody could see.
# fonts-dejavu-core is a fixed, packaged set, and the stylesheet names only
# those families (docs/DECISIONS.md D80).
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS base

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/

RUN apt-get update && apt-get install --no-install-recommends --yes \
      libpango-1.0-0 \
      libpangoft2-1.0-0 \
      libharfbuzz0b \
      libffi8 \
      fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# pg_dump, for §11's backups
#
# "Nightly pg_dump to R2 … plus a dump taken immediately before every
# publish." The pre-publish dump is taken by *this* process, so it cannot be
# delegated to the postgres container, and the client must therefore live
# here.
#
# From PGDG rather than Debian, because the major version has to match the
# server: bookworm ships client 15, and pg_dump refuses outright to dump a
# server newer than itself. A client/server mismatch is the kind of fault
# nobody discovers until the restore, which is the one moment it must not be
# discovered (docs/DECISIONS.md D97).
#
# The key is fetched to a keyring file and the repository is signed by it —
# never `apt-key`, which trusts a key for every repository on the system.
# ---------------------------------------------------------------------------
ARG PG_MAJOR=16

RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates curl gnupg \
    && install -d /usr/share/keyrings \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
         | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] \
http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
         > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install --no-install-recommends --yes "postgresql-client-${PG_MAJOR}" \
    && apt-get purge --yes curl gnupg \
    && apt-get autoremove --yes \
    && rm -rf /var/lib/apt/lists/*

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
