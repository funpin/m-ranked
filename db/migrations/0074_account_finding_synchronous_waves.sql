-- 0074 — аккаунтная находка «волны реакций сразу на многих постах».
--
-- Вид synchronous_waves (anomaly_analysis/v2/account_findings.py): дни, когда
-- синхронный подъём реакций (признак 8) получили 10 и больше постов аккаунта.
-- Таблица находок не меняется, расширяется только перечень видов. Ночное
-- задание переписывает находки целиком, поэтому новый вид появляется после
-- его ближайшего запуска.
--
-- Откат: удалить строки вида и вернуть прежний перечень —
--   DELETE FROM analytics.account_anomaly_finding WHERE kind = 'synchronous_waves';
--   и ограничение из 0073.
BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE analytics.account_anomaly_finding DROP CONSTRAINT IF EXISTS account_anomaly_finding_kind_check;
ALTER TABLE analytics.account_anomaly_finding ADD CONSTRAINT account_anomaly_finding_kind_check
    CHECK (kind = ANY (ARRAY['early_pack'::text, 'regular_reactions'::text, 'late_growth'::text,
                             'late_engagement'::text, 'synchronous_waves'::text]));

COMMIT;
