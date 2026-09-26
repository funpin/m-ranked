-- 0044 — сводка для главной страницы: вузы, аккаунты, публикации, замеры
--
-- Главная показывает живые, но не мгновенные цифры. Точный подсчёт замеров —
-- несколько секунд базы по миллионам строк, поэтому он делается раз в сутки
-- шагом планового обслуживания (db/tools/refresh-site-summary.sql), а API
-- читает одну готовую строку. Площадки считаются из данных: новая площадка
-- появится в сводке без правки схемы.
CREATE TABLE analytics.site_summary (
    id smallint DEFAULT 1 NOT NULL,
    institutions integer NOT NULL,
    accounts integer NOT NULL,
    accounts_by_platform jsonb NOT NULL,
    publications bigint NOT NULL,
    snapshots bigint NOT NULL,
    computed_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT site_summary_pkey PRIMARY KEY (id),
    CONSTRAINT site_summary_single_row CHECK (id = 1),
    CONSTRAINT site_summary_counts_check CHECK (institutions >= 0 AND accounts >= 0 AND publications >= 0 AND snapshots >= 0)
);

COMMENT ON TABLE analytics.site_summary IS 'Одна строка: цифры главной страницы, пересчёт раз в сутки шагом обслуживания.';

GRANT SELECT ON TABLE analytics.site_summary TO api_read;
GRANT SELECT, INSERT, UPDATE ON TABLE analytics.site_summary TO maintenance;
