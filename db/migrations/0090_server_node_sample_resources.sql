-- 0090 — история ресурсов серверов-сборщиков для вкладки «Серверы» и бота.
--
-- Агент узла (operations/storage/agent.py, версия 2) считает загрузку CPU и
-- скорости сети и диска по разности счётчиков между минутными запусками и
-- шлёт минутные точки очередью: точка, не дошедшая из-за перезапуска
-- приёмника при выкатке, уходит следующим отчётом со своим временем. Здесь
-- для них столбцы; release — версия выпуска на узле, по её смене панель
-- связывает пропуск замеров с обновлением.
--
-- Строка — раз в минуту вместо раза в пять минут: около 100 байт, 14 суток
-- хранения (main_agent) — около 2 МБ на сервер. Новые столбцы без значения
-- по умолчанию: ALTER меняет только каталог и таблицу не переписывает.
--
-- Бот (/status → серверы) читает реестр, историю ресурсов и журнал циклов
-- сбора — только чтение.
--
-- Откат:
--   ALTER TABLE ops_and_admin.server_node_sample DROP COLUMN cpu_percent, DROP COLUMN swap_used_bytes,
--     DROP COLUMN net_rx_bytes_per_second, DROP COLUMN net_tx_bytes_per_second,
--     DROP COLUMN disk_read_bytes_per_second, DROP COLUMN disk_write_bytes_per_second, DROP COLUMN release;
--   REVOKE SELECT ON ops_and_admin.server_node, ops_and_admin.server_node_sample, ingest.collection_run FROM telegram_bot;
--   REVOKE USAGE ON SCHEMA ingest FROM telegram_bot;
BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE ops_and_admin.server_node_sample
    ADD COLUMN IF NOT EXISTS cpu_percent real,
    ADD COLUMN IF NOT EXISTS swap_used_bytes bigint,
    ADD COLUMN IF NOT EXISTS net_rx_bytes_per_second real,
    ADD COLUMN IF NOT EXISTS net_tx_bytes_per_second real,
    ADD COLUMN IF NOT EXISTS disk_read_bytes_per_second real,
    ADD COLUMN IF NOT EXISTS disk_write_bytes_per_second real,
    ADD COLUMN IF NOT EXISTS release text;

GRANT SELECT ON TABLE ops_and_admin.server_node, ops_and_admin.server_node_sample TO telegram_bot;
GRANT USAGE ON SCHEMA ingest TO telegram_bot;
GRANT SELECT ON TABLE ingest.collection_run TO telegram_bot;

COMMIT;
