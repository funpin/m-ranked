-- 0051 — поздний отклик: реестр поста и профиль аккаунта
--
-- Сравнение аккаунта с его собственной историей не видит постоянного отклика
-- на старые посты: повторяющееся поведение становится «нормой»
-- (research/smart-engagement-2026-09/TAIL_RATIO.md). Анализ сравнивает долю
-- реакций на поздние просмотры поста с его же долей в первые сутки, а
-- аккаунт — с другими аккаунтами той же площадки.
--
--   * post_anomaly_state.tail_ledger — компактная сводка позднего отклика поста
--     (~200 байт), её пишет работник анализа из уже прочитанного ряда; новых
--     чтений замеров нет. tail_ledger_version — версия формата: при её смене
--     работник пересчитывает сводку.
--   * account_tail_profile — строка на аккаунт и сутки, её пишет ночное задание
--     из сводок постов, не читая замеров. Хранится 90 суток (~336 строк в сутки).
--
-- Добавление колонок без значения по умолчанию меняет только каталог:
-- таблица не переписывается. Существующие выводы не трогаются.
--
-- Откат: DROP TABLE analytics.account_tail_profile;
--        ALTER TABLE analytics.post_anomaly_state DROP COLUMN tail_ledger, DROP COLUMN tail_ledger_version.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '2min';

ALTER TABLE analytics.post_anomaly_state
    ADD COLUMN IF NOT EXISTS tail_ledger jsonb,
    ADD COLUMN IF NOT EXISTS tail_ledger_version smallint;

-- Существующие строки сводки не имеют; NOT VALID не сканирует таблицу.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'post_anomaly_state_tail_ledger_check') THEN
        ALTER TABLE analytics.post_anomaly_state
            ADD CONSTRAINT post_anomaly_state_tail_ledger_check
                CHECK (tail_ledger IS NULL OR jsonb_typeof(tail_ledger) = 'object'::text) NOT VALID;
    END IF;
END $$;

COMMENT ON COLUMN analytics.post_anomaly_state.tail_ledger IS
  'Сводка позднего отклика поста по точным замерам: ранняя точка, концы окна 4–14 суток, московские сутки с известным чистым приростом реакций.';

CREATE TABLE IF NOT EXISTS analytics.account_tail_profile (
    account_id uuid NOT NULL REFERENCES catalog.platform_account(id) ON DELETE CASCADE,
    computed_for date NOT NULL,
    platform text NOT NULL,
    status smallint,
    abstain_reason text,
    metrics jsonb NOT NULL,
    method_version text NOT NULL,
    computed_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT account_tail_profile_pkey PRIMARY KEY (account_id, computed_for),
    CONSTRAINT account_tail_profile_platform_check
        CHECK (platform = ANY (ARRAY['telegram'::text, 'vk'::text, 'max'::text, 'rutube'::text])),
    -- Статус: 0 — отклик обычный для площадки, 1 — необычный, 2 — устойчиво
    -- необычный. NULL — воздержание, и тогда причина обязательна.
    CONSTRAINT account_tail_profile_status_check
        CHECK ((status IS NULL AND abstain_reason IS NOT NULL AND btrim(abstain_reason) <> ''::text)
            OR (status BETWEEN 0 AND 2 AND abstain_reason IS NULL)),
    CONSTRAINT account_tail_profile_metrics_check CHECK (jsonb_typeof(metrics) = 'object'::text),
    CONSTRAINT account_tail_profile_method_version_check CHECK (btrim(method_version) <> ''::text)
);

CREATE INDEX IF NOT EXISTS account_tail_profile_retention_idx
    ON analytics.account_tail_profile (computed_for);

COMMENT ON TABLE analytics.account_tail_profile IS
  'Поздний отклик аккаунта относительно аккаунтов площадки, раз в сутки. Статистическая необычность, не доказательство искусственного происхождения (ADR-006).';

REVOKE ALL ON TABLE analytics.account_tail_profile FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE analytics.account_tail_profile TO analytics_worker;
GRANT SELECT ON TABLE analytics.account_tail_profile TO api_read;

COMMIT;
