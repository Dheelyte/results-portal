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
- **A URL already set on the Alembic `Config` wins over settings.** `env.py`
  fills in `sqlalchemy.url` from settings only when the caller has not supplied
  one. Overriding unconditionally would send a migration aimed at a throwaway
  test database — or at a restored backup — silently at the development
  database instead. The migration tests depend on this, and caught it.
- **Migrations never run at container start** (§11). `alembic upgrade head`
  stays an explicit step in both development and deployment.
- `alembic/versions/0001_baseline.py` creates nothing. It establishes the chain
  and the `alembic_version` table; the schema of §4 arrives in milestone 3.

### D8 — Networking and exposed ports

> **Superseded in part by D13**, which moved the API onto its own hostname.
> The port and exposure decisions below still stand; the path-based routing
> described here does not.

Caddy publishes `8080:8080` in development — port 80 needs root and commonly
collides, and matching the port inside and out keeps the `Host` header's port
identical to the site address in the Caddyfile.

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

Tailwind is pinned to an exact version for both `tailwindcss` and
`@tailwindcss/postcss`, not a caret range. Tailwind v4's work is done by a
native `@tailwindcss/oxide` binary whose ABI tracks the release: pinning the
plugin at 4.0.0 while npm floated oxide to 4.3.3 broke every CSS build with
`Missing field 'negated' on ScannerOptions.sources`. Bump the two together.

**Operational note.** `node_modules` lives in a named volume so the host needs
no Node installed. Rebuilding the image does *not* refresh that volume, so
after a change to `web/package.json`:

```bash
docker compose rm -sf web
docker volume rm results-portal_web_node_modules results-portal_web_next_cache
docker compose up -d --wait web
```

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

---

## Milestone 0 — blocking questions (2026-10-20)

All four decided by the client, 2026-10-20.

### B2 — The head teacher and the admin are two distinct roles

The head teacher approves results. A separate admin holds a portal-wide
overview. They are not the same person.

**Consequences.** §1.6's workflow stands unchanged: approve (head teacher) and
publish (admin) remain two steps, which preserves the audit trail that §4.9
depends on. `users.role` stays the single-value enum of §4.1 —
`('admin','head_teacher','teacher','parent')` — and milestone 2 can build the
users table as specified. The §5.2 matrix needs no change.

**Fallback, should one person ever need both:** issue two accounts rather than
widen `role` to a set. Recorded here so it is a known answer rather than a
rediscovered problem.

### B1 — The narrative is split between class teacher and specialist

The specialist teacher writes the curriculum-area narrative for their own
subject. The class teacher writes every other curriculum area, and all of
sections B through J.

**Consequences.** §5.2's single "Write narrative sections" row has been split
into three, and the scope resolver for narrative entries now has two paths
rather than one: a class-teacher scope over the pupils of their class, and a
subject-teacher scope over the pupils they teach for one section.

Sections B–J (Work/Study Habits, Attendance/Tardiness, Attitude, Classroom
Behaviour, Outside Behaviour, Character Development, Peer Relations, Personal
Development, Performance) are behavioural, not subject-bound, and stay entirely
with the class teacher.

**Still open, needed by milestone 3.** Two pieces of this are not yet settled
and the `narrative_sections` table cannot be finalised without them:

1. **Which of the seven curriculum areas are specialist-taught?** The seven are
   English Language Arts, Mathematics, Science, Social Studies, Computer
   Skills, Art & Music, Physical Education. Computer Skills, Art & Music and
   Physical Education are the likely three, but Science may also be specialist
   at this school.
2. **How does a curriculum area map to a scored subject?** §1.4 notes the two
   lists differ. "Computer Skills" maps cleanly to the scored subject
   "Computer", and "Physical Education" to "Physical/Health Education", but
   **"Art & Music" spans "Creative Art" and no music subject exists in the
   scored list at all.** Whoever teaches music, if anyone, has no class-subject
   to hang authorship on.

The likely schema answer is a nullable `narrative_sections.subject_id`: when
set, the teacher assigned to that class-subject writes the section; when null,
the class teacher does. That is a data-model change and so is **not** being
made until asked (CLAUDE.md rule 7).

