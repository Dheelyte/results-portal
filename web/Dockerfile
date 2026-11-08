# syntax=docker/dockerfile:1

FROM node:22-alpine AS base
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

# ---------------------------------------------------------------------------
# deps — install from the lockfile alone
# ---------------------------------------------------------------------------
FROM base AS deps
COPY package.json package-lock.json* ./
RUN --mount=type=cache,target=/root/.npm \
    if [ -f package-lock.json ]; then npm ci; else npm install; fi

# ---------------------------------------------------------------------------
# dev — next dev with hot reload; compose bind-mounts the source over this
# ---------------------------------------------------------------------------
FROM base AS dev
COPY --from=deps /app/node_modules ./node_modules
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev"]

# ---------------------------------------------------------------------------
# builder — production build
# ---------------------------------------------------------------------------
FROM base AS builder
# Both of these are inlined into the client bundle by `next build`, so they
# have to be present *here* — an `NEXT_PUBLIC_*` value supplied only at run
# time arrives too late and the browser gets whatever the code falls back to.
#
# `NEXT_PUBLIC_API_URL` was missing until 2026-11-08, and
# `docker-compose.prod.yml` had been passing it for milestones: an undeclared
# build arg is silently dropped, so a production image shipped
# `lib/api/client.ts`'s development fallback — `http://api.localhost:8080` —
# and every browser-side call from the staff screens would have gone nowhere.
# Nothing caught it because the server-rendered paths use
# `INTERNAL_API_URL` instead, which is read at run time and was correct.
ARG NEXT_PUBLIC_SITE_URL
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_SITE_URL=$NEXT_PUBLIC_SITE_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ---------------------------------------------------------------------------
# prod — standalone server, unprivileged user
# ---------------------------------------------------------------------------
FROM base AS prod
ENV NODE_ENV=production

COPY --from=builder /app/public ./public
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

USER node
EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0
CMD ["node", "server.js"]
