# Deploy target services in shadow mode

Owner: application operator. Database migrations additionally require the
database operator. Production execution requires a named operator and approved
change ticket. This procedure does not modify DNS, HAProxy or public routing.

## One-time host preparation

Create independent, non-login Unix users: `m-ranked-api`, `m-ranked-web`,
`m-ranked-outbox`, `m-ranked-maintenance`, `m-ranked-anomaly`, `m-ranked-backup`,
`m-ranked-backup-read`, `m-ranked-restore` and
`m-ranked-collector-{telegram,vk,max,rutube}`. Give collector users the shared
primary group `m-ranked-collector`. On DR only, use
`m-ranked-backup-readers` as the backup service's primary group and as a
supplementary group of the read-only repository account. Do not put any
application runtime user in the `postgres`, `redis`, `sudo` or deployment
group. Add only `m-ranked-anomaly` to the `node-exporter` supplementary group so
it can atomically replace its bounded analyzer textfile.

Create the separate `m-ranked-identity-readers` group on each host that stores
original identity receipts. The reverse, backup and restore units receive it
through `SupplementaryGroups`; API and collector users must **not** be members.
Their own directory ownership supplies write access without access to any other
writer's receipts. Provision the group before installing these units:

```bash
rtk sudo groupadd --system m-ranked-identity-readers
```

For an existing group, first verify its membership and purpose instead of
recreating it. The two receipt parents remain root-owned `0755`; writer leaves
use setgid `2750` with this reader group. New immutable files inherit the group
and are explicitly published as `0440`, even with service umask `0077`.

First create the trusted artifact parent before the host accepts a bundle, and
require that this release name is unused:

```bash
rtk sudo install -d -o root -g root -m 0755 /srv/m-ranked-artifacts
rtk sudo test ! -e /srv/m-ranked-artifacts/RELEASE
rtk sudo test ! -L /srv/m-ranked-artifacts/RELEASE
```

Transfer the reviewed bundle with a root-controlled workflow that creates its
files as root with safe modes; `RELEASE` must exactly equal the planned release
ID. Never upload into a user-owned directory and then recursively repair it as
root. If any unprivileged account ever owned or could rename content in the
bundle, discard that copy and restage it. Before copying any bundle file to
another privileged location, verify the root and tree without mutating them:

```bash
rtk sudo /bin/bash -p -c '
  set -Eeuo pipefail
  PATH=/usr/bin:/bin:/usr/sbin:/sbin
  release_path=/srv/m-ranked-artifacts/RELEASE
  test -d "$release_path" && test ! -L "$release_path"
  test "$(readlink -f -- "$release_path")" = "$release_path"
  test -x "$release_path/operations/scripts/deploy-shadow.sh"
  unsafe_owner="$(find "$release_path" ! -user root -print -quit)"
  unsafe_mode="$(find "$release_path" \( -type f -o -type d \) -perm /022 -print -quit)"
  unsafe_hardlink="$(find "$release_path" -type f -links +1 -print -quit)"
  test -z "$unsafe_owner"
  test -z "$unsafe_mode"
  test -z "$unsafe_hardlink"
'
```

Then install the new files without touching the legacy units:

