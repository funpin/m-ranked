SET ROLE migration_owner;
SET lock_timeout='10s';

-- Legacy catalogue references accept both HTTP and HTTPS. These are display
-- links, never outbound fetch instructions. Keep protocol restrictions on
-- provider clients and immutable raw evidence unchanged.
DO $constraints$
DECLARE item record; changed integer:=0;
BEGIN
    FOR item IN
        SELECT relation.relname,con.conname
        FROM pg_constraint con JOIN pg_class relation ON relation.oid=con.conrelid
        JOIN pg_namespace namespace ON namespace.oid=relation.relnamespace
        WHERE namespace.nspname='catalog' AND con.contype='c'
          AND relation.relname IN ('platform_account','account_identity_history')
          AND pg_get_constraintdef(con.oid) LIKE '%https://%'
    LOOP
        EXECUTE format('ALTER TABLE catalog.%I DROP CONSTRAINT %I',item.relname,item.conname);
        changed:=changed+1;
    END LOOP;
    IF changed<>2 THEN RAISE EXCEPTION 'catalogue URL constraint inventory changed'; END IF;
END $constraints$;
ALTER TABLE catalog.platform_account ADD CONSTRAINT platform_account_web_url
    CHECK(current_url IS NULL OR current_url ~* '^https?://');
ALTER TABLE catalog.account_identity_history ADD CONSTRAINT account_history_web_url
    CHECK(url IS NULL OR url ~* '^https?://');
ALTER TABLE analytics.legacy_overview_account DROP CONSTRAINT legacy_overview_account_url_check;
ALTER TABLE analytics.legacy_overview_account ADD CONSTRAINT legacy_overview_account_web_url
    CHECK(url IS NULL OR url ~* '^https?://');

-- An update with an expected version must never silently create a replacement
-- after the original account has been removed. Legacy upsert uses no expected
-- version; modern create additionally supplies an empty expectedAccountVersions.
DO $command$
DECLARE definition text; needle text:=E'            ELSE\n                INSERT INTO catalog.platform_account(institution_id,platform,canonical_external_id,current_username,';
BEGIN
    SELECT pg_get_functiondef('ops_and_admin.catalog_command(text,uuid,bigint,jsonb,text,uuid)'::regprocedure) INTO definition;
    IF (length(definition)-length(replace(definition,needle,'')))/length(needle)<>1 THEN
        RAISE EXCEPTION 'catalogue command create branch changed';
    END IF;
    EXECUTE replace(definition,needle,E'            ELSIF p_expected IS NOT NULL THEN\n                outcome:=''version_conflict'';\n            ELSE\n                INSERT INTO catalog.platform_account(institution_id,platform,canonical_external_id,current_username,');
END $command$;
RESET ROLE;
