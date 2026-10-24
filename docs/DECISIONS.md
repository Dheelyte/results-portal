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

### D4 — The repository lives on GitHub

*Updated 2026-10-20: the remote was added by the client during milestone 3.*

No git repository existed at the start. "CI runs lint and tests on every push"
needs one, so `git init` was run on the project root.

The remote is now `github.com/Dheelyte/results-portal`, which settles the
question this entry originally left open and confirms D1's choice of GitHub
Actions. The workflow runs on the first push.

**Still open:** who owns the account long term, and whether the repository
moves to an HSD or school-owned organisation at handover. That is adjacent to
the hosting and data-protection questions in §13's project-level list — the
repository holds no pupil data, but it does hold the deployment configuration.

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
class teacher drops from sixteen passages per pupil to roughly thirteen, but
a specialist who teaches every class now writes one passage for **every pupil
in the school** — around 500 — against a class teacher's 30 × 14. Worth putting
to the school alongside N7 (all sixteen sections, or a reduced set?).

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
- §4.6's sixteen narrative sections

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

---

## Milestone 2 — auth (2026-10-20)

### D17 — `refresh_tokens` is a new table, not in §4

§5.1 requires refresh tokens to be opaque, hashed at rest, rotated on use,
and to have reuse detected. §4 specifies no table for them.

```
refresh_tokens(id, school_id, user_id, token_hash, family_id,
               issued_at, expires_at, revoked_at, replaced_by)
```

**`family_id`** groups every token descended from one login. Rotation issues a
successor in the same family and marks the predecessor revoked, linking them
through `replaced_by`. Presenting a token that is already revoked means the
chain has leaked, so the **entire family** is revoked rather than just that
token.

That logs out the legitimate user as well as the attacker. This is the
intended outcome: the honest user signs in again, and the stolen token is
worthless. Revoking only the replayed token would leave the attacker's
successor working.

**Why the refresh token is opaque while the access token is a JWT.** A JWT
cannot be withdrawn before it expires. Thirty minutes of that is tolerable;
thirty days is not. The refresh token means nothing without its row, so
revocation takes effect immediately.

**Why SHA-256 rather than Argon2 for the token hash.** The token is 256 bits of
system-generated randomness, so there is no low-entropy guess space for a slow
hash to defend — it would only tax every refresh. Passwords are the opposite
case, which is why they use Argon2id.

### D18 — `audit_log` pulled forward from milestone 3

§4.9 requires a row for **every failed login** and every account creation.
Those are milestone 2 events, so building auth without the table would mean
shipping a known gap and backfilling nothing. Milestone 3 now creates the rest
of §4 and not this.

`services/audit.py` is the only writer, and it scrubs a list of forbidden keys
from `before`/`after` before the row is built. CLAUDE.md forbids tokens and
password hashes in logs; `audit_log` is as much a log as stdout is. The key is
kept and the value replaced, so "the password changed" stays legible while the
value never appears.

### D19 — UUID v7 implemented rather than taken as a dependency

§4 asks for UUID v7 primary keys. Python 3.12's `uuid` module stops at version
5, and native `uuidv7()` arrives in Postgres 18, not the 16 this project runs.

`app/models/ids.py` implements RFC 9562 §5.7 in about twenty lines rather than
adding a package for one function (CLAUDE.md rule 7). A v7 value begins with a
millisecond timestamp, so rows inserted together sort together and index pages
stay dense where random v4 keys would scatter inserts.

Tested against the specification: version nibble, variant bits, embedded
timestamp, uniqueness over 10,000 values, and ordering across milliseconds.

### D20 — The access token carries `must_change_password`

So the §5.1 gate can be enforced without a database read on every request.

`CurrentUser` admits a user who still owes a password change; `ActiveUser`
refuses them with **409**, not 403 — nothing is forbidden, the account is in a
state the user can resolve. `/auth/change-password` depends on `CurrentUser`,
or there would be no way out of the gate.

The user row is still loaded on every request, so a deactivated account stops
working immediately rather than when its access token expires.

### D21 — Login failures are deliberately indistinguishable

An unknown identifier, a wrong password and a deactivated account all return
the same 401 with the same body. Distinguishing them turns the login form into
an account-enumeration oracle, and at this school the identifier is often a
parent's phone number, which is guessable.

A locked account returns **423 Locked**, which does reveal that the account
exists. That is a deliberate trade: a parent who cannot get in needs to know
why, and the lock is reachable by anyone willing to make five wrong guesses
anyway.

`decode_access_token` collapses every failure — expired, bad signature, wrong
token type, malformed — to one exception with one message, for the same reason.

### D22 — Password rules: a length floor and nothing else

§5.1 sets no password policy. Ten characters minimum, no composition rules.
Complexity requirements mostly produce `Password1!`, and this system's users
are teachers and parents on phones. The temporary-password alphabet excludes
`O 0 l I 1 o` because those get read down a phone line (§5.1 has the admin
pass them on by SMS or WhatsApp).

