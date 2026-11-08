# Runbook

Operating the School Results Portal: backups, restores, the E2E journey, and
the handful of things that go wrong.

Written for whoever is on the other end of the phone when the school rings,
which may not be the person who built it. Every command here has been run.

Cross-references: `ARCHITECTURE.md` §11 for the deployment, §5.1 for the login
defences, and `DECISIONS.md` D96–D99 for why each of these works the way it
does.

---

## 0. Deploying for the first time

From a clone on the production host. Every command is run from the repository
root, and every one of them has been run.

### Before you start

- **DNS.** Two A records pointing at this server, under **one registrable
  domain** — `portal.example.ng` and `api.example.ng`. Not two unrelated
  domains: A11 and `Caddyfile.prod` explain why, and getting it wrong forces
  `SameSite=None` and CSRF tokens before anyone can sign in.
- **Ports 80 and 443 open.** Caddy needs 80 for the ACME challenge even
  though it redirects.
- **Docker Engine with the Compose plugin.** `docker compose version`.

### 1 · The environment file

```bash
cp .env.example .env
```

Then edit it. These must change; the rest can keep their defaults:

| Key | What to put |
|---|---|
| `POSTGRES_PASSWORD` | a generated password |
| `DATABASE_URL` | the same password — `postgresql+asyncpg://portal:<password>@postgres:5432/portal` |
| `JWT_SECRET` | `python3 -c 'import secrets; print(secrets.token_urlsafe(64))'` |
| `WEB_DOMAIN` | `portal.example.ng` |
| `API_DOMAIN` | `api.example.ng` |

`APP_ENV`, `PUBLIC_WEB_ORIGIN` and the two `NEXT_PUBLIC_*` values are set by
the production overlay from `WEB_DOMAIN` and `API_DOMAIN` — leave them.

The API **refuses to start** in production if `JWT_SECRET` is the development
value or shorter than 32 bytes. That is deliberate.

### 2 · Build and start

```bash
export COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml

docker compose build          # ~10 min the first time
docker compose up -d --wait
```

`COMPOSE_FILE` saves repeating `-f ... -f ...` on every later command. If you
open a new shell, export it again — or spell both files out.

Caddy provisions TLS on first request to each hostname; the first load of
each is slow and then it is cached.

### 3 · Migrations, then the first account

Migrations are **never** run at container start (§11), so they are a step:

```bash
docker compose exec api alembic upgrade head
docker compose exec api alembic current      # should print the head revision
```

There is no self-registration (§5.1), so the first admin is made by hand:

```bash
docker compose exec api python -m app.bootstrap \
    --school "Self-Starters House Montessori School" \
    --short-name SSHMS \
    --admin-name "Head of Admin" \
    --admin-email admin@example.ng
```

It prints a temporary password **once** — the account must change it at first
sign-in — and refuses to run if an admin already exists. Do **not** run
`python -m app.seed` on this host: it is demo data.

### 4 · Check it

```bash
curl -fsS https://$API_DOMAIN/healthz   && echo        # 200
curl -fsS https://$API_DOMAIN/readyz    && echo        # 200 = database reachable
curl -fsSo /dev/null -w '%{http_code}\n' https://$WEB_DOMAIN/          # 200
curl -fsSo /dev/null -w '%{http_code}\n' https://$WEB_DOMAIN/healthz   # 404, see §1
curl -fsSo /dev/null -w '%{http_code}\n' https://$API_DOMAIN/docs      # 404 in production
```

Then by hand: sign in at `https://$WEB_DOMAIN/login` as the bootstrapped
admin and confirm the change-password gate fires. **If the staff screens
cannot reach the API, the image was built without `NEXT_PUBLIC_API_URL`** —
that value is inlined at build time, and `docs/DECISIONS.md` D110 is the
story.

Take one backup by hand before anyone depends on the schedule, and confirm it
lands in the volume rather than inside the container:

```bash
docker compose exec api python -m app.backup --reason first-deploy
docker compose exec postgres ls -lh /backups/*/
```

### 5 · The nightly schedule

§2 below has the crontab line and the off-host copy that is **still
outstanding** — dumps currently sit on the same disk as the database they
protect.

### Upgrading later

```bash
git pull
docker compose exec api python -m app.backup --reason before-upgrade
docker compose build
docker compose up -d --wait
docker compose exec api alembic upgrade head
```