```bash
rtk sudo install -d -o root -g root -m 0755 \
  /etc/m-ranked /etc/m-ranked/nginx /opt/m-ranked \
  /opt/m-ranked/releases /var/lib/m-ranked
rtk sudo install -d -o root -g root -m 0700 \
  /etc/m-ranked/credentials /var/lib/m-ranked/deploy-reports
rtk sudo install -d -o root -g root -m 0750 \
  /var/lib/m-ranked/release-gates /var/lib/m-ranked/migration-reports \
  /var/lib/m-ranked/migration-snapshots /var/lib/m-ranked/cutover
rtk sudo install -d -o m-ranked-api -g m-ranked-api -m 0750 \
  /var/lib/m-ranked/api
rtk sudo install -d -o root -g root -m 0755 \
  /var/lib/m-ranked/identity-receipts /var/lib/m-ranked/identity-receipts/collector
rtk sudo install -d -o m-ranked-api -g m-ranked-identity-readers -m 2750 \
  /var/lib/m-ranked/identity-receipts/admin
for platform in telegram vk max rutube; do
  rtk sudo install -d -o "m-ranked-collector-$platform" -g m-ranked-identity-readers -m 2750 \
    "/var/lib/m-ranked/identity-receipts/collector/$platform"
done
rtk sudo install -d -o m-ranked-web -g m-ranked-web -m 0750 \
  /var/lib/m-ranked/web-cache
rtk sudo install -d -o m-ranked-maintenance -g m-ranked-maintenance -m 0700 \
  /var/lib/m-ranked/maintenance
rtk sudo install -d -o m-ranked-anomaly -g m-ranked-anomaly -m 0750 \
  /var/lib/m-ranked/anomaly
rtk sudo install -d -o root -g node-exporter -m 0770 \
  /var/lib/node_exporter/textfile_collector
rtk sudo install -d -o root -g m-ranked-collector -m 0750 \
  /var/lib/m-ranked/collectors
rtk sudo install -d -o m-ranked-collector-telegram -g m-ranked-collector -m 0700 \
  /var/lib/m-ranked/collectors/telegram
rtk sudo install -d -o m-ranked-collector-vk -g m-ranked-collector -m 0700 \
  /var/lib/m-ranked/collectors/vk
rtk sudo install -d -o m-ranked-collector-max -g m-ranked-collector -m 0700 \
  /var/lib/m-ranked/collectors/max
rtk sudo install -d -o m-ranked-collector-rutube -g m-ranked-collector -m 0700 \
  /var/lib/m-ranked/collectors/rutube
rtk sudo install -o root -g root -m 0644 \
  /srv/m-ranked-artifacts/RELEASE/operations/systemd/* /etc/systemd/system/
rtk sudo install -o root -g root -m 0644 \
  /srv/m-ranked-artifacts/RELEASE/operations/nginx/proxy-common.conf \
  /srv/m-ranked-artifacts/RELEASE/operations/nginx/security-headers.conf \
  /etc/m-ranked/nginx/
rtk sudo install -o root -g root -m 0644 \
  /srv/m-ranked-artifacts/RELEASE/operations/nginx/routes/phase-0-legacy.conf \
  /etc/m-ranked/nginx/routes-active.conf
rtk sudo install -o root -g root -m 0644 \
  /srv/m-ranked-artifacts/RELEASE/operations/nginx/m-ranked-strangler.conf \
  /etc/nginx/conf.d/m-ranked-strangler.conf
rtk sudo install -o root -g root -m 0644 \
  /srv/m-ranked-artifacts/RELEASE/operations/tmpfiles.d/m-ranked-transition.conf \
  /etc/tmpfiles.d/m-ranked-transition.conf
rtk sudo systemd-tmpfiles --create /etc/tmpfiles.d/m-ranked-transition.conf
rtk sudo systemctl daemon-reload
```

These receipt commands provision a new tree. If private `0700`/`0400` receipts
already exist, stop their writers and follow the verified metadata-only
conversion in [IDENTITY_RECEIPTS.md](IDENTITY_RECEIPTS.md) before starting reverse
sync. Changing only a directory to `2750` intentionally leaves old `0400` files
unacceptable; changing contents or recursively widening the entire root is not
a migration procedure.

The tmpfiles rule recreates the fixed mode-`0600`, root-owned transition-lock
inode after every reboot. Install it from the reviewed release bundle before
the first deploy; never rerun tmpfiles provisioning, replace or delete the lock
while a transition is active.

Do not install `m-ranked-strangler.conf` beside another enabled server block for
`m.funpin.org`; on a clone, disable only the copied target test block. In
production, replacing the currently active edge file is its own approved
routing change.

Copy each
`/srv/m-ranked-artifacts/RELEASE/operations/env/*.env.example` to
`/etc/m-ranked/*.env`, remove the
`.example` suffix, review endpoints and install mode `0640`, owner `root`, group
of the corresponding service. Examples intentionally contain no passwords.

## Credential matrix

