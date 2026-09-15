# Deploy M-Ranked

Owner: application operator. Database bootstrap/restore requires a database
operator. Commands below assume an immutable release at
`/opt/m-ranked/releases/<release>` and symlink `/opt/m-ranked/current`.

## Prerequisites

- Python 3.13+, Node 24 and pnpm;
- PostgreSQL 18 and `psql`;
- system users for API, web, anomaly worker and each collector;
- private systemd credentials under `/etc/m-ranked/credentials`;
- a verified pgBackRest repository and restore drill.

## Build and install

```bash
python3 -m venv .venv
# Релиз ставит только среды выполнения, и только по хешам: pytest, Playwright
# и прочий инструментарий живут в requirements/dev.txt и в релиз не попадают.
.venv/bin/pip install --require-hashes --no-deps --upgrade -r requirements/tooling.lock
.venv/bin/pip install --require-hashes --no-deps --only-binary=:all: -r requirements/api.lock
.venv/bin/pip install --require-hashes --no-deps --no-build-isolation -r requirements/collector.lock
.venv/bin/pip install --require-hashes --no-deps --only-binary=:all: -r requirements/anomaly.lock
# PyMax собирается из закреплённого коммита отдельным шагом: зависимость из git
# несовместима с проверкой хешей, поэтому она и вынесена в отдельный файл.
.venv/bin/pip install --no-deps -r requirements/pymax.txt
# Режим telegram_web дополнительно требует браузера:
# .venv/bin/pip install --requirement requirements/telegram-web.txt
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
```

Lock-файлы пересоздаются только скриптом и только целиком:

```bash
python3 operations/scripts/generate_python_lock.py requirements/api.txt requirements/api.lock
python3 operations/scripts/generate_python_lock.py requirements/collector.txt \
  requirements/collector.lock --extra setuptools==80.9.0 wheel==0.45.1
```

Перед выкаткой проверьте, что задание `supply-chain` и `container-images`
прошли на этом коммите, а вложения провенанса относятся к тем же SBOM:

```bash
gh attestation verify --owner funpin sbom-image-api.json
```

Оба задания обязаны быть required checks для `alpha` и релизной ветки
(Settings → Rules → Rulesets). Без этого ворота можно обойти слиянием.

Copy the repository tree and the standalone Next.js output into the immutable
release, then atomically update `/opt/m-ranked/current`. Do not copy `.env`,
provider sessions, dumps or credentials into a release.

## Database

A fresh cluster is created by `infra/postgres/init/001-create-roles.sh` and
`002-apply-schema.sh`, which applies `db/migrations/*.sql` in order.
Applications do not migrate a database at startup. Before activating a release:

```sql
SELECT contract_id FROM ops_and_admin.schema_contract;
```

The required value is `live-read-2026-09-13-text-fingerprint`. For an existing cluster, apply
only a separately reviewed forward schema change after a verified backup and
isolated restore; never replay the bootstrap set over a populated database.

## Credentials

Install examples from `operations/env/` as mode 0600 environment files.
Database passwords, `ADMIN_AUTH_USERS` and `ADMIN_CSRF_SECRET` are systemd
credentials loaded by `m-ranked-target-api.service`. Collectors use one
mode-0600 libpq passfile plus one platform-scoped auth file. Session state stays
under `/var/lib/m-ranked/collectors/<platform>`.

### Administrative sign-in

Every entry in `ADMIN_AUTH_USERS` carries `totpSecret`, a base32 secret of at
least sixteen bytes, and a bcrypt hash of at least ten rounds. All entries must
share the same bcrypt cost: a cheaper hash for one account would tell an
attacker by response time which names exist. The API refuses to start when a
secret is missing, when the costs differ, or when `ADMIN_CSRF_SECRET` is shorter
than 32 bytes; only a stand that is not production may set
`ADMIN_REQUIRE_MFA=false`. Mint a secret and the enrolment URI with:

```bash
python - <<'SECRET'
import base64, os, urllib.parse
secret = base64.b32encode(os.urandom(20)).decode().rstrip("=")
print(secret)
print("otpauth://totp/" + urllib.parse.quote("m-ranked:admin")
      + "?secret=" + secret + "&issuer=m-ranked&digits=6&period=30")
SECRET
```

Password and one-time code are separate fields and are presented once, to
`POST /api/v1/admin/session`. The response carries no session token: that lives
only in the `__Host-mranked-admin` cookie, which is `Secure`, `HttpOnly`,
`SameSite=Strict` and `Path=/`. The body carries a CSRF token bound to that one
session. A code is spent when the session is created, so ordinary multi-request
work needs no further code, and the same code cannot open a second session.

```bash
jar=$(mktemp)
curl --silent --show-error --cookie-jar "$jar" --header 'Content-Type: application/json' \
  --data '{"username":"admin","password":"…","otp":"123456"}' \
  https://m.funpin.org/api/v1/admin/session   # 201, тело несёт CSRF-токен
curl --silent --cookie "$jar" https://m.funpin.org/api/v1/admin/jobs?limit=1
curl --silent --cookie "$jar" --request DELETE --header "X-XSRF-TOKEN: $token" \
  https://m.funpin.org/api/v1/admin/session
rm -f "$jar"
```

Sessions expire on idle (`ADMIN_SESSION_IDLE_SECONDS`, default 30 minutes) and
absolutely (`ADMIN_SESSION_ABSOLUTE_SECONDS`, default 8 hours). Every request
re-checks the session against `ops_and_admin.admin_session`, so removing an
account from `ADMIN_AUTH_USERS` or changing its roles invalidates its sessions
on the next request. `DELETE /api/v1/admin/sessions` revokes every session of
one account without disclosing any token.

Repeated failures are answered with 429 and `Retry-After` **per source address**
only. An account is never locked out: five wrong attempts from a stranger must
not keep its owner from signing in.

### Ordering and worker assumptions

Migration `0025_admin_session.sql` must be applied before the API release that
depends on it; `/api/v1/health/ready` reports DOWN until the tables exist.

Session state, the one-time-code ledger and the per-address backoff live in
PostgreSQL, so they survive a restart and are shared. The API still runs a
single uvicorn worker (`api/__main__.py`); before running more than one worker
or more than one host, re-read `api/security.py` — the bcrypt admission
semaphore is the only remaining per-process security limit, and it bounds CPU
rather than granting access.

## Activate

```bash
systemctl daemon-reload
systemctl enable --now m-ranked-target.target
systemctl enable --now m-ranked-target-maintenance.timer
systemctl enable --now m-ranked-target-backup-daily.timer
systemctl enable --now m-ranked-target-backup-weekly.timer
systemctl enable --now m-ranked-target-backup-monthly.timer
systemctl enable --now m-ranked-target-restore-verify.timer
```

Verify bounded health endpoints, four collector units, anomaly worker, outbox
age, database space, WAL archive and the latest successful restore. A deploy is
not complete while any required unit is restarting or freshness exceeds its
configured threshold.