The dump comes first because `alembic upgrade` is the step that can lose
data, and §11's pre-publication dumps do not cover a deploy.

---

## 1. The stack

```bash
docker compose up -d --wait              # postgres, api, web, caddy
docker compose exec api alembic upgrade head
```

Migrations are **never** run at container start (§11). They are an explicit
step, because a container restart under load must not alter the schema.

| | Development | Production |
|---|---|---|
| Web | `http://localhost:8080` | `https://$WEB_DOMAIN` |
| API | `http://api.localhost:8080` | `https://$API_DOMAIN` |
| Health | `/healthz`, `/readyz` — **API host only** | same |

If `api.localhost` does not resolve, add `127.0.0.1 api.localhost` to
`/etc/hosts`. Both hostnames must share one registrable domain (A11): that is
what keeps the refresh cookie `SameSite=Lax`.

### The first account

There is no self-registration (§5.1), so the first admin is made by hand:

```bash
docker compose exec api python -m app.bootstrap --help
```

It prints a temporary password **once** and refuses to run if an admin
already exists.

---

## 2. Backups

§11: *"nightly `pg_dump` to R2, 30 days retained, plus a dump taken
immediately before every publish. Results data is irreplaceable — no teacher
will rewrite 480 passages. Document and test the restore procedure; an
untested backup is not a backup."*

### Taking one

```bash
docker compose exec api python -m app.backup                      # nightly
docker compose exec api python -m app.backup --reason before-upgrade
docker compose exec api python -m app.backup --prune-only         # retention only
```

Dumps land in `BACKUP_STORE` (default `/var/lib/portal/backups`, a named
volume) as `<year>/portal-<timestamp>Z-<reason>.dump` — Postgres
custom format, so `pg_restore` can read one table out of it.

### The nightly schedule

On the **host**, not in a container, because a cron daemon inside a service
is another process to supervise for no gain:

```cron
# /etc/cron.d/portal-backup — 01:30 Africa/Lagos
30 1 * * *  root  cd /srv/results-portal && /usr/bin/docker compose exec -T api python -m app.backup --reason nightly >> /var/log/portal-backup.log 2>&1
```

Check it is running:

```bash
docker compose exec api ls -lh /var/lib/portal/backups/*/
```

### Before every publish

Automatic. `services/publication.py` takes a dump before it moves a single
row, and **refuses to publish if the dump fails** — the point of a safety net
is that it is there the one time it matters. The admin sees:

> The pre-publication backup could not be taken, so nothing was published.

Almost always a full disk. Free space, or prune, and publish again. If
results genuinely must go out with the backup store broken, set
`REQUIRE_PREPUBLISH_BACKUP=false` and restart the API — and put it back
afterwards.

### Off-host copies

The dumps sit on the same host as the database, which is not a backup. §11's
diagram puts them in R2. Until that account exists, copy them off nightly:

```cron
45 1 * * *  root  rclone copy /var/lib/docker/volumes/results-portal_backup_store/_data r2:sshms-backups
```

**This is the one open item in this runbook.** A dump on the same disk as the
database survives a bad migration and nothing else.

---

## 3. Restoring

**Rehearsed on 2026-11-05** against the development database, which held two
published reports and 32 narrative passages. Every command below is the one
that was run; `DECISIONS.md` D99 has the output.

A restore is destructive. Read all six steps before running any.

```bash
# 1. Stop the writers. The API and the web app — not Postgres, which the
#    restore needs.
docker compose stop web api

# 2. Choose the dump.
docker compose exec postgres ls -1 /backups/2026/

# 3. Restore into a fresh database, never into the live one. `pg_restore
#    --clean` over a database being read leaves a half-restored schema and no
#    way to tell how far it got.
docker compose exec postgres createdb -U portal portal_restored
docker compose exec postgres pg_restore -U portal -d portal_restored --no-owner \
  /backups/2026/portal-<timestamp>Z-<reason>.dump

# 4. Check it before you swap. Counts first, then the thing nobody can
#    rewrite: a frozen grade.
docker compose exec postgres psql -U portal -d portal_restored -c "
  select (select count(*) from pupils) as pupils,
         (select count(*) from narrative_entries) as passages,
         (select count(*) from result_entries) as entries,
         (select count(*) from term_reports) as reports;"

