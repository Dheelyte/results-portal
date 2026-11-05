"""§11's pre-publication dump, and the dump itself.

§11: "nightly `pg_dump` to R2, 30 days retained, plus a dump taken
**immediately before every publish**. Results data is irreplaceable — no
teacher will rewrite 480 passages. Document and test the restore procedure;
an untested backup is not a backup."

Two halves, and they are tested separately:

- **That publication takes one**, that a failure refuses the publish, and
  that the escape hatch works. The dump itself is the recorder from
  `conftest.py` here, because the behaviour under test is publication's.
- **That the dump is real** — a genuine `pg_dump` of the suite's own
  database, checked to be a restorable archive. That is the half the sentence
  above is about, so it runs the real binary and nothing is stubbed.
"""

import datetime as dt
import os
import pathlib

import pytest
from sqlalchemy import select

from app import backup, config
from app.models import PublicationState, TermReport
from tests.integration import test_publication as publication

# The publication suite's fixtures, reused rather than rebuilt: a class
# approved, graded and ready to publish is forty lines of setup. Assigned
# rather than imported, because a fixture is registered by the name it has in
# the module that uses it.
approved_class = publication.approved_class
admin = publication.admin
parent = publication.parent

publish = publication.publish

# ---------------------------------------------------------------------------
# Publication takes one, and will not go on without it
# ---------------------------------------------------------------------------


async def test_publishing_takes_a_dump_first(client, admin, approved_class, backups) -> None:
    response = await publish(client, admin, approved_class)

    assert response.status_code == 200, response.text
    assert backups.calls == ["pre-publish"]


async def test_a_failed_dump_refuses_the_publish(
    client, admin, approved_class, backups, session
) -> None:
    """The whole point. A safety net nobody checks is not a safety net, and
    the one time it matters is the time it was missing."""
    backups.fail_with = "pg_dump exited 1."

    response = await publish(client, admin, approved_class)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "nothing was published" in detail

    # And nothing moved: the refusal is before any row is touched.
    states = await session.scalars(
        select(TermReport.state).where(TermReport.term_id == approved_class.term.id)
    )
    assert set(states) == {PublicationState.DRAFT}


async def test_the_refusal_names_no_connection_detail(
    client, admin, approved_class, backups
) -> None:
    """D9's rule, applied here: a libpq error quotes the DSN, and the DSN
    carries the password."""
    backups.fail_with = "pg_dump exited 2."

    detail = (await publish(client, admin, approved_class)).json()["detail"].lower()

    for leak in ("portal", "5432", "asyncpg", "password", "postgresql://"):
        assert leak not in detail


async def test_the_escape_hatch_publishes_without_one(
    client, admin, approved_class, backups, monkeypatch
) -> None:
    """A school whose backup store is broken on release day can still get
    results out — deliberately, and only by changing a setting."""
    backups.fail_with = "pg_dump exited 1."
    monkeypatch.setattr(config.settings, "require_prepublish_backup", False)

    response = await publish(client, admin, approved_class)

    assert response.status_code == 200, response.text
    assert response.json()["published"]


async def test_a_second_publish_takes_a_second_dump(client, admin, approved_class, backups) -> None:
    """ "Immediately before every publish" — R13's corrections mean there is
    often more than one."""
    assert (await publish(client, admin, approved_class)).status_code == 200
    assert (await publish(client, admin, approved_class)).status_code == 200

    assert backups.calls == ["pre-publish", "pre-publish"]


async def test_a_refused_publish_takes_no_dump(client, admin, approved_class, backups) -> None:
    """Withholding without a reason is refused by R12, before the dump. A
    dump per rejected click would fill the disk with nothing."""
    pupil = approved_class.pupils["Ada"].id

    response = await publish(client, admin, approved_class, withhold=[pupil], reason="  ")

    assert response.status_code == 422, response.text
    assert backups.calls == []


# ---------------------------------------------------------------------------
# The dump itself — the real pg_dump, nothing stubbed
# ---------------------------------------------------------------------------


#: The real `backup.take`, captured at import time — before `conftest.py`'s
#: autouse recorder can replace it. The tests below call this directly, so
#: they run the actual binary whatever the rest of the suite is doing.
_real_take = backup.take


