"""Fixtures shared by every suite.

Database fixtures live in `tests/integration/conftest.py` — unit tests are
pure and must not be dragged through Postgres to run.
"""

import pytest

from app.auth.password import hash_password

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