Changing a password revokes every refresh token the user holds — a password
change is how someone responds to a suspected compromise, so leaving sessions
alive would defeat it.

### D23 — `JWT_SECRET` must be real in production

The API refuses to start when `APP_ENV=production` and the signing key is
either the development placeholder or shorter than 32 bytes (RFC 7518 §3.2 for
HMAC-SHA256). A weak signing key lets anyone mint an admin token, and failing
to boot is a far better outcome than running insecurely.

### D24 — `python -m app.bootstrap` creates the first admin

§5.1 says accounts are admin-created and never self-registered, which leaves
no way to create the *first* one. A command rather than an endpoint: an
unauthenticated "create an admin" route is a back door however carefully
guarded. It refuses to run once an admin exists, takes every value from the
caller rather than seeding constants (§2.3), and prints the temporary password
once to stdout — not through the logger, which goes wherever logs go.

### D25 — The OpenAPI schema and the generated client are committed

`api/openapi.json` and `web/lib/api/schema.d.ts` are both in the repository,
and CI regenerates both and fails on any difference. An API change then shows
up in review as a schema diff, and a forgotten regeneration is caught by the
build rather than by a type error weeks later.

### D26 — Test fixtures truncate rather than roll back

The auth rules commit deliberately: a failed login must persist its attempt
counter even though the request fails. A harness that wrapped each test in a
rolled-back transaction would hide exactly that behaviour, so the integration
fixtures `TRUNCATE` between tests instead.

The suite runs on one event loop (`asyncio_default_test_loop_scope = "session"`)
because the application's engine is built at import time and pools connections;
a loop per test hands a later test a connection bound to a closed loop.

---

## Milestone 3 — schema and seed (2026-10-20)

### D27 — The card has sixteen narrative sections, not seventeen

**A correction to the specification, found while seeding.**

ARCHITECTURE.md said "seventeen" in ten places and sized the teacher workload
at 510 passages for a class of 30. Its own enumerated list in §1.4 does not
support that:

- **A — Area of Curriculum:** English Language Arts, Mathematics, Science,
  Social Studies, Computer Skills, Art & Music, Physical Education — **7**
- **B through J:** Work/Study Habits, Attendance/Tardiness, Attitude,
  Classroom Behaviour, Outside Behaviour, Character Development, Peer
  Relations, Personal Development, Performance — **9**

7 + 9 = **16**. The photographs confirm it: "Area of Curriculum" is a group
heading with no ruled lines of its own, and the nine lettered sections B–J
each have three.

The brief says the photographs win wherever they disagree with the spec, so
sixteen it is. ARCHITECTURE.md, CARD-FINDINGS.md and the workload arithmetic
(510 → **480** per class of 30) have all been corrected.

**Why it mattered enough to chase.** R8 defines a pupil's narrative as complete
when every active section has a body, and R10 blocks class submission until
every pupil's narrative is complete. A hardcoded seventeen would have made
submission unreachable — the gate would never open, with no useful explanation.
As it happens nothing is hardcoded (§2.3): completeness counts active rows. The
count was only ever wrong in prose.

### D28 — R9's attendance invariant is enforced by two triggers

§4.7 requires `times_present + times_absent = terms.times_school_opened`,
enforced in the service layer *and* with a trigger so that no path can write a
bad row. Postgres cannot express a cross-table CHECK, so migration 0003 adds:

- **`attendance_bounds`** on `attendance_records` — rejects a row whose
  present + absent does not equal the term's opened count, or whose present
  exceeds it. A NULL `times_school_opened` means the admin has not set the
  term calendar yet, so there is nothing to check and the row is allowed.
- **`term_attendance_consistency`** on `terms` — the other direction. Changing
  `times_school_opened` after attendance exists would leave rows the first
  trigger forbids, so the change is refused with a count of how many records
  would stop adding up.

The second trigger is not in the spec. Without it the invariant holds only for
new rows and rots quietly the first time an admin corrects the term calendar,
which is a normal thing to do.

A5 assumes the equality is exact. If the school allows a discrepancy, both
triggers relax in one migration.

### D29 — `subjects.is_specialist`, set in the platform

Per the client's instruction that subjects are created in the platform and
"can be flagged as a special subject". A boolean on `subjects`, not on
`class_subjects`: a subject is specialist school-wide, not per class.

A CHECK forbids a group heading from being specialist — a group holds no
scores and so has no teacher to be a specialist.

Which subjects carry the flag is the school's to set and change. The demo seed
starts Computer, Creative Art, Physical/Health Education and French as
specialist, purely so the §5.2 union case (a teacher who is class teacher of
one class and subject teacher in another) exists in development data.

### D30 — Seeding is idempotent and never re-asserts an edited value

`app/seed/reference.py` creates the subject tree, the card's grade bands and
the narrative sections **only when absent**. It never updates an existing row.

This is §2.3 in practice: seeded values are starting points the school owns.
Re-running the seed after an admin has renamed a subject or moved a grade
boundary must not quietly undo their work, and a seed that upserts would do
exactly that on the next deploy.

