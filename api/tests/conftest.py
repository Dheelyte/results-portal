"""Fixtures shared by every suite, and the redirection that keeps the
development database safe.

Database fixtures live in `tests/integration/conftest.py` — unit tests are
pure and must not be dragged through Postgres to run.
"""

# --- The redirection, before anything imports app.db ----------------------
# `app.db` builds its engine at import time from `settings.dsn`, so the only
# way to point the suite elsewhere is to change the environment before that
# import happens.  This is the first module pytest loads, which makes here the
# one place it can be done.
#
# Why it matters: `clean_database` empties every table between tests.  Resolved
# from the same `.env` the application uses, that is the school's data
# (docs/DECISIONS.md D46).
import os

from sqlalchemy import make_url

from app import config

os.environ["DATABASE_URL"] = config.settings.test_dsn

# The suite declares itself as the test environment, which does two things:
# `Settings.test_dsn` above is already resolved, and `auth/password.py` picks
# its cheap Argon2 profile. Several hundred logins at the production cost of
# 725 ms each is four minutes of hashing and nothing else
# (docs/DECISIONS.md D61).
#
# `test` is not `production`, so nothing else changes: the only other branch
# on this setting is `is_production`, which governs the OpenAPI routes and the
# Secure cookie flag, and both behave as they do in development.
os.environ["APP_ENV"] = "test"
config.get_settings.cache_clear()
config.settings = config.get_settings()

# A belt-and-braces check rather than a comment: if the redirection above ever
# stops working, the suite refuses to start instead of deleting rows.
_resolved = make_url(config.settings.dsn).database
if not (_resolved or "").endswith("_test"):
    raise RuntimeError(
        f"Refusing to run: the suite would use the database {_resolved!r}, whose name "
        "does not end in '_test'. Set TEST_DATABASE_URL to a throwaway database."
    )

import pytest  # noqa: E402

from app.auth.password import hash_password  # noqa: E402

# Long enough to satisfy the change-password rule, so one constant serves
# every test.
TEST_PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="session")
def password_hash() -> str:
    """Hash the test password once.

    Argon2id is deliberately slow. Hashing per user per test would add minutes
    to the suite for no coverage.
    """
    return hash_password(TEST_PASSWORD)
