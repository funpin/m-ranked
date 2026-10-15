-- 0082 — справочник с Сервера 2 доходит до сборщиков Сервера 1.
--
-- В профиле B команды каталога (/manage → ops_and_admin.catalog_command)
-- пишут только базу Сервера 2, а сборщики читают catalog.platform_account из
-- своей базы на Сервере 1. Ничего между ними справочник не переносило: РУДН
-- (09.10) и пять вузов 15.10 не опрашивались, пока строки не скопировали
-- руками.
--
-- Две функции, по одной на сторону:
--
-- catalog.catalog_sync_snapshot() — Сервер 2. Один запрос, одно согласованное
--   чтение: учреждения, их внешние коды, аккаунты, псевдонимы каталога и
--   версии идентичности, заведённые администратором (source_run_id IS NULL).
--   Версии, увиденные сборщиком, пришли с Сервера 1 и там уже есть. Около
--   1 100 строк, ~250 КБ JSON. Вызывает приёмник переноса (collector_ingest).
--
-- catalog.apply_catalog_sync(jsonb) — Сервер 1, одна транзакция. Вызывает
--   отправитель переноса (outbox_worker).
--   * institution, institution_external_id, platform_account и псевдонимы —
--     с теми же id. Сервер 2 владелец: учреждения и внешние коды повторяют его
--     целиком; у аккаунта переносятся учреждение, режим доступа, включён,
--     удалён. Каждая запись сравнивает значения и ничего не пишет, если они
--     совпадают.
--   * account_identity_history и account_external_identity — без id: у
--     каждой базы своя последовательность. Версия администратора ложится,
--     только если она новее всего, что знает Сервер 1 об этом аккаунте.
--     Если сборщик увидел аккаунт позже правки, его наблюдение новее и
--     остаётся — сборщик не перетирается. current_username/title/url
--     меняются только вместе с такой открытой версией.
--   * Замки идентичности аккаунтов берутся до первой записи и в порядке id —
--     тот же ключ, что у сборщика (repository._persist_account_identity),
--     поэтому взаимной блокировки с записью пачки нет. lock_timeout 5 с:
--     занятый сборщиком аккаунт откладывает синхронизацию до следующего
--     прохода, а не держит сбор.
--
-- Откат: DROP FUNCTION catalog.apply_catalog_sync(jsonb);
--        DROP FUNCTION catalog.catalog_sync_snapshot();
--   Перенесённые строки остаются — они те же, что на Сервере 2.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE OR REPLACE FUNCTION catalog.catalog_sync_snapshot() RETURNS jsonb
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'catalog'
    AS $$
SELECT jsonb_build_object(
    'version', 1,
    'institutions', coalesce((
        SELECT jsonb_agg(to_jsonb(row) ORDER BY row.id) FROM catalog.institution row), '[]'::jsonb),
    'institutionExternalIds', coalesce((
        SELECT jsonb_agg(to_jsonb(row) ORDER BY row.id) FROM catalog.institution_external_id row), '[]'::jsonb),
    'accounts', coalesce((
        SELECT jsonb_agg(to_jsonb(row) ORDER BY row.id) FROM catalog.platform_account row), '[]'::jsonb),
    'aliases', coalesce((
        SELECT jsonb_agg(to_jsonb(row) ORDER BY row.entity_type, row.legacy_id)
          FROM catalog.legacy_entity_alias row
         WHERE row.entity_type IN ('institutions', 'channels', 'platform_accounts')), '[]'::jsonb),
    'identityHistory', coalesce((
        SELECT jsonb_agg(to_jsonb(row) - 'id' - 'source_run_id'
                         ORDER BY row.platform_account_id, row.valid_from)
          FROM catalog.account_identity_history row
         WHERE row.source_run_id IS NULL), '[]'::jsonb),
    'externalIdentities', coalesce((
        SELECT jsonb_agg(to_jsonb(row) - 'id' - 'source_run_id'
                         ORDER BY row.platform_account_id, row.identity_namespace, row.valid_from)
          FROM catalog.account_external_identity row
         WHERE row.source_run_id IS NULL), '[]'::jsonb)
)
$$;

CREATE OR REPLACE FUNCTION catalog.apply_catalog_sync(p_snapshot jsonb) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'catalog'
    SET lock_timeout TO '5s'
    SET statement_timeout TO '60s'
    AS $$
