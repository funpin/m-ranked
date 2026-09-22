# M-Ranked operations

Один базовый набор units обслуживает два профиля. Профиль A запускает весь
стек target'ом `m-ranked-target.target`. Профиль B делит его между
`m-ranked-target-profile-b-server1.target` (collectors) и
`m-ranked-target-profile-b-server2.target` (presentation). Различия настроек и
сетевых allowlist выражены необязательными EnvironmentFile и drop-in, а не
копиями service-файлов.

Порядок запуска:

1. подготовить Unix users, database roles и systemd credentials;
2. установить один immutable release;
3. проверить contract id `live-read-2026-09-13-text-fingerprint`;
4. запустить target выбранного профиля;
5. включить maintenance и backup/restore timers;
6. проверить `/health`, `/api/v1/health`, свежесть сборщиков и outbox.

Ранбуки:

- [DEPLOY.md](runbooks/DEPLOY.md);
- [BACKUP_RESTORE.md](runbooks/BACKUP_RESTORE.md);
- [DR_STANDBY.md](runbooks/DR_STANDBY.md);
- [ROLLBACK.md](runbooks/ROLLBACK.md);
- [HEALTH.md](runbooks/HEALTH.md);
- [IDENTITY_RECEIPTS.md](runbooks/IDENTITY_RECEIPTS.md).

Перед доставкой выполните `scripts/check-runtime-config.py` и
`scripts/check-doc-links.py`. Первый связывает все EnvironmentFile и
LoadCredential с примерами и [реестром credentials](env/CREDENTIALS.md), а
также сверяет переменные с runtime-кодом. Скрипты ограничены backup, restore,
WAL archive, collector preflight, проверками и maintenance. DDL не выполняется
приложениями при старте.
