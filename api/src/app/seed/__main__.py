"""Seed the development database.

    docker compose exec api python -m app.seed

Refuses to run if the database already holds pupils — this is development and
test data, never something to point at a real deployment.
"""

import asyncio
import sys

from app.db import SessionLocal
from app.seed.demo import DEMO_PASSWORD, seed_demo


async def run() -> dict[str, int]:
    async with SessionLocal() as session:
        return await seed_demo(session)


def main() -> int:
    try:
        counts = asyncio.run(run())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Demo data created:")
    for name, count in counts.items():
        print(f"  {name:<20} {count}")
    print(f"\nEvery demo account signs in with: {DEMO_PASSWORD}")
    print("  admin@sshms.test · head@sshms.test · teacher1-3@sshms.test · parent1-8@sshms.test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