DECLARE
    result jsonb := '{}'::jsonb;
    changed integer;
    key text;
    account_id uuid;
    version record;
BEGIN
    -- Отправитель переноса Сервера 1 входит под outbox_worker или под
    -- логином, входящим в эту роль; другим писать справочник нельзя.
    IF NOT pg_has_role(session_user, 'outbox_worker', 'member') THEN
        RAISE EXCEPTION 'apply_catalog_sync is for the transfer sender only' USING ERRCODE = '42501';
    END IF;
    IF jsonb_typeof(p_snapshot) IS DISTINCT FROM 'object' OR p_snapshot->'version' IS DISTINCT FROM '1'::jsonb THEN
        RAISE EXCEPTION 'unsupported catalog snapshot' USING ERRCODE = '22023';
    END IF;
    FOREACH key IN ARRAY ARRAY['institutions', 'institutionExternalIds', 'accounts', 'aliases',
                               'identityHistory', 'externalIdentities'] LOOP
        IF jsonb_typeof(p_snapshot->key) IS DISTINCT FROM 'array' THEN
            RAISE EXCEPTION 'catalog snapshot lacks %', key USING ERRCODE = '22023';
        END IF;
    END LOOP;
    -- Пустой справочник — признак сбоя источника, а не правды: внешние коды
    -- повторяют его с удалением, и пустой снимок стёр бы их.
    IF jsonb_array_length(p_snapshot->'institutions') = 0 OR jsonb_array_length(p_snapshot->'accounts') = 0 THEN
        RAISE EXCEPTION 'catalog snapshot is empty' USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended('catalog-sync', 0));

    -- Замки идентичности всех аккаунтов, которые эта синхронизация тронет,
    -- до первой записи и по порядку. Обычно таких нет.
    FOR account_id IN
        SELECT target.id FROM (
            SELECT incoming.id FROM jsonb_populate_recordset(NULL::catalog.platform_account, p_snapshot->'accounts') incoming
              JOIN catalog.platform_account current ON current.id = incoming.id
             WHERE (current.institution_id, current.access_mode, current.enabled, current.deleted_at)
                   IS DISTINCT FROM (incoming.institution_id, incoming.access_mode, incoming.enabled, incoming.deleted_at)
            UNION
            SELECT incoming.platform_account_id FROM jsonb_populate_recordset(NULL::catalog.account_identity_history, p_snapshot->'identityHistory') incoming
             WHERE NOT EXISTS (
                   SELECT 1 FROM catalog.account_identity_history known_row
                    WHERE known_row.platform_account_id = incoming.platform_account_id
                      AND (known_row.valid_from >= incoming.valid_from OR known_row.valid_to > incoming.valid_from))
            UNION
            SELECT incoming.platform_account_id FROM jsonb_populate_recordset(NULL::catalog.account_external_identity, p_snapshot->'externalIdentities') incoming
             WHERE NOT EXISTS (
                   SELECT 1 FROM catalog.account_external_identity known_row
                    WHERE known_row.platform_account_id = incoming.platform_account_id
                      AND known_row.identity_namespace = incoming.identity_namespace
                      AND (known_row.valid_from >= incoming.valid_from OR known_row.valid_to > incoming.valid_from))
        ) target ORDER BY target.id
    LOOP
        PERFORM pg_advisory_xact_lock(hashtextextended('account-identity:' || account_id::text, 0));
    END LOOP;

    -- Учреждения: Сервер 2 единственный, кто их пишет.
    UPDATE catalog.institution current
       SET canonical_name = incoming.canonical_name, short_name = incoming.short_name,
           status = incoming.status, created_at = incoming.created_at, updated_at = incoming.updated_at,
           row_version = incoming.row_version, deleted_at = incoming.deleted_at
      FROM jsonb_populate_recordset(NULL::catalog.institution, p_snapshot->'institutions') incoming
     WHERE current.id = incoming.id
       AND (current.canonical_name, current.short_name, current.status, current.created_at,
            current.updated_at, current.row_version, current.deleted_at)
           IS DISTINCT FROM (incoming.canonical_name, incoming.short_name, incoming.status, incoming.created_at,
                             incoming.updated_at, incoming.row_version, incoming.deleted_at);
    GET DIAGNOSTICS changed = ROW_COUNT;
    result := result || jsonb_build_object('institutionsUpdated', changed);
    INSERT INTO catalog.institution(id, canonical_name, short_name, status, created_at, updated_at, row_version, deleted_at)
    SELECT id, canonical_name, short_name, status, created_at, updated_at, row_version, deleted_at
      FROM jsonb_populate_recordset(NULL::catalog.institution, p_snapshot->'institutions')
    ON CONFLICT (id) DO NOTHING;
    GET DIAGNOSTICS changed = ROW_COUNT;
    result := result || jsonb_build_object('institutionsInserted', changed);

    -- Внешние коды учреждений повторяются целиком, с удалением: сборщики их
    -- не пишут. Удаление и правка идут раньше вставки, чтобы закрытая на
    -- Сервере 2 версия освободила место открытой.
    DELETE FROM catalog.institution_external_id current
     WHERE NOT EXISTS (
           SELECT 1 FROM jsonb_populate_recordset(NULL::catalog.institution_external_id,
                                                  p_snapshot->'institutionExternalIds') incoming
            WHERE incoming.id = current.id);
    GET DIAGNOSTICS changed = ROW_COUNT;
    result := result || jsonb_build_object('institutionExternalIdsDeleted', changed);
    UPDATE catalog.institution_external_id current
       SET institution_id = incoming.institution_id, namespace = incoming.namespace,
           external_id = incoming.external_id, valid_from = incoming.valid_from,
           valid_to = incoming.valid_to, verified_at = incoming.verified_at
      FROM jsonb_populate_recordset(NULL::catalog.institution_external_id, p_snapshot->'institutionExternalIds') incoming
     WHERE current.id = incoming.id
       AND (current.institution_id, current.namespace, current.external_id, current.valid_from,
            current.valid_to, current.verified_at)
           IS DISTINCT FROM (incoming.institution_id, incoming.namespace, incoming.external_id, incoming.valid_from,
                             incoming.valid_to, incoming.verified_at);
    GET DIAGNOSTICS changed = ROW_COUNT;
    result := result || jsonb_build_object('institutionExternalIdsUpdated', changed);
    INSERT INTO catalog.institution_external_id(id, institution_id, namespace, external_id, valid_from, valid_to, verified_at)
    SELECT id, institution_id, namespace, external_id, valid_from, valid_to, verified_at
      FROM jsonb_populate_recordset(NULL::catalog.institution_external_id, p_snapshot->'institutionExternalIds')
    ON CONFLICT (id) DO NOTHING;
    GET DIAGNOSTICS changed = ROW_COUNT;
    result := result || jsonb_build_object('institutionExternalIdsInserted', changed);

    -- Аккаунты: то, что решает администратор. Видимые имя, заголовок и
    -- адрес принадлежат версиям идентичности ниже.
    UPDATE catalog.platform_account current
       SET institution_id = incoming.institution_id, access_mode = incoming.access_mode,
           enabled = incoming.enabled, deleted_at = incoming.deleted_at,
           updated_at = greatest(current.updated_at, incoming.updated_at),
           row_version = current.row_version + 1
      FROM jsonb_populate_recordset(NULL::catalog.platform_account, p_snapshot->'accounts') incoming
     WHERE current.id = incoming.id
       AND (current.institution_id, current.access_mode, current.enabled, current.deleted_at)
           IS DISTINCT FROM (incoming.institution_id, incoming.access_mode, incoming.enabled, incoming.deleted_at);
    GET DIAGNOSTICS changed = ROW_COUNT;
    result := result || jsonb_build_object('accountsUpdated', changed);
    -- Конфликт по живому (площадка, внешний ключ) с другим id не ломает
    -- синхронизацию: строка пропускается и считается ниже.
    INSERT INTO catalog.platform_account(id, institution_id, platform, canonical_external_id, current_username,
           current_title, current_url, access_mode, enabled, created_at, updated_at, row_version, deleted_at)
    SELECT id, institution_id, platform, canonical_external_id, current_username,
           current_title, current_url, access_mode, enabled, created_at, updated_at, row_version, deleted_at
      FROM jsonb_populate_recordset(NULL::catalog.platform_account, p_snapshot->'accounts')
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS changed = ROW_COUNT;
    result := result || jsonb_build_object('accountsInserted', changed);
    SELECT count(*) INTO changed FROM jsonb_populate_recordset(NULL::catalog.platform_account, p_snapshot->'accounts') incoming
     WHERE NOT EXISTS (SELECT 1 FROM catalog.platform_account current WHERE current.id = incoming.id);
    result := result || jsonb_build_object('accountConflicts', changed);

    INSERT INTO catalog.legacy_entity_alias(entity_type, legacy_id, target_uuid, legacy_route, source_hash, created_at)
    SELECT entity_type, legacy_id, target_uuid, legacy_route, source_hash, created_at
      FROM jsonb_populate_recordset(NULL::catalog.legacy_entity_alias, p_snapshot->'aliases')
     WHERE entity_type IN ('institutions', 'channels', 'platform_accounts')
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS changed = ROW_COUNT;
    result := result || jsonb_build_object('aliasesInserted', changed);

    -- Версии видимой идентичности, заведённые администратором. Ложится только
    -- версия новее всего, что Сервер 1 знает об аккаунте; старше — значит,
    -- сборщик уже видел аккаунт после правки, и его наблюдение остаётся.
    changed := 0;
    FOR version IN
        SELECT incoming.* FROM jsonb_populate_recordset(NULL::catalog.account_identity_history, p_snapshot->'identityHistory') incoming
          JOIN catalog.platform_account account ON account.id = incoming.platform_account_id
         ORDER BY incoming.platform_account_id, incoming.valid_from
    LOOP
        -- Версия уже есть или Сервер 1 знает что-то не раньше её начала.
        -- Конец версии, закрытой следующей версией администратора, равен
        -- началу следующей и её не загораживает.
        CONTINUE WHEN EXISTS (
            SELECT 1 FROM catalog.account_identity_history known_row
             WHERE known_row.platform_account_id = version.platform_account_id
               AND (known_row.valid_from >= version.valid_from OR known_row.valid_to > version.valid_from));
        UPDATE catalog.account_identity_history SET valid_to = version.valid_from
         WHERE platform_account_id = version.platform_account_id AND valid_to IS NULL;
        INSERT INTO catalog.account_identity_history(platform_account_id, username, title, url, valid_from, valid_to)
        VALUES (version.platform_account_id, version.username, version.title, version.url,
                version.valid_from, version.valid_to);
        IF version.valid_to IS NULL THEN
            UPDATE catalog.platform_account
               SET current_username = version.username, current_title = version.title,
                   current_url = version.url, updated_at = greatest(updated_at, version.valid_from),
                   row_version = row_version + 1
             WHERE id = version.platform_account_id
               AND (current_username, current_title, current_url)
                   IS DISTINCT FROM (version.username, version.title, version.url);
        END IF;
        changed := changed + 1;
    END LOOP;
    result := result || jsonb_build_object('identityVersionsInserted', changed);

    -- Нативные идентификаторы (chat_id MAX и т. п.), заданные администратором:
    -- то же правило по паре (аккаунт, пространство имён).
    changed := 0;
    FOR version IN
        SELECT incoming.* FROM jsonb_populate_recordset(NULL::catalog.account_external_identity, p_snapshot->'externalIdentities') incoming
          JOIN catalog.platform_account account ON account.id = incoming.platform_account_id
         ORDER BY incoming.platform_account_id, incoming.identity_namespace, incoming.valid_from
    LOOP
        CONTINUE WHEN EXISTS (
            SELECT 1 FROM catalog.account_external_identity known_row
             WHERE known_row.platform_account_id = version.platform_account_id
               AND known_row.identity_namespace = version.identity_namespace
               AND (known_row.valid_from >= version.valid_from OR known_row.valid_to > version.valid_from));
        UPDATE catalog.account_external_identity SET valid_to = version.valid_from
         WHERE platform_account_id = version.platform_account_id
           AND identity_namespace = version.identity_namespace AND valid_to IS NULL;
        INSERT INTO catalog.account_external_identity(platform_account_id, identity_namespace, external_id,
               valid_from, valid_to, verified_at)
        VALUES (version.platform_account_id, version.identity_namespace, version.external_id,
                version.valid_from, version.valid_to, version.verified_at);
        changed := changed + 1;
    END LOOP;
    result := result || jsonb_build_object('externalIdentitiesInserted', changed);

    RETURN result;
END
$$;

REVOKE ALL ON FUNCTION catalog.catalog_sync_snapshot() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION catalog.catalog_sync_snapshot() TO collector_ingest;
REVOKE ALL ON FUNCTION catalog.apply_catalog_sync(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION catalog.apply_catalog_sync(jsonb) TO outbox_worker;

COMMIT;