`app/seed/demo.py` is separate and refuses to run against a database that
already holds pupils.

---

## Milestone 4 — authorization (2026-10-21)

### D31 — Authorization is split into visibility and capability

`authz/scope.py` answers *which rows may this caller see*; `authz/policy.py`
answers *may this caller perform this action*. Two modules because the two
questions genuinely differ, and conflating them produces the wrong answer in
both directions.

An admin sees every class-subject — they assign the teachers — and may not
enter a single score against one. A head teacher sees every class in order to
review it and writes no narrative. A parent sees two pupils and may do almost
nothing with them.

§5.2 also wants the two to *fail differently*. A capability denial is a 403.
A row outside scope is a **404**, because a 403 confirms the row exists:

> "A subject teacher hitting another class's results must get a 404."

Scope functions therefore return a `Select` rather than a boolean, so a router
builds its query from a filtered statement and cannot produce a 403 by
accident.

### D32 — Teacher scope comes from the tables, never from `users.role`

The §5.2 matrix has separate columns for "class teacher" and "subject
teacher". Neither is a role: both are `UserRole.TEACHER`. What separates them
is a row in `class_teachers` or in `teaching_assignments`, and one teacher is
routinely both in different classes.

So the scoped checks take the database, and `class_ids_taught_by` is a union
of the two routes. The specification calls this out by name — "class teacher
of 4A and subject teacher of French in 5B gets the union of both scopes,
nothing wider" — and it is asserted directly.

The distinction has teeth:

- **Score entry** is per *class-subject*. Being class teacher of 4A does not
  grant 4A Computer; that belongs to whoever is assigned to teach it.
- **Attendance, growth and submission** are per *class*, and only for the
  class teacher. A specialist who teaches the class does not record its
  attendance.

### D33 — The matrix is data, and every cell is asserted

`policy.ROLE_ACTIONS` is a table of role to permitted actions, shaped to read
against §5.2 side by side. The test suite parametrises 4 roles × 14 actions
and asserts all 56 cells, so a cell cannot go untested by omission — and a
further test fails if an `Action` is added without a row in the expectation
table.

The pure cells live in `tests/unit/`: `policy.can` reads a role and an active
flag and touches no database. The scoped half needs real rows and stays in
`tests/integration/`.

### D34 — A test enforces "no router composes a raw select()"

§5.2 says it; `tests/unit/test_no_raw_tenant_queries.py` checks it, by walking
the AST of every module under `routers/` for a `select()` against a
tenant-scoped model.

A convention nobody checks lasts until the first busy afternoon, and the
failure mode here — one router that forgets `school_id` — is precisely how a
school portal leaks another family's results. The guard was verified by
planting a violating router and watching it fail; a scan that passes
vacuously is worse than no scan.

A companion test fails if a new tenant table is added without being listed, so
the scan's coverage cannot quietly shrink.

### D35 — Test cleanup uses DELETE, not TRUNCATE

Measured, not assumed. Across this schema `TRUNCATE ... CASCADE` costs about
**650ms** per call — it rewrites each table's file and fsyncs — against about
**19ms** for a DELETE over the same, nearly always empty, tables. At one call
per test that was the difference between a three-minute suite and a
one-minute one.

The delete order is derived from `Base.metadata.sorted_tables` reversed, so a
table added in a later milestone is cleaned without anyone remembering to add
it to a list.

This does not revisit D26: cleanup is still between tests rather than a
rolled-back transaction, because the auth rules commit on purpose.

---

# Milestone 5 — admin setup

### D36 — Creating a term creates both of its assessment periods

`POST /terms` inserts the term **and** a row for each half, with no dates.

§1.1 states the two halves as a fact about the domain rather than an option:
"each term has two assessment periods … this is the single most important
structural fact about this system". Treating them as something an admin might
forget to add allows a state where a teacher opens their class and has nowhere
to enter scores — a state nothing else in the system would notice.

`POST /terms/{id}/assessment-periods` is therefore an **upsert keyed on
`half`**, not a plain insert: both rows already exist, so the only thing the
call can mean is "these are the dates". It answers 201 if it had to create a
row and 200 if it updated one, so the response is still honest.

Cost to reverse: low. Deleting the two rows and making the POST a plain insert
is a few lines, and nothing stores anything against an empty period.

### D37 — Endpoints added beyond §7's list

§7 was written before B1 was answered and before §1.5's editability
requirement was reconciled with it. Six verbs were missing. Each is recorded
here rather than quietly added, per rule 9.

| Endpoint | Why it has to exist |
|---|---|
| `POST /sessions/{id}/current` | §2.3 requires the active session to be set in the platform, never derived from the clock. Something has to set it. |
| `POST /terms/{id}/current` | The same, for the active term. |
| `PATCH /terms/{id}` | `times_school_opened` is R9's denominator and is rarely known on the day a term is created. |
| `PATCH /subjects/{id}` | §1.5: "the list must be admin-editable and the display order must be configurable". The card leaves blank rows for additions. |
| `PUT /pupils/{id}/enrollment` | §7 assumed enrolment always happened with pupil creation. A roll typed in before the classes were settled needs placing, and pupils change class mid-year. |
| `POST /grading-scales/{id}/activate` | Switching between versions is the point of versioning them (§4.5), and answering N1 means saying "use this one from now on". |
| `GET/PUT /classes/{id}/narrative-assignments` | B1 as settled in D15 needs an admin surface. §7 predates that answer. |

