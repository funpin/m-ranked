# M-Ranked frontend

Next.js 16.3.3 App Router frontend for the public Spring API. It never reads SQLite or PostgreSQL directly.

## Runtime

- `API_BASE_URL` points to the Spring origin and defaults to `http://127.0.0.1:8080`.
- `pnpm dev`, `pnpm test`, `pnpm typecheck`, and `pnpm build` are the supported local checks.
- The production build uses `output: "standalone"`; deployment must copy `.next/static` beside the standalone server as in the standard Next.js layout.
- `/manage` is intentionally client-only. HTTP Basic credentials and the CSRF token live only in the page's JavaScript memory; they are never put in URL parameters, browser storage, Next server environment variables, or server-rendered markup. Reloading, leaving, or explicitly signing out destroys the session reference.

### Admin deployment gate

The current phase-2 and phase-3 Nginx route sets deliberately keep `/manage`
on legacy and return `404` for `/api/v1/admin/**`; do not loosen those phases in
place. A future, separately reviewed admin routing phase must send `GET /manage`
to the Next upstream and `/api/v1/admin/` directly to Spring on the **same HTTPS
origin**. It must preserve the browser's `Authorization`, `Cookie`,
`X-XSRF-TOKEN`, and `X-Correlation-Id` request headers, preserve Spring's
`Set-Cookie`, `WWW-Authenticate`, `Cache-Control: no-store`, and
`application/problem+json` response headers, reject non-TLS public access, and
must not log authorization/cookie/header values or request bodies. CORS is not
part of this design; a split frontend/API origin will fail closed.

Enable that route only after Basic-auth roles, CSRF cookie path
`/api/v1/admin`, TLS forwarding, `401`/`403`/`409` behavior, rate limiting, and
operator sign-out have passed a production-like rehearsal. Viewer credentials
can inspect jobs and minimal account state, but Spring correctly denies account
mutations.

## Route compatibility

| Browser route | Spring API source | Current behavior |
|---|---|---|
| `/` | `GET /api/v1/overview` | Bounded overview, filters, search, sort, cursor pagination |
| `/rating` | `GET /api/v1/rating` | Revision-pinned legacy activity ranking: Telegram channels or VK/RUTUBE institutions plus the top 50 publications. MAX and all-platform views remain pending. The entity list is capped at 200 and reports truncation in the API metadata. |
| `/compare` | `GET /api/v1/overview` + `GET /api/v1/compare` | With `submitted=true`, Telegram reads at most 50 repeated legacy `channels` IDs, while VK/RUTUBE read repeated `institutions` IDs. The irrelevant namespace is ignored; relevant duplicates are de-duplicated in first occurrence order and unmapped IDs are omitted without substitution. Missing/false `submitted` ignores both bookmarked ID lists and uses a bounded default. Invalid or excess relevant values fail. MAX and all-platform browser views remain pending and do not call the data API. |
| `/institutions/{id}` | `GET /api/v1/institutions/{legacyId}` | Institution aggregate by platform and period |
| `/channels/{id}` | `GET /api/v1/accounts/{legacyId}?legacyType=channels` | Telegram account detail; an accepted legacy `platform` query redirects to the canonical URL |
| `/posts/{id}` | `GET /api/v1/publications/{legacyId}?legacyType=posts` | Latest Telegram measurement; `history_limit` is preserved but history is not invented |
| `/platform-posts/{id}` | `GET /api/v1/publications/{legacyId}?legacyType=platform_posts` | Latest generic-platform measurement; legacy `platform` query canonicalizes or 404s |
| `/platform-accounts/{id}` | `GET /api/v1/accounts/{legacyId}?legacyType=platform_accounts` | Account detail; linked Telegram rows retain the legacy 307-style redirect to `/channels/{id}` |
| `/manage` | Client-side same-origin `GET /api/v1/admin/csrf`, `GET /api/v1/admin/jobs[/{id}]`, `GET /api/v1/admin/platform-accounts/{id}`, `PUT /api/v1/admin/platform-accounts/{id}/enabled` | Memory-only Basic session, bounded run/account inspection, server-sourced optimistic-version confirmation; remains behind a future admin routing gate |

Detail-page publication lists, neighboring-post navigation, reaction breakdown,
the legacy comparison engagement/conversion curve, and an all-platform comparison cohort
need dedicated bounded `/api/v1` projections before parity can be claimed.

Legacy `/manage` parity is also incomplete: the bounded account-state read now
supplies the current `rowVersion` without exposing external identifiers or raw
collector evidence, but the target still cannot add/delete/edit institutions or
accounts, edit native IDs, trigger collection or M‑Rating refreshes, or show
integration/storage status.
