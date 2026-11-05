"""Database backups (ARCHITECTURE.md §11, docs/DECISIONS.md D97).

§11, in full: "nightly `pg_dump` to R2, 30 days retained, plus a dump taken
immediately before every publish. Results data is irreplaceable — no teacher
will rewrite 480 passages. Document and test the restore procedure; an
untested backup is not a backup."

So there are two callers:

- `python -m app.backup`, from the host's crontab — see `docs/RUNBOOK.md`.
- `services/publication.py`, before it publishes a class. Publication is the
  moment the data becomes something parents have seen, and R13's correction
  path rewrites rows; a dump taken a moment earlier is the only way back.

**Where it goes.** A directory, as the report cache does, and for the same
reason: §0 is a single host, and a bucket adds an account, a credential and a
network dependency on the results-night path (CLAUDE.md rule 8). `_Store`
below is the whole surface R2 would have to satisfy — `put`, `list`, `delete`
— and §11's diagram is where it goes next.

**Why `pg_dump` and not a filesystem snapshot.** A dump is restorable onto a
different host and a different Postgres patch level, which is the situation a
restore actually happens in. `-Fc` (custom format) is used because it is
compressed and `pg_restore` can read a single table out of it, which matters
when the thing to undo is one class's publication rather than the whole term.
"""

import argparse
import dataclasses
import datetime as dt
import logging
import pathlib
import re
import subprocess
import sys

from sqlalchemy import make_url

from app.config import get_settings

logger = logging.getLogger(__name__)

#: §11: "30 days retained".
DEFAULT_RETAIN_DAYS = 30

#: What a dump is called, **relative to the store** — which is already a
#: directory of nothing but backups, so the key does not repeat the word. UTC
#: and sortable, so `ls` is newest-last and a lexicographic comparison is a
#: chronological one. A year of subdirectories keeps `ls` readable after the
#: first few hundred.
KEY_FORMAT = "%Y/portal-%Y%m%dT%H%M%SZ"

#: The reason is part of the filename, so the runbook can tell a nightly dump
#: from the one taken before a publish without opening anything.
SAFE_REASON = re.compile(r"[^a-z0-9-]+")

#: pg_dump writes a warning to stderr for perfectly good dumps (unsupported
#: ACLs on an extension, typically), so a non-zero exit is the only failure
#: signal that means anything.
DUMP_TIMEOUT_SECONDS = 600


class BackupFailed(RuntimeError):
    """The dump did not happen. The message is safe to show an admin.

    Never carries pg_dump's stderr verbatim: a connection error from libpq
    includes the DSN, and the DSN includes the password.
    """


@dataclasses.dataclass(frozen=True, slots=True)
class Backup:
    key: str
    size_bytes: int
    taken_at: dt.datetime
    reason: str


def reason_slug(reason: str) -> str:
    cleaned = SAFE_REASON.sub("-", reason.strip().lower()).strip("-")
    return cleaned or "manual"


class _Store:
    """The backup directory. Three methods, so R2 can replace it."""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root

    def put(self, key: str, content: bytes) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written aside and moved into place, so a half-written dump is never
        # mistaken for a backup — which is precisely the failure §11 means by
        # "an untested backup is not a backup".
        temporary = path.with_name(path.name + ".part")
        temporary.write_bytes(content)
        temporary.replace(path)

    def list(self) -> list[pathlib.Path]:
        if not self.root.is_dir():
            return []
        return sorted(p for p in self.root.rglob("*.dump") if p.is_file())

    def delete(self, path: pathlib.Path) -> None:
        path.unlink(missing_ok=True)


def store() -> _Store:
    return _Store(get_settings().backup_store_path)


def _libpq_url(dsn: str) -> str:
    """The application's DSN as something libpq understands, **without** the
    password.

    SQLAlchemy's `postgresql+asyncpg://` is not a libpq URL; pg_dump wants
    `postgresql://`. The password is stripped here and supplied through
    `PGPASSWORD` instead, because argv is what `ps` shows to anyone on the
    host.
    """
    url = make_url(dsn).set(drivername="postgresql")
    return url.set(password=None).render_as_string(hide_password=False)


