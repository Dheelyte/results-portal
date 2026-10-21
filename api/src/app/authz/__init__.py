"""Authorization.

Two halves, deliberately separate:

- `scope.py` — **visibility**. Builds SELECTs already filtered to the rows a
  caller may see at all. Every router builds its query from one of these; no
  router composes a raw `select()` against tenant data (CLAUDE.md rule 4).
- `policy.py` — **capability**. Answers "may this caller perform this action",
  which is a different question from "which rows exist for them".

The split matters because the two do not coincide. An admin can see every
class-subject in order to assign a teacher to it, and may not enter a single
score against it. A head teacher sees every class in order to review it, and
writes no narrative.
"""

from app.authz import policy, scope

__all__ = ["policy", "scope"]