| Process | Unix user | PostgreSQL role | Secret mechanism |
|---|---|---|---|
| Spring public API | `m-ranked-api` | `api_read` | systemd config-tree credentials |
| platform collector | one user/platform | `collector_ingest` | `PGPASSFILE` credential |
| projection publisher | `m-ranked-maintenance` | `maintenance` | `PGPASSFILE` credential |
| anomaly analyzer | `m-ranked-anomaly` | `analytics_worker` | `PGPASSFILE` credential |
| cache outbox | `m-ranked-outbox` | `api_write_admin` | `PGPASSFILE` + Redis credential |
| bounded maintenance | `m-ranked-maintenance` | `maintenance` | `PGPASSFILE` credential |
| one-time database transition | database operator | `migration_owner` | libpq credential used only in the approved schema cutover |
| backup monitoring | `m-ranked-backup` | `backup` | `PGPASSFILE` credential |
| base backup/repository | DR `m-ranked-backup` | none; forced SSH to PG hosts | repository config/SSH key |
| restore repository read | DR `m-ranked-backup-read` | none | read-only repository group + forced SSH |
| WAL archive | PG-host `postgres` | local server owner | archive-only pgBackRest config/SSH key |

The outbox uses only `SELECT` plus column-limited publication-state updates, but
the frozen baseline has no dedicated outbox database role. Reusing
`api_write_admin` also exposes admin write capabilities that the worker does
not need. The final contract removes that role's historical-bootstrap execution grant, but a
dedicated least-privilege outbox role remains a future additive migration.

Systemd credentials must be regular files, never symlinks. A libpq passfile is
one line, mode `0600`, for example
`127.0.0.1:5432:mranked:collector_ingest:<secret>`. Platform session/token files
are separate per collector. A process must not receive another platform's
session or the migration-owner credential.

Each collector also gets a root-owned, mode-`0600`
`/etc/m-ranked/credentials/collector-PLATFORM-auth.env`. Systemd copies it into
the unit credential directory and passes only its path through
`COLLECTOR_PLATFORM_AUTH_FILE`; the collector's native strict loader reads at
most 16 KiB before the direct ExecStart continues. The file is UTF-8
`KEY=value`, with blank and `#` lines allowed. Unknown, duplicate or malformed
keys, group/world permission bits, symlinks, and a conflicting direct env value
fail closed. Only these keys are allowed:

- Telegram `public_web`: an empty auth file; `mtproto`: `TELEGRAM_API_ID` and
  `TELEGRAM_API_HASH` (and change `DATA_SOURCE` deliberately).
- VK: `VK_ACCESS_TOKEN` only.
- MAX: `MAX_USER_PHONE` only.
- RUTUBE: an empty auth file.

For the example's Telegram `public_web` mode and for RUTUBE, create the two
intentionally empty credentials explicitly; an MTProto deployment populates
the Telegram keys instead. Provision VK/MAX through the host secret workflow
rather than shell history:

```bash
rtk sudo install -o root -g root -m 0600 /dev/null \
  /etc/m-ranked/credentials/collector-telegram-auth.env
rtk sudo install -o root -g root -m 0600 /dev/null \
  /etc/m-ranked/credentials/collector-rutube-auth.env
```

Never put `COLLECTOR_DATABASE_URL`, `PGPASSFILE`, `PYTHONPATH`, loader variables
or shell syntax in an auth file. Telegram and MAX client session databases are
writable runtime state under `/var/lib/m-ranked/collectors/PLATFORM`, mode
`0600`, owned only by that platform's Unix user; back them up as separately
encrypted secrets. Collectors receive no Redis credential because they commit
the PostgreSQL outbox instead of publishing cache events directly.

Collectors emit `projection.rebuild.requested`, not a cache-visible revision.
They neither start nor require the projection publisher. An operator invokes
the publisher explicitly with `--once`; its systemd unit is a bounded oneshot
and is not enabled by either target. It reuses only the maintenance libpq
credential and has no platform, Redis, migration-owner or raw-payload
credential. It coalesces pending requests to the newest
`analytics.dataset_revision`, invokes the serving-only rebuild entry point,
verifies the seven serving states, including publication history, and atomically emits idempotent
`dataset.revision.changed` plus `projection.published` events. The cache relay
never claims rebuild requests or lifecycle events and delivers all other
cache-invalidation events, including the dataset event, to Redis. A stale
revision race or rebuild failure rolls back. A later explicit invocation may
retry after capacity and failure review; there is no daemon retry loop.

Before every start, `collector-preflight.sh` refuses a missing, empty, symlinked,
wrong-owner or non-`0600` Telegram MTProto/MAX session. Telegram Web mode
similarly requires an owner-writable private browser-profile directory. Perform
interactive authorization out of band as the platform Unix user; a production
systemd service must never wait for a console password or OTP.

