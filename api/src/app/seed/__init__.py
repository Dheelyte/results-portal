"""Seed data.

Two distinct things live here, and the difference matters:

**Reference data** (`reference.py`) — the subject tree, the grade bands, the
narrative sections. These are the school's real configuration, read off the
printed card. They are *seeded* so nobody meets a blank screen, and **editable
in the platform afterwards** (ARCHITECTURE.md §2.3). Seeding is idempotent and
never re-asserts a value the school has since changed.

**Demo data** (`demo.py`) — the fictional school of §10, for development and
tests. Never run against a real deployment.
"""

from app.seed.demo import seed_demo
from app.seed.reference import seed_reference

__all__ = ["seed_demo", "seed_reference"]