@pytest.fixture
def real_backup(monkeypatch, tmp_path) -> pathlib.Path:
    """A store of this test's own for the real dumps below."""
    store = tmp_path / "backups"
    monkeypatch.setattr(config.settings, "backup_store", str(store))
    return store


def test_a_dump_is_a_restorable_archive(real_backup: pathlib.Path) -> None:
    """ "An untested backup is not a backup."

    Runs the real binary against the suite's own database and checks the
    result is something `pg_restore` will read: the custom format's magic
    header, `PGDMP`.
    """
    taken = _real_take(reason="suite")

    assert taken.size_bytes > 0
    archive = real_backup / taken.key
    assert archive.is_file(), f"expected {taken.key} under {real_backup}"
    assert archive.read_bytes()[:5] == b"PGDMP"


def test_the_dump_is_named_by_when_and_why(real_backup: pathlib.Path) -> None:
    taken = _real_take(reason="Before Restore!")

    # Sortable, UTC, and the reason flattened to something a filename can
    # hold, so the runbook can tell a nightly dump from a pre-publish one.
    assert taken.key.startswith(f"{dt.datetime.now(dt.UTC).year}/portal-")
    assert taken.key.endswith("-before-restore.dump")
    assert taken.reason == "before-restore"


def test_retention_deletes_what_has_aged_out(real_backup: pathlib.Path) -> None:
    """§11: "30 days retained"."""
    old = _real_take(reason="old")
    kept = _real_take(reason="today")

    stale = (dt.datetime.now(dt.UTC) - dt.timedelta(days=31)).timestamp()
    os.utime(real_backup / old.key, (stale, stale))

    removed = backup.prune(retain_days=30)

    assert removed == [pathlib.Path(old.key).name]
    assert not (real_backup / old.key).exists()
    assert (real_backup / kept.key).is_file()


def test_retention_of_zero_days_keeps_everything(real_backup: pathlib.Path) -> None:
    """A deployment that has not decided yet must not lose anything."""
    taken = _real_take(reason="keep-me")

    assert backup.prune(retain_days=0) == []
    assert (real_backup / taken.key).is_file()


def test_a_missing_pg_dump_is_a_clear_failure(monkeypatch, real_backup) -> None:
    """The error an operator actually sees if the image is wrong (D97).

    `subprocess.run` is made to raise what the kernel raises when the binary
    is absent, rather than emptying `PATH` — `_dump` passes a fixed `PATH` to
    the child on purpose, so that a stray `PGDATABASE` cannot redirect the
    backup, and a test that fiddled with the parent's would prove nothing.
    """

    def no_such_binary(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "pg_dump")

    monkeypatch.setattr(backup.subprocess, "run", no_such_binary)

    with pytest.raises(backup.BackupFailed) as raised:
        _real_take(reason="no-binary")

    assert "pg_dump is not installed" in str(raised.value)


def test_a_nonzero_exit_names_the_code_and_nothing_else(monkeypatch, real_backup) -> None:
    """pg_dump's stderr can quote the DSN, and the DSN carries the
    password, so a failure reports the exit code alone (D97)."""

    class Failed:
        returncode = 1
        stdout = b""
        stderr = b"connection to postgresql://portal:portal@postgres:5432/portal failed"

    monkeypatch.setattr(backup.subprocess, "run", lambda *a, **k: Failed())

    with pytest.raises(backup.BackupFailed) as raised:
        _real_take(reason="broken")

    message = str(raised.value)
    assert "exited 1" in message
    for leak in ("portal", "5432", "postgresql://", "password"):
        assert leak not in message.lower()


def test_an_empty_archive_is_not_a_backup(monkeypatch, real_backup) -> None:
    """pg_dump can exit 0 having written nothing — a full disk, usually. §11:
    "an untested backup is not a backup"."""

    class Empty:
        returncode = 0
        stdout = b""
        stderr = b""

    monkeypatch.setattr(backup.subprocess, "run", lambda *a, **k: Empty())

    with pytest.raises(backup.BackupFailed, match="empty archive"):
        _real_take(reason="empty")
