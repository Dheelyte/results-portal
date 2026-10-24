"""Password hashing with Argon2id (ARCHITECTURE.md §5.1).

Pure functions over strings — no database, no request context — so the rules
that use them stay testable in isolation.
"""

import secrets
import string

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import settings

# argon2-cffi's defaults are the RFC 9106 low-memory profile: Argon2id,
# time_cost=3, memory_cost=64MiB, parallelism=4. Appropriate for a login path
# on a single modest host; raising memory_cost would slow results-night logins
# for every parent at once.
#
# Measured on the development host (4 cores): **725 ms per verification**.
# That is the intended cost of a password hash, and it is also a capacity
# figure worth knowing — see `docs/DECISIONS.md` D61, which asks for it to be
# measured on the real host before launch. Lowering it is a security decision
# and belongs with the school, not here.
PRODUCTION_PARAMETERS: dict[str, int] = {}

# Under `APP_ENV=test` only. The suite performs several hundred logins, and at
# 725 ms each that is four minutes of Argon2 and nothing else. These numbers
# are deliberately too weak for anything real: `test_password.py` asserts that
# any other environment gets the profile above, so the weakening cannot leak
# into development, let alone production.
TEST_PARAMETERS = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


def hasher_for(app_env: str) -> PasswordHasher:
    """The hasher for an environment. One place, so the choice is auditable."""
    if app_env == "test":
        return PasswordHasher(**TEST_PARAMETERS)
    return PasswordHasher(**PRODUCTION_PARAMETERS)


_hasher = hasher_for(settings.app_env)

# Unambiguous alphabet: no O/0, l/1/I. Temporary passwords get read aloud over
# the phone and copied off a WhatsApp message (§5.1), and "was that an ell or a
# one" is a support call.
_TEMPORARY_ALPHABET = "".join(c for c in string.ascii_letters + string.digits if c not in "O0lI1o")


def hash_password(password: str) -> str:
    """Hash a password for storage. The result embeds its own parameters."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Whether the password matches the hash.

    Returns False rather than raising on a mismatch or a corrupt hash, so no
    caller can accidentally turn a failed login into a 500 that distinguishes
    "wrong password" from "malformed hash".
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Whether a stored hash was made with weaker parameters than current.

    Checked on successful login: if the cost parameters are raised later,
    accounts migrate as their owners sign in rather than all at once.
    """
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        # Unreadable hashes cannot be rehashed from a hash alone; an admin
        # reset is the only route. Do not claim it can be fixed here.
        return False


def generate_temporary_password(length: int = 12) -> str:
    """A temporary password for a newly created or reset account (§5.1).

    Paired with `must_change_password = True`, so it is only ever used once.
    """
    if length < 8:
        raise ValueError("temporary passwords must be at least 8 characters")
    return "".join(secrets.choice(_TEMPORARY_ALPHABET) for _ in range(length))
