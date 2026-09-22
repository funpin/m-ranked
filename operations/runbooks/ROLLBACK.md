# Application rollback

Rollback means activating the previous immutable Python/Next.js release against
the same compatible PostgreSQL contract. It does not recreate the retired
SQLite/Java stack and never copies data back to another database.

## Откат миграции A → B

Сначала остановите изменение состояния, затем верните чтение. Не удаляйте
dump, cursor record, outbox/inbox, certificates, старый release или журналы до
закрытия инцидента.

| Последний выполненный шаг | Откат |
| --- | --- |
| Provisioning Сервера 2, без restore | Остановить units С2; конфигурацию можно убрать после сохранения evidence. С1 не менялся. |
| Snapshot/dump или restore на С2 | Остановить С2, сохранить/изолировать восстановленную DB и dump; продолжать профиль A. Экспортированный snapshot не переиспользовать. |
| Firewall/mTLS/receiver smoke | Остановить receiver, вернуть reviewed firewall rules. Не отзывать client cert, пока откат не проверен. |
| Collectors остановлены, хвост переоткрыт, но traffic ещё на С1 | Остановить target B S1, вернуть `collector-profile.env` к profile A/убрать overlay и drop-in, оставить retention `off`, запустить collectors профиля A. Локальный inbox дедуплицирует повтор хвоста; сверить cursor и freshness. |
| HTTPS transport работает, traffic ещё на С1 | Как выше: остановить B collectors, вернуть in-process и перезапустить по режиму scheduler. С2 сохранить как evidence; полная DB С1 всё ещё авторитетна. |
| Traffic переведён на С2, retention `off` или `dry-run` | Сначала вернуть DNS/nginx/upstream на проверенные API/web С1. Затем откатить transport как в предыдущей строке. Остановить presentation С2 только после health/read/admin проверки С1. |
| Retention `on`, но ни одна partition не dropped | Немедленно поставить `off`, перезапустить collectors по режиму scheduler и выполнить предыдущую строку. Подтвердить по audit/metrics, что released count не вырос. |
| Первая monthly partition dropped | Конфигурационный rollback запрещён: С1 больше не полная копия. Остановить retention и writers, восстановить полную историю из С2 или проверенного backup на новый путь/host по `BACKUP_RESTORE.md`, сверить contract/cursors/checksums и только затем переключать traffic. |

Dry-run обратим и не является точкой невозврата. `on` становится необратимым
не в момент записи env, а в момент первого успешного drop. Не пытайтесь
воссоздать удалённую partition обратным SQL или из неполного outbox.

После любого отката сравните produced/acknowledged/applied cursors, backlog,
quarantine, полный public/admin health и один цикл каждой платформы. Certificate
revocation и удаление firewall exception выполняются только после стабилизации
отката отдельным разрешением; преждевременный revoke отрезает повторный drain.

## Откат application release

1. Stop `m-ranked-target.target`.
2. Point `/opt/m-ranked/current` atomically to the previous verified release.
3. Confirm that release accepts the current
   `ops_and_admin.schema_contract.contract_id`.
4. Start `m-ranked-target.target`.
5. Verify health, one bounded public read, admin authentication and collector
leases before reopening external traffic.

## Phase scheduler rollback

The phase scheduler has no schema migration. To roll back scheduler behaviour
without changing the release, set `COLLECTOR_SCHEDULE_MODE=legacy` in
`collector-common.env` and restart the four collector instances one by one.
Existing `collector.phase.v1` checkpoints are inert in legacy mode and may be
kept for investigation. Do not delete running `collection_run` rows: a newer
worker can resume them by their deterministic logical slot.

The process-local public response cache is deliberately empty after rollback.
Cold reads repopulate it from the authoritative revision endpoint. Keep the
version-independent `m-ranked-target-web-cache-gc.timer` active: it bounds the
writable active cache even when an older release still uses Next.js filesystem
fetch entries. Cache eviction never requires copying a newer entry into the
older release.

Do not use a retired cache as rollback state. The preserved
`/var/lib/m-ranked/web-cache-b66ad66-retired-20260921` directory is evidence,
not an application input, and requires separate explicit approval for any
mutation.

If the incident includes an incompatible schema change or database corruption,
do not start an older binary. Follow [BACKUP_RESTORE.md](BACKUP_RESTORE.md) and
restore PostgreSQL on an isolated host to the selected recovery point. Retain
the failed release, logs, outbox state and restore evidence for investigation.
