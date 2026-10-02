-- 0052 — снимки состояния сервера для панели управления
--
-- Таймер ops-sample раз в пять минут пишет строку: ресурсы машины, службы
-- systemd, прирост журнала nginx и метрики конвейера (api/tools/ops_sample.py).
-- Панель только читает готовые строки. Хранится 30 суток, удаляет сам таймер:
-- около 8 640 строк по килобайту.
--
-- Откат: DROP TABLE ops_and_admin.host_sample;
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS ops_and_admin.host_sample (
    observed_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    sample jsonb NOT NULL,
    CONSTRAINT host_sample_pkey PRIMARY KEY (observed_at),
    CONSTRAINT host_sample_object_check CHECK (jsonb_typeof(sample) = 'object')
);

GRANT SELECT, INSERT, DELETE ON TABLE ops_and_admin.host_sample TO maintenance;
GRANT SELECT ON TABLE ops_and_admin.host_sample TO api_write_admin;

COMMIT;
