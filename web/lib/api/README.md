# Generated API client

Types and client functions in this directory are **generated from the API's
OpenAPI schema**. Never hand-write them (CLAUDE.md, Conventions).

Nothing is generated yet — the API exposes only `/healthz` and `/readyz` in
milestone 1, and the `/api/v1` surface of ARCHITECTURE.md §7 arrives with
milestone 2. The generation step is added then, along with a CI check that the
committed output matches the current schema.