def _dump(dsn: str) -> bytes:
    """Run pg_dump and return the archive.

    Held in memory: this school's dump is a few megabytes, and buffering it
    means `_Store.put` can write-then-rename, so a dump is either complete or
    absent.
    """
    url = make_url(dsn)
    environment = {
        "PGPASSWORD": url.password or "",
        # pg_dump needs nothing else from the environment, and passing less
        # means a stray PGDATABASE cannot redirect the backup.
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    command = [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        f"--dbname={_libpq_url(dsn)}",
    ]

    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            command,
            capture_output=True,
            env=environment,
            timeout=DUMP_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise BackupFailed(
            "pg_dump is not installed in this image. §11's backups need the "
            "postgresql-client package; see api/Dockerfile."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise BackupFailed(f"pg_dump did not finish within {DUMP_TIMEOUT_SECONDS}s.") from exc

    if completed.returncode != 0:
        # The exit code only. pg_dump's stderr can contain the DSN, and the
        # DSN contains the password.
        logger.error("pg_dump failed", extra={"returncode": completed.returncode})
        raise BackupFailed(
            f"pg_dump exited {completed.returncode}. The server log has the exit code; "
            "run it by hand from the api container to see why."
        )

    if not completed.stdout:
        raise BackupFailed("pg_dump produced an empty archive.")

    return completed.stdout


def take(*, reason: str, retain_days: int = DEFAULT_RETAIN_DAYS) -> Backup:
    """Dump the database, store it, and prune what has aged out.

    Synchronous on purpose. It shells out to pg_dump and writes a file; there
    is nothing to await, and a caller inside a request wants to know whether
    it worked before it goes on (see `services/publication.py`).
    """
    settings = get_settings()
    taken_at = dt.datetime.now(dt.UTC)
    key = f"{taken_at.strftime(KEY_FORMAT)}-{reason_slug(reason)}.dump"

    archive = _dump(settings.dsn)
    keeper = store()
    keeper.put(key, archive)

    logger.info(
        "database backed up",
        extra={"key": key, "bytes": len(archive), "reason": reason_slug(reason)},
    )

    pruned = prune(retain_days=retain_days)
    if pruned:
        logger.info("old backups pruned", extra={"removed": len(pruned)})

    return Backup(key=key, size_bytes=len(archive), taken_at=taken_at, reason=reason_slug(reason))


def prune(*, retain_days: int = DEFAULT_RETAIN_DAYS) -> list[str]:
    """Delete dumps older than the retention window (§11: 30 days).

    By the file's own modification time rather than by parsing its name: a
    dump copied or restored from elsewhere should still age out, and a name
    this code did not write should not be trusted to say when it was made.
    """
    if retain_days <= 0:
        return []

    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=retain_days)
    keeper = store()
    removed: list[str] = []

    for path in keeper.list():
        modified = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.UTC)
        if modified < cutoff:
            keeper.delete(path)
            removed.append(path.name)

    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.backup",
        description="Dump the database and prune old dumps (ARCHITECTURE.md §11).",
    )
    parser.add_argument(
        "--reason",
        default="nightly",
        help="Why this dump was taken; becomes part of the filename.",
    )
    parser.add_argument(
        "--retain-days",
        type=int,
        default=DEFAULT_RETAIN_DAYS,
        help="Delete dumps older than this. 0 keeps everything.",
    )
    parser.add_argument(
        "--prune-only",
        action="store_true",
        help="Apply the retention window without taking a new dump.",
    )
    arguments = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        if arguments.prune_only:
            removed = prune(retain_days=arguments.retain_days)
            print(f"pruned {len(removed)} backup(s)")
            return 0

        backup = take(reason=arguments.reason, retain_days=arguments.retain_days)
    except BackupFailed as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        return 1

    print(f"{backup.key}  {backup.size_bytes} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