§7 has been amended to list them.

### D38 — Exactly one current session and one current term, enforced in the service

Promoting one demotes every other, in the same transaction.

`scope.current_session_id` resolves the current session with `LIMIT 1`. Two
current rows would not raise anything — they would silently pick one, and half
the portal would scope itself to the wrong year. The same applies to the
current term.

**Why the service and not a partial unique index.** An index of the form
`UNIQUE (school_id) WHERE is_current` would reject the intermediate state
inside the promotion, where the old and new row are briefly both current.
Doing it in one `UPDATE … WHERE id != :new` followed by the promotion avoids
that without needing deferred constraints. Enforced by
`test_only_one_session_is_ever_current` and its term counterpart.

A belt-and-braces index remains available if the school ever edits rows
outside the application. Not added: nothing writes to this database but the
application, and rule 3 makes every schema change a migration.

**Related:** making a session current also demotes any current term in another
session, because two pointers that disagree scope the portal to neither. A
term outside the current session cannot be made current at all — that is a
409, so moving the school into another year stays a deliberate act.

### D39 — Coherence rules on dates

Three refusals, each because the alternative is a report card nobody can
explain:

- A session or term must start before it ends.
- A term must fall inside its session.
- A half term's window must fall inside its term, and a term's dates cannot be
  narrowed so that they orphan a window already set.

§4.2 states none of these. They are not new requirements, they are the
arithmetic of the ones it does state, and without them the cumulative averages
of R5 — "across the terms the pupil was present for" — have no reliable notion
of which term a date belongs to.

Cost to reverse: low. Each is one guard in `services/academic.py`.

### D40 — The whole admin surface is audited, not only what §4.9 lists

§4.9 requires an audit row for grading-scale and marks-obtainable changes,
account creation and password resets. Every other setup mutation writes one
too: sessions, terms, half terms, classes, houses, subjects, class subject
lists, teacher assignments, pupils, enrolments, narrative sections and
assignments, and phrase-bank entries.

§4.9's list is a minimum. "Who changed the current term" is the first question
asked when a class of results goes missing, and `audit_log` already exists —
the marginal cost is one call per write.

What those rows may **not** contain is unchanged: `services/audit.py` is still
the only writer, `FORBIDDEN_KEYS` still scrubs, and the pupil payloads carry
ids rather than names, because CLAUDE.md keeps a pupil's identity out of a log
as firmly as it keeps a score out.

### D41 — The admin screens are client-rendered, and §8.5 will need more than that

§8 says "server components by default". These screens are client components,
and not by preference.

The session lives in an httpOnly refresh cookie scoped to `api.<domain>`
(D13). The Next.js server runs on `<domain>` and cannot read that cookie, so
it cannot render a signed-in page at all. The access token is held in memory
and never in `localStorage`, where any successful XSS would read it.

For the setup screens this costs nothing: they are interactive forms used by
one administrator a few times a term.

**It does not generalise to the parent view.** §8.5 asks for a server-rendered
report card under **150 KB** of first load with no client-side fetching, and
the shared JavaScript bundle alone is already ~105 KB. Before milestone 12 one
of these has to happen:

1. The web app holds its own httpOnly session cookie on `<domain>` and proxies
   to the API server-side. The cleanest fit for §8.5, and it means a second
   place that handles sessions.
2. The report page is client-rendered and the 150 KB target is renegotiated
   with the school. Honest, but it gives up a stated requirement on the one
   page where a 3G connection was assumed.
3. The parent's PDF link carries a signed token and the HTML page is thinner
   than the PDF route — partial, and does not help the landing page.

Flagged now rather than discovered in milestone 12. Nothing in this milestone
forecloses any of the three.

### D42 — Marks obtainable: what "configured" means, and what cannot be lowered

**N2 is unanswered and nothing here invents an answer.** No column has a
default anywhere in the code.

Two judgements were needed to make the setup checklist able to say yes:

**"Configured" means the sheet's terminal column plus at least one CA test.**
Not all five CA tests: N2 is open, the school may use fewer than five in a
given half, and demanding all five would block a term on a number nobody has.
The terminal column — Mid Term Test on the first-half sheet, Exam on the
second — is required, because without it the sheet's largest component is
unvalidated.

**A maximum cannot be lowered below a score already entered against it.** §4.4
lets the school change these numbers and this does not stop that; it stops the
one change that silently makes stored data invalid. Lowering Mid Term Test to
20 when a teacher has entered 35 leaves a row that R1 would have rejected on
entry and that prints on a card as it stands. The refusal reports **how many**
entries exceed the new maximum and never the scores themselves.

