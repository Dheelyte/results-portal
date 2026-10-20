# Generated API client

`schema.d.ts` is **generated from the API's OpenAPI schema**. Never hand-write
or hand-edit it (CLAUDE.md, Conventions).

## Regenerating

After any change to a route or a Pydantic schema:

```bash
docker compose exec -T api python scripts/export_openapi.py > api/openapi.json
docker compose exec -T web npm run generate:api
```

Both `api/openapi.json` and `schema.d.ts` are committed, so an API change shows
up in the diff rather than only in a running container. CI regenerates both and
fails if they differ from what is committed — which is how a forgotten
regeneration gets caught.
