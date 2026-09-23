-- 0036 — таблицы анализа аномальной динамики v2
--
-- Причина: v2 хранит по посту одну текущую строку вывода, а историю — только
-- сменами вывода. Прежний анализ писал ревизию на каждый прогон и восемь
-- таблиц вокруг неё; при ~17 000 анализов в час это рост без пользы для
-- страницы поста, которой нужен только текущий вывод.
--
-- Что создаётся — только в схеме analytics:
--   * post_anomaly_state — строка на пост: уровень, признаки, качество, версии,
--     расписание следующего анализа, заморозка и статус проверки по ADR-006;
--   * post_anomaly_log — журнал смен вывода, только вставка;
--   * anomaly_norm_version, anomaly_norm — версии норм и их параметры по
--     площадке, аккаунту (NULL — норма площадки), метрике и возрастному
--     интервалу (NULL — параметры на весь возраст, например затухание).
--
-- published_at в состоянии — копия из ingest.publication. Она нужна дважды:
-- очередь приоритета «свежие первыми» читается индексом без соединения, а
-- чтение рядов заранее знает месяцы публикаций и отсекает партиции замеров
-- по published_month на этапе планирования.
--
-- Права. analytics_worker читает ряды через существующие представления
-- ingest и catalog — SELECT на четыре представления выдаётся здесь, других
-- прав на ingest и catalog у него не появляется. На новые таблицы — чтение,
-- вставка и обновление; журнал — только вставка. api_read читает только
-- текущее состояние поста.
--
-- Что не меняется: ops_and_admin.schema_contract (сборщики и API не читают
-- новых таблиц), восемь таблиц прежнего анализа, перенос, рейтинг, обзор.
-- Прежние таблицы удаляются отдельной миграцией после проверки v2.
--
-- Откат: DROP TABLE четырёх таблиц в обратном порядке и REVOKE SELECT на
-- представления у analytics_worker. Данные v2 пересчитываются заново.

CREATE TABLE analytics.anomaly_norm_version (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_version text NOT NULL,
    status text NOT NULL,
    reference_failures jsonb DEFAULT '[]'::jsonb NOT NULL,
    drift jsonb DEFAULT '{}'::jsonb NOT NULL,
    previous_version_id bigint REFERENCES analytics.anomaly_norm_version(id),
    created_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    decided_at timestamp with time zone,
    CONSTRAINT anomaly_norm_version_status_check
        CHECK (status = ANY (ARRAY['accepted'::text, 'rejected'::text, 'drift_review'::text])),
    CONSTRAINT anomaly_norm_version_model_version_check CHECK (btrim(model_version) <> ''::text),
    CONSTRAINT anomaly_norm_version_reference_failures_check
        CHECK (jsonb_typeof(reference_failures) = 'array'::text),
    CONSTRAINT anomaly_norm_version_drift_check CHECK (jsonb_typeof(drift) = 'object'::text),
    -- Отклонённая версия — это версия, не прошедшая эталон, и наоборот.
    CONSTRAINT anomaly_norm_version_rejection_check
        CHECK ((status = 'rejected'::text) = (jsonb_array_length(reference_failures) > 0))
);

-- Анализ всегда берёт последнюю принятую версию.
CREATE INDEX anomaly_norm_version_accepted_idx
    ON analytics.anomaly_norm_version USING btree (id DESC) WHERE (status = 'accepted'::text);

CREATE TABLE analytics.anomaly_norm (
    norm_version_id bigint NOT NULL REFERENCES analytics.anomaly_norm_version(id) ON DELETE CASCADE,
    platform text NOT NULL,
    account_id uuid REFERENCES catalog.platform_account(id),
    metric text NOT NULL,
    age_band smallint,
    params jsonb NOT NULL,
    sample_size integer NOT NULL,
    norm_posts integer NOT NULL,
    confidence real NOT NULL,
    CONSTRAINT anomaly_norm_platform_check
        CHECK (platform = ANY (ARRAY['telegram'::text, 'vk'::text, 'max'::text, 'rutube'::text])),
    CONSTRAINT anomaly_norm_metric_check
        CHECK (metric = ANY (ARRAY['views'::text, 'reactions'::text, 'comments'::text, 'shares'::text, 'erv'::text])),
    CONSTRAINT anomaly_norm_age_band_check CHECK ((age_band IS NULL) OR (age_band BETWEEN 0 AND 4)),
    CONSTRAINT anomaly_norm_params_check CHECK (jsonb_typeof(params) = 'object'::text),
    CONSTRAINT anomaly_norm_sample_size_check CHECK ((sample_size >= 0) AND (norm_posts >= 0)),
    CONSTRAINT anomaly_norm_confidence_check CHECK ((confidence >= (0)::real) AND (confidence <= (1)::real)),
    CONSTRAINT anomaly_norm_key UNIQUE NULLS NOT DISTINCT (norm_version_id, platform, account_id, metric, age_band)
);

