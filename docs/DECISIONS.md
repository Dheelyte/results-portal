# Decisions

An entry here for everything the specification did not settle, with the date and
who decided. Working assumptions about the *school* live in `ARCHITECTURE.md`
§14 instead; when one of those is confirmed or overturned it moves here.

Answers to the open questions of §13 belong here too, as they arrive.

---

## Milestone 1 — skeleton (2026-10-20)

### D1 — CI runs on GitHub Actions

*Decided by the client, 2026-10-20.*

ARCHITECTURE.md requires CI but names no provider, and the repository had no
remote. `.github/workflows/ci.yml` runs on every push and pull request with
three jobs: `api` (ruff, migrations against an empty database, pytest against a
real Postgres 16 service), `web` (lint, typecheck, build), and `compose` (brings
the full stack up and exercises the milestone's done-when criteria through
Caddy).

**To reverse:** the jobs are ordinary shell steps; porting to GitLab CI or
Woodpecker is a translation of the YAML, not a rework.

### D2 — Python dependencies managed with `uv`, lockfile committed

*Decided by the client, 2026-10-20.*

`api/pyproject.toml` plus a committed `api/uv.lock`. CI installs with
`uv sync --frozen`, and the Docker images use the same lockfile, so a CI run, a
developer's machine and production resolve to identical versions.

**To reverse:** `uv export --format requirements-txt` produces a pinned
`requirements.txt` for a pip-based toolchain at any time.

### D3 — Report card photographs moved to `docs/report-card/`

*Decided by the client, 2026-10-20.*

The photographs were at `report-card/*.HEIC` in the repository root, while
ARCHITECTURE.md §3 and §9 refer to `docs/report-card/*.jpg`. The four files were
moved to `docs/report-card/`, and JPG renditions were committed alongside the
HEIC originals, so the paths in the specification resolve and the images open in
a browser. Originals retained — they are the reference for the PDF in
milestone 11 and are the highest-fidelity copy available.

### D4 — The repository was initialised with git, with no remote

No git repository existed. "CI runs lint and tests on every push" needs one.
`git init` was run on the project root; no remote is configured, so the workflow
in `.github/workflows/` does not execute until one is added.

**Open:** which host the repository lives on, and who owns the account. This is
adjacent to the hosting and data-protection questions in §13's project-level
list.

### D5 — Structured JSON logs via the standard library, not `structlog`

ARCHITECTURE.md §11 requires structured JSON logs to stdout but names no
library. `api/src/app/logging.py` is a ~40-line `logging.Formatter` that emits
one JSON object per line. It adds no dependency, and it is explicit about which
fields are serialised — which matters, because CLAUDE.md forbids a score, a
narrative passage, a token or a pupil's identity ever reaching a log.

**To reverse:** adopting `structlog` later is a change to one module;
`configure_logging()` is the only entry point and every caller uses
`logging.getLogger(__name__)`.

### D6 — `pydantic-settings` added as a dependency

The only runtime dependency not already named in ARCHITECTURE.md §2. §11
requires all configuration to come from environment variables, and
`pydantic-settings` is the Pydantic-v2 way to do that with validation. It is
maintained by the Pydantic authors and is the conventional companion to a
dependency the specification already mandates.

Raised under CLAUDE.md rule 7 rather than added silently. Say the word if you
would rather read `os.environ` directly.

### D7 — Alembic conventions

- **The database URL comes from `app.config.settings`, not `alembic.ini`.** §11
  forbids secrets in the repository, and `alembic.ini` is committed.
- **Sequential, explicit revision ids** (`0001_baseline`, `0002_…`) with
  `file_template = %%(rev)s_%%(slug)s`. This is a single-branch repository;
  readable history beats collision resistance. Pass `--rev-id 0002` when
  creating the next revision.
- **`compare_type` and `compare_server_default` are on from the first
  revision**, so milestone 3's autogenerate notices a changed `numeric(5,2)` or
  a changed `DEFAULT` instead of skipping it silently.
- **Migrations never run at container start** (§11). `alembic upgrade head`
  stays an explicit step in both development and deployment.
- `alembic/versions/0001_baseline.py` creates nothing. It establishes the chain
  and the `alembic_version` table; the schema of §4 arrives in milestone 3.

### D8 — Networking and exposed ports

Caddy publishes `8080:80` in development — port 80 needs root and commonly
collides. It routes `/api/*`, `/healthz`, `/readyz`, `/docs`, `/redoc` and
`/openapi.json` to the API and everything else to Next.js.

`api`, `web` and `postgres` are additionally published on `127.0.0.1` (8000,
3000, 5432) for direct access while developing. Loopback only, and
`docker-compose.prod.yml` removes all three — in production Caddy is the only
way in.

The OpenAPI routes are **development only**: absent from `Caddyfile.prod`, and
FastAPI sets `docs_url=None` when `APP_ENV=production`. Closed at both layers.

### D9 — `/readyz` fails with a body that names no connection detail

A readiness endpoint is normally unauthenticated, so its failure response is
effectively public. It returns `503 {"status": "not_ready", "database":
"unreachable"}` and nothing else — no host, user, password, port, driver or
exception text. `db.check_database()` returns a boolean rather than raising, so
no driver message can reach a response body through an unhandled exception. The
detail is logged server-side at `warning`.

This extends CLAUDE.md's "never log or expose" rule to infrastructure detail,
which the rule does not name explicitly but is the same class of leak.

Both halves are tested, and the `compose` CI job re-checks the body after
stopping Postgres for real.

### D10 — Web stack pinned

Node 22 (active LTS), Next 15.1, React 19, TypeScript 5.7, Tailwind v4 — the
current defaults for a new Next 15 App Router project, which is what
ARCHITECTURE.md §2 asks for. Exact versions in `web/package.json`, resolved
through a committed `package-lock.json`.

`next.config.ts` sets `output: "standalone"` so the production image ships a
self-contained server, and `poweredByHeader: false`.

### D11 — `.env.example` carries milestone-1 keys only

§11 says `.env.example` lists every key. It lists every key *in use*: app
environment, log level, database, the web app's two origins, and Caddy's site
address. Auth secrets arrive with milestone 2, object storage with milestone 11,
Sentry with milestone 13 — each milestone adds its own keys here as it lands.
Listing keys for features that do not exist invites someone to configure a
setting nothing reads.

### D12 — Directory skeleton created ahead of its milestones

`api/src/app/{schemas,services,auth,authz,seed}`, `api/src/app/pdf/templates`
and `web/components` exist with a `.gitkeep` and nothing else. They are the
layout of ARCHITECTURE.md §3, present so that CLAUDE.md rule 2 ("business rules
live in `api/src/app/services/`") is visible from the first commit rather than
discovered in milestone 5. No stub code was written into them.

`api/src/app/models/` contains only the declarative `Base`, which Alembic needs
as an autogenerate target. It defines no tables — those are milestone 3's, and
milestone 3 is blocked on B1–B3.
