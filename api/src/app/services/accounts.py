"""Staff and parent accounts (ARCHITECTURE.md §5.1, §7).

§5.1: accounts are **admin-created and never self-registered**. There is no
sign-up route anywhere in this system, which is why this module exists — it is
the only way an account comes into being, apart from `app.bootstrap` creating
the very first admin.

N8, answered: pupils, users and subjects are entered by hand in the platform.
No CSV import. See docs/DECISIONS.md.
"""

import datetime as dt
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import generate_temporary_password, hash_password
from app.authz import scope
from app.models import AuditAction, GuardianPupil, Pupil, RefreshToken, User, UserRole
from app.services import audit
from app.services.errors import Conflict, Invalid
from app.services.support import all_of, integrity_guard, one_or_404

logger = logging.getLogger(__name__)

USER_FIELDS = ("role", "full_name", "email", "phone", "must_change_password", "is_active")


@dataclass(frozen=True)
class CreatedAccount:
    """A new account and its temporary password.

    The password is returned **once**, to the admin who created the account,
    and is never stored in readable form, never logged and never audited —
    `audit.FORBIDDEN_KEYS` includes it by name. If the admin loses it, the
    answer is a reset, not a lookup.
    """

    user: User
    temporary_password: str


def _normalise(email: str | None, phone: str | None) -> tuple[str | None, str | None]:
    """Trim both identifiers and turn blanks into None.

    An empty string is not a missing value to Postgres, so "" would satisfy
    the `identifier_present` CHECK while being unusable to log in with.

    Email case is left alone: `users.email` is citext, so the database already
    compares case-insensitively, and lower-casing what the admin typed would
    make the portal disagree with the school's own records.
    """
    cleaned_email = (email or "").strip() or None
    cleaned_phone = (phone or "").strip() or None
    return cleaned_email, cleaned_phone


async def list_users(
    db: AsyncSession,
    actor: User,
    *,
    role: UserRole | None = None,
    include_inactive: bool = True,
) -> Sequence[User]:
    stmt = scope.scoped_users(actor)
    if role is not None:
        stmt = stmt.where(User.role == role)
    if not include_inactive:
        stmt = stmt.where(User.is_active.is_(True))
    return await all_of(db, stmt.order_by(User.full_name))


async def get_user(db: AsyncSession, actor: User, user_id: uuid.UUID) -> User:
    return await one_or_404(db, scope.scoped_users(actor).where(User.id == user_id), "user")


async def create_user(
    db: AsyncSession,
    actor: User,
    *,
    role: UserRole,
    full_name: str,
    email: str | None = None,
    phone: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> CreatedAccount:
    """Create an account with a temporary password (§5.1).

    `must_change_password` is true, so the temporary password works exactly
    once: `auth.dependencies.get_active_user` refuses every endpoint but
    `/auth/change-password` until it has been replaced.
    """
    email, phone = _normalise(email, phone)
    if email is None and phone is None:
        # Also the `identifier_present` CHECK. Checked here so the admin reads
        # a sentence instead of a constraint name — and because a parent with
        # neither identifier cannot be told how to sign in (§5.1, A7).
        raise Invalid("Give an email address or a phone number — the account signs in with one.")

    if not full_name.strip():
        raise Invalid("Give the person's full name. It is printed on the report card.")

    temporary_password = generate_temporary_password()

    record = User(
        school_id=actor.school_id,
        role=role,
        full_name=full_name.strip(),
        email=email,
        phone=phone,
        password_hash=hash_password(temporary_password),
        must_change_password=True,
        is_active=True,
    )
    db.add(record)

    async with integrity_guard(db, "An account with that email address or phone number exists."):
        await db.flush()

    # §4.9 requires a row for every account creation.
    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.USER_CREATED,
        entity_type="user",
        entity_id=record.id,
        after=audit.snapshot(record, USER_FIELDS),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(record)

    return CreatedAccount(user=record, temporary_password=temporary_password)


async def reset_password(
    db: AsyncSession,
    actor: User,
    user_id: uuid.UUID,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> CreatedAccount:
    """Issue a fresh temporary password for someone else's account (§7).

    Every session the account holds is revoked. A reset is what an admin does
    when a parent's phone has been lost or a password has been shared around,
    and leaving the existing sessions alive would defeat it.
    """
    record = await get_user(db, actor, user_id)

    temporary_password = generate_temporary_password()
    record.password_hash = hash_password(temporary_password)
    record.must_change_password = True
    # The lockout counter is cleared too: an account locked by failed attempts
    # is exactly the account whose owner rings the school for a reset.
    record.failed_attempts = 0
    record.locked_until = None

    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == record.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=dt.datetime.now(dt.UTC))
    )

    # §4.9 requires a row for every password reset.
    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.PASSWORD_RESET,
        entity_type="user",
        entity_id=record.id,
        after={"must_change_password": True, "sessions_revoked": True},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(record)

    return CreatedAccount(user=record, temporary_password=temporary_password)


