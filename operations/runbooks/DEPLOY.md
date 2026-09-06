# Deploy target services in shadow mode

Owner: application operator. Database migrations additionally require the
database operator. Production execution requires a named operator and approved
change ticket. This procedure does not modify DNS, HAProxy or public routing.

## One-time host preparation

Create independent, non-login Unix users: `m-ranked-api`, `m-ranked-web`,
`m-ranked-outbox`, `m-ranked-maintenance`, `m-ranked-backup`,
`m-ranked-backup-read`, `m-ranked-restore` and
`m-ranked-collector-{telegram,vk,max,rutube}`. Give collector users the shared
primary group `m-ranked-collector`. On DR only, use
`m-ranked-backup-readers` as the backup service's primary group and as a
supplementary group of the read-only repository account. Do not put any
application runtime user in the `postgres`, `redis`, `sudo` or deployment
group.

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
| cache outbox | `m-ranked-outbox` | `api_write_admin` | `PGPASSFILE` + Redis credential |
| bounded maintenance | `m-ranked-maintenance` | `maintenance` | `PGPASSFILE` credential |
| Flyway gate | deployment operator | `migration_owner` | root/group-readable Flyway config |
| backup monitoring | `m-ranked-backup` | `backup` | `PGPASSFILE` credential |
| base backup/repository | DR `m-ranked-backup` | none; forced SSH to PG hosts | repository config/SSH key |
| restore repository read | DR `m-ranked-backup-read` | none | read-only repository group + forced SSH |
| WAL archive | PG-host `postgres` | local server owner | archive-only pgBackRest config/SSH key |

The outbox uses only `SELECT` plus column-limited publication-state updates, but
the frozen baseline has no dedicated outbox database role. Reusing
`api_write_admin` also exposes the narrow V4 collection-status/rebuild grants
that the worker does not need. This is the narrowest currently deployable role
and remains a recorded privilege gap for a future additive migration.

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
The projection publisher reuses only the maintenance libpq credential; it has
no platform, Redis, migration-owner or raw-payload credential. It coalesces
pending requests to the newest `analytics.dataset_revision`, invokes only the
current `SECURITY DEFINER` `analytics.rebuild_core_projections(bigint)` entry point,
verifies all nine named states, and atomically emits idempotent
`dataset.revision.changed` plus `projection.published` events. The cache relay
never claims rebuild requests and sends only the dataset event to Redis;
`projection.published` is recorded without a duplicate invalidation. A stale
revision race or rebuild failure rolls back and is retried with bounded backoff.

Before every start, `collector-preflight.sh` refuses a missing, empty, symlinked,
wrong-owner or non-`0600` Telegram MTProto/MAX session. Telegram Web mode
similarly requires an owner-writable private browser-profile directory. Perform
interactive authorization out of band as the platform Unix user; a production
systemd service must never wait for a console password or OTP.

## Release artifact

CI prepares one immutable directory containing:

- `backend/m-ranked-backend.jar` built on Java 21;
- `frontend/server.js`, `.next/static` and `public` copied from the Next.js
  standalone build;
- `.venv` and `collector_target` with the four-platform CLI;
- the hardened projection-publisher unit, worker and non-secret env example;
- Flyway source migrations V1–V29 and this `operations/`
  tree;
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

The migration files are immutable release inputs:

