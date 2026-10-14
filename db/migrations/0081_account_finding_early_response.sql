-- 0081 — аккаунтная находка «ранний отклик выше площадки» (ВК без видео,
-- anomaly_analysis/v2/reach_findings.py::early_response_findings). Таблица не
-- меняется, расширяется только перечень видов. Находка читает отметку
-- первого замера из сводок постов (tail_ledger.marks.first), которые уже
-- хранятся; ночное задание переписывает находки целиком, поэтому вид
-- появляется после его ближайшего запуска.
--
-- Откат: удалить строки вида и вернуть перечень 0080 —
--   DELETE FROM analytics.account_anomaly_finding WHERE kind = 'early_response';
--   и ограничение из 0080.
BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE analytics.account_anomaly_finding DROP CONSTRAINT IF EXISTS account_anomaly_finding_kind_check;
ALTER TABLE analytics.account_anomaly_finding ADD CONSTRAINT account_anomaly_finding_kind_check
    CHECK (kind = ANY (ARRAY['early_pack'::text, 'regular_reactions'::text, 'late_growth'::text,
                             'late_engagement'::text, 'synchronous_waves'::text,
                             'engagement_shift'::text, 'night_reactions'::text,
                             'view_packs'::text, 'view_waves'::text, 'level3_share'::text,
                             'flat_daily_views'::text, 'promotion'::text, 'early_response'::text]));

COMMIT;
