-- Витрина карточек обзора.
--
-- Четыре числа на карточке — прирост показателей всех публикаций, у которых
-- внутри окна есть наблюдение. Живым запросом это стоило 299 тысяч буферов и
-- почти шести секунд на экране «Общий / 30 дней»: на каждую из тридцати тысяч
-- публикаций приходится отдельный поиск значения на начало окна. Считать это
-- на каждый запрос незачем — числа одинаковы для всех читателей, поэтому они
-- пересчитываются по расписанию и лежат готовыми.
CREATE TABLE analytics.overview_card_metrics (
    scope_platform text NOT NULL,
    entity_id uuid NOT NULL,
    period text NOT NULL,
    publication_count bigint DEFAULT 0 NOT NULL,
    views_samples integer DEFAULT 0 NOT NULL,
    total_views numeric,
    median_views numeric,
    reactions_samples integer DEFAULT 0 NOT NULL,
    total_reactions numeric,
    median_reactions numeric,
    comments_samples integer DEFAULT 0 NOT NULL,
    total_comments numeric,
    median_comments numeric,
    shares_samples integer DEFAULT 0 NOT NULL,
    total_shares numeric,
    median_shares numeric,
    computed_as_of timestamp with time zone NOT NULL,
    refreshed_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT overview_card_metrics_period_check
        CHECK ((period = ANY (ARRAY['3h'::text, '1d'::text, '7d'::text, '30d'::text]))),
    CONSTRAINT overview_card_metrics_scope_check
        CHECK ((scope_platform = ANY (ARRAY['all'::text, 'telegram'::text, 'vk'::text, 'max'::text, 'rutube'::text]))),
    CONSTRAINT overview_card_metrics_pkey PRIMARY KEY (scope_platform, entity_id, period)
);

COMMENT ON TABLE analytics.overview_card_metrics IS 'Готовые агрегаты карточек обзора: прирост показателей публикаций с наблюдением внутри окна. Пересчитывается по расписанию, читается только на выборке.';
COMMENT ON COLUMN analytics.overview_card_metrics.computed_as_of IS 'Правый край окна, по которому посчитан прирост.';
COMMENT ON COLUMN analytics.overview_card_metrics.publication_count IS 'Сколько публикаций попало в окно — знаменатель покрытия.';

GRANT SELECT ON TABLE analytics.overview_card_metrics TO api_read;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE analytics.overview_card_metrics TO maintenance;
