"""Password hashing with Argon2id (ARCHITECTURE.md §5.1).

Pure functions over strings — no database, no request context — so the rules
that use them stay testable in isolation.
"""

import secrets
import string

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2-cffi's defaults are the RFC 9106 low-memory profile: Argon2id,
# time_cost=3, memory_cost=64MiB, parallelism=4. Appropriate for a login path
# on a single modest host; raising memory_cost would slow results-night logins
# for every parent at once.
_hasher = PasswordHasher()

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