CREATE TABLE analytics.post_anomaly_state (
    publication_id uuid PRIMARY KEY REFERENCES ingest.publication(id),
    published_at timestamp with time zone NOT NULL,
    level smallint DEFAULT 0 NOT NULL,
    signals jsonb DEFAULT '[]'::jsonb NOT NULL,
    quality jsonb DEFAULT '{}'::jsonb NOT NULL,
    analyzed_at timestamp with time zone,
    analyzed_points integer DEFAULT 0 NOT NULL,
    last_point_observed_at timestamp with time zone,
    norm_version_id bigint REFERENCES analytics.anomaly_norm_version(id),
    detector_versions jsonb DEFAULT '{}'::jsonb NOT NULL,
    next_due_at timestamp with time zone NOT NULL,
    frozen boolean DEFAULT false NOT NULL,
    review_status text DEFAULT 'unreviewed'::text NOT NULL,
    error_code text,
    attempts integer DEFAULT 0 NOT NULL,
    lag_seconds integer,
    updated_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT post_anomaly_state_level_check CHECK ((level >= 0) AND (level <= 3)),
    CONSTRAINT post_anomaly_state_signals_check CHECK (jsonb_typeof(signals) = 'array'::text),
    CONSTRAINT post_anomaly_state_quality_check CHECK (jsonb_typeof(quality) = 'object'::text),
    CONSTRAINT post_anomaly_state_detector_versions_check CHECK (jsonb_typeof(detector_versions) = 'object'::text),
    CONSTRAINT post_anomaly_state_counts_check
        CHECK ((analyzed_points >= 0) AND (attempts >= 0) AND ((lag_seconds IS NULL) OR (lag_seconds >= 0))),
    -- Статусы ручной проверки — ADR-006; ручной проверки пока нет, поле заложено.
    CONSTRAINT post_anomaly_state_review_status_check
        CHECK (review_status = ANY (ARRAY['unreviewed'::text, 'explained'::text, 'unresolved'::text, 'data_error'::text, 'dismissed'::text])),
    CONSTRAINT post_anomaly_state_error_code_check CHECK ((error_code IS NULL) OR (btrim(error_code) <> ''::text))
);

-- Очередь: что пора анализировать. Замороженные посты в неё не входят.
CREATE INDEX post_anomaly_state_due_idx
    ON analytics.post_anomaly_state USING btree (next_due_at) WHERE (NOT frozen);
-- Приоритет: свежие посты первыми.
CREATE INDEX post_anomaly_state_priority_idx
    ON analytics.post_anomaly_state USING btree (published_at DESC) WHERE (NOT frozen);

CREATE TABLE analytics.post_anomaly_log (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    publication_id uuid NOT NULL REFERENCES ingest.publication(id),
    changed_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    change text NOT NULL,
    previous_level smallint,
    level smallint NOT NULL,
    signals jsonb NOT NULL,
    detector_versions jsonb NOT NULL,
    norm_version_id bigint REFERENCES analytics.anomaly_norm_version(id),
    reason text NOT NULL,
    CONSTRAINT post_anomaly_log_change_check
        CHECK (change = ANY (ARRAY['appeared'::text, 'level_changed'::text, 'sign_added'::text, 'sign_removed'::text])),
    CONSTRAINT post_anomaly_log_level_check
        CHECK ((level BETWEEN 0 AND 3) AND ((previous_level IS NULL) OR (previous_level BETWEEN 0 AND 3))),
    CONSTRAINT post_anomaly_log_signals_check CHECK (jsonb_typeof(signals) = 'array'::text),
    CONSTRAINT post_anomaly_log_detector_versions_check CHECK (jsonb_typeof(detector_versions) = 'object'::text),
    CONSTRAINT post_anomaly_log_reason_check CHECK (btrim(reason) <> ''::text)
);

CREATE INDEX post_anomaly_log_publication_idx
    ON analytics.post_anomaly_log USING btree (publication_id, changed_at DESC);

COMMENT ON TABLE analytics.post_anomaly_state IS
  'Текущий вывод анализа v2 по посту. Сигнал сам по себе не доказывает искусственное происхождение активности (ADR-006).';
COMMENT ON TABLE analytics.post_anomaly_log IS
  'Журнал смен вывода анализа v2: появление, смена уровня, появление и исчезновение признака. Только вставка.';

REVOKE ALL ON TABLE analytics.anomaly_norm_version, analytics.anomaly_norm,
    analytics.post_anomaly_state, analytics.post_anomaly_log FROM PUBLIC;

GRANT SELECT, INSERT, UPDATE ON TABLE analytics.anomaly_norm_version, analytics.anomaly_norm,
    analytics.post_anomaly_state TO analytics_worker;
GRANT INSERT ON TABLE analytics.post_anomaly_log TO analytics_worker;
GRANT SELECT ON TABLE ingest.visible_publication, ingest.publication_metric_snapshot_active,
    ingest.account_metric_snapshot_active, catalog.visible_platform_account TO analytics_worker;

GRANT SELECT ON TABLE analytics.post_anomaly_state TO api_read;
