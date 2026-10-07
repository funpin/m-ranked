-- 0073 — аккаунтные находки анализа динамики
--
-- Закономерность, видимая только на многих постах аккаунта сразу:
-- повторяющийся стартовый пакет реакций, слишком ровный отклик, устойчиво
-- необычный поздний отклик (anomaly_analysis/v2/account_findings.py). Строка
-- на аккаунт и вид находки; ночное задание переписывает строки целиком и
-- удаляет те, чья закономерность за окно не подтвердилась. `members` — посты
-- окна, из которых складывается находка: страница поста ссылается на неё.
--
-- Находка считается отдельно от уровней постов и в них не входит.
--
-- Откат: DROP TABLE analytics.account_anomaly_finding;
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '2min';

CREATE TABLE IF NOT EXISTS analytics.account_anomaly_finding (
    account_id uuid NOT NULL REFERENCES catalog.platform_account(id) ON DELETE CASCADE,
    kind text NOT NULL,
    platform text NOT NULL,
    status smallint NOT NULL,
    window_start date NOT NULL,
    window_end date NOT NULL,
    metrics jsonb NOT NULL,
    members uuid[] NOT NULL DEFAULT '{}'::uuid[],
    method_version text NOT NULL,
    computed_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT account_anomaly_finding_pkey PRIMARY KEY (account_id, kind),
    CONSTRAINT account_anomaly_finding_kind_check
        CHECK (kind = ANY (ARRAY['early_pack'::text, 'regular_reactions'::text, 'late_growth'::text, 'late_engagement'::text])),
    CONSTRAINT account_anomaly_finding_platform_check
        CHECK (platform = ANY (ARRAY['telegram'::text, 'vk'::text, 'max'::text, 'rutube'::text])),
    -- 1 — необычно для площадки, 2 — устойчиво (в обеих половинах окна).
    CONSTRAINT account_anomaly_finding_status_check CHECK (status BETWEEN 1 AND 2),
    CONSTRAINT account_anomaly_finding_window_check CHECK (window_start < window_end),
    CONSTRAINT account_anomaly_finding_metrics_check CHECK (jsonb_typeof(metrics) = 'object'::text),
    CONSTRAINT account_anomaly_finding_method_version_check CHECK (btrim(method_version) <> ''::text)
);

-- Страница поста ищет находки, в которые он входит.
CREATE INDEX IF NOT EXISTS account_anomaly_finding_members_idx
    ON analytics.account_anomaly_finding USING gin (members);

COMMENT ON TABLE analytics.account_anomaly_finding IS
  'Аккаунтные находки анализа динамики: закономерность на многих постах относительно аккаунтов площадки. Статистическая необычность, не доказательство искусственного происхождения (ADR-006).';

REVOKE ALL ON TABLE analytics.account_anomaly_finding FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE analytics.account_anomaly_finding TO analytics_worker;
GRANT SELECT ON TABLE analytics.account_anomaly_finding TO api_read;

COMMIT;
