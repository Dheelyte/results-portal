# CLAUDE.md — School Results Portal

Read `docs/ARCHITECTURE.md` before writing code. It is the specification; this
file is how you work.

## What this is

A results portal for Self-Starters House Montessori School, built by HSD
Technologies. ~500 pupils, ~450 accounts, three result releases a year. Small,
and it must be correct.

## Stack

FastAPI (Python 3.12, async) · SQLAlchemy 2.0 + asyncpg · Alembic · Pydantic v2 ·
PostgreSQL 16 · Next.js 15 App Router + TypeScript + Tailwind · WeasyPrint ·
Docker Compose.

## Rules

1. **Follow the build order** in ARCHITECTURE.md §12. Finish a milestone green
   before starting the next. Do not jump ahead to the interesting parts.
2. **Business rules live in `api/src/app/services/`.** Never in a router, never
   in a React component, never duplicated across both.
3. **Every schema change is an Alembic migration.** Never edit a model without
   generating and reviewing the migration. Never hand-edit the database.
4. **Authorization comes from `authz/scope.py`.** No router builds a raw
   `select()` against tenant data. Every query is filtered by `school_id` and by
   the caller's scope.
5. **Never compute or display class position.** The school does not rank pupils.
6. **Never recompute a grade on a published result.** Grades are snapshotted at
   approval. See ARCHITECTURE.md §4.4.
7. **Ask before changing the data model or adding a dependency.** Both are
   expensive to reverse.
8. **No new infrastructure.** No Redis, Celery, Kafka, Keycloak, microservices,
   or GraphQL. If you believe one is genuinely needed, write the case in
   `docs/DECISIONS.md` and ask first.
9. **Do not invent requirements.** ARCHITECTURE.md §13 lists what is still
   undecided and §14 the assumptions already in force. Stop and ask; do not
   guess and build. If you must assume something to keep moving, add it to §14
   with its cost to reverse — never bury it in code.
10. **Tests are part of the work, not a later milestone.** A rule in §6 ships
    with its unit test. An endpoint ships with its authorization tests.

## Commands

```bash
docker compose up -d                              # full stack
docker compose exec api alembic upgrade head      # migrations
docker compose exec api alembic revision --autogenerate -m "..."
docker compose exec api pytest                    # all tests
docker compose exec api pytest tests/unit -q      # fast loop
docker compose exec api python -m app.seed        # demo data
docker compose exec api python -m app.recompute_averages --dry-run   # R3
docker compose exec api pytest tests/integration/test_report_card.py \
    --golden-update                               # rewrite the card's golden text (§9)
docker compose exec api python -m app.backup      # §11's dump; --prune-only for retention
cd web && npm run dev                             # frontend (Turbopack; D111)
cd web && npm run dev:webpack                     # the same on webpack
cd web && npm run typecheck && npm run lint && npm test

# §10's E2E journey. Needs a freshly seeded database and its own container,
# behind a compose profile — docs/RUNBOOK.md §4 has the whole sequence.
docker compose --profile e2e run --rm e2e

# §8.0's shell and every route behind it. Re-runnable against any seeded
# stack, which is what to reach for after a change to the interface.
docker compose --profile e2e run --rm e2e npx playwright test e2e/navigation.spec.ts
```

## Conventions

- Python: `ruff` + `ruff format`, full type hints, `async def` throughout.
- SQLAlchemy 2.0 style only — `Mapped[]` / `mapped_column()`, no legacy `Query`.
- Pydantic: separate `Create`, `Update` and `Read` schemas. Never expose an ORM
  model directly.
- Money-free, but all scores are `numeric(5,2)`. Never `float` for a score.
- Timestamps `timestamptz`, stored UTC, rendered `Africa/Lagos`.
- Frontend types are generated from the OpenAPI schema into `web/lib/api/`.
  Never hand-write them.
- Commit messages: `area: what changed` (e.g. `results: enforce attendance bound`).

## Never log or expose

Scores, comments, tokens, password hashes, or a pupil's identity in logs or
error messages. PDFs are served only through short-lived signed URLs.

## Operations

`docs/RUNBOOK.md` is how this is run: backups and the restore procedure
(§11), the E2E journey, and what to do when a sign-in is refused or a parent
says a result is missing. Keep it true — every command in it has been run,
and that is the only reason it is worth having.

## When you finish a milestone

Run the full test suite, then write a short entry in `docs/DECISIONS.md`
covering anything you decided that the spec did not settle.