Cost to reverse: low. Both are single functions in `services/marks.py`.

### D43 — Grade bands are checked over whole marks only, and the gap is real

`validate_bands` refuses overlapping bands, bands outside 0–100, and any gap
that leaves a **whole mark** unresolved.

It does **not** cover fractions, and the card's own scale is why that matters:
0–39, 40–49, 50–59 and so on leave 39.5 in no band, and `numeric(5,2)` with
R1's one decimal place permits exactly that value.

The resolution — whether a period average is rounded before banding, and to
what — is part of the unanswered **N3**. Guessing it here would put a rounding
rule in the one place nobody would look for it. So the limit is pinned by a
test, `test_fractional_coverage_is_not_claimed`, which asserts the current
behaviour and will fail deliberately when N3 is answered in milestone 9.

### D44 — A subject with scores entered cannot be removed from a class

`PUT /classes/{id}/subjects` refuses to drop an offering that has
`result_entries` behind it, and says to retire the subject instead.

R7's own direction is also guarded: an existing subject cannot be turned into
a group heading while any class offers it, because a heading carries no scores
and the existing ones would have nowhere to live.

Deleting would either orphan scores or cascade them away. Retiring keeps the
record, which is what §4.5's whole argument about reproducing a printed card
depends on.

### D45 — Test cleanup is ordered explicitly, not by autouse

`tests/integration/conftest.py`'s `session` fixture now requests
`clean_database` by name even though that fixture is autouse.

Three tests failed intermittently in fixture setup with a bare
`401 Incorrect username or password`. The cause was ordering: when the autouse
wipe lost the race against the requested fixture chain, it ran **between** a
user being committed and that user logging in. The symptom looked like an
authentication bug and was nowhere near one.

Naming the dependency makes the order a fact rather than a tendency. Cost to
reverse: none; it is one parameter.

### D46 — The test suite runs against its own database

**Raised as a known issue in milestone 5; fixed at the start of milestone 6.**
The original entry follows, then what was done.

`pytest` resolves `DATABASE_URL` from the same `.env` the application uses, and
`clean_database` empties every table before each test. Running the suite
locally therefore **destroys whatever is in the development database**.

CI is unaffected — it runs its own `postgres` service container.

Not fixed in this milestone, because the fix touches `docker-compose.yml`,
`.env.example` and the CI workflow, and that is worth doing deliberately
rather than in passing. The shape of it: a second database (`portal_test`)
created by an init script, and a `TEST_DATABASE_URL` the test configuration
prefers. Raised with the client rather than silently absorbed.

**Fixed, 2026-10-23.** Close to that shape, with two changes that make it need
no setup at all:

- `Settings.test_dsn` **derives** the test database from `DATABASE_URL` by
  appending `_test`. `TEST_DATABASE_URL` overrides it but nobody has to set
  it, so a fresh checkout is safe before anyone has read this file.
- `tests/conftest.py` — the first module pytest loads, and therefore the only
  place this can happen — rewrites `DATABASE_URL` from it **before anything
  imports `app.db`**, which builds its engine at import time. It then refuses
  to start at all if the resolved database name does not end in `_test`.
- A session fixture creates the database if it is absent and runs
  `alembic upgrade head` on it, so the schema under test is the migration
  chain's output rather than `metadata.create_all` — which would let a model
  and its migration disagree without any test noticing (rule 3).

No init script, because one only runs on a fresh `pgdata` volume and would
have missed every existing checkout. Two tests guard it: one on the
derivation, one asserting the live engine is on a `_test` database.

**One database, so one run at a time.** `clean_database` empties every table
between tests, so two `pytest` processes against the same checkout fight: the
second one's wipe blocks on the first one's locks, or fails with a foreign-key
violation naming a table it has already emptied. A killed run can leave a
connection *idle in transaction* holding the same locks, which looks identical.

To check, and to clear a stale one:

```bash
docker compose exec postgres psql -U portal -d portal_test \
  -c "select pid, state, query from pg_stat_activity where datname = 'portal_test'"
docker compose exec postgres psql -U portal -d portal_test \
  -c "select pg_terminate_backend(pid) from pg_stat_activity
      where datname = 'portal_test' and state = 'idle in transaction'"
```

Not worth solving with a database per worker: the suite is single-process by
design (one session-scoped event loop, D-note in `pyproject.toml`), and
`TEST_DATABASE_URL` is there for anyone who genuinely needs a second one.

### D47 — Never run `next build` inside the development container

The dev `web` container keeps `.next` in a named volume shared with
`next dev`. Running `next build` in it writes production artefacts into that
directory, and the dev server then serves `MODULE_NOT_FOUND` from a
half-production `.next` until the volume is emptied and the container
restarted. Worse, the build itself fails there for an unrelated reason:
`NODE_ENV=development` is set for the dev server, and `next build` under it
mixes React's development and production runtimes, which surfaces as
`Cannot read properties of null (reading 'useState')` during prerendering —
nothing to do with the page it names.

