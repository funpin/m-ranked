-- 0029 — удалить отказанный CSV-export контур
--
-- Приложение больше не публикует CSV endpoints и collectors больше не
-- материализуют копию каждого snapshot для legacy CSV/reverse-sync.
-- Numeric aliases не относятся к export и остаются для старых URL/ID.
--
-- Порядок production rollout: остановить collectors, развернуть код без записи
-- в эту таблицу, применить миграцию и только после этого снова запустить
-- collectors. DROP освобождает heap и индексы без построчного DELETE/WAL.

BEGIN;
SET LOCAL lock_timeout = '5s';

DROP TABLE IF EXISTS analytics.legacy_native_export_lexeme;

COMMIT;