async def list_children(
    db: AsyncSession, actor: User, guardian_user_id: uuid.UUID
) -> Sequence[Pupil]:
    guardian = await get_user(db, actor, guardian_user_id)

    child_ids = (
        scope.scoped_pupils(actor)
        .with_only_columns(Pupil.id)
        .join(GuardianPupil, GuardianPupil.pupil_id == Pupil.id)
        .where(GuardianPupil.guardian_user_id == guardian.id)
    )
    return await all_of(
        db,
        scope.scoped_pupils(actor)
        .where(Pupil.id.in_(child_ids))
        .order_by(Pupil.last_name, Pupil.first_name),
    )


async def link_children(
    db: AsyncSession,
    actor: User,
    guardian_user_id: uuid.UUID,
    *,
    children: Sequence[tuple[uuid.UUID, str | None, bool]],
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Sequence[Pupil]:
    """Attach pupils to a parent account (§7, §4.1).

    Additive, matching §7's POST: calling it again with one more child adds
    that child rather than replacing the family. A guardian already linked has
    their relationship and primary flag updated, so the same call is safe to
    repeat.

    This is the link §5.2's most important filter depends on — a parent sees
    exactly the pupils named here and no others — so it is admin-only and
    audited.
    """
    guardian = await get_user(db, actor, guardian_user_id)
    if guardian.role is not UserRole.PARENT:
        raise Invalid(
            f"{guardian.full_name} is not a parent account, so children cannot be attached to it."
        )
    if not children:
        raise Invalid("Name at least one child to attach.")

    pupil_ids = [pupil_id for pupil_id, _, _ in children]
    known = {
        pupil.id
        for pupil in await all_of(db, scope.scoped_pupils(actor).where(Pupil.id.in_(pupil_ids)))
    }
    if len(known) != len(set(pupil_ids)):
        # Deliberately vague: confirming which identifier is unknown would let
        # an id be probed for existence.
        raise Invalid("One or more of those pupils does not exist.")

    # `guardian_pupils` carries no school_id of its own (§4.1) — it is a join
    # table between two tables that do — so the tenant filter comes through
    # the scoped pupil query.
    existing = {
        row.pupil_id: row
        for row in await all_of(
            db,
            select(GuardianPupil).where(
                GuardianPupil.guardian_user_id == guardian.id,
                GuardianPupil.pupil_id.in_(scope.scoped_pupils(actor).with_only_columns(Pupil.id)),
            ),
        )
    }

    for pupil_id, relationship, is_primary in children:
        row = existing.get(pupil_id)
        if row is None:
            row = GuardianPupil(guardian_user_id=guardian.id, pupil_id=pupil_id)
            db.add(row)
        row.relationship = relationship
        row.is_primary = is_primary

    async with integrity_guard(db, "That child is already attached to this account."):
        await db.flush()

    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.GUARDIAN_CHILDREN_SET,
        entity_type="user",
        entity_id=guardian.id,
        # Pupil ids, never names: CLAUDE.md keeps a pupil's identity out of
        # the log, and an id resolves for anyone entitled to resolve it.
        before={"pupil_ids": sorted(str(pid) for pid in existing)},
        after={"pupil_ids": sorted(str(pid) for pid in set(existing) | set(pupil_ids))},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()

    return await list_children(db, actor, guardian.id)


async def count_by_role(db: AsyncSession, actor: User) -> dict[UserRole, int]:
    """Accounts per role, for the admin's overview."""
    counts = dict.fromkeys(UserRole, 0)
    for user in await list_users(db, actor):
        counts[user.role] += 1
    return counts


async def parents_without_children(db: AsyncSession, actor: User) -> Sequence[User]:
    """Parent accounts with nothing attached — they would sign in to nothing."""
    linked = select(GuardianPupil.guardian_user_id)
    return await all_of(
        db,
        scope.scoped_users(actor)
        .where(User.role == UserRole.PARENT, User.is_active.is_(True), User.id.notin_(linked))
        .order_by(User.full_name),
    )


async def ensure_no_conflict(
    db: AsyncSession, actor: User, *, email: str | None, phone: str | None
) -> None:
    """Whether an identifier is already taken, for a friendlier pre-check."""
    email, phone = _normalise(email, phone)
    taken: list[str] = []
    if email is not None:
        if await db.scalar(scope.scoped_users(actor).where(User.email == email)):
            taken.append("email address")
    if phone is not None:
        if await db.scalar(scope.scoped_users(actor).where(User.phone == phone)):
            taken.append("phone number")
    if taken:
        raise Conflict(f"An account with that {' and '.join(taken)} already exists.")