To verify a production build locally, build the image:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml build web
```

That runs `next build` in the image builder, with no `.next` volume and
`NODE_ENV` unset. It is also what CI does and what a deploy does, so it is the
check that means something.

If the dev server has already been poisoned:

```bash
docker compose exec web sh -c 'rm -rf .next/*'
docker compose restart web
```

### D48 — The single-file `openapi.json` mount does not survive a host rewrite

`docker-compose.yml` mounts `./api/openapi.json` into the web container so
`npm run generate:api` works without mounting the whole `api/` tree. Rewriting
that file from the host can leave the container's mount pointing at an
unlinked inode, and `generate:api` then fails with
`ENOENT /app/openapi.json` — the same class of problem as editing a
single-file-mounted file with `sed -i` (D10).

The fix is one command:

```bash
docker compose up -d --force-recreate web
```

CI is unaffected: its web job copies `../api/openapi.json` into place itself
rather than relying on a mount.

---

## Milestone 6 — score entry

### D49 — The grid renders the columns the server sends

§8.1 describes two layouts: "five CA tests plus Mid Term Test, or five CA
tests plus Exam". The obvious reading is two components, or one component with
a conditional. Neither is what was built.

`GET /class-subjects/{id}/entries` returns `columns` — the card's own column
list for that half — and the grid renders exactly that. The browser never
decides which half it is looking at.

**Why.** `COLUMNS_BY_HALF` in `services/marks.py` already had to exist: R1
validates against it and the Marks Obtainable screen is built from it. A
second copy in TypeScript would be a business rule in a React component
(rule 2) and the two would eventually disagree — most likely the day the
school answers N2 and a column's maximum moves.

A consequence worth knowing: a column added to a sheet later needs no
frontend change beyond a label.

### D50 — Reference data is readable by everyone in the school; only an admin may change it

§5.2's first three rows give the calendar, the subject list, the grading
scale, the narrative sections and the Marks Obtainable row to the **admin
alone**, and milestone 5 implemented that as `_school_wide_only` in
`authz/scope.py` — admin and head teacher see the rows, a teacher and a parent
see nothing.

Milestone 6 showed that to be too narrow. A teacher cannot enter a score
without knowing which half's sheet is open, what each column is marked out of,
and what grade an average earns. With those scopes closed, the grid 404s on
its own sheet.

So `authz/scope.py` now distinguishes two questions, which §5.2 conflates
because it is a table about *verbs*:

- **May this caller change it?** The admin alone. Enforced by the capability
  gates in `authz/dependencies.py`, unchanged, and asserted endpoint by
  endpoint in `test_setup_authz.py`.
- **May this caller see it?** Everyone in the school, for
  `academic_sessions`, `terms`, `assessment_periods`, `subjects`, `houses`,
  `grading_scales`, `grade_bands`, `narrative_sections` and
  `marks_obtainable` — via `_reference_data`.

None of those tables holds a pupil, a score or a comment. Every one of them is
printed on the card a parent is given. Widening sight of them reveals nothing
about any child, and the write surface did not move.

`users`, `enrollments` and `comment_bank` keep `_school_wide_only`: staff
names and contact details, which class a child is in, and the phrase bank are
not reference data.

**Cost to reverse:** low. One function, nine call sites.

### D51 — `GET /my/assignments` carries the term and its sheets, and defaults to the current term

§7 lists `GET /my/assignments?term_id=` returning a list. Two problems with
that as written, both discovered while building the grid:

1. A teacher has no endpoint that tells them which term is current — §5.2 gives
   `/terms` to the admin — so they could not supply `term_id`.
2. Nor could they discover the two `assessment_period_id`s, without which
   there is no sheet to open.

So `term_id` is optional and defaults to the current term (§2.3 puts that
setting in the platform), and the response is an object carrying the term, its
assessment periods, and the assignments. A 409 explains it when no term is
current, rather than an empty list implying there is no work.

This is the same kind of gap D37 recorded in milestone 5: not new
functionality, the missing half of a requirement stated elsewhere.

### D52 — The production overlay names its images apart

`docker-compose.prod.yml` sets `image: results-portal-api-prod` and
`results-portal-web-prod`.

Without that, both compose files build `results-portal-web`, so verifying a
production build (which D47 says to do) overwrites the development image with
one that has no source mount and no `--reload`. The next `docker compose up`
then starts it and the container restart-loops on
`Cannot find module '/app/server.js'`, with nothing to connect that to the
build run earlier. It happened twice during milestone 6 before being fixed.

### D53 — The frontend's pure logic is tested with Node's own runner

§8.1's harder requirements — inline validation, draft recovery, the autosave
indicator — are logic, and logic ships with its tests (rule 10). The project
has no JavaScript test framework, and adding one needs permission (rule 7).

Node 22 can run TypeScript directly (`--experimental-strip-types`) and has a
test runner built in, so `npm test` runs 46 tests over `lib/scores.ts`,
`lib/drafts.ts` and `autosaveLabel` with **nothing added to
`package.json`'s dependencies**.

What this buys: R1's browser mirror, the draft reconciliation (including
storage that throws, which is what a locked-down Android WebView does), and
every string in the save indicator.

What it does not: anything that needs a DOM or a React renderer. The grid
component itself, hydration, focus movement and `credentials: "include"` are
**not covered by any automated test**, and §12 puts end-to-end at milestone
13. Two consequences:

- Logic that must be tested is kept out of the component. `lib/scores.ts`
  exists for that reason as much as for rule 2.
- `tsconfig.json` gains `allowImportingTsExtensions`, and the two intra-`lib`
  imports under test are written `./scores.ts`, because Node's resolver needs
  the extension at every hop.

### D54 — R3's two averages agree today, and that agreement is the placeholder

R3 names two figures — *Mid Term Ave.* on the first-half sheet, *Total
Weighted Average* on the second — and says to "implement as two named
functions in `services/grading.py` with the current best guess clearly marked
as a placeholder". Both now exist and both compute the same thing: the pupil's
marks as a percentage of the marks obtainable for that sheet.

Different names on a printed card almost certainly mean different arithmetic,
and `total_weighted_average` is the one most likely to be wrong — "weighted"
is a word the card uses and that function does not yet honour. N3 is the
question.

The placeholder was chosen for three properties that survive whatever the
answer is:

- **Scale-free.** Whatever the maxima turn out to be (N2), the result is
  0–100, which is the range the grade bands describe.
- **Blank counts as zero, and an untouched row has no average at all** —
  exactly what R2's generated `ca_test_total` column does. A half-entered row
  reads low in both columns consistently, rather than the average disagreeing
  with the total printed beside it.
- **A column with no maximum is not on the sheet**, so it counts in neither
  the numerator nor the denominator. A school using three CA tests is marked
  out of three.

`python -m app.recompute_averages` backfills when the answer arrives, and
refuses to touch a row carrying a snapshotted `grade_letter` — a printed card
must keep saying what was printed (§4.5, rule 6). It reports how many rows it
skipped for that reason, so a formula change after an approval is visible
rather than silent.

---

## Milestone 7 — the narrative, attendance and growth

### D55 — Reading the phrase bank is a separate action from managing it

§5.2's third row reads "Grading scale, marks obtainable, narrative sections,
comment bank — **admin** ✅", with a dash in every other column. Taken
literally, a class teacher may not read the phrase bank.

That cannot be right. §4.6: "A class of 30 needs **480 written passages per
term** from one class teacher. Without a strong phrase bank this feature will
not be used as intended. Treat the comment bank as core, not optional." §8.2
puts a phrase-bank button beside every one of the sixteen sections. The row is
about *managing* the bank — adding, retiring, editing — which stays with the
admin alone.

So `policy.Action` gained `USE_COMMENT_BANK`, granted to the admin, the head
teacher (who has `head_teacher`-scoped phrases for the remark in milestone 9)
and the teacher, and denied to parents. `GET /phrases` is its own endpoint
rather than a widened gate on the admin's `GET /comment-bank`: it returns only
the **active** entries and takes no part in managing them.

This also corrects **D50**, which said `comment_bank` would keep
`_school_wide_only` on the grounds that a phrase bank is not reference data.
That was wrong in practice and the entry is left standing rather than edited,
because the reasoning is worth keeping visible: the test of "reference data"
is not whether the table sounds like configuration, it is whether a user needs
to read it to do the job the matrix gives them.

### D56 — `services/wellbeing.py` and `services/reports.py`

§4.7 says to enforce R9 "in `services/results.py` **and** with a trigger", and
§3's tree lists no module for attendance or for the report's own fields.

R9 is not in `results.py`. That module is the score sheet — R1 through R4, R7,
the bulk upsert — and attendance is a different page of the card, written by a
different person (the class teacher, not whoever teaches the subject), on a
different screen. Two modules instead:

- **`services/wellbeing.py`** — attendance and growth. §4.7's own title.
- **`services/reports.py`** — the fields that hang off `term_reports` and
  belong to no subject and no section. The class teacher's comment now; the
  head teacher's remark, `position_text` and the promotion decision when
  milestone 9 arrives, rather than each landing wherever its endpoint was
  built.

The rules still live in `services/` (rule 2) and the trigger still backs R9.
Only the file names differ from §3, which §3 now records.

**Why the service check is not redundant with the trigger.** A trigger can
only raise. It cannot say *which* of thirty pupils is wrong or which field,
and §8.3 needs exactly that to show the teacher where to look.

### D57 — Each PUT got the GET §7 omitted

§7 lists `PUT /classes/{id}/attendance`, `/growth` and `/comments`, and no GET
for any of them; nor a GET for one pupil's narrative. No screen can edit what
it cannot read, so each has its matching GET.

Same family as D37 and D51: not new functionality, the missing half of a
requirement stated elsewhere in the document. §7 now records them.

### D58 — A subject teacher may read a class's records but not write them

§5.2 reads "Attendance, growth records — **own class**", in the class-teacher
column only. Milestone 7's first draft enforced the *scope* (the class must be
one the teacher touches) but not the *relationship*, which left a subject
teacher of 4A able to write 4A's attendance.

It was found by tightening a test that had been written too loosely — it
asserted the request was refused (`status_code in (403, 404, 422)`) without
saying how. Replacing that with the exact status and message is what exposed
the hole, which is the argument for never writing the loose form: it passes
against the bug.

Both halves now hold, and they answer differently on purpose:

- **Reading** is open to any teacher the class is in scope for. A specialist
  needs to see whose records are still missing, and the page is how they see
  it.
- **Writing** requires being class teacher of that class — a **403**, not a
  404, because the class is already visible to the caller. There is nothing
  left to conceal, and naming the missing relationship ("only the class
  teacher records this") is more use than pretending the class does not exist.

The same split already applied to the narrative through
`policy.writable_narrative_sections`, which is where the pattern came from.

### D59 — `writable_narrative_sections` answers D15 sixteen times at once

`policy.can_write_narrative` answers "may this teacher write that section",
one section at a time. The narrative screen needs all sixteen answers to
render one page, and sixteen round trips to paint a page is absurd on the 3G
connection §8.5 assumes.

`policy.writable_narrative_sections` returns the whole set, using the same two
rules in the same order: a section assigned to this user, they write; every
section with no assignment at all falls to the class teacher. A section
assigned to *somebody else* is writable by neither the class teacher nor
anyone but that person — which is the entire point of the assignment, and is
asserted from both sides in `test_narrative_writing.py`.

The two functions must agree. They are deliberately written to look alike, and
the integration tests exercise the set-returning one through the endpoint that
uses it.

### D60 — Sections the teacher does not own are shown read-only, not hidden

A class teacher opening a pupil's page sees all sixteen sections, with the
specialist's rendered read-only rather than omitted.

Hiding them would be tidier and worse. The class teacher needs to see that
the section exists and is somebody's job — R8 counts it towards "complete",
so a blank they cannot see would make a pupil permanently incomplete for no
visible reason. And a specialist writing one curriculum area needs to read
what the class teacher said about the same child, to avoid contradicting it.

Reading and writing are separate questions throughout this milestone, and
this is the visible consequence.

### D61 — Argon2 costs 725 ms per login on this hardware, and the suite cannot pay it

Measured in the development container, 4 cores, with argon2-cffi's defaults
(RFC 9106 low-memory: Argon2id, time_cost 3, memory_cost 64 MiB,
parallelism 4):

```
argon2 verify: 725 ms
argon2 hash:  1503 ms
```

Two consequences, and they are different problems.

**The suite.** It performs several hundred logins — every authorization test
signs in through the real endpoint on purpose, so the 403 it asserts is the
one a browser would get. At 725 ms each that was four minutes of Argon2 and
nothing else, and it tripled the suite's runtime between milestones 6 and 7
as the authorization tables grew.

Fixed by giving `APP_ENV=test` a deliberately feeble profile
(`time_cost=1, memory_cost=8KiB, parallelism=1`) in `auth/password.py`, chosen
in one function, `hasher_for`. `tests/conftest.py` sets `APP_ENV=test`
alongside the database redirection; `test` is not `production`, so the only
other branch on that setting — `is_production`, governing the OpenAPI routes
and the Secure cookie flag — behaves exactly as in development.

Measured on `test_teacher_authz.py`, which is almost nothing but logins:
**119.3s before, 18.6s after** — 74 tests either way. Argon2 no longer appears
in the suite's slowest durations at all; the migration tests do, and those are
slow because each one creates and drops a database.

`test_password.py` asserts that **every other** value of `APP_ENV`, including
unknown ones and the empty string, gets the strong profile. Without that test
this change would be a loaded gun. An Argon2 hash embeds its own parameters,
so a hash made under either profile verifies under the other and
`needs_rehash` migrates it on the owner's next login — which is also asserted.

**The capacity question, which is for the school.** 725 ms of CPU per login,
with parallelism 4 on 4 cores, is roughly 1.4 logins per second at
saturation. §0 puts peak concurrency at "a few hundred parents on the evening
results are released". Three hundred parents signing in over two minutes is
2.5 logins per second — above that ceiling, so the queue grows and some
parents see a slow login or a timeout.

This is **not** fixed here, because lowering the cost of a password hash is a
security decision and it belongs with the school and with whoever hosts it.
What to do about it, roughly in order of preference:

1. **Measure on the real host first.** This container is not the production
   box, and the figure may be much better or much worse.
2. **Fewer logins.** The 30-day refresh token already means a parent signs in
   once a month, not once a visit (§5.1). Most of results night should be
   refreshes, which are cheap. Worth confirming against the real pattern.
3. **More cores**, which is the honest fix if the figure holds: Argon2's
   parallelism means the cost is CPU, and this is a single-host deployment by
   design (§0).
4. **Lower `memory_cost`** last, and only with the figure in front of
   somebody who can weigh it.

Raised as an open item rather than tuned silently.