**Workload note.** This redistributes the §8.2 load rather than reducing it. A
class teacher drops from seventeen passages per pupil to roughly fourteen, but
a specialist who teaches every class now writes one passage for **every pupil
in the school** — around 500 — against a class teacher's 30 × 14. Worth putting
to the school alongside N7 (all seventeen sections, or a reduced set?).

### B3 — No import of earlier terms

Earlier terms will not be loaded into the system.

**Consequences.** No historical-import milestone and no import CSV format —
this removes work rather than adding it. The second-half sheet's *1st Term
Ave.*, *2nd Term Ave.* and *Annual Scores (Ave.)* columns will have no data in
the first year; §9 already requires that a cumulative column be omitted when
the pupil has no results for that term, rather than printed empty or
zero-filled, so no change is needed to carry this.

This is also what makes assumption A1 cheap to reverse, and the two reinforce
each other.

**Still open, now low-stakes:** which term is go-live. With no import it no
longer changes the data model — only which columns appear on the first cards
printed, and that is already conditional.

### A11 — Same-origin at `/api/*` — ❌ **REVERSED the same day. See D13.**

*Moved here from ARCHITECTURE.md §14, where it was a working assumption.*

The original decision: the API is served through Caddy on the same origin as
the web application, so the application carries no CORS configuration.

**This was reversed hours later**, before any auth code was written, in favour
of a dedicated `api.*` subdomain. The entry is kept rather than deleted so the
reversal is visible: §14 had priced A11 at *Low now, Medium after milestone 2*
precisely because this kind of change gets expensive once the refresh cookie
exists, and that pricing is what made catching it early worth the five files
it cost.

The replacement is **D13**.

---

## Milestone 0 continued — onboarding, configurability, topology (2026-10-20)

All decided by the client, 2026-10-20.

### N8 — Pupils, users and subjects are onboarded manually in the platform

There is no external source to import from and no CSV format. The admin enters
pupils, staff, parent accounts and subjects through the platform, and sets the
active term there too.

**Consequences.**

- `POST /pupils/import` is struck from §7. It is descoped, not impossible — if
  typing proves painful the endpoint can return, and that is a product call.
- Milestone 5's admin screens carry more weight than the spec implied: they are
  now the *only* way data enters the system, so their quality decides whether
  setup is tolerable.
- The admission-number question behind N8 dissolves: the platform assigns them,
  so uniqueness is enforced by the `UNIQUE (school_id, admission_number)`
  constraint of §4.1 rather than hoped for.

**Raised, not blocking.** Roughly 500 pupils, 450 parent accounts and 30 staff
is on the order of a thousand records — a day or two of typing before go-live.
Worth scheduling deliberately rather than discovering the week before.

### D14 — Nothing in the configurable set is hardcoded

> "Students and the portal users will be onboarded through the platform by
> manually entering their details. Subjects will also be created through the
> platform and they can be flagged as a special subject. The active term will
> also be determined on the platform. All these details and similar ones should
> not be hardcoded."

**The rule, as I am applying it.** *Seeded* initial data is fine — the school
should not meet a blank screen on day one — but every seeded value must be
editable in the platform afterwards, and none may be a compiled-in constant
that drives behaviour.

So these still ship as **seed rows**, exactly as the spec says:

- §1.5's subject list, with English as a group over five sub-subjects
- §1.3's seven grade bands
- §4.6's seventeen narrative sections

And none of these may exist anywhere in the codebase:

- a `CURRENT_TERM` constant — the active term is `terms.is_current`, set by an
  admin (§4.2 already has the column)
- a hardcoded set of specialist subjects — a flag on the row, set by an admin
- an enum or literal list of subject names
- a grade-band table in Python — `grading_scales` and `grade_bands` are rows
  (§4.5), and they are versioned precisely so the school can change them

This generalises what the spec already wanted in places (§1.5 "admin-editable",
§4.5 versioned scales, marks obtainable as configuration) into a standing rule,
so it stops being a series of local judgement calls.

**Where it binds hardest:** the seed module. Seeding must be idempotent and
must never *re-assert* a value the school has since edited.

