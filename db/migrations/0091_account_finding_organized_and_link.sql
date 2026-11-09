-- 0091 — аккаунтные находки «организованный отклик» и «связь реакций с просмотрами»
-- (account-findings-v8, anomaly_analysis/v2/account_findings.py и reach_findings.py).
-- Таблица не меняется, расширяется только перечень видов. Ночное задание
-- переписывает находки целиком: новые виды появляются после его ближайшего запуска.
--
-- Откат: удалить строки видов и вернуть перечень 0081 —
--   DELETE FROM analytics.account_anomaly_finding WHERE kind IN ('organized_response', 'reaction_view_link');
--   и ограничение из 0081.
BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE analytics.account_anomaly_finding DROP CONSTRAINT IF EXISTS account_anomaly_finding_kind_check;
ALTER TABLE analytics.account_anomaly_finding ADD CONSTRAINT account_anomaly_finding_kind_check
    CHECK (kind = ANY (ARRAY['early_pack'::text, 'regular_reactions'::text, 'late_growth'::text,
                             'late_engagement'::text, 'synchronous_waves'::text,
                             'engagement_shift'::text, 'night_reactions'::text,
                             'view_packs'::text, 'view_waves'::text, 'level3_share'::text,
                             'flat_daily_views'::text, 'promotion'::text, 'early_response'::text,
                             'organized_response'::text, 'reaction_view_link'::text]));

COMMIT;
