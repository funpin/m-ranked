-- 0080 — аккаунтная находка «похоже на продвижение записей» (ВК,
-- anomaly_analysis/v2/reach_findings.py::promotion_findings). Таблица не
-- меняется, расширяется только перечень видов. Находке нужны сводки постов
-- версии 6 (сутки ВК): работник строит их при ближайшем анализе поста,
-- `backfill --days 40` — сразу для окна. Ночное задание переписывает находки
-- целиком, поэтому вид появляется после его ближайшего запуска.
--
-- Откат: удалить строки вида и вернуть перечень 0079 —
--   DELETE FROM analytics.account_anomaly_finding WHERE kind = 'promotion';
--   и ограничение из 0079.
BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE analytics.account_anomaly_finding DROP CONSTRAINT IF EXISTS account_anomaly_finding_kind_check;
ALTER TABLE analytics.account_anomaly_finding ADD CONSTRAINT account_anomaly_finding_kind_check
    CHECK (kind = ANY (ARRAY['early_pack'::text, 'regular_reactions'::text, 'late_growth'::text,
                             'late_engagement'::text, 'synchronous_waves'::text,
                             'engagement_shift'::text, 'night_reactions'::text,
                             'view_packs'::text, 'view_waves'::text, 'level3_share'::text,
                             'flat_daily_views'::text, 'promotion'::text]));

COMMIT;
