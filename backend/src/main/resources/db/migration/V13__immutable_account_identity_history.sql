-- Canonical account identity is fixed at creation. Discovery of a native ID is
-- a new external-identity version, never a rewrite of the canonical key.
CREATE OR REPLACE FUNCTION catalog.guard_canonical_account_identity()
RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.platform IS DISTINCT FROM OLD.platform
       OR NEW.canonical_external_id IS DISTINCT FROM OLD.canonical_external_id THEN
        RAISE EXCEPTION 'canonical account identity is immutable' USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER platform_account_canonical_identity_immutable
BEFORE UPDATE ON catalog.platform_account FOR EACH ROW
EXECUTE FUNCTION catalog.guard_canonical_account_identity();

-- A current history row can only be closed once. Re-observation inserts a new
-- row; even the schema owner cannot rewrite or remove a historical value.
CREATE OR REPLACE FUNCTION catalog.guard_account_identity_history()
RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
    IF TG_OP='DELETE' THEN
        RAISE EXCEPTION 'account identity history is append-only' USING ERRCODE='55000';
    END IF;
    IF OLD.valid_to IS NOT NULL OR NEW.valid_to IS NULL
       OR NEW.valid_to <= OLD.valid_from
       OR (to_jsonb(NEW)-'valid_to') IS DISTINCT FROM (to_jsonb(OLD)-'valid_to') THEN
        RAISE EXCEPTION 'only closing the current account identity version is allowed' USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER account_identity_history_immutable BEFORE UPDATE OR DELETE
ON catalog.account_identity_history FOR EACH ROW
EXECUTE FUNCTION catalog.guard_account_identity_history();
CREATE TRIGGER account_external_identity_immutable BEFORE UPDATE OR DELETE
ON catalog.account_external_identity FOR EACH ROW
EXECUTE FUNCTION catalog.guard_account_identity_history();
