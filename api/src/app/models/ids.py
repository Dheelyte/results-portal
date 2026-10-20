"""UUID version 7 primary keys (ARCHITECTURE.md §4).

Python 3.12's `uuid` module stops at version 5, and Postgres 16 has no native
`uuidv7()` — that arrives in Postgres 18. So generation happens here.

This is implemented rather than taken as a dependency: RFC 9562 §5.7 specifies
the layout exactly, it is twenty lines, and the alternative is another package
in the dependency tree for one function (CLAUDE.md rule 7).

Why version 7 rather than 4: a v7 value begins with a millisecond timestamp, so
rows inserted together sort together. That keeps B-tree index pages dense,
where random v4 keys scatter inserts across the whole index. At this scale it
is not a performance necessity — it is simply free, and it makes
`ORDER BY id` a meaningful approximation of insertion order.
"""

import secrets
import time
import uuid

_VERSION = 0x7
_VARIANT_RFC4122 = 0b10


def uuid7() -> uuid.UUID:
    """A UUID version 7, per RFC 9562 §5.7.

    Layout, most significant bit first:

        48 bits  unix timestamp in milliseconds
         4 bits  version (7)
        12 bits  random
         2 bits  variant (0b10)
        62 bits  random

    Values generated within the same millisecond are ordered randomly relative
    to each other. RFC 9562 permits using the 12 random bits as a counter to
    make that monotonic; at a few hundred writes a day it would buy nothing.
    """
    unix_ts_ms = time.time_ns() // 1_000_000

    random_bits = secrets.randbits(74)
    rand_a = random_bits >> 62
    rand_b = random_bits & ((1 << 62) - 1)

    value = (unix_ts_ms & ((1 << 48) - 1)) << 80
    value |= _VERSION << 76
    value |= rand_a << 64
    value |= _VARIANT_RFC4122 << 62
    value |= rand_b

    return uuid.UUID(int=value)


def timestamp_of(value: uuid.UUID) -> float:
    """The embedded creation time of a v7 UUID, as a Unix timestamp in seconds.

    Useful in tests and when auditing; not used in application logic, because a
    timestamp column is explicit where an embedded one is a trick.
    """
    if value.version != 7:
        raise ValueError(f"not a version 7 UUID: version {value.version}")
    return (value.int >> 80) / 1000.0
