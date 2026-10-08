-- 0075 — аккаунтные находки «отклик вырос без роста аудитории» и «реакции
-- приходят ночью».
--
-- Виды engagement_shift и night_reactions (anomaly_analysis/v2/account_findings.py,
-- account-findings-v3). Таблица находок не меняется, расширяется только
-- перечень видов. Ночное задание переписывает находки целиком, поэтому новые
-- виды появляются после его ближайшего запуска; ночным реакциям нужны сводки
-- постов версии 4 (почасовой поздний прирост).
--
-- Откат: удалить строки видов и вернуть перечень 0074 —
--   DELETE FROM analytics.account_anomaly_finding WHERE kind IN ('engagement_shift', 'night_reactions');
--   и ограничение из 0074.
BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE analytics.account_anomaly_finding DROP CONSTRAINT IF EXISTS account_anomaly_finding_kind_check;
ALTER TABLE analytics.account_anomaly_finding ADD CONSTRAINT account_anomaly_finding_kind_check
    CHECK (kind = ANY (ARRAY['early_pack'::text, 'regular_reactions'::text, 'late_growth'::text,
                             'late_engagement'::text, 'synchronous_waves'::text,
                             'engagement_shift'::text, 'night_reactions'::text]));

COMMIT;
