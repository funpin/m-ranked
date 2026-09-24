# Backup, WAL and PITR

Owners: database operator and restore operator. Targets are RPO ≤ 15 minutes and
RTO ≤ 2 hours. A streaming standby is not a backup.

Use the example pgBackRest configurations in `operations/backup/`. Keep the
encrypted repository outside the primary failure domain, use separate
archive/backup/restore SSH identities, pin host keys and deny interactive
shells.

Install `/etc/m-ranked/backup.env` and `restore-verify.env` from their examples;
install `dump-backup.env` only for the fallback dump timer below. The two
pgBackRest config credentials and every other credential format are inventoried
in [`operations/env/CREDENTIALS.md`](../env/CREDENTIALS.md); never put repository
keys or database passwords into these EnvironmentFile examples.

PostgreSQL must archive WAL continuously with `archive_timeout=15min`.
Enable daily, weekly and monthly backup timers plus daily restore verification:

```bash
systemctl enable --now m-ranked-target-backup-daily.timer
systemctl enable --now m-ranked-target-backup-weekly.timer
systemctl enable --now m-ranked-target-backup-monthly.timer
systemctl enable --now m-ranked-target-restore-verify.timer
```

The verifier restores into a new private directory, starts PostgreSQL without a
network listener, checks page checksums and `pg_amcheck --all`, requires
PostgreSQL 18.6 and schema contract `live-read-2026-09-13-text-fingerprint`, records the latest
dataset revision and removes only its own temporary cluster. Quarterly
`m-ranked-target-pitr-drill.timer` replays archived WAL to a chosen point.

During an incident, freeze writers, retain the damaged primary, restore to a
new host/path and verify contract, checksums, revision and RPO/RTO before any
promotion. Provider session files and identity receipts live outside PostgreSQL;
back them up separately with distinct encryption and verify their inventory.

## Ночной снимок там, где нет pgBackRest

Подготовленная policy описана в [STORAGE_BUDGET.md](STORAGE_BUDGET.md).
На production при проверке 24.09.2026 ещё действовали три локальных копии,
архив WAL был выключен. Изложенные выше RPO/RTO — цели целевой pgBackRest
схемы, не подтверждённые свойства действующего nightly dump.

Новый `dump-backup.sh` использует один lock, проверяет резерв до запуска,
ограничивает поток 5 ГБ и сохраняет 11 ГБ доступного места во время записи.
Проверка декодирует весь архив, а не только TOC. Это проверка целостности,
не restore. Ротация сохраняет последнюю копию с receipt реального restore
плюс `BACKUP_KEEP` новых. При KEEP=1 это временно две готовые копии и ещё
одна создаваемая; для бюджета считать максимум **три**, пока verifier не
проверяет каждую новую копию до следующего backup. Без receipt ротация
отказывается удалять что-либо; оператор должен устранить причину до следующего
запуска. Резерв продолжает ограничивать накопление даже при ошибке verifier.

После успешного restore receipt `<basename>.restore-verified.json` содержит
`dump` (basename), `sha256`, `restore_exit_code: 0`. Записывать receipt
на production разрешается только вместе с согласованным rollout после
проверки всего restore, ролей/ACL и smoke queries. Один только `--no-owner
--no-acl` drill не доказывает восстановление production permissions.

Установка требует одобрения пакета. Все четыре helper должны идти вместе:

```bash
install -d -m 0755 /usr/local/libexec/m-ranked
for file in dump-backup.sh backup-stream.py rotate-dumps.py storage_guard.py; do
  install -o root -g root -m 0755 "operations/scripts/$file" "/usr/local/libexec/m-ranked/$file"
done
```

Это не замена pgBackRest: восстановление — на момент snapshot, без PITR.
Проверенный 24.09.2026 порядок для полного custom dump: новый изолированный
кластер с исходной bootstrap superuser, определения ролей **без паролей**,
затем три отдельные фазы. Единственный параллельный запуск целиком на проверенном
архиве активировал partition trigger раньше нужного UNIQUE-ограничения и упал.

```bash
# Только выделенная restore DB, никогда production DB.
for section in pre-data data post-data; do
  pg_restore --exit-on-error --jobs=2 --section="$section" \
    --dbname="$RESTORE_DATABASE_URL" "$DUMP_FILE" || exit
done
```

Проверить schema contract, invalid indexes, роли/ACL, receipts, representative
history/API queries и внешний evidence inventory. Последний проверенный dump
восстановился локально за <=353s после передачи; это не обещание RTO на S2.
130 NOT VALID constraints требуют отдельной проверки целостности, а external
raw files/credentials вообще не входят в database dump. Receipt хранить рядом
с dump только после успешной проверки; ротация сверяет SHA256 перед удалением.
