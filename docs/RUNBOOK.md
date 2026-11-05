# Runbook

Operating the School Results Portal: backups, restores, the E2E journey, and
the handful of things that go wrong.

Written for whoever is on the other end of the phone when the school rings,
which may not be the person who built it. Every command here has been run.

Cross-references: `ARCHITECTURE.md` §11 for the deployment, §5.1 for the login
defences, and `DECISIONS.md` D96–D99 for why each of these works the way it
does.

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

---

## 5. Things that go wrong

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
