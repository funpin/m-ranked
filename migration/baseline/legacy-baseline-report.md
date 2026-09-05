# M-Ranked legacy baseline report

Captured 2026-09-03 in `/Users/funpin/Documents/ChatGPT/TG-monitoring` before
the Phase A compatibility seam was introduced. All diagnostic shell commands
were run through `rtk`. No network-backed collector was invoked.

## Reproducible baseline

- Git: branch `alpha`, HEAD `a63455c` (`merge: promote beta to alpha`). Existing
  untracked migration/docs work was not modified by the audit.
- Python: project virtual environment reports 3.13.5; README contract is 3.11+.
- Test command: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q -p no:cacheprovider`.
- Result: **153 passed in 5.28 s**. Collection-only result: **153 tests in
  0.36 s**. No skip was reported.
- Dependency lock is `requirements.txt`, including FastAPI 0.116.1, Uvicorn
  0.35.0, Jinja2 3.1.6, Telethon 1.40.0, pytest 8.4.1, HTTPX 0.28.1,
  BeautifulSoup 4.13.4, Playwright 1.62.0, python-multipart 0.0.20, and PyMax at
  commit `53103f...`.

The suite uses temporary SQLite files and fake/mocked remote APIs. It covers
analytics primitives, migrations and persistence behavior, collectors,
scheduler cadence, web HTML/routes and CSV happy paths. It does not establish a
PostgreSQL/Java/Next/Redis baseline, a persistent representative golden
dataset, OpenAPI compatibility, load/memory limits, accessibility, or visual
regression. Playwright is used for Telegram Web behavior, not screenshot
comparison.

## Browser visual baseline

On 2026-09-03 the running legacy application was captured again through the
in-app Chromium browser after closing every existing tab before each viewport
change. This matters because an already-open tab keeps its previous viewport.
The browser-reported layout viewport was verified on every route as 390×844
(mobile) and 1440×900 (desktop). The files use a historical `.png` suffix but
the capture API encoded them as JPEG; consumers must detect the content type
instead of trusting the suffix.

| Route | Mobile artifact (SHA-256) | Desktop artifact (SHA-256) |
|---|---|---|
| `/?platform=telegram&period=1d` | `legacy-overview-mobile-viewport.png` (`6d7f3388…`) | `legacy-overview-desktop-viewport.png` (`259fb82d…`) |
| `/rating?platform=telegram&period=1d` | `legacy-rating-mobile-viewport.png` (`3711732b…`) | `legacy-rating-desktop-viewport.png` (`6cc87ffc…`) |
| `/compare?platform=telegram&period=24` | `legacy-compare-mobile-viewport.png` (`3b4d4f3f…`) | `legacy-compare-desktop-viewport.png` (`fa5215a9…`) |
| `/channels/35` | `legacy-channel-mobile-viewport.png` (`95ede4d5…`) | `legacy-channel-desktop-viewport.png` (`e145ae9c…`) |

Viewport screenshots and matching accessibility-oriented DOM snapshots are in
`migration/baseline/screenshots/`. On the three scrolling mobile pages,
`document.documentElement.scrollWidth` was 379 for an inner width of 390; the
channel page was exactly 390. No horizontal content overflow was observed.
These artifacts are the authoritative legacy visual baseline. Older files
without the `-viewport` suffix were captured before viewport isolation was
verified and must not be used for pixel-regression gates.

## Captured local database

`data/reactions.db` was 160 KiB and `PRAGMA quick_check` returned `ok`.

| Table | Rows |
|---|---:|
| `schema_migrations` | 14 |
| `channels` | 2 |
| `posts` | 0 |
| `post_messages` | 0 |
| `reaction_snapshots` | 0 |
| `app_state` | 3 |
| `institutions` | 2 |
| `platform_accounts` | 7 |
| `platform_posts` | 0 |
| `platform_snapshots` | 0 |

The seven enabled accounts were Telegram 2, VK 2, MAX 2, and Rutube 1. The
captured database contains no representative observations, deletions, NULL/0
cases, albums, reposts, or late histories. It is suitable for schema/state
inventory only. It had migration 14 while source code contains migration 15;
running normal initialization changes it.

## Local empty-data request measurements

These are local FastAPI `TestClient` timings, not production SLOs. “Cold” is one
first request; “warm” is the median of ten subsequent requests. Connection and
SELECT counts are top-level traced SQL statements; work inside a correlated
subquery is not counted separately.

| Request | Cold ms | Warm median ms | Connections / SELECTs |
|---|---:|---:|---:|
| `/health` | 20.898 | 15.649 | 23 / 23 |
| `/` | 31.377 | 5.792 | 6 / 6 |
| `/?platform=vk` | 31.926 | 6.704 | 7 / 7 |
| `/rating` | 17.023 | 4.418 | 4 / 4 |
| `/rating?platform=vk` | 19.831 | 2.996 | 2 / 2 |
| `/compare` | 11.904 | 3.630 | 3 / 3 |
| `/compare?platform=vk` | 13.612 | 3.630 | 3 / 3 |
| one Telegram channel | 14.009 | 5.129 | 5 / 5 |
| one VK account | 14.264 | 3.587 | 3 / 3 |
| `/export/snapshots.csv` | 3.157 | 2.216 | 1 / 1 |
| `/export/snapshots.csv?platform=all` | 3.089 | 2.203 | 1 / 1 |
| `/manage` | 194.504 | 104.412 | 6 / 6 |

The management route recursively stats the entire project directory on every
GET, which dominates its empty-data measurement.

## Coupling and scale findings

- `web/app.py` contains more than twenty raw SQL call sites and consumes
  `sqlite3.Row`. The original `platform_analytics.py` also accepted concrete
  `Database` and issued SQL directly.
- Collectors originally accepted concrete `Database`, opened connections, and
  threaded private `_conn` values through persistence methods. The Telegram
  collector also executed a raw latest-snapshot query itself.
- Compare performs an application-level N+1 access pattern: one entity list,
  one post query per selected entity, and one snapshot query per qualifying
  post: **`1 + K + P`** connections/SELECTs. For 24 entities with 50 posts this
  is 1,225 top-level calls.
- `list_platform_posts` is one statement but includes three correlated
  per-publication subqueries in addition to the latest-snapshot lookup. Several
  other latest-metric reads use correlated subqueries.
- A page is assembled from multiple independent connections, not a single
  request-scoped read transaction or common `asOf` instant.
- Channel history, compare, ratings, platform publication snapshots, and both
  exports contain unbounded materialization paths. Rating sorts every eligible
  publication in Python before slicing the top 50.
- CSV “streaming” buffers the DB result, converted rows, `StringIO`, and final
  string in memory. `platform=all` omits Telegram because Telegram observations
  remain in legacy tables.
- Overview cache is process-local and keyed by collector completion timestamp,
  not by an authoritative dataset revision. Multi-worker consistency is not
  defined.

## Analytics invariants and known contradictions

- Naive datetimes are interpreted as UTC. Ages are clamped at zero. History is
  complete when first age is less than or equal to the configured threshold.
- Delta reaction maps use the sorted union of keys, treat missing keys as zero,
  retain negative resets, and omit zero deltas.
- Hourly as-of selects the latest sample at or before each whole-hour boundary;
  it never reads a future sample. Fixed-cohort curves require both the start
  and horizon sample.
- Persisted reaction rate is `delta * 3600 / max(1, elapsed_seconds)` and may be
  negative. Uncertainty begins above 1.5 times the expected interval.
- `insert_snapshot` accepts jump thresholds but currently persists
  `spike = false`; the pure spike helper and UI fields therefore do not reflect
  newly detected spikes.
- Public Telegram alone creates a synthetic publication zero. MTProto does
  not. Generic-platform activity may infer a zero from timely first age without
  consulting `history_forced_incomplete`, while compare uses a different
  early-snapshot/full-history rule.
- Platform rating initializes total fields to zero. A metric with no supported
  samples can therefore aggregate to zero while its average remains NULL.

## Collection, retention, and deployment baseline

- One collector service process starts Telegram plus every enabled
  VK/MAX/Rutube loop. Loops are independent, non-overlapping per adapter, and
  preserve start-to-start cadence; uncaught cycle exceptions are logged and the
  loop continues.
- Measurement-bucket uniqueness supplies per-slot idempotency, but there is no
  durable collection-run table or dataset revision.
- `archive_and_purge` is called only by public Telegram collection. Generic
  observations grow indefinitely. Existing gzip CSV archives have no manifest,
  checksum, schema version, row-count verification, or restore drill.
- SQLite backup uses the backup API, `quick_check`, atomic rename/fsync, mode
  0600, and daily systemd scheduling, but retains one local copy and excludes
  sessions, environment, and archives.
- `m-ranked-web.service` and `m-ranked-collector.service` run as the same user,
  both have read/write data access, and both run runtime migrations. There is
  no separate migration role or job.
- HAProxy terminates TCP/SNI routing into nginx TLS on 8443; nginx proxies the
  application on 127.0.0.1:8090. Source defaults and `.env.example` use
  `WEB_PORT=8080`, so a fresh documented configuration does not match nginx
  without an operator override.
- Nginx sets HSTS, nosniff, referrer, and frame headers. There is no CSP; charts
  load Chart.js 4.4.7 from jsDelivr at runtime.

## Phase A exit limitation

The route/schema/report inventory and compatibility ports reduce refactor risk,
but **Phase A must not be considered complete** until a checked-in,
representative golden dataset covers at least NULL versus zero, counter resets,
deleted/recovered publications, album membership, VK joint posts, reposts,
forced-incomplete history, synthetic baseline, and reaction breakdown. That
dataset must drive route/HTML, analytics, and byte-for-byte CSV goldens before
storage or formula changes.
