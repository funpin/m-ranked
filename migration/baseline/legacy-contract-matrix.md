# M-Ranked legacy compatibility matrix

Captured from the Python/FastAPI implementation on 2026-09-03. This file is a
contract inventory, not a proposal. The application has 26 application routes:
13 GET and 13 POST. FastAPI additionally exposes `/openapi.json`, `/docs`,
`/docs/oauth2-redirect`, and `/redoc`; `/static` is mounted separately.

## GET routes and query contract

| Route | Query parameters | Response and compatibility behavior |
|---|---|---|
| `GET /health` | none | JSON. Returns `status: "ok"` even when integration checks are unhealthy. |
| `GET /emoji/{emoji_id}` | path value must be 1-32 digits | Telegram custom-emoji image or 404. Process-local six-hour cache; only HTTPS assets on `t.me`, `*.telegram.org`, and `*.telesco.pe`; maximum accepted body 2 MB. |
| `GET /` | `period=1d`; `sort=median_reactions`; `direction`; `platform=telegram`; `q=""` with max length 200 | SSR overview. Valid periods: `3h`, `1d`, `7d`, `30d`; invalid becomes `1d`. Platform aliases: `tg` to `telegram`, `общий` to `all`; invalid becomes `telegram`. `q` is stripped. Missing sort values remain last in either direction. |
| `GET /rating` | `period=30d`; `channel_sort=engagement`; `channel_direction=desc`; `post_sort=view_share`; `post_direction=desc`; `platform=telegram` | SSR rating. Full implementations: Telegram, VK, Rutube. MAX and `all` render pending state. Directions outside `asc`/`desc` become `desc`. |
| `GET /manage` | optional `m_rating_status`, `channel_status`, `platform_status`, `institution_id:int` | SSR administration. HTTP Basic required. Missing configured password gives 503; invalid credentials give 401 and `WWW-Authenticate: Basic`. |
| `GET /institutions/{institution_id}` | `platform=all` | SSR aggregate. One selected Telegram channel redirects 307 to `/channels/{id}`; one selected non-Telegram account redirects 307 to `/platform-accounts/{id}`; missing institution is 404. |
| `GET /platform-accounts/{account_id}` | undeclared legacy `platform` is read from raw query string | SSR account. A linked Telegram account redirects 307 to its channel. Compatible legacy `platform=all` or matching platform redirects 307 to the canonical queryless URL; mismatch is 404. |
| `GET /platform-posts/{post_id}` | undeclared legacy `platform` | SSR publication. Compatible legacy value redirects 307 to canonical URL; mismatch or missing post is 404. |
| `GET /channels/{channel_id}` | undeclared legacy `platform` | SSR Telegram channel. `platform=telegram` redirects 307 to canonical URL; any other normalized platform is 404. Missing channel is a plain HTML 404. |
| `GET /posts/{post_id}` | `history_limit=100`, integer 50-1000; undeclared legacy `platform` | SSR Telegram publication. Canonical redirect/mismatch rules match channel route. Missing post is plain HTML 404. Chart loads all snapshots; history table is limited by `history_limit`. |
| `GET /compare` | repeated `channels:int`; repeated `institutions:int`; `period=72`; `include_partial=false`; `submitted=false`; `platform=telegram` | SSR comparison. Valid periods: 24, 48, 72, 168, 336 hours; invalid becomes 72. With `submitted=false`, submitted identifiers are ignored and every entity is selected. Telegram, VK, and Rutube are implemented; MAX and `all` are pending. |
| `GET /export/snapshots.csv` | `platform=telegram` | Download. Invalid platform normalizes to Telegram. `all` reads only generic `platform_*` tables and therefore omits legacy Telegram rows. |
| `GET /export/posts.csv` | `platform=telegram` | Download. Same platform behavior and Telegram omission for `all`. |

Rating sort keys and null placement are platform-specific. Telegram ranks enabled
channels (including channels with no publications) by `average`, `total`,
`engagement`, or `subscribers`; its posts accept `reactions`, `subscriber_share`,
`view_share`, or `views`. Invalid entity keys fall back to `engagement`, while an
invalid Telegram post key falls back to `reactions` (the omitted default remains
`view_share`). A Telegram ascending sort places missing values first; descending
places them last.

VK and Rutube group publications by institution and accept entity keys `average`,
`total`, `engagement`, `views`, and `subscribers`. Their post keys are
`reactions`, `views`, `comments`, `interactions`, and `view_share`; VK additionally
accepts `shares`. Invalid post keys fall back to `view_share`. Missing values are
always appended after available values in both directions. Publication results
are limited to the first 50 after sorting. Rutube's legacy table still renders
only average/total views, video count, subscribers, and video views: its clickable
`average_views` and `posts` headers are not accepted by the handler and therefore
fall back to `engagement` without showing an active sort arrow.

