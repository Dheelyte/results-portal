"""Print the OpenAPI schema as JSON on stdout.

The frontend client is generated from this schema, never hand-written
(CLAUDE.md, Conventions). The schema is committed so that an API change shows
up in the diff, and so CI can prove the committed client still matches it.

    docker compose exec -T api python scripts/export_openapi.py > api/openapi.json
    cd web && npm run generate:api

Writing to stdout rather than to a file keeps the container from needing a
writable bind mount for one generated artefact.
"""

import json
import sys

from app.main import app


def main() -> int:
    # sort_keys and a trailing newline so the file is byte-stable between runs
    # and a diff means a real API change.
    sys.stdout.write(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
