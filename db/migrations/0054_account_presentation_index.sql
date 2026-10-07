-- 0054 — быстрый статус аккаунта для панели управления
--
-- legacy_account_presentation искала последний результат сбора по аккаунту,
-- сортируя по completed_at, а индекс есть только по (platform_account_id,
-- started_at DESC): на каждый аккаунт перебиралась вся его история сбора —
-- 22 мс на аккаунт, 7,4 с на каталог из 332 аккаунтов, и вкладка «Каналы»
-- открывалась 5–8 секунд (однажды — 503 по таймауту шлюза).
--
-- Порядок по started_at идёт по индексу: на данных Сервера 2 весь каталог —
-- 32 мс, а выбранная строка совпала у всех 332 аккаунтов (у одного аккаунта
-- циклы не перекрываются: позже начатый и завершается позже).
--
-- Откат: прежнее определение из 0013_functions.sql.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE OR REPLACE FUNCTION ops_and_admin.legacy_account_presentation(p_account uuid) RETURNS TABLE(access_mode text, last_error_code text, error_present boolean)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'catalog', 'ingest'
    SET statement_timeout TO '3s'
    AS $$
    SELECT CASE account.access_mode::text
             WHEN 'public_web' THEN 'public'
             WHEN 'public_api' THEN 'public'
             WHEN 'official_api' THEN 'api'
             WHEN 'user_session' THEN 'user'
             ELSE account.access_mode::text
           END,
           CASE WHEN result.status IN ('failed', 'partial')
                THEN coalesce(result.sanitized_error_code, 'collection_failed') END,
           coalesce(result.status IN ('failed', 'partial'), false)
      FROM catalog.visible_platform_account AS account
      LEFT JOIN LATERAL (
          SELECT status, sanitized_error_code
            FROM ingest.collection_account_result
           WHERE platform_account_id = account.id
             AND completed_at IS NOT NULL
           ORDER BY started_at DESC, id DESC
           LIMIT 1
      ) AS result ON true
     WHERE account.id = p_account
$$;

COMMIT;
