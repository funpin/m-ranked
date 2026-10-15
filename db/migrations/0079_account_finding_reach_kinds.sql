-- 0079 — аккаунтные находки по охватам: пакеты и волны просмотров, много
-- постов уровня 3, просмотры без суточного ритма (account-findings-v4,
-- anomaly_analysis/v2/reach_findings.py). Таблица не меняется, расширяется
-- только перечень видов. Ночное задание переписывает находки целиком, поэтому
-- новые виды появляются после его ближайшего запуска; волнам нужны сводки
-- постов версии 5 (часы притока).
--
-- Откат: удалить строки видов и вернуть перечень 0075 —
--   DELETE FROM analytics.account_anomaly_finding
--    WHERE kind IN ('view_packs', 'view_waves', 'level3_share', 'flat_daily_views');
--   и ограничение из 0075.
BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE analytics.account_anomaly_finding DROP CONSTRAINT IF EXISTS account_anomaly_finding_kind_check;
ALTER TABLE analytics.account_anomaly_finding ADD CONSTRAINT account_anomaly_finding_kind_check
    CHECK (kind = ANY (ARRAY['early_pack'::text, 'regular_reactions'::text, 'late_growth'::text,
                             'late_engagement'::text, 'synchronous_waves'::text,
                             'engagement_shift'::text, 'night_reactions'::text,
                             'view_packs'::text, 'view_waves'::text, 'level3_share'::text,
                             'flat_daily_views'::text]));

COMMIT;
