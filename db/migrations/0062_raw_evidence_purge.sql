-- 0062 — сырые доказательства действительно убираются.
--
-- Склад файлов приёма (/var/lib/m-ranked/transfer-ingest/raw-evidence) не
-- убирался ни разу: служба приёма работает ролью collector_ingest, а функция
-- снятия ссылки выдана только maintenance — каждый час InsufficientPrivilege,
-- 311 тысяч файлов и 1,3 ГБ от 21–22 сентября. Строки ingest.raw_payload
-- (297 тысяч, все просрочены с сентября) держала выключенная чистка: её
-- включение упёрлось бы во внешний ключ карантина.
--
-- Обе функции теперь пропускают доказательства в карантине (их держат для
-- разбора), а снятие ссылки разрешено и роли приёма.
--
-- Откат: прежние тела функций из 0011, REVOKE для collector_ingest.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE OR REPLACE FUNCTION ops_and_admin.purge_expired_raw_payload(p_limit integer DEFAULT 10000) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ingest', 'ops_and_admin'
    SET lock_timeout TO '10s'
    AS $$
DECLARE
    deleted_count bigint;
BEGIN
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100000 THEN
        RAISE EXCEPTION 'raw payload purge limit must be between 1 and 100000';
    END IF;
    WITH doomed AS (
        SELECT id
          FROM ingest.raw_payload payload
         WHERE purge_after <= transaction_timestamp()
           AND NOT EXISTS (SELECT 1 FROM ingest.evidence_quarantine quarantine
                            WHERE quarantine.raw_payload_id = payload.id)
         ORDER BY purge_after, id
         FOR UPDATE SKIP LOCKED
         LIMIT p_limit
    ), deleted AS (
        DELETE FROM ingest.raw_payload payload
         USING doomed
         WHERE payload.id = doomed.id
         RETURNING 1
    )
    SELECT count(*) INTO deleted_count FROM deleted;
    RETURN deleted_count;
END $$;

CREATE OR REPLACE FUNCTION ops_and_admin.purge_raw_evidence_reference(p_uri text, p_now timestamp with time zone) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ingest'
    AS $$
DECLARE removed bigint;
BEGIN
 DELETE FROM ingest.raw_payload payload
  WHERE payload.external_ref = p_uri AND payload.purge_after <= p_now
    AND NOT EXISTS (SELECT 1 FROM ingest.evidence_quarantine quarantine
                     WHERE quarantine.raw_payload_id = payload.id);
 GET DIAGNOSTICS removed = ROW_COUNT;
 RETURN removed;
END $$;

GRANT EXECUTE ON FUNCTION ops_and_admin.purge_raw_evidence_reference(text, timestamp with time zone) TO collector_ingest;
-- Уборка файлов не трогает доказательства в карантине — ей надо их видеть.
GRANT SELECT ON ingest.evidence_quarantine TO collector_ingest, maintenance;

COMMIT;
