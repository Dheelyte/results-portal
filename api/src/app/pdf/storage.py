"""Where a generated card is kept (ARCHITECTURE.md §9, §11).

§9 fixes the object key:

    reports/{session}/{term}/{admission_number}-{version}.pdf

and §11's diagram puts the bucket in R2. This module is the seam between the
two, and for now it writes to a directory on the host.

**Why not R2 yet.** §0 is a single host and §2.1 says to generate on demand
and cache the artifact; a bucket adds an account, a credential, a network
dependency on the results-night path and — in development — a MinIO container
nobody asked for (CLAUDE.md rule 8). The interface below is the whole of what
an R2 implementation would have to satisfy: `put`, `get`, `exists`. Swapping
it is a settings change and one class (docs/DECISIONS.md D82).

**Why the key still matters.** It is versioned because R13 requires it: "the
previously published PDF is retained, never overwritten". A correction writes
`-2.pdf` beside `-1.pdf`, and the old card stays exactly as the parent
received it.
"""

import logging
import pathlib
import re

logger = logging.getLogger(__name__)

# Anything that is not one of these is replaced, because an admission number
# is typed by a person and §9's key becomes a filesystem path here and an
# object key in a bucket later. "SSHMS/2026/004" would otherwise create
# directories.
UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe(part: str) -> str:
    """One path segment, with anything surprising flattened to a hyphen."""
    cleaned = UNSAFE.sub("-", part.strip()).strip("-.")
    return cleaned or "unknown"


def object_key(*, session_name: str, term: str, admission_number: str, version: int) -> str:
    """§9's key, exactly: reports/{session}/{term}/{admission}-{version}.pdf."""
    return f"reports/{safe(session_name)}/{safe(term)}/{safe(admission_number)}-{version}.pdf"


class LocalStore:
    """The artifact cache, as a directory.

    Deliberately small. Everything above it — the signed URL, the version in
    the key, who may ask for a card — is decided elsewhere, so replacing this
    with a bucket touches nothing but these three methods.
    """

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root

    def _path(self, key: str) -> pathlib.Path:
        # `object_key` builds every key this sees, but a path join is the one
        # place a traversal would be unrecoverable, so it is checked here too.
        candidate = (self.root / key).resolve()
        if not candidate.is_relative_to(self.root.resolve()):
            raise ValueError("object key escapes the store")
        return candidate

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def put(self, key: str, content: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written beside and moved into place, so a reader never sees a
        # half-written card — regeneration happens while parents are reading.
        temporary = path.with_suffix(".part")
        temporary.write_bytes(content)
        temporary.replace(path)
        logger.info("report stored", extra={"key": key, "bytes": len(content)})
        return key

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.is_file() else None
