"""The declarative base every model inherits from, plus shared column types."""

import datetime as dt
import uuid

from sqlalchemy import DateTime, MetaData, text
from sqlalchemy.orm import DeclarativeBase, mapped_column

# Predictable constraint names, so a migration can drop one by name rather than
# by whatever the database happened to generate.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for all ORM models (SQLAlchemy 2.0 style)."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def uuid_pk():
    """Primary key column.

    §4 asks for UUID v7, which Postgres gains natively in 18 and which this
    project's Postgres 16 does not have. Generation happens in Python; see
    app.models.ids.
    """
    from app.models.ids import uuid7

    return mapped_column(primary_key=True, default=uuid7)


def utc_now_column(**kwargs):
    """A timestamptz defaulting to the database's own clock.

    The default is server-side so that a row written by a migration or by psql
    is stamped the same way as one written by the application.
    """
    return mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        **kwargs,
    )


__all__ = ["Base", "uuid_pk", "utc_now_column", "dt", "uuid"]