Overview sort keys are exact:

- Telegram: `name`, `subscribers`, `posts`, `views`, `reactions`,
  `median_reactions`, `m_rating`; default is `median_reactions`.
- `all`: `name`, `m_rating`, `coverage`, `accounts`; default is `m_rating`.
- VK/MAX/Rutube: `name`, `median_reactions`, `m_rating`, `reactions`,
  `views`, `posts`, `subscribers`; default is `median_reactions`.
- Direction defaults to ascending for `name`, descending otherwise.

Rating sort keys are exact:

- Telegram institutions: `average`, `total`, `engagement`, `subscribers`;
  publications: `reactions`, `subscriber_share`, `view_share`, `views`.
- VK/Rutube institutions: `average`, `total`, `engagement`, `views`,
  `subscribers`; publications: `reactions`, `views`, `comments`,
  `interactions`, `view_share`; VK additionally accepts `shares`.

## POST routes and form contract

Every POST requires HTTP Basic and a `csrf_token` form field equal to the
configured shared secret. Forms are `application/x-www-form-urlencoded`.
Successful mutations redirect with status 303.

| Route | Exact form fields | Success target / special validation |
|---|---|---|
| `POST /manage/m-rating/update` | `csrf_token` | `/manage?m_rating_status=updated`; exceptions redirect to `...=error`. |
| `POST /manage/channels` | `channel`, `csrf_token` | `/manage?channel_status=added`; Telegram reference is normalized and validated. |
| `POST /manage/institutions` | `name`, `short_name=""`, `csrf_token` | `platform_status=institution-added&institution_id={id}`; blank name is 400. |
| `POST /manage/institutions/{institution_id}` | `name`, `short_name`, `csrf_token` | `platform_status=institution-updated&institution_id={id}`; missing is 404. |
| `POST /manage/institutions/{institution_id}/accounts` | `telegram=""`, `vk=""`, `max_account=""`, `rutube=""`, `csrf_token` | Requires at least one nonblank account. Blank values do not remove existing accounts; nonblank values upsert/re-enable. |
| `POST /manage/platform-accounts/{account_id}/disable` | `csrf_token` | `platform_status=account-disabled&institution_id={id}`. |
| `POST /manage/platform-accounts/{account_id}/enable` | `csrf_token` | `platform_status=account-enabled&institution_id={id}`. |
| `POST /manage/platform-accounts/{account_id}/delete` | `csrf_token` | `platform_status=account-deleted&institution_id={id}`; destructive cascade. |
| `POST /manage/platform-accounts/{account_id}/native-id` | `native_id`, `csrf_token` | Updates native ID; nonblank MAX value must be numeric. |
| `POST /manage/platform-accounts` | `institution_id`, `platform`, `reference`, `title=""`, `url=""`, `csrf_token` | Only `vk`, `max`, `rutube`; Telegram is rejected here. |
| `POST /manage/channels/{channel_id}/disable` | `csrf_token` | `channel_status=disabled`; also disables linked platform account. |
| `POST /manage/channels/{channel_id}/enable` | `csrf_token` | `channel_status=enabled`; also enables linked platform account. |
| `POST /manage/channels/{channel_id}/delete` | `csrf_token` | `channel_status=deleted`; destructive removal of history and linked account. |

The current management template visibly exposes institution/account matrix
operations and M-Rating refresh. The legacy channel-add, generic
platform-account-add, and native-ID routes remain live HTTP contracts even
where the current page has no prominent form for them.

## CSV byte-level mapping

The implementation uses Python `csv.writer`'s Excel dialect: comma separator,
quote escaping, CRLF record endings. Starlette encodes the resulting string as
UTF-8; there is no BOM. Each response is advertised as CSV and has a quoted
`Content-Disposition` filename. The complete result is materialized in memory
before the response is returned.

| Route/mode | Filename | Header, in byte order |
|---|---|---|
| snapshots, Telegram | `snapshots.csv` | `канал,id_публикации,опубликовано,измерено,возраст_часов,реакций_всего,изменение_реакций,просмотры,изменение_просмотров,комментарии,изменение_комментариев,реакции_json` |
| snapshots, generic platform | `snapshots-{platform}.csv` | `площадка,вуз,аккаунт,id_публикации,опубликовано,измерено,возраст_часов,просмотры,реакции,комментарии,репосты,сырой_json` |
| posts, Telegram | `posts.csv` | `канал,id_публикации,опубликовано,полная_история,последнее_число_реакций,последнее_число_просмотров,последнее_число_комментариев,максимальный_скачок,возраст_скачка_часов` |
| posts, generic platform | `posts-{platform}.csv` | `площадка,вуз,аккаунт,id_публикации,опубликовано,тип,ссылка,последние_просмотры,последние_реакции,последние_комментарии,последние_репосты` |

