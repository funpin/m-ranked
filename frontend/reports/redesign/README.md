# Redesign validation

The completed UI passes `corepack pnpm check` with Node 24 and pnpm 11.19.0:
103 unit tests, 102 Playwright cases, lint, type generation, OpenAPI drift,
production build and every route's firstLoad budget. Six focused Python tests
also pass after retiring the integration runner's pixel-audit mode.

Browser coverage includes desktop/mobile, both themes, native forms without
JavaScript, CSRF/version payloads, confirmation/cancellation, keyboard skip
navigation and controls working while the SVG runtime is delayed. Settled
rating and management screenshots were visually reviewed at 1440×900 and
390×844. The API contracts, transports and route handlers are unchanged.

`calibration.json` records the separate frontend calibration after splitting
renderers: five cold mobile samples per route, including 207 series × 337 hours
in both comparison plots. Its build ID and fetched script hashes identify that
calibration artifact. The final build's static route sizes are recorded in
`../bundle-budget.json`; minor subsequent layout/contrast fixes are covered by
the final browser suite, not retroactively attributed to the calibration build.

| Route | LCP p75 | INP p75 | Initial JS gzip, including plots |
| --- | ---: | ---: | ---: |
| Telegram overview | 1268 ms | 64 ms | 155 KiB |
| All-platform overview | 1156 ms | 40 ms | 155 KiB |
| Telegram rating | 1200 ms | 72 ms | 155 KiB |
| Comparison, 207 series | 7240 ms | 2472 ms | 281 KiB |
| Publication history | 1076 ms | 216 ms | 299 KiB |

CLS was 0 except comparison (0.015). The comparison result reflects the accepted
SVG tradeoff and does not meet field Core Web Vitals thresholds. Route budgets
retain ordinary-route ceilings and give chart routes approximately 15% measured
headroom. The real-API mobile gate still requires its original corpus, revision,
artifact and quiet-host evidence; this synthetic calibration is not production
acceptance or a PostgreSQL integration run.