## Database schema contract

There is one supported database shape: `storage-publisher-final-2026-09-08-r4`.
A clean PostgreSQL volume applies
`backend/src/main/resources/db/final-schema.sql` directly after role creation.
It does not create a Flyway schema or replay historical SQL files.

An existing production database is changed exactly once with
`operations/sql/transition-production-to-final.sql`. This is a separately
approved database operation, never part of application startup or a normal
deploy. Before running it, capture a current backup, prove an isolated restore,
and rehearse the same file against a production-shaped restored copy. The SQL
checks the observed source schema, runs in one transaction and refuses both an
unknown source and an already-final database.

The database operator applies the reviewed release copy with `psql
--no-psqlrc --set ON_ERROR_STOP=1` using the
`migration_owner` credential. After it commits, verify:

```sql
SELECT contract_id FROM ops_and_admin.schema_contract;
```

Only the exact value `storage-publisher-final-2026-09-08-r4` permits the new API,
collectors, Publisher and outbox worker to start. Start the application release
after the transition; never keep a compatibility mode that accepts both old
and final schemas. The existing production Flyway history table may remain as
inert audit data, but no process reads it.

## Release artifact

CI prepares one immutable directory containing:

- `backend/m-ranked-backend.jar` built on Java 21;
- `frontend/server.js`, `.next/static` and `public` copied from the Next.js
  standalone build;
- `.venv`, `collector_target` and `anomaly_analysis` with the four-platform collector CLI and independent analyzer;
- the hardened projection-publisher unit, worker and non-secret env example;
- the declarative `backend/src/main/resources/db/final-schema.sql`, the guarded
  `operations/sql/transition-production-to-final.sql`, and this `operations/` tree;
- `SYMLINKS.sha256`, with one newline-terminated, bytewise C-sorted
  `<sha256(raw symlink-target bytes)>  <relative link path>` record per shipped
  symlink (a zero-byte file when there are none), and `SHA256SUMS` covering
  exactly every shipped regular file, including `SYMLINKS.sha256`. Link paths
  must match `[A-Za-z0-9._+@%/-]+`; unescaped raw targets must match
  `[-A-Za-z0-9._+@%/=:,~]+`. An internal link's raw target must be relative and
  its first-hop parent must remain inside the release, so an external alias
  that currently points back inside is not accepted. Every link must resolve
  inside the release; the only external exceptions are `.venv/bin/python`,
  `.venv/bin/python3` and `.venv/bin/python3.13` resolving canonically to
  `/usr/bin/python3.13` or `/usr/local/bin/python3.13`.

The two database artifacts are immutable release inputs. Their SHA-256 values
are captured from the release tree in the deploy report; no per-version SQL
manifest exists.

Do not build or download dependencies as root on the production host. Do not
place `.env`, session files, private keys, database dumps or tokens in a release.
The deploy script rejects common secret/data filenames, verifies `SHA256SUMS`,
recomputes the complete `SYMLINKS.sha256` inventory, rejects missing,
retargeted, broken or escaping links and special files, then verifies the
copied tree again in a unique temporary directory before an atomic rename. It
derives the report manifest and hashes of the final schema and production transition again from the staging
tree, the installed tree, and the active tree after health checks; a
source/staging or staging/installed provenance change fails closed. A failed
copy is retained outside the release namespace for operator inspection and is
never activated.

As required by the initial preparation above, the bundle and every ancestor
must be root-owned and non-group/world-writable before anything is invoked or
installed from it. Every regular file and directory in the bundle must be
root-owned and non-group/world-writable, and regular files must have one hard
link. The deploy entrypoint requires `--release-dir` to be this exact physical
artifact root and rechecks the source and destination inode chains throughout
the operation.

On the disposable production-like clone, stage first; this changes no service
or route on that clone:

```bash
rtk sudo /srv/m-ranked-artifacts/RELEASE/operations/scripts/deploy-shadow.sh \
  --release-dir /srv/m-ranked-artifacts/RELEASE \
  --release-id RELEASE --operator OPERATOR --ticket CHANGE
```