| Migration | Required SHA-256 |
|---|---|
| `V1__target_baseline.sql` | `dc0ded29c5b7b42860dbabd04988c1803900685dc074c25adf5969e8be8d9fb1` |
| `V2__rebuild_core_projections.sql` | `113e94524c6617bf59ab7dc2760615bf9c6d10538c12290400e15f85df16c7dd` |
| `V3__collector_observation_times_and_identity_grants.sql` | `5233f98d3b39db74a449b1e9852f252def1606c5982e87d40ec366275d388ad1` |
| `V4__admin_collection_run_status_grants.sql` | `d5af14bfc692e9e3b57ed257b3632fbc616cb65ba47babb2aebb1d7dea5b7e82` |
| `V5__legacy_activity_period_projection.sql` | `d56c124e2d68eb9897d3fe9d10bde0adf730ea02b84e0d7ec09660775438ea41` |
| `V6__comparison_valid_observation_hourly_projection.sql` | `4ac99091046d40345c7024d3fab96ceb779fafb836c18c6a750f748f7bd29c64` |
| `V7__activity_rating_read_grants.sql` | `95244a71a992fb8d9de387622224ddb52365120ac47c4d0cf4cbb20f4e36f0eb` |
| `V8__legacy_overview_projection.sql` | `dc855dde66a705808e1565e3f56c4555995d370805cee68ee9293ae7fa0aec9c` |
| `V9__immutable_observations_quality_archive_fence.sql` | `2e165a561c9f839ec36af5bcc4c88b967778a9f11fb69e28dc71bbe5e053db50` |
| `V10__consistent_public_queries_and_formula_guards.sql` | `126bc5263ecc56eb6a09342bc92f62bf74ef32d1bf1ca285e54454d7e9cf3b0b` |
| `V11__bridge_identity_lineage_and_reconciliation.sql` | `1e804126491b16f77be5af6db60ac45947d7ba782f5829de39f42d62f5240cff` |
| `V12__detail_history_projection.sql` | `60dc3c9fd9d4997959f5b168e12f63a9553b93146023e826a0b57b607a43b100` |
| `V13__immutable_account_identity_history.sql` | `ab306bda84d76d4239e67d33232247c1d318d306ebd183962eda5d2b2a4b2cd0` |
| `V14__public_archived_publication_text.sql` | `261c257e7816c93ea84cb7d1318b711cbb0e6c518b30df57877cef92afb5f9e6` |
| `V15__verified_source_preservation.sql` | `07891ccbeb0cfcf881b090f91c6efd2da5c0fc9fd45b49e4dc1bd9a90e15d941` |
| `V16__audited_catalog_commands.sql` | `a350e3564567c4fd9e99ff69f0b541cc5de2d8c661dbb505c9efe4abfc2b35ad` |
| `V17__legacy_csv_compatibility_projection.sql` | `44696090aabda6ba3c971aa27b933b7f31a4d9392d2266d8294e158015a52b83` |
| `V18__official_rating_commands.sql` | `481fde448839a5a164cf7aea16d9c109126f0005fb227d97ab8e2b521b4e60c9` |
| `V19__safe_health_operational_snapshot.sql` | `85cb7579c6c1c91f47a250014f4d522a4a2e9a3d785afbe490516d5b5f86a503` |
| `V20__catalog_url_and_version_compatibility.sql` | `e8e96cf550e31311a0d0b96a915c09bf4f93cec69ff3cce84b932dbd29cb4aa2` |
| `V21__legacy_period_first_observation_policy.sql` | `6270ec9827ec901728b309eb537f06ab4f2487d541bd4b8e32f92c26cc840ba8` |
| `V22__durable_legacy_csv_archive_facts.sql` | `a645b247e1fd6055e17e05636f7f0ec05ed240ac95106178fc7fdfe9d5c0921f` |
| `V23__official_rating_entity_context.sql` | `dcea6278b2c218803984d27e4828fcb8f7d42af34cf357e619b7ae93768b652c` |
| `V24__ordered_history_reaction_details.sql` | `0f0886c8804b7bc4329c7f7461322ad9eb62924412cac02b24caca06942863db` |
| `V25__safe_legacy_account_presentation.sql` | `c6497ad2f0bd4ceeb39efff48ad62cbbf625d64969cd68b15dd36e30031d7fa1` |
| `V26__independent_projection_verifier_reads.sql` | `1ff9ed8a785641972a290b7f9fcc48dff6e1130fdf7e83d0adf9e572b9b96ea8` |
| `V27__retained_disabled_platform_period_metrics.sql` | `95736d8f4d4f7be9c5904f7118b85532e508f93b6fc94130e5395fb31e92ed97` |
| `V28__identity_command_receipt_verifier_acl.sql` | `215a382daced28ca93dd6580f68c768ee050964fc57ab9591d76b63da5c83020` |
| `V29__monotonic_native_identity_transitions.sql` | `b608a4ccfa204348033203bdd9b6dd3eea2b0d79ff72f2af8fbb776687b095de` |

Do not build or download dependencies as root on the production host. Do not
place `.env`, session files, private keys, database dumps or tokens in a release.
The deploy script rejects common secret/data filenames, verifies `SHA256SUMS`,
recomputes the complete `SYMLINKS.sha256` inventory, rejects missing,
retargeted, broken or escaping links and special files, then verifies the
copied tree again in a unique temporary directory before an atomic rename. It
derives the report manifest and frozen V1-V29 hashes again from the staging
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

Activate only the shadow services. The script validates the frozen
V1–V29 hashes, runs Flyway `validate → migrate → validate`,
and then requires exactly 29 successful versioned migrations with schema
version 29 before it atomically moves the `current` symlink. It starts the projection publisher
before checking API/Web readiness, waits through the bounded activation gate
for the latest nine-state publication, and restarts the outbox worker. It never
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

- `m-ranked-shadow.target`: target API, Web, cache-outbox and continuous
  latest-revision projection publisher.
- `m-ranked-target.target`: post-writer-cutover target including four isolated
  collectors; every collector requires and starts after the publisher. Never
  enable before `CUTOVER.md` Gate W.
- `m-ranked-target-projection-publisher.service`: performs a bounded `--once`
  catch-up as `ExecStartPre`, then polls continuously under the maintenance
  role. It never mutates ingestion facts or needs DDL/raw-payload privileges.
- `m-ranked-target-maintenance.timer`: creates upcoming partitions and reports
  capacity/outbox/default-partition state. Raw payload purge is disabled unless
  explicitly set to `true` after retention acceptance.
- backup/restore timers are installed on their documented primary/DR hosts.

The Web unit bind-mounts its private `/var/lib/m-ranked/web-cache` over
`frontend/.next/cache`; the immutable release remains read-only while Next.js
image/data cache writes stay disposable and isolated from other Unix users.

The collector command is exactly
`.venv/bin/python -m collector_target --platform PLATFORM --partition default`;
`--once` is reserved for controlled smoke runs. V3 is required because it adds
independent `scheduled_at`/`collected_at` instants and the narrow identity-history
grants used by this collector runtime. V4 grants the authenticated admin role
collection-run reads plus execution of the existing audited projection rebuild,
without direct observation/raw-payload access. V5 restores legacy-compatible
activity-period projection semantics while preserving the narrow runtime grant
boundary. Public readiness fails closed when the raw latest revision does not
have all nine states ready, while ordinary public reads continue to resolve the
newest fully published nine-state snapshot. The shadow API unit intentionally
receives only `api_read`; target admin activation and credentials remain a
separate parity/routing gate while legacy `/manage` owns administration.
