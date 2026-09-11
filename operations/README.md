# M-Ranked operations

Эксплуатационный набор относится к одному активному стеку:
FastAPI, четыре Python-сборщика, anomaly worker, Next.js и PostgreSQL.

Порядок запуска:

1. подготовить Unix users, database roles и systemd credentials;
2. установить один immutable release;
3. проверить contract id `live-read-2026-09-13`;
4. запустить `m-ranked-target.target`;
5. включить maintenance и backup/restore timers;
6. проверить `/health`, `/api/v1/health`, свежесть сборщиков и outbox.

Ранбуки:

- [DEPLOY.md](runbooks/DEPLOY.md);
- [BACKUP_RESTORE.md](runbooks/BACKUP_RESTORE.md);
- [DR_STANDBY.md](runbooks/DR_STANDBY.md);
- [ROLLBACK.md](runbooks/ROLLBACK.md);
- [HEALTH.md](runbooks/HEALTH.md);
- [IDENTITY_RECEIPTS.md](runbooks/IDENTITY_RECEIPTS.md).

Скрипты ограничены backup, restore, WAL archive, collector preflight и
maintenance. DDL не выполняется приложениями при старте.