Materialization path is `db.query -> list[sqlite3.Row] -> list[list] ->
StringIO -> getvalue() -> one-element StreamingResponse`; it is not streaming.

## SQLite schema mapping

All timestamps are ISO text. Boolean values are bare integers without CHECK
constraints. Scores are REAL, counters are INTEGER. The database itself does
not enforce append-only observations: rows can be updated or cascaded away.

| Table | Columns | Keys and notable constraints |
|---|---|---|
| `schema_migrations` | `version`, `applied_at` | `version` PK. |
| `channels` | `id`, `telegram_id`, `username`, `title`, `enabled`, `added_at`, `last_seen_message_id`, `last_checked_at`, `last_error`, subscriber triplet, Telegram M-Rating rank/score/period/measured, `institution_id`, `platform_account_id` | `username` NOCASE UNIQUE. The two linkage columns have no FK and no index. |
| `posts` | identity and Telegram IDs, publication/discovery times, first-observation age, history flags, baseline flag, type, album ambiguity, repost, created/deletion/missing evidence | FK `channel_id -> channels`; UNIQUE `(channel_id, logical_key)` and `(channel_id, telegram_message_id)`. |
| `post_messages` | `post_id`, `telegram_message_id` | Composite PK; post FK with DELETE CASCADE. |
| `reaction_snapshots` | measured time/bucket/age, total and breakdown JSON, raw JSON, reaction/comment/view deltas, rate, uncertainty, spike, synthetic, created | Post FK with DELETE CASCADE; UNIQUE `(post_id, measurement_bucket)`; indices on post/age, post/measured descending, measured/post. |
| `app_state` | `key`, `value` | `key` PK. Holds collector cycle markers and current M-Rating metadata. |
| `institutions` | identity/name/short name/created, current social/TG/VK/MAX/Rutube rank and score, rating period/measured | No unique institution name and no rating history table. |
| `platform_accounts` | institution/platform/external/native/user/title/url, enabled/access/data-quality, subscriber triplet, last check/error, added | FK to institution without cascade; platform CHECK; UNIQUE `(platform, external_key)`; no native-ID uniqueness. |
| `platform_posts` | account/external identity, publication/discovery/type/url, raw JSON, deletion/missing evidence, history flags, source ID, joint/additional-author/repost flags, created | Account FK with DELETE CASCADE; UNIQUE `(platform_account_id, external_id)`; account/publication index. |
| `platform_snapshots` | post, measured time/bucket/age, nullable views/reactions/comments/shares, raw JSON, created | Post FK with DELETE CASCADE; UNIQUE `(platform_post_id, measurement_bucket)`; same three access-path indices as Telegram snapshots. |

Source migrations are numbered 1 through 15. The captured local database had
versions 1 through 14 applied, so the next ordinary `initialize()` will apply
version 15 (MAX URL backfill and forced-incomplete marking for existing MAX
history). Both web and collector composition roots currently execute runtime
DDL migration with write access.

## Feature and semantic mapping

| Feature | Current implementation | Compatibility semantics to preserve |
|---|---|---|
| Telegram MTProto collection | `Collector` + Telethon reader | Albums form one logical post; counters use max, not sum; two-check deletion; no synthetic publication baseline. |
| Telegram public collection | `PublicWebCollector` | Rounded public counters; timely first discovery inserts synthetic zero at age 0; optional Telegram Web exact comments; archive/purge runs only here. |
| VK collection | `VkCollector` + `VkClient` | Joint-post canonical identity; transient zero after positive high-water mark becomes NULL with raw evidence; two-check deletion. |
| MAX collection | `MaxCollector` + user-session client | Sequential account processing, reaction breakdown, two-check deletion; comments/shares may be NULL. |
| Rutube collection | `RutubeCollector` + public client | Own long cadence; concurrent account/metric requests; shares NULL; no known-post point refresh or deletion detection. |
| Overview | SQL window bounds plus Python aggregation | Observation window is `(start, end]`; timely new posts may use zero base; otherwise two in-window snapshots are required; medians are rounded with `floor(x + 0.5)`. |
| Rating | Latest cumulative snapshot for posts published since cutoff | Telegram engagement uses reactions/subscribers. VK/Rutube interactions sum available reactions/comments/shares and divide by views. MAX is pending. |
| Compare | Per-post snapshot load, hourly as-of, fixed-cohort median | Never uses a future sample; gaps carry last known value. Full Telegram requires history-complete. `include_partial` permits late start but still requires horizon coverage. |
| Retention | gzip CSV archive then delete | Only legacy Telegram posts and only from public-web cycles; no generic-platform retention. Existing archive omits comment deltas, raw state, album members and deletion/repost evidence. |
| Web | FastAPI + Jinja SSR | Charts use Chart.js 4.4.7 from jsDelivr; CSS/JS otherwise inline. Theme key is `m-ranked-theme`. |