docker compose exec postgres psql -U portal -d portal_restored -c "
  select state, count(*) from term_reports group by state;"

docker compose exec postgres psql -U portal -d portal_restored -c "
  select p.admission_number, s.name, re.grade_letter, re.period_average
    from result_entries re
    join pupils p on p.id = re.pupil_id
    join class_subjects cs on cs.id = re.class_subject_id
    join subjects s on s.id = cs.subject_id
   where re.grade_letter is not null
   order by p.admission_number, s.name limit 4;"

# And the schema is where the code expects it:
docker compose exec postgres psql -U portal -d portal_restored -At \
  -c "select version_num from alembic_version"

# 5. Swap. Keep the old one — a restore from the wrong dump is survivable,
#    one with nothing behind it is not.
docker compose exec postgres psql -U portal -d postgres \
  -c "alter database portal rename to portal_broken_$(date +%Y%m%d);"
docker compose exec postgres psql -U portal -d postgres \
  -c "alter database portal_restored rename to portal;"

# 6. Back up, and confirm.
docker compose up -d api web
docker compose exec api alembic current          # must print (head)
curl -f http://api.localhost:8080/readyz
```

Then **look at a card**. §4.5 forbids recomputing a grade on a published
result, so a restore that silently regraded would be the worst outcome there
is, and the only way to know is to open one:

```bash
curl -f http://localhost:8080/children/<pupil>/<term> -H "Cookie: <parent session>"
```

Keep `portal_broken_*` for a week. Drop it once the school has had a normal
day.

### A caution the drill turned up

The dumps live in a volume mounted on **both** containers — `pg_dump` runs in
`api`, `pg_restore` in `postgres` — at `/var/lib/portal/backups` and
`/backups` respectively. If a deployment ever drops that second mount, the
restore starts with a copy:

```bash
docker compose cp api:/var/lib/portal/backups/2026/portal-….dump /tmp/
docker compose cp /tmp/portal-….dump postgres:/tmp/
```

### What a restore does *not* undo

- **Generated PDFs.** They live in their own volume, keyed by admission
  number and version (§9). A restore that rewinds past a correction leaves
  the newer `-2.pdf` in the cache; it is regenerated on demand, so this
  self-corrects, but a parent holding the link still has the old file.
- **Refresh tokens.** Restoring an older `refresh_tokens` table invalidates
  sessions issued since. Everyone signs in again. That is correct, and worth
  warning the school about before a restore rather than after.

## 4. The E2E journey

§10 asks for one: *set up → enter both periods → narrative → submit →
approve → publish → parent downloads and acknowledges.*

```bash
docker compose down -v && docker compose up -d --wait   # an empty database
docker compose exec api alembic upgrade head
docker compose exec api python -m app.seed
docker compose --profile e2e run --rm e2e
```

### There are two specs, and they want different things

| Spec | Needs | Proves |
|---|---|---|
| `full-term.spec.ts` | a **freshly seeded** database | the work of a term can be done |
| `navigation.spec.ts` | a seeded database, in any state | §8.0's shell and every route behind it can be reached |

The second is the one to reach for after a change to the interface: it is
re-runnable against a stack that has already been through the journey, which
is exactly when the journey cannot run (a class publishes once). Run it alone
with

```bash
docker compose --profile e2e run --rm e2e npx playwright test e2e/navigation.spec.ts
```

It signs in about twenty times, so it needs the same raised per-IP limit as
the journey — see below.

### Give it room to sign in

The journey signs in at every step, from one address, and §5.1's per-IP limit
is 20 attempts per 15 minutes (A34). The API tokens are cached for the run,
but the **browser** sign-ins cannot be: the staff screens hold their access
token in memory (D41), so each test's fresh context signs in again — which is
part of what is being tested. Raise the limit for the E2E stack:

```bash
LOGIN_IP_MAX_ATTEMPTS=200 docker compose up -d --force-recreate api
```

A run that ends in `429` on a sign-in has hit this, not a bug.

### Another project on 5432

`docker compose up -d` fails with *Bind for 0.0.0.0:5432 failed: port is
already allocated* when something else on the machine is using Postgres's
port. The portal's own containers do not need the mapping — the api reaches
the database at `postgres:5432` over the Docker network — so the quickest way
past it is an override that drops the published port:

```yaml
# /tmp/no-pgport.yml
services:
  postgres:
    ports: !reset []
