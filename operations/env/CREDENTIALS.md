# Runtime credentials

Every file below is provisioned directly on the host with mode `0600`, owned by
root, and exposed to a service only through `LoadCredential=`. Values never
belong in an EnvironmentFile, command line, journal, metric or repository.

| Credential source | Consumer | Format/example |
| --- | --- | --- |
| `api-read-db-password` | API, official rating | one password line |
| `api-write-admin-db-password` | API, official rating | one password line |
| `outbox-worker-db-password` | API, official rating | one password line |
| `admin-auth-users.json` | API | JSON account array described in `DEPLOY.md` |
| `admin-csrf-secret` | API | random value of at least 32 bytes |
| `collector-pgpass` | collectors | PostgreSQL `.pgpass` line |
| `collector-<platform>-auth.env` | one collector | shell-free `NAME=value` lines: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `CHANNELS`, `VK_ACCESS_TOKEN`, or `MAX_USER_PHONE` as applicable |
| `transfer-client.crt`, `transfer-client.key`, `transfer-ca.crt` | Profile B Server 1 collectors | PEM client chain, private key and issuing CA |
| `transfer-ingest-pgpass` | transfer receiver | PostgreSQL `.pgpass` line |
| `transfer-sender-pgpass` | transfer sender | PostgreSQL `.pgpass` line |
| `transfer-server.crt`, `transfer-server.key`, `transfer-ca.crt` | Profile B Server 2 receiver | PEM server chain, private key and issuing CA |
| `redis.acl` | Redis | copy `redis.acl.example`, replace its placeholder once |
| `redis-url` | API | copy `redis-url.credential.example` with the same password |
| `anomaly-pgpass`, `maintenance-pgpass` | background workers | PostgreSQL `.pgpass` line |
| `pgbackrest-repository.conf`, `pgbackrest-restore.conf` | backup/restore | rendered from the reviewed examples under `operations/backup/` |

Certificate issuance, distribution and revocation require separate production
approval. Keep the old client certificate valid for the documented 30-day
overlap; revoke it only after a completed migration or rollback.
