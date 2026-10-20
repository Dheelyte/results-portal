"""Create the first school and the first admin.

§5.1 says accounts are created by an admin and never self-registered, which
leaves no way to create the *first* one. This is that way, and it is
deliberately a command rather than an endpoint: an unauthenticated
"create an admin" route is a back door, however carefully guarded.

    docker compose exec api python -m app.bootstrap \
        --school "Self-Starters House Montessori School" \
        --short-name "SSHMS" \
        --admin-name "..." \
        --admin-email "..."

Refuses to run if an admin already exists. Prints a temporary password once;
it is not stored anywhere in readable form and cannot be shown again.

Nothing here is seed data. Every value comes from the caller, per the
no-hardcoding rule (ARCHITECTURE.md §2.3).
"""

import argparse
import asyncio
import sys

from sqlalchemy import func, select

from app.auth.password import generate_temporary_password, hash_password
from app.db import SessionLocal
from app.models import AuditAction, School, User, UserRole
from app.services import audit


async def bootstrap(
    *,
    school_name: str,
    short_name: str,
    admin_name: str,
    admin_email: str | None,
    admin_phone: str | None,
) -> str:
    """Create the school and its first admin. Returns the temporary password."""
    if not admin_email and not admin_phone:
        raise SystemExit("error: the admin needs an --admin-email or an --admin-phone.")

    async with SessionLocal() as session:
        existing = await session.execute(
            select(func.count()).select_from(User).where(User.role == UserRole.ADMIN)
        )
        if existing.scalar_one() > 0:
            raise SystemExit(
                "error: an admin already exists. Create further accounts through the platform."
            )

        school = await session.scalar(select(School).limit(1))
        if school is None:
            school = School(name=school_name, short_name=short_name)
            session.add(school)
            await session.flush()
            await audit.record(
                session,
                school_id=school.id,
                action=AuditAction.SCHOOL_CREATED,
                entity_type="school",
                entity_id=school.id,
                after={"name": school_name, "short_name": short_name},
                reason="bootstrap",
            )

        temporary_password = generate_temporary_password()
        admin = User(
            school_id=school.id,
            role=UserRole.ADMIN,
            email=admin_email,
            phone=admin_phone,
            full_name=admin_name,
            password_hash=hash_password(temporary_password),
            must_change_password=True,
        )
        session.add(admin)
        await session.flush()

        await audit.record(
            session,
            school_id=school.id,
            actor_id=admin.id,
            action=AuditAction.USER_CREATED,
            entity_type="user",
            entity_id=admin.id,
            after={"role": UserRole.ADMIN.value, "full_name": admin_name},
            reason="bootstrap",
        )
        await session.commit()

    return temporary_password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.bootstrap",
        description="Create the first school and admin account.",
    )
    parser.add_argument("--school", required=True, help="Full school name.")
    parser.add_argument("--short-name", required=True, help="Short name, e.g. SSHMS.")
    parser.add_argument("--admin-name", required=True, help="The admin's full name.")
    parser.add_argument("--admin-email", help="The admin's email address.")
    parser.add_argument("--admin-phone", help="The admin's phone number.")
    args = parser.parse_args(argv)

    password = asyncio.run(
        bootstrap(
            school_name=args.school,
            short_name=args.short_name,
            admin_name=args.admin_name,
            admin_email=args.admin_email,
            admin_phone=args.admin_phone,
        )
    )

    # stdout, not the logger: the JSON log goes wherever logs go, and this must
    # not. Shown once, never recoverable.
    print("\nAdmin account created.")
    print(f"  Temporary password: {password}")
    print("\nIt is shown once and cannot be recovered. The admin must change it on first sign-in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