```

```bash
docker compose -f docker-compose.yml -f /tmp/no-pgport.yml     up -d --force-recreate postgres --wait
docker compose restart api        # its connection pool is holding dead sockets
```

`!reset` matters: Compose **appends** to a sequence like `ports` when it
merges files, so a bare `ports: []` changes nothing. And a container whose
start failed on the port is left with no network attached, which looks like
*database unreachable* even once the port is free — hence
`--force-recreate` rather than `start`.

What is lost is `psql` from the host; `docker compose exec postgres psql`
still works, and that is what every command in this runbook uses.

### Development is stricter than production here

The staff screens restore a session after a reload from the refresh cookie on
`api.<domain>`. Chrome treats `localhost` as a **public suffix**, so
`localhost` and `api.localhost` are cross-*site* in development while
`portal.x.ng` and `api.x.ng` are same-site in production — `SameSite=Lax`
withholds the cookie in the first case and sends it in the second. A hard
reload of a staff screen in development therefore lands on the sign-in page,
and in production does not.

This errs safe, and the journey sidesteps it by **clicking** through the
staff screens rather than navigating to URLs, which is what an admin does
anyway. To mirror production exactly, add

```
127.0.0.1  portal.sshms.test  api.sshms.test
```

to `/etc/hosts`, point the `Caddyfile` at those two names, and set
`PUBLIC_WEB_ORIGIN`, `NEXT_PUBLIC_SITE_URL` and `NEXT_PUBLIC_API_URL` to
match. `.test` is reserved and is not a public suffix, so the two become
same-site.

It needs a **freshly seeded** database: the journey publishes a class, and a
class can only be published once. Re-running it against a stack it has
already run against will fail at the submit step, which is correct.

The browser lives in Microsoft's Playwright image, under a compose profile,
so `docker compose up -d` never starts it. The image tag and
`web/package.json`'s `@playwright/test` version must match.

### The nav is behind a menu button at this viewport

The journey runs at a phone viewport, where §8.0's sidebar is a drawer. The
spec has `openMenu(page)` and `navigate(page, /…/)` for that, and clicks
scoped to `getByRole("main")` wherever the sidebar now shows the same name as
the page body — a teacher's own classes, and the review queue. A step that
cannot find a link it used to find is usually one of those two things and not
a regression.

---

## 5. Things that go wrong

### The suite fails everywhere at once, for no reason in the diff

Two `pytest` runs are sharing the test database. `clean_database` empties
every table between tests, so a second run truncates the first one's fixtures
mid-test and both collapse into a wall of `E`s and `F`s.

The usual cause is a **`timeout` wrapped around `docker compose exec`**:

```bash
timeout 200 docker compose exec api pytest -q      # don't
```

That kills the local client. The `pytest` inside the container keeps going,
unsupervised, and the next run collides with it. `ps` and `pgrep` are not in
the api image, so the obvious check for a stray process silently reports
nothing:

```bash
# Does not work — prints an empty line, which is not the same as "none"
docker compose exec api sh -c 'ps ax | grep -c pytest'

# Works. `[p]ytest` so the scan does not match its own command line, which
# it otherwise does — that pattern is in it.
docker compose exec api sh -c \
  'ls /proc | grep -E "^[0-9]+$" | while read p; do
     tr "\0" " " < /proc/$p/cmdline 2>/dev/null | grep -q "[p]ytest" && echo "$p"
   done'
docker compose exec api sh -c 'kill -9 <pid>'
```

Run the suite without a client-side timeout — it takes about eight minutes —
and let it finish.

### A screen takes seconds to open, and the URL bar does not even change

That is `next dev` compiling the route, not the application. The server's own
log says which one:

```bash
docker compose logs web --tail=50 | grep -E "Compiling|Compiled"
#  ○ Compiling /admin/subjects ...
#  ✓ Compiled /admin/subjects in 3.2s (503 modules)
```

A first visit to a route costs seconds; a revisit costs ~150 ms, and `<Link>`
does not prefetch in development, so every route pays it once per server
start. `npm run dev` uses Turbopack, which holds the worst case under a
second after a one-off ~15 s cache build on the first request.

In a production build there is no difference between a first visit and a
revisit — both about 100 ms (`docs/DECISIONS.md` D111 has the figures). To see
that for yourself, build the image and run it behind the same Caddy:

```bash
docker build --target prod \
  --build-arg NEXT_PUBLIC_SITE_URL=http://localhost:8080 \
  --build-arg NEXT_PUBLIC_API_URL=http://api.localhost:8080 \
  -t portal-web-perf ./web

