"""UUID version 7 primary keys (ARCHITECTURE.md §4)."""

import time
import uuid

import pytest

from app.models.ids import timestamp_of, uuid7


def test_version_and_variant_are_correct() -> None:
    """RFC 9562 §5.7: version nibble 7, variant bits 0b10."""
    value = uuid7()

    assert value.version == 7
    assert (value.int >> 62) & 0b11 == 0b10


def test_the_embedded_timestamp_is_now() -> None:
    assert abs(timestamp_of(uuid7()) - time.time()) < 2.0


def test_values_are_unique() -> None:
    assert len({uuid7() for _ in range(10_000)}) == 10_000


def test_values_sort_by_creation_time() -> None:
    """The reason for v7 over v4: inserts land together in the index."""
    first = uuid7()
    time.sleep(0.005)
    second = uuid7()

    assert first < second
    assert str(first) < str(second)


def test_timestamp_of_rejects_other_uuid_versions() -> None:
    with pytest.raises(ValueError, match="version 4"):
        timestamp_of(uuid.uuid4())