A stage-only invocation consumes that release ID by creating its immutable
destination. It is not a first half that can later be resumed with
`--activate-shadow` for the same ID on the same host. After clone validation,
run the activation command below once on production; it performs its own fresh
staging and activation under the transition lock.

On the production-like clone, validate units and Nginx before activation:

```bash
rtk sudo systemd-analyze verify /etc/systemd/system/m-ranked-target-*.service \
  /etc/systemd/system/m-ranked-target-*.timer \
  /etc/systemd/system/m-ranked-*.target
rtk sudo nginx -t -c /etc/nginx/nginx.conf
```

Activate only the shadow services. The script validates the immutable release
manifest and both schema artifacts, then requires the database's exact
`storage-publisher-final-2026-09-08-r4` contract before it atomically moves the `current` symlink.
It checks API/Web readiness against the newest already-published serving
generation and restarts the outbox worker. It never
starts target collectors, stops legacy units or reloads Nginx.

The artifact copy of `deploy-shadow.sh` is the exceptional pre-activation
entrypoint. Its script, `transition-lock.sh` and every ancestor directory must
already be root-owned and non-group/world-writable; never run a user-writable
checkout with `sudo`. It takes the same fixed mode-`0600`
`/run/lock/m-ranked-transition.lock` on FD 8 as preflight, routing, writer
cutover and rollback and holds it through all verification, staging,
activation, health and recovery work. Contention fails closed with exit 75;
there is no environment or emergency bypass and the lock inode is never
deleted after an operation. Prohibit previously installed deploy/cutover
entrypoints that predate this guard; they cannot join the shared lock
retroactively.

```bash
rtk sudo /srv/m-ranked-artifacts/RELEASE/operations/scripts/deploy-shadow.sh \
  --release-dir /srv/m-ranked-artifacts/RELEASE \
  --release-id RELEASE --operator OPERATOR --ticket CHANGE \
  --activate-shadow --confirm DEPLOY:RELEASE:CHANGE
```

Inspect `http://127.0.0.1:18090` through an SSH tunnel. Required shadow gates are
API contract, normalized legacy/target responses, visual diff, accessibility,
constant query counts and performance budgets. A failed activation returns the
`current` symlink to the preceding target release; legacy remains untouched.

## Unit ownership

- `m-ranked-shadow.target`: target API, Web and cache-outbox only.
- `m-ranked-target.target`: post-writer-cutover target including four isolated
  collectors. The collectors are independent of publication. Never enable
  before `CUTOVER.md` Gate W.
- `m-ranked-target-projection-publisher.service`: explicit bounded `--once`
  publication under the maintenance role, protected by a process lock and a
  free-capacity guard. It never mutates ingestion facts or needs
  DDL/raw-payload privileges.
- `m-ranked-target-maintenance.timer`: creates upcoming partitions and reports
  capacity/outbox/default-partition state. Raw payload purge is disabled unless
  explicitly set to `true` after retention acceptance.
- `m-ranked-target-anomaly-analysis.service`: evaluates bounded publication
  histories through the least-privilege `analytics_worker` role. It is a
  non-core `Wants=` dependency: failure never changes the seven-projection
  readiness barrier or prevents API/core activation.
- backup/restore timers are installed on their documented primary/DR hosts.

The Web unit bind-mounts its private `/var/lib/m-ranked/web-cache` over
`frontend/.next/cache`; the immutable release remains read-only while Next.js
image/data cache writes stay disposable and isolated from other Unix users.

The collector command is exactly
`.venv/bin/python -m collector_target --platform PLATFORM --partition default`;
`--once` is reserved for controlled smoke runs. The final schema contains
independent `scheduled_at`/`collected_at` instants and the narrow identity-history
grants used by this collector runtime. It grants the authenticated admin role
collection-run reads and routes audited admin changes through the
projection-control outbox, without direct observation/raw-payload access. The final contract preserves
legacy-compatible activity-period projection semantics and the narrow runtime grant
boundary. Public readiness fails closed only when no complete seven-projection
serving generation exists. Raw ingestion may safely advance beyond that
watermark; ordinary public reads resolve the newest coherent serving
generation. Content and legacy-export projections retain independent
watermarks and are not part of readiness. The shadow API unit intentionally
receives only `api_read`; target admin activation and credentials remain a
separate parity/routing gate while legacy `/manage` owns administration.