cat > /tmp/web-prod.yml <<'YAML'
services:
  web:
    image: portal-web-perf
    build: !reset null
    environment:
      NODE_ENV: production
      INTERNAL_API_URL: http://api:8000
    volumes: !reset []
YAML

docker compose -f docker-compose.yml -f /tmp/web-prod.yml \
    up -d --force-recreate --no-deps web
docker compose up -d --force-recreate --no-deps web   # back to the dev server
```

**Both `--build-arg`s matter.** `NEXT_PUBLIC_*` values are inlined into the
client bundle at build time, and an image built without them ships the
development fallbacks (`docs/DECISIONS.md` D110).

### `next build` fails with "`<Html>` should not be imported outside of pages/_document"

The build ran with `NODE_ENV=development`, which the dev compose service sets
(`docker-compose.yml`). Next then builds against the development react-dom and
the error comes out of its pages-router fallback, naming a file nobody wrote.
The real production build is unaffected: the Dockerfile's `builder` stage and
CI both leave `NODE_ENV` alone.

So build the way production does, which is also the only build worth
believing:

```bash
docker build --target prod ./web
```

Running `next build` inside the dev container has a second problem anyway —
`.next` is a named volume shared with the running dev server, and the two
clobber each other mid-build ("Cannot find module for page …", or a missing
`.nft.json` while collecting traces).

### A parent, teacher or admin cannot sign in: "too many sign-in attempts"

§5.1's per-IP limit (A34): 20 attempts per 15 minutes per address, counting
successes. The 429 carries `Retry-After` in seconds.

It is on the **address**, not the account, so a school behind one connection
can exhaust it between them during a results week. If that happens:

```bash
# Raise it in .env and restart the API. Both keys are environment-driven
# precisely so this needs no deploy.
LOGIN_IP_MAX_ATTEMPTS=60
```

Do **not** confuse it with the account lockout, which is 5 failures and 15
minutes and returns **423**, not 429. That one clears itself, or an admin
resets the password:

```
POST /api/v1/users/{user_id}/reset-password     # returns a temporary one, once
```

### A parent says the result is not there

Three possibilities, and R12 shows the parent the same sentence for all
three, on purpose:

1. The class is not published. Check `/admin/publish`.
2. The child is **withheld**. The reason is on that screen and in the audit
   log; the parent is never shown it.
3. They are looking at the wrong term.

### A card looks wrong after a correction

R13's edit path regrades against the **snapshotted** scale, never today's
(§4.4). The previous PDF is retained, never overwritten — a correction writes
`-2.pdf` beside `-1.pdf`. If a parent has the old one, that is by design.

### The averages are wrong across the board

R3's formula is still a documented placeholder (A3, N3). If the school
confirms it:

```bash
docker compose exec api python -m app.recompute_averages --dry-run
```

It will not touch an approved class — §4.5 again.

### `/readyz` returns 503

The database is unreachable. The body names no connection detail on purpose
(D9), so look at the logs:

```bash
docker compose logs --tail 100 postgres api
```

---

## 6. Still outstanding

In rough order of how much it would hurt to be without:

1. **Off-host backups.** The dumps are on the same disk as the database.
   That covers a bad migration, a wrong `UPDATE` and a mistaken publish —
   most of what actually happens — and nothing at all if the host is lost.
   §2 has the `rclone` line; it needs the R2 account.
2. **Sentry.** §11 asks for it with PII scrubbing on. Needs an account and a
   DSN.
3. **CI has never run.** The workflow is written and complete, including the
   E2E job, but the repository has no remote yet. Everything in this runbook
   was run by hand instead.

## 7. What is not covered here

- **R2.** The seam is `app/backup.py`'s `_Store` and `app/pdf/storage.py`'s
  `LocalStore`; see D82 and D97. Swapping either is one class.
- **A second host.** §0 is one host by design. Two would need the report
  cache and the backup store to move off local disk first.
- **Rate limits beyond login.** §5.1 asks for login only. Nothing else is
  limited, and nothing else is as expensive to guess at.