### D15 — Narrative sections carry their own teacher assignment

Settling the sub-question left open by B1.

§1.4 notes that the seven narrative curriculum areas are **not** the same list
as the eighteen scored subjects. Rather than map between them, the two lists
stay unconnected: `narrative_sections` get their own per-class teacher
assignment, which an admin sets.

**Why this over linking to a scored subject.** The mapping does not exist
cleanly. "Computer Skills" → *Computer* and "Physical Education" →
*Physical/Health Education* both work, but **"Art & Music" has no counterpart**
— the scored list has *Creative Art* and no music subject at all. A link-based
design needs an answer for that case; an assignment-based one does not, because
the admin simply picks whoever writes it.

It is also the answer most consistent with D14: who writes what is data the
school edits, not a structure baked into the schema.

**Consequence for §5.2.** The single "Write narrative sections" row became
three: behavioural sections B–J and non-specialist curriculum areas to the
class teacher, specialist curriculum areas to the assigned teacher. Already
applied.

**Built in milestone 3**, with the rest of the schema.

### A9 — Confirmed: 300–600 pupils

*Moved here from ARCHITECTURE.md §14.*

The school's roll is in the range §0 assumes. The single-host design — one
FastAPI process, one Postgres, no queue, no cache, PDFs generated on demand —
is correct and needs no revisiting. §14 had this at **High** cost to reverse
because everything in §0 follows from it; it is now settled.

### D13 — The API has its own subdomain, sharing a parent domain

**Replaces A11**, which was confirmed as same-origin earlier the same day and
reversed before any auth code existed.

The API is served from `api.<domain>`; the web app from `<domain>` (or
`portal.<domain>`). **Both must sit under the same registrable domain.**

**Why the same-parent-domain constraint matters.** Requests from the web app to
the API are then cross-**origin** but still same-**site**, because `SameSite`
compares registrable domains rather than origins. That means the refresh-token
cookie of §5.1 keeps `SameSite=Lax` and the CSRF protection it provides. Put
the two on unrelated domains and every request becomes cross-site, forcing
`SameSite=None; Secure` — which removes that protection, needs explicit CSRF
tokens, and runs into Safari's ITP.

**What this costs, applied in milestone 1:**

- `Caddyfile` — two site blocks keyed on hostname instead of one keyed on path.
  Caddy now listens on 8080 inside the container as well as out, so the `Host`
  header's port matches the site address exactly.
- `Caddyfile.prod` — `API_DOMAIN` and `WEB_DOMAIN` replace `SITE_ADDRESS`;
  Caddy provisions TLS for both.
- `.env.example` — `PUBLIC_WEB_ORIGIN`, `NEXT_PUBLIC_API_URL`, `API_DOMAIN`,
  `WEB_DOMAIN` added.
- `docker-compose*.yml`, `web/app/page.tsx`, `.github/workflows/ci.yml`.
- `/healthz` and `/readyz` now answer on the **API host only**. CI asserts that
  the web host returns 404 for them, so a regression to same-origin routing
  cannot pass silently.

**Development.** `api.localhost:8080` and `localhost:8080`, both through Caddy.
`*.localhost` resolves to loopback without an `/etc/hosts` entry on most
systems; CI pins it explicitly because runner images vary.

**One caveat, stated because it will otherwise confuse someone.** Browsers may
treat `localhost` as a public suffix, which would make `localhost` ↔
`api.localhost` **cross-site in development while production is same-site**.
That errs safe — anything working in dev works in production — but it can
produce dev-only cookie puzzles. For an exact mirror, add to `/etc/hosts`:

```
127.0.0.1  portal.sshms.test  api.sshms.test
```

and set the origin variables to match. Worth doing when the cookie work starts
in milestone 2, not before.

### D16 — Three dependencies approved

- **`argon2-cffi`** — Argon2id password hashing, named in §5.1.
- **`pyjwt`** — access-token encode and decode, named in §5.1.
- **`pydantic-settings`** — environment configuration, shipped in milestone 1
  and approved retroactively (supersedes the open question in D6).

All three raised under CLAUDE.md rule 7 before use.
