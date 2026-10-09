-- 0076 — очередь приёма не копит мёртвые строки.
--
-- Отчёт хранилища 09.10 (operations/scripts/storage-report.sh):
-- ops_and_admin.transfer_inbox — 3,7 млн обновлений, 75 тыс. мёртвых строк
-- (12,9 %). Порог автоочистки по умолчанию — 20 % таблицы, и до него
-- таблица успевает вырасти. Как в 0061: очистка раньше.
--
-- Параметр меняется под SHARE UPDATE EXCLUSIVE: чтению и записи не мешает.
-- Уже набранное место он не возвращает.
--
-- Откат: ALTER TABLE ops_and_admin.transfer_inbox RESET (autovacuum_vacuum_scale_factor);
BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE ops_and_admin.transfer_inbox
    SET (autovacuum_vacuum_scale_factor = 0.02);

COMMIT;
