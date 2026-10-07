-- Public read exposes only the reviewed reference count; admin controls updates.
BEGIN;
CREATE OR REPLACE FUNCTION analytics.official_social_rating_count() RETURNS integer
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO pg_catalog AS $$
  SELECT coalesce((SELECT CASE
    WHEN value->>'institutions' ~ '^[1-9][0-9]{0,3}$' THEN (value->>'institutions')::integer
    ELSE 233 END
    FROM ops_and_admin.operational_checkpoint
    WHERE checkpoint_key='admin.m_rating.coverage' AND scope_type='system'
      AND scope_id IS NULL AND platform IS NULL
    LIMIT 1), 233)
$$;
REVOKE ALL ON FUNCTION analytics.official_social_rating_count() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analytics.official_social_rating_count() TO api_read;
COMMIT;
