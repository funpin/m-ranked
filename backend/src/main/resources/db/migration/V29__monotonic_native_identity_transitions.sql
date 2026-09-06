-- Closing a future-observed native identity must not let later reenrollment
-- reopen history before that accepted boundary. Earlier values remain immutable.
SET ROLE migration_owner;
SET lock_timeout='10s';
DO $command$
DECLARE definition text;
    needle text:=E'SELECT greatest(transaction_timestamp(),max(valid_from)+interval ''1 microsecond'') INTO transition\n                            FROM catalog.account_external_identity WHERE platform_account_id=target\n                            AND identity_namespace=account.platform::text||'':native_id'' AND valid_to IS NULL;';
    replacement text:=E'SELECT greatest(transaction_timestamp(),max(greatest(valid_from,valid_to))+interval ''1 microsecond'') INTO transition\n                            FROM catalog.account_external_identity WHERE platform_account_id=target\n                            AND identity_namespace=account.platform::text||'':native_id'';';
BEGIN
    SELECT pg_get_functiondef('ops_and_admin.catalog_command(text,uuid,bigint,jsonb,text,uuid)'::regprocedure) INTO definition;
    IF (length(definition)-length(replace(definition,needle,'')))/length(needle)<>1 THEN
        RAISE EXCEPTION 'native identity transition branch changed';
    END IF;
    EXECUTE replace(definition,needle,replacement);
END $command$;
RESET ROLE;
