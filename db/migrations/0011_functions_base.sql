-- 0011 — функции, не зависящие от представлений
-- Порождается из каталога эталонной базы; см. db/README.md.

-- analytics.anomaly_input_is_unchanged(uuid, text, text)
CREATE FUNCTION analytics.anomaly_input_is_unchanged(p_publication_id uuid, p_input_hash text, p_manifest_hash text) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'analytics'
    AS $$
SELECT EXISTS(
    SELECT 1 FROM analytics.publication_analysis_state state
     WHERE state.publication_id=p_publication_id
       AND state.current_success_attempt_id IS NOT NULL
       AND state.status IN ('ready','partial')
       AND state.input_hash=p_input_hash
       AND state.detector_manifest_hash=p_manifest_hash
)
$$;

-- analytics.latest_dataset_revision()
-- Без материализованных проекций публиковать нечего: ревизия видна сразу после
-- фиксации. Прежняя latest_fully_published_dataset_revision() возвращала последнюю
-- ревизию, для которой все семь проекций имели статус ready, и была барьером,
-- из-за которого свежие данные не показывались до прогона publisher.
CREATE FUNCTION analytics.latest_dataset_revision() RETURNS TABLE(id bigint, committed_at timestamp with time zone)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'analytics'
    AS $$
SELECT revision.id, revision.committed_at
  FROM analytics.dataset_revision revision
 ORDER BY revision.id DESC
 LIMIT 1
$$;

-- analytics.anomaly_operational_metrics()
CREATE FUNCTION analytics.anomaly_operational_metrics() RETURNS jsonb
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'analytics', 'ops_and_admin'
    AS $$
SELECT jsonb_build_object(
  'candidate_backlog',(SELECT count(*) FROM ops_and_admin.anomaly_analysis_candidate),
  'eligible_backlog',(SELECT count(*) FROM ops_and_admin.anomaly_analysis_candidate WHERE eligible_at<=transaction_timestamp()),
  'oldest_candidate_age_seconds',(SELECT coalesce(greatest(0,extract(epoch FROM transaction_timestamp()-min(eligible_at))),0) FROM ops_and_admin.anomaly_analysis_candidate),
  'expired_leases',(SELECT count(*) FROM ops_and_admin.anomaly_analysis_candidate WHERE claim_token IS NOT NULL AND leased_until<transaction_timestamp()),
  'retry_candidates',(SELECT count(*) FROM ops_and_admin.anomaly_analysis_candidate WHERE retry_count>0),
  'failures_last_hour',(SELECT count(*) FROM analytics.publication_analysis_attempt WHERE status='failed' AND completed_at>=transaction_timestamp()-interval '1 hour'),
  'latest_analysis_revision',(SELECT coalesce(max(id),0) FROM analytics.anomaly_analysis_revision),
  'latest_source_dataset_revision',(SELECT coalesce(max(source_dataset_revision_id),0) FROM analytics.publication_analysis_state),
  'source_revision_lag',greatest(0,
      coalesce((SELECT id FROM analytics.latest_dataset_revision()),0)
      -(SELECT coalesce(max(source_dataset_revision_id),0) FROM analytics.publication_analysis_state)),
  'last_success_unixtime',(SELECT coalesce(extract(epoch FROM max(completed_at)),0) FROM analytics.publication_analysis_attempt WHERE status='succeeded')
)
$$;

-- analytics.append_anomaly_review(uuid, text, text, text, uuid, uuid, text)
CREATE FUNCTION analytics.append_anomaly_review(p_finding_id uuid, p_decision text, p_private_comment text, p_subject text, p_correlation_id uuid, p_idempotency_key uuid, p_request_digest text) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'analytics', 'ops_and_admin'
    AS $$
DECLARE existing ops_and_admin.anomaly_command_receipt%ROWTYPE; publication uuid; key uuid; review uuid; revision bigint; result jsonb;
BEGIN
 SELECT * INTO existing FROM ops_and_admin.anomaly_command_receipt WHERE subject=p_subject AND command_type='review' AND idempotency_key=p_idempotency_key;
 IF FOUND THEN
   IF existing.request_digest<>p_request_digest THEN RAISE EXCEPTION 'idempotency digest conflict' USING ERRCODE='23505'; END IF;
   RETURN existing.result;
 END IF;
 IF p_decision NOT IN ('explained','unresolved','data_error','dismissed') OR length(coalesce(p_private_comment,''))>2000 THEN
   RAISE EXCEPTION 'invalid anomaly review'; END IF;
 SELECT publication_id,finding_key INTO publication,key FROM analytics.publication_anomaly_finding WHERE id=p_finding_id;
 IF publication IS NULL THEN RAISE EXCEPTION 'anomaly finding not found' USING ERRCODE='P0002'; END IF;
 review:=gen_random_uuid();
 INSERT INTO analytics.anomaly_analysis_revision(publication_id,reason) VALUES(publication,'review') RETURNING id INTO revision;
 INSERT INTO analytics.publication_anomaly_review(id,publication_id,finding_key,finding_id,analysis_revision_id,reviewer_subject,decision,private_comment)
 VALUES(review,publication,key,p_finding_id,revision,p_subject,p_decision::analytics.review_decision,p_private_comment);
 UPDATE analytics.publication_analysis_state SET analysis_revision_id=revision WHERE publication_id=publication;
 result:=jsonb_build_object('reviewId',review,'findingId',p_finding_id,'analysisRevision',revision,'decision',p_decision);
 INSERT INTO ops_and_admin.anomaly_command_receipt VALUES(p_subject,'review',p_idempotency_key,p_request_digest,result,transaction_timestamp());
 INSERT INTO ops_and_admin.audit_log(subject,action,target_type,target_id,correlation_id,after_state,outcome)
 VALUES(p_subject,'anomaly.review.append','publication_anomaly_finding',p_finding_id,p_correlation_id,
        jsonb_build_object('decision',p_decision),'succeeded');
 RETURN result;
END $$;

-- analytics.create_manual_anomaly_signal(uuid, text, text, text, timestamp with time zone, timestamp with time zone, jsonb, text, uuid, uuid, text)
CREATE FUNCTION analytics.create_manual_anomaly_signal(p_publication_id uuid, p_metric text, p_severity text, p_explanation_code text, p_start_at timestamp with time zone, p_end_at timestamp with time zone, p_evidence jsonb, p_subject text, p_correlation_id uuid, p_idempotency_key uuid, p_request_digest text) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'analytics', 'ops_and_admin'
    AS $_$
DECLARE existing ops_and_admin.anomaly_command_receipt%ROWTYPE; finding uuid; revision bigint; result jsonb;
BEGIN
 SELECT * INTO existing FROM ops_and_admin.anomaly_command_receipt WHERE subject=p_subject AND command_type='manual_signal' AND idempotency_key=p_idempotency_key;
 IF FOUND THEN
   IF existing.request_digest<>p_request_digest THEN RAISE EXCEPTION 'idempotency digest conflict' USING ERRCODE='23505'; END IF;
   RETURN existing.result;
 END IF;
 IF p_metric NOT IN ('views','reactions','comments','shares') OR p_severity NOT IN ('low','medium','high')
    OR p_explanation_code !~ '^[a-z0-9_]{1,80}$' OR p_end_at<=p_start_at OR pg_column_size(p_evidence)>8192 THEN
   RAISE EXCEPTION 'invalid manual anomaly signal'; END IF;
 finding:=gen_random_uuid();
 INSERT INTO analytics.anomaly_analysis_revision(publication_id,reason) VALUES(p_publication_id,'manual_signal') RETURNING id INTO revision;
 INSERT INTO analytics.publication_anomaly_finding(id,finding_key,publication_id,created_analysis_revision_id,origin,metric,severity,
   explanation_code,suspicious_start_at,suspicious_end_at,evidence)
 VALUES(finding,finding,p_publication_id,revision,'manual',p_metric::analytics.metric_key,p_severity,p_explanation_code,p_start_at,p_end_at,p_evidence);
 INSERT INTO analytics.publication_analysis_state(publication_id,analysis_revision_id,status)
 VALUES(p_publication_id,revision,'pending') ON CONFLICT(publication_id) DO UPDATE SET analysis_revision_id=excluded.analysis_revision_id;
 result:=jsonb_build_object('findingId',finding,'analysisRevision',revision);
 INSERT INTO ops_and_admin.anomaly_command_receipt VALUES(p_subject,'manual_signal',p_idempotency_key,p_request_digest,result,transaction_timestamp());
 INSERT INTO ops_and_admin.audit_log(subject,action,target_type,target_id,correlation_id,after_state,outcome)
 VALUES(p_subject,'anomaly.manual_signal.create','publication_anomaly_finding',finding,p_correlation_id,
        jsonb_build_object('publicationId',p_publication_id,'metric',p_metric,'severity',p_severity),'succeeded');
 RETURN result;
END $_$;

-- analytics.extract_publication_history_as_of(uuid[], bigint, integer)
CREATE FUNCTION analytics.extract_publication_history_as_of(p_publication_ids uuid[], p_source_dataset_revision bigint, p_max_points integer) RETURNS TABLE(publication_id uuid, institution_id uuid, account_id uuid, platform text, published_at timestamp with time zone, deleted_at timestamp with time zone, history_completeness text, source_revision_at timestamp with time zone, snapshot_id text, observed_at timestamp with time zone, age_seconds integer, views_count bigint, reactions_count bigint, comments_count bigint, shares_count bigint, views_quality text, reactions_quality text, comments_quality text, shares_quality text, synthetic boolean, interval_uncertain boolean, correction_sequence bigint, supersedes_snapshot_id text, metric_semantics_version integer, capability_version integer, supported_metrics text[], point_ordinal bigint, total_points bigint)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'catalog', 'ingest', 'analytics'
    SET statement_timeout TO '15s'
    AS $$
DECLARE anchor timestamptz;
BEGIN
    IF cardinality(p_publication_ids)<1 OR cardinality(p_publication_ids)>100 OR p_max_points<1 OR p_max_points>10000 THEN
        RAISE EXCEPTION 'invalid anomaly extraction bounds';
    END IF;
    SELECT pinned.committed_at INTO anchor
      FROM analytics.anomaly_source_revision pinned
     WHERE pinned.dataset_revision_id=p_source_dataset_revision;
    IF anchor IS NULL THEN RAISE EXCEPTION 'source dataset revision is not fully published'; END IF;
    RETURN QUERY
    WITH ranked_corrections AS (
        SELECT snapshot.*,
               row_number() OVER(PARTITION BY snapshot.published_month,snapshot.publication_id,snapshot.sampling_bucket
                                 ORDER BY snapshot.correction_sequence DESC,snapshot.id DESC) AS correction_rank
          FROM ingest.publication_metric_snapshot snapshot
         WHERE snapshot.publication_id=ANY(p_publication_ids) AND snapshot.created_at<=anchor
    ), effective AS (
        SELECT snapshot.*,
               row_number() OVER(PARTITION BY snapshot.publication_id ORDER BY snapshot.observed_at,snapshot.id) AS ordinal,
               count(*) OVER(PARTITION BY snapshot.publication_id) AS points
          FROM ranked_corrections snapshot WHERE snapshot.correction_rank=1
    )
    SELECT publication.id,account.institution_id,account.id,account.platform::text,publication.published_at,
           publication.deleted_at,publication.history_completeness::text,anchor,
           effective.id::text,effective.observed_at,effective.age_seconds,
           CASE WHEN effective.views_quality IN ('invalid','suspected_reset') THEN NULL ELSE effective.views_count END,
           CASE WHEN effective.reactions_quality IN ('invalid','suspected_reset') THEN NULL ELSE effective.reactions_count END,
           CASE WHEN effective.comments_quality IN ('invalid','suspected_reset') THEN NULL ELSE effective.comments_count END,
           CASE WHEN effective.shares_quality IN ('invalid','suspected_reset') THEN NULL ELSE effective.shares_count END,
           effective.views_quality::text,effective.reactions_quality::text,effective.comments_quality::text,effective.shares_quality::text,
           effective.synthetic,effective.interval_uncertain,effective.correction_sequence,effective.supersedes_snapshot_id::text,
           effective.metric_semantics_version,effective.capability_version,
           ARRAY(SELECT capability.metric_key::text
                   FROM (SELECT DISTINCT ON (c.metric_key) c.metric_key,c.supported
                           FROM analytics.platform_metric_capability c
                          WHERE c.platform=account.platform AND c.effective_from<=anchor
                            AND (c.retired_at IS NULL OR c.retired_at>anchor)
                          ORDER BY c.metric_key,c.capability_version DESC) capability
                  WHERE capability.supported ORDER BY 1),
           effective.ordinal,effective.points
      FROM effective
      JOIN ingest.publication publication ON publication.id=effective.publication_id
      JOIN catalog.platform_account account ON account.id=publication.primary_account_id
     WHERE effective.ordinal<=p_max_points+1
     ORDER BY publication.id,effective.ordinal;
END $$;

-- analytics.guard_legacy_period_policy()
CREATE FUNCTION analytics.guard_legacy_period_policy() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'analytics'
    AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('analytics.legacy_period_policy',0));
    -- Прежде барьером была последняя опубликованная проекция. Проекций нет,
    -- данные отдаются живыми, поэтому политику нельзя привязать к ревизии
    -- старее последней зафиксированной: её данные уже отданы наружу.
    IF NEW.effective_from_revision<coalesce((SELECT max(id) FROM analytics.dataset_revision),0)
       OR NEW.effective_from_revision<=coalesce((SELECT max(effective_from_revision) FROM analytics.legacy_period_policy),0)
       OR NOT EXISTS(SELECT 1 FROM analytics.dataset_revision WHERE id=NEW.effective_from_revision AND cause='configuration') THEN
        RAISE EXCEPTION 'period policy requires a new unpublished configuration revision' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;

-- analytics.legacy_period_first_age_limit(bigint)
CREATE FUNCTION analytics.legacy_period_first_age_limit(p_revision bigint) RETURNS integer
    LANGUAGE sql STABLE
    SET search_path TO 'pg_catalog', 'analytics'
    AS $$
    SELECT first_age_limit_seconds FROM analytics.legacy_period_policy
    WHERE effective_from_revision<=p_revision ORDER BY effective_from_revision DESC LIMIT 1
$$;

-- analytics.observation_quality_from_rank(integer)
CREATE FUNCTION analytics.observation_quality_from_rank(p_rank integer) RETURNS ingest.observation_quality
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'ingest', 'analytics'
    AS $$
    SELECT CASE coalesce(p_rank, 3)
        WHEN 0 THEN 'exact'
        WHEN 1 THEN 'rounded'
        WHEN 2 THEN 'estimated'
        WHEN 3 THEN 'unknown'
        WHEN 4 THEN 'degraded'
        WHEN 5 THEN 'suspected_reset'
        ELSE 'invalid'
    END::ingest.observation_quality
$$;

-- analytics.observation_quality_rank(ingest.observation_quality)
CREATE FUNCTION analytics.observation_quality_rank(p_quality ingest.observation_quality) RETURNS smallint
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'ingest', 'analytics'
    AS $$
    SELECT CASE p_quality
        WHEN 'exact' THEN 0
        WHEN 'rounded' THEN 1
        WHEN 'estimated' THEN 2
        WHEN 'unknown' THEN 3
        WHEN 'degraded' THEN 4
        WHEN 'suspected_reset' THEN 5
        WHEN 'invalid' THEN 6
    END::smallint
$$;

-- analytics.ordered_history_reactions(text, boolean)
CREATE FUNCTION analytics.ordered_history_reactions(p_text text, p_signed boolean DEFAULT false) RETURNS jsonb
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'pg_catalog'
    AS $_$
DECLARE document json;entry record;result jsonb;
BEGIN
    IF p_text IS NULL OR octet_length(p_text)>1048576 THEN RETURN NULL; END IF;
    document:=p_text::json;
    IF json_typeof(document)<>'object' THEN RETURN NULL; END IF;
    IF (SELECT count(*) FROM json_each(document))>1024 THEN RETURN NULL; END IF;
    FOR entry IN SELECT key,value FROM json_each(document) LOOP
        -- Only reaction labels and integer counts cross the public boundary. The
        -- retained payload itself, arbitrary fields, URLs and secrets stay private.
        IF entry.key='' OR length(entry.key)>200 OR entry.key~'[[:cntrl:]]'
            OR entry.key~*'(password|secret|token|session|cookie|authorization|://)'
            OR json_typeof(entry.value)<>'number' OR entry.value::text!~'^-?[0-9]+$'
            OR (entry.value::text)::numeric NOT BETWEEN '-9223372036854775808'::numeric AND '9223372036854775807'::numeric
            OR (NOT p_signed AND (entry.value::text)::bigint<0) THEN RETURN NULL; END IF;
    END LOOP;
    -- Python json.loads keeps the first key position and the last duplicate value.
    WITH entries AS (
        SELECT key,value,ordinality,min(ordinality) OVER(PARTITION BY key) AS first_position
        FROM json_each(document) WITH ORDINALITY
    ), last_value AS (
        SELECT DISTINCT ON(key) key,value,first_position FROM entries ORDER BY key,ordinality DESC
    )
    SELECT coalesce(jsonb_agg(jsonb_build_object('reaction',key,'count',(value::text)::bigint)
        ORDER BY first_position),'[]'::jsonb) INTO result FROM last_value;
    RETURN result;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN RETURN NULL;
END $_$;


SET default_tablespace = '';

SET default_table_access_method = heap;

-- analytics.publish_anomaly_failure(uuid, uuid, bigint, uuid, bigint, text, text, text, integer, integer, timestamp with time zone, text, integer)
CREATE FUNCTION analytics.publish_anomaly_failure(p_publication_id uuid, p_claim_token uuid, p_generation bigint, p_attempt_key uuid, p_source_revision bigint, p_manifest_hash text, p_preprocessor text, p_aggregator text, p_semantic_version integer, p_capability_version integer, p_started_at timestamp with time zone, p_error_code text, p_retry_seconds integer) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'analytics', 'ops_and_admin'
    SET statement_timeout TO '15s'
    AS $_$
DECLARE attempt uuid; revision bigint; source_at timestamptz; previous_failure uuid; has_success boolean;
BEGIN
    IF p_error_code !~ '^[a-z0-9_]{1,64}$' OR p_retry_seconds<1 OR p_retry_seconds>86400 THEN
       RAISE EXCEPTION 'invalid anomaly failure envelope'; END IF;
    SELECT id INTO attempt FROM analytics.publication_analysis_attempt
     WHERE publication_id=p_publication_id AND attempt_key=p_attempt_key;
    IF FOUND THEN SELECT analysis_revision_id INTO revision FROM analytics.publication_analysis_attempt WHERE id=attempt; RETURN revision; END IF;
    PERFORM 1 FROM ops_and_admin.anomaly_analysis_candidate
     WHERE publication_id=p_publication_id AND claim_token=p_claim_token AND claimed_generation=p_generation FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'anomaly claim lost' USING ERRCODE='55000'; END IF;
    SELECT committed_at INTO source_at FROM analytics.anomaly_source_revision WHERE dataset_revision_id=p_source_revision;
    IF source_at IS NULL THEN RAISE EXCEPTION 'source revision was not pinned as fully published'; END IF;
    SELECT latest_failure_attempt_id,current_success_attempt_id IS NOT NULL INTO previous_failure,has_success
      FROM analytics.publication_analysis_state WHERE publication_id=p_publication_id FOR UPDATE;
    INSERT INTO analytics.anomaly_analysis_revision(publication_id,reason)
      VALUES(p_publication_id,'automatic_failure') RETURNING id INTO revision;
    INSERT INTO analytics.publication_analysis_attempt(
      publication_id,attempt_key,status,claimed_generation,source_dataset_revision_id,source_revision_at,
      detector_manifest_hash,preprocessing_version,aggregator_version,metric_semantics_version,capability_version,
      started_at,error_code,analysis_revision_id
    ) VALUES(p_publication_id,p_attempt_key,'failed',p_generation,p_source_revision,source_at,p_manifest_hash,
      p_preprocessor,p_aggregator,p_semantic_version,p_capability_version,p_started_at,p_error_code,revision)
      RETURNING id INTO attempt;
    INSERT INTO analytics.publication_analysis_state(publication_id,analysis_revision_id,latest_failure_attempt_id,status)
      VALUES(p_publication_id,revision,attempt,CASE WHEN has_success THEN 'stale' ELSE 'failed' END)
    ON CONFLICT(publication_id) DO UPDATE SET analysis_revision_id=excluded.analysis_revision_id,
      latest_failure_attempt_id=excluded.latest_failure_attempt_id,status=excluded.status;
    IF previous_failure IS NOT NULL AND previous_failure<>attempt THEN
      PERFORM ops_and_admin.record_anomaly_attempt_tombstone(previous_failure,attempt,'superseded_by_failure');
      DELETE FROM analytics.publication_analysis_attempt WHERE id=previous_failure;
    END IF;
    UPDATE ops_and_admin.anomaly_analysis_candidate SET claim_token=NULL,claimed_generation=NULL,leased_until=NULL,
      retry_count=least(retry_count+1,20),last_error_code=p_error_code,
      eligible_at=transaction_timestamp()+make_interval(secs=>p_retry_seconds),updated_at=transaction_timestamp()
     WHERE publication_id=p_publication_id AND claim_token=p_claim_token AND claimed_generation=p_generation;
    RETURN revision;
END $_$;

-- analytics.publish_anomaly_success(uuid, uuid, bigint, uuid, bigint, text, text, text, text, integer, integer, timestamp with time zone, text, numeric, text, jsonb)
CREATE FUNCTION analytics.publish_anomaly_success(p_publication_id uuid, p_claim_token uuid, p_generation bigint, p_attempt_key uuid, p_source_revision bigint, p_input_hash text, p_manifest_hash text, p_preprocessor text, p_aggregator text, p_semantic_version integer, p_capability_version integer, p_started_at timestamp with time zone, p_status text, p_score numeric, p_severity text, p_findings jsonb) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'analytics', 'ops_and_admin'
    SET statement_timeout TO '15s'
    AS $$
DECLARE attempt uuid; revision bigint; source_at timestamptz; previous_success uuid;
BEGIN
    IF p_status NOT IN ('ready','partial') OR (p_score IS NOT NULL AND (p_score<0 OR p_score>1))
       OR jsonb_typeof(p_findings)<>'array' OR jsonb_array_length(p_findings)>200 THEN
        RAISE EXCEPTION 'invalid anomaly success envelope';
    END IF;
    SELECT id INTO attempt FROM analytics.publication_analysis_attempt
     WHERE publication_id=p_publication_id AND attempt_key=p_attempt_key;
    IF FOUND THEN
        SELECT analysis_revision_id INTO revision FROM analytics.publication_analysis_attempt WHERE id=attempt;
        RETURN revision;
    END IF;
    PERFORM 1 FROM ops_and_admin.anomaly_analysis_candidate
     WHERE publication_id=p_publication_id AND claim_token=p_claim_token AND claimed_generation=p_generation FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'anomaly claim lost' USING ERRCODE='55000'; END IF;
    SELECT committed_at INTO source_at FROM analytics.anomaly_source_revision WHERE dataset_revision_id=p_source_revision;
    IF source_at IS NULL THEN RAISE EXCEPTION 'source revision was not pinned as fully published'; END IF;
    INSERT INTO analytics.anomaly_analysis_revision(publication_id,reason)
      VALUES(p_publication_id,'automatic_success') RETURNING id INTO revision;
    INSERT INTO analytics.publication_analysis_attempt(
      publication_id,attempt_key,status,claimed_generation,source_dataset_revision_id,source_revision_at,input_hash,
      detector_manifest_hash,preprocessing_version,aggregator_version,metric_semantics_version,capability_version,
      started_at,analysis_revision_id
    ) VALUES(p_publication_id,p_attempt_key,'succeeded',p_generation,p_source_revision,source_at,p_input_hash,
      p_manifest_hash,p_preprocessor,p_aggregator,p_semantic_version,p_capability_version,p_started_at,revision)
      RETURNING id INTO attempt;
    INSERT INTO analytics.publication_anomaly_finding(
      id,finding_key,publication_id,attempt_id,created_analysis_revision_id,origin,metric,detector_id,detector_version,
      suspicion_score,severity,explanation_code,suspicious_start_at,suspicious_end_at,start_snapshot_id,end_snapshot_id,
      evidence,quality_codes,alternative_explanation_codes
    ) SELECT md5(attempt::text||':'||keyed.finding_key::text)::uuid,keyed.finding_key,p_publication_id,attempt,revision,
      'automatic',keyed.metric::analytics.metric_key,
      keyed.detector_id,keyed.detector_version,keyed.score,keyed.severity,keyed.explanation_code,
      keyed.start_at,keyed.end_at,keyed.start_snapshot_id,keyed.end_snapshot_id,
      keyed.evidence,coalesce(keyed.quality_codes,ARRAY[]::text[]),coalesce(keyed.alternative_codes,ARRAY[]::text[])
      FROM (
        SELECT finding.*,
               md5(p_publication_id::text||':automatic:'||finding.metric||':'||finding.detector_id||':'
                   ||finding.detector_version||':'||coalesce(finding.start_snapshot_id,'')||':'
                   ||coalesce(finding.end_snapshot_id,''))::uuid AS finding_key
          FROM jsonb_to_recordset(p_findings) AS finding(
            metric text,detector_id text,detector_version text,score numeric,severity text,explanation_code text,
            start_at timestamptz,end_at timestamptz,start_snapshot_id text,end_snapshot_id text,evidence jsonb,
            quality_codes text[],alternative_codes text[])
      ) keyed;
    SELECT current_success_attempt_id INTO previous_success
      FROM analytics.publication_analysis_state WHERE publication_id=p_publication_id FOR UPDATE;
    INSERT INTO analytics.publication_analysis_state(
      publication_id,analysis_revision_id,current_success_attempt_id,status,suspicion_score,automatic_severity,
      affected_metrics,active_automatic_finding_count,source_dataset_revision_id,source_revision_at,analyzed_at,
      input_hash,detector_manifest_hash,preprocessing_version,aggregator_version
    ) SELECT p_publication_id,revision,attempt,p_status,p_score,p_severity,
      coalesce(array_agg(DISTINCT (item->>'metric')::analytics.metric_key) FILTER(WHERE item ? 'metric'),ARRAY[]::analytics.metric_key[]),
      jsonb_array_length(p_findings),p_source_revision,source_at,transaction_timestamp(),p_input_hash,p_manifest_hash,p_preprocessor,p_aggregator
      FROM jsonb_array_elements(p_findings) item
    ON CONFLICT(publication_id) DO UPDATE SET
      analysis_revision_id=excluded.analysis_revision_id,current_success_attempt_id=excluded.current_success_attempt_id,
      status=excluded.status,suspicion_score=excluded.suspicion_score,automatic_severity=excluded.automatic_severity,
      affected_metrics=excluded.affected_metrics,active_automatic_finding_count=excluded.active_automatic_finding_count,
      source_dataset_revision_id=excluded.source_dataset_revision_id,source_revision_at=excluded.source_revision_at,
      analyzed_at=excluded.analyzed_at,input_hash=excluded.input_hash,detector_manifest_hash=excluded.detector_manifest_hash,
      preprocessing_version=excluded.preprocessing_version,aggregator_version=excluded.aggregator_version;
    IF previous_success IS NOT NULL AND previous_success<>attempt THEN
        -- Two-slot retention: the superseded generated payload is removed after the
        -- pointer switch; the audit log keeps only safe attempt metadata.
        PERFORM ops_and_admin.record_anomaly_attempt_tombstone(previous_success,attempt,'superseded_by_success');
        DELETE FROM analytics.publication_analysis_attempt WHERE id=previous_success;
    END IF;
    PERFORM ops_and_admin.complete_anomaly_noop(p_publication_id,p_claim_token,p_generation);
    RETURN revision;
END $$;

-- analytics.refresh_history_reaction_details(bigint)
CREATE FUNCTION analytics.refresh_history_reaction_details(p_revision bigint) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'analytics'
    AS $$
DECLARE written bigint;
BEGIN
    WITH history AS MATERIALIZED (
        SELECT item.*,
               lag(item.reaction_breakdown) OVER chronology AS prior_reactions,
               lag(item.reactions_count) OVER chronology AS prior_reactions_count
          FROM analytics.publication_history AS item
         WHERE dataset_revision_id = p_revision
        WINDOW chronology AS (
            PARTITION BY publication_id
            ORDER BY observed_at, published_month, snapshot_id
        )
    ), entries AS (
        SELECT history.*,
               coalesce(
                   analytics.ordered_history_reactions(
                       reaction_breakdown::text, false
                   ),
                   '[]'::jsonb
               ) AS current_entries,
               CASE
                 WHEN reactions_count IS NULL OR prior_reactions_count IS NULL
                   THEN NULL
                 ELSE (
                   SELECT coalesce(jsonb_agg(jsonb_build_object(
                       'reaction', key, 'count', difference
                   ) ORDER BY key COLLATE "C"), '[]'::jsonb)
                     FROM (
                       SELECT key,
                              coalesce((reaction_breakdown->>key)::bigint, 0)
                              - coalesce((prior_reactions->>key)::bigint, 0)
                              AS difference
                         FROM (
                           SELECT jsonb_object_keys(reaction_breakdown) AS key
                           UNION
                           SELECT jsonb_object_keys(prior_reactions) AS key
                         ) AS keys
                     ) AS deltas
                    WHERE difference <> 0
                 )
               END AS delta_entries
          FROM history
    )
    UPDATE analytics.publication_history AS target
       SET reaction_entries = entries.current_entries,
           delta_reaction_entries = entries.delta_entries,
           delta_reaction_breakdown = CASE
             WHEN entries.delta_entries IS NULL THEN NULL
             ELSE (
               SELECT coalesce(jsonb_object_agg(
                   value->>'reaction', value->'count'
               ), '{}'::jsonb)
                 FROM jsonb_array_elements(entries.delta_entries)
             )
           END,
           lineage = target.lineage || jsonb_build_object(
               'reactionDetailsSource', 'canonical'
           )
      FROM entries
     WHERE target.publication_id = entries.publication_id
       AND target.published_month = entries.published_month
       AND target.snapshot_id = entries.snapshot_id
       AND target.dataset_revision_id = p_revision;
    GET DIAGNOSTICS written = ROW_COUNT;
    RETURN written;
END
$$;

-- analytics.refresh_official_account_ratings(bigint)
CREATE FUNCTION analytics.refresh_official_account_ratings(p_revision bigint) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'analytics', 'rating'
    AS $$
DECLARE written bigint;
BEGIN
    UPDATE analytics.legacy_overview_card
       SET rating_rank = NULL,
           rating_score = NULL,
           rating_period = NULL,
           rating_fetched_at = NULL
     WHERE platform = 'telegram'
       AND dataset_revision_id = p_revision;

    WITH latest AS (
        SELECT DISTINCT ON (observation.platform_account_id) observation.*
          FROM rating.official_account_rating_observation AS observation
          JOIN analytics.dataset_revision AS revision ON revision.id = p_revision
         WHERE observation.fetched_at <= revision.committed_at
         ORDER BY observation.platform_account_id,
                  observation.fetched_at DESC,
                  observation.id DESC
    )
    UPDATE analytics.legacy_overview_card AS card
       SET rating_rank = latest.rank,
           rating_score = latest.score,
           rating_period = latest.period,
           rating_fetched_at = latest.fetched_at
      FROM latest
     WHERE card.platform = 'telegram'
       AND card.entity_id = latest.platform_account_id
       AND card.dataset_revision_id = p_revision;
    GET DIAGNOSTICS written = ROW_COUNT;
    RETURN written;
END
$$;

-- catalog.guard_account_identity_history()
CREATE FUNCTION catalog.guard_account_identity_history() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
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

-- catalog.guard_canonical_account_identity()
CREATE FUNCTION catalog.guard_canonical_account_identity() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.platform IS DISTINCT FROM OLD.platform
       OR NEW.canonical_external_id IS DISTINCT FROM OLD.canonical_external_id THEN
        RAISE EXCEPTION 'canonical account identity is immutable' USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END $$;

-- ingest.assert_publication_snapshot_month()
CREATE FUNCTION ingest.assert_publication_snapshot_month() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'ingest'
    AS $$
DECLARE
    expected_month date;
BEGIN
    SELECT date_trunc('month', published_at AT TIME ZONE 'UTC')::date
      INTO expected_month
      FROM ingest.publication
     WHERE id = NEW.publication_id;
    IF expected_month IS NULL OR expected_month <> NEW.published_month THEN
        RAISE EXCEPTION 'published_month % does not match publication % month %',
            NEW.published_month, NEW.publication_id, expected_month;
    END IF;
    RETURN NEW;
END
$$;

-- ingest.fence_reaction_insert()
CREATE FUNCTION ingest.fence_reaction_insert() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ingest', 'ops_and_admin'
    AS $$
DECLARE snapshot_xid xid8; previous_count bigint;
BEGIN
 PERFORM ops_and_admin.assert_publication_partition_writable(NEW.snapshot_published_month);
 SELECT reaction_count INTO previous_count FROM ingest.reaction_breakdown
 WHERE snapshot_published_month=NEW.snapshot_published_month AND snapshot_id=NEW.snapshot_id AND reaction_key=NEW.reaction_key;
 IF FOUND THEN
   IF previous_count=NEW.reaction_count THEN RETURN NULL; END IF;
   RAISE EXCEPTION 'reaction replay differs from immutable observation' USING ERRCODE='55000';
 END IF;
 SELECT ingested_xid INTO snapshot_xid FROM ingest.publication_metric_snapshot
 WHERE published_month=NEW.snapshot_published_month AND id=NEW.snapshot_id;
 -- Breakdown must be committed with its parent. Later additions change the
 -- event fingerprint and therefore must belong to a new correction snapshot.
 IF snapshot_xid IS DISTINCT FROM pg_current_xact_id() THEN
   RAISE EXCEPTION 'reaction breakdown must be inserted with its observation' USING ERRCODE='55000';
 END IF;
 RETURN NEW;
END $$;

-- ingest.prepare_immutable_account_snapshot()
CREATE FUNCTION ingest.prepare_immutable_account_snapshot() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ingest'
    AS $$
DECLARE previous ingest.account_metric_snapshot%ROWTYPE;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('account-observation:'||NEW.platform_account_id::text||':'||NEW.observed_at::text,0));
 NEW.subscriber_quality:=coalesce(NEW.subscriber_quality,NEW.quality);
 SELECT * INTO previous FROM ingest.account_metric_snapshot
  WHERE platform_account_id=NEW.platform_account_id AND observed_at=NEW.observed_at AND source_fingerprint=NEW.source_fingerprint;
 IF FOUND THEN
   IF (to_jsonb(previous)-ARRAY['id','created_at','collection_run_id','correction_sequence','supersedes_snapshot_id','correction_reason','ingested_xid'])
    IS DISTINCT FROM (to_jsonb(NEW)-ARRAY['id','created_at','collection_run_id','correction_sequence','supersedes_snapshot_id','correction_reason','ingested_xid']) THEN
     RAISE EXCEPTION 'fingerprint reused for different observation' USING ERRCODE='23505';
   END IF;
   RETURN NULL;
 END IF;
 SELECT * INTO previous FROM ingest.account_metric_snapshot
  WHERE platform_account_id=NEW.platform_account_id AND observed_at=NEW.observed_at ORDER BY correction_sequence DESC LIMIT 1;
 NEW.correction_sequence:=CASE WHEN FOUND THEN previous.correction_sequence+1 ELSE 0 END;
 NEW.supersedes_snapshot_id:=previous.id;
 NEW.correction_reason:=CASE WHEN previous.id IS NOT NULL THEN coalesce(nullif(btrim(NEW.correction_reason),''),'provider_payload_changed') END;
 RETURN NEW;
END $$;

-- ingest.prepare_immutable_publication_snapshot()
CREATE FUNCTION ingest.prepare_immutable_publication_snapshot() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ingest', 'ops_and_admin'
    AS $$
DECLARE previous ingest.publication_metric_snapshot%ROWTYPE;
BEGIN
 NEW.ingested_xid:=pg_current_xact_id();
 PERFORM ops_and_admin.assert_publication_partition_writable(NEW.published_month);
 PERFORM pg_advisory_xact_lock(hashtextextended('observation:'||NEW.published_month::text||':'||NEW.publication_id::text||':'||NEW.sampling_bucket::text,0));
 NEW.views_quality:=coalesce(NEW.views_quality,NEW.quality);
 NEW.reactions_quality:=coalesce(NEW.reactions_quality,NEW.quality);
 NEW.comments_quality:=coalesce(NEW.comments_quality,NEW.quality);
 NEW.shares_quality:=coalesce(NEW.shares_quality,NEW.quality);
 SELECT * INTO previous FROM ingest.publication_metric_snapshot
  WHERE published_month=NEW.published_month AND publication_id=NEW.publication_id
   AND sampling_bucket=NEW.sampling_bucket AND source_fingerprint=NEW.source_fingerprint;
 IF FOUND THEN
   previous.metric_evidence:=coalesce(previous.metric_evidence,(SELECT payload FROM ingest.metric_evidence_dictionary WHERE id=previous.metric_evidence_id));
   IF (to_jsonb(previous)-ARRAY['id','created_at','collection_run_id','correction_sequence','supersedes_snapshot_id','correction_reason','ingested_xid','metric_evidence_id'])
    IS DISTINCT FROM (to_jsonb(NEW)-ARRAY['id','created_at','collection_run_id','correction_sequence','supersedes_snapshot_id','correction_reason','ingested_xid','metric_evidence_id']) THEN
     RAISE EXCEPTION 'fingerprint reused for different observation' USING ERRCODE='23505';
   END IF;
   RETURN NULL;
 END IF;
 SELECT * INTO previous FROM ingest.publication_metric_snapshot
  WHERE published_month=NEW.published_month AND publication_id=NEW.publication_id
   AND sampling_bucket=NEW.sampling_bucket ORDER BY correction_sequence DESC LIMIT 1;
 NEW.correction_sequence:=CASE WHEN FOUND THEN previous.correction_sequence+1 ELSE 0 END;
 NEW.supersedes_snapshot_id:=previous.id;
 NEW.correction_reason:=CASE WHEN previous.id IS NOT NULL THEN coalesce(nullif(btrim(NEW.correction_reason),''),'provider_payload_changed') END;
 RETURN NEW;
END $$;

-- ingest.reject_evidence_dictionary_mutation()
CREATE FUNCTION ingest.reject_evidence_dictionary_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 -- Interned evidence is referenced by observations whose archive record must
 -- stay byte-identical, so a dictionary entry is write-once: updating or
 -- deleting one would silently rewrite history that is already published.
 RAISE EXCEPTION 'metric evidence dictionary entries are immutable' USING ERRCODE='55000';
END $$;

-- ingest.reject_new_unavailable_evidence()
CREATE FUNCTION ingest.reject_new_unavailable_evidence() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 IF NEW.legacy_evidence_unavailable THEN RAISE EXCEPTION 'new evidence must be retrievable' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

-- ingest.reject_observation_mutation()
CREATE FUNCTION ingest.reject_observation_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
 -- Only the owner-operated backfill may replace storage; logical data remains
 -- exactly identical, including every counter, timestamp and lineage field.
 IF TG_OP='UPDATE' AND current_user='migration_owner'
    AND TG_TABLE_SCHEMA='ingest' AND TG_TABLE_NAME LIKE 'publication_metric_snapshot%' THEN
   IF (to_jsonb(OLD)-ARRAY['metric_evidence','metric_evidence_id'])
        IS NOT DISTINCT FROM (to_jsonb(NEW)-ARRAY['metric_evidence','metric_evidence_id'])
      AND OLD.metric_evidence IS NOT NULL AND OLD.metric_evidence_id IS NULL
      AND NEW.metric_evidence IS NULL AND NEW.metric_evidence_id IS NOT NULL
      AND OLD.metric_evidence IS NOT DISTINCT FROM
          (SELECT payload FROM ingest.metric_evidence_dictionary WHERE id=NEW.metric_evidence_id) THEN
     RETURN NEW;
   END IF;
 END IF;
 RAISE EXCEPTION 'observations are append-only; insert a correction' USING ERRCODE='55000';
END $$;

-- ops_and_admin.abort_publication_archive(date)
CREATE FUNCTION ops_and_admin.abort_publication_archive(p_month date) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ops_and_admin'
    AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('observation-partition:'||p_month::text,0));
 UPDATE ops_and_admin.publication_partition_fence SET state='active',manifest_id=NULL,changed_at=transaction_timestamp()
 WHERE published_month=p_month AND state='archiving';
END $$;

-- ops_and_admin.allocate_catalog_alias(text, uuid)
CREATE FUNCTION ops_and_admin.allocate_catalog_alias(p_type text, p_target uuid) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'catalog'
    AS $$
DECLARE result bigint; candidate bigint; alias_sequence regclass;
BEGIN
    IF p_type NOT IN ('institutions','channels','platform_accounts') THEN
        RAISE EXCEPTION 'unsupported alias';
    END IF;
    SELECT legacy_id INTO result
      FROM catalog.legacy_entity_alias
     WHERE entity_type=p_type AND target_uuid=p_target;
    IF result IS NOT NULL THEN RETURN result; END IF;
    alias_sequence := CASE p_type
        WHEN 'institutions' THEN 'catalog.legacy_alias_institutions_seq'::regclass
        WHEN 'channels' THEN 'catalog.legacy_alias_channels_seq'::regclass
        ELSE 'catalog.legacy_alias_platform_accounts_seq'::regclass
    END;
    LOOP
        candidate := nextval(alias_sequence);
        INSERT INTO catalog.legacy_entity_alias(
            entity_type,legacy_id,target_uuid,legacy_route
        ) VALUES(
            p_type,candidate,p_target,
            '/'||replace(p_type,'_','-')||'/'||candidate
        )
        ON CONFLICT DO NOTHING
        RETURNING legacy_id INTO result;
        IF result IS NOT NULL THEN RETURN result; END IF;
        SELECT legacy_id INTO result
          FROM catalog.legacy_entity_alias
         WHERE entity_type=p_type AND target_uuid=p_target;
        IF result IS NOT NULL THEN RETURN result; END IF;
    END LOOP;
END
$$;

-- ops_and_admin.assert_publication_partition_writable(date)
CREATE FUNCTION ops_and_admin.assert_publication_partition_writable(p_month date) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ops_and_admin'
    AS $$
DECLARE current_state text;
BEGIN
 -- Shared transaction lock drains *all* existing snapshot/reaction writers
 -- before an archiver obtains its exclusive lock and publishes the fence.
 PERFORM pg_advisory_xact_lock_shared(hashtextextended('observation-partition:'||p_month::text,0));
 SELECT state INTO current_state FROM ops_and_admin.publication_partition_fence WHERE published_month=p_month;
 IF current_state IS NOT NULL AND current_state<>'active' THEN
   RAISE EXCEPTION 'publication partition % is fenced (%)',p_month,current_state USING ERRCODE='55000';
 END IF;
END $$;

-- ops_and_admin.begin_publication_archive(date)
CREATE FUNCTION ops_and_admin.begin_publication_archive(p_month date) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ops_and_admin'
    AS $$
DECLARE current_state text;
BEGIN
 IF p_month IS NULL OR p_month<>date_trunc('month',p_month)::date THEN RAISE EXCEPTION 'canonical month required'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('observation-partition:'||p_month::text,0));
 SELECT state INTO current_state FROM ops_and_admin.publication_partition_fence WHERE published_month=p_month;
 IF current_state='archived' THEN RAISE EXCEPTION 'partition already archived' USING ERRCODE='55000'; END IF;
 INSERT INTO ops_and_admin.publication_partition_fence(published_month,state)
 VALUES(p_month,'archiving') ON CONFLICT(published_month) DO UPDATE SET state='archiving',changed_at=transaction_timestamp();
END $$;

-- ops_and_admin.catalog_command(text, uuid, bigint, jsonb, text, uuid)
CREATE FUNCTION ops_and_admin.catalog_command(p_action text, p_target uuid, p_expected bigint, p_body jsonb, p_actor text, p_correlation uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'catalog', 'analytics', 'ops_and_admin'
    SET lock_timeout TO '10s'
    SET statement_timeout TO '15min'
    AS $_$
DECLARE
    before_state jsonb; after_state jsonb; result jsonb; receipt ops_and_admin.catalog_command_receipt%ROWTYPE;
    account catalog.platform_account%ROWTYPE; institution catalog.institution%ROWTYPE;
    target uuid:=p_target; parent uuid; previous_parent uuid; revision bigint; alias_id bigint;
    request_digest text; outcome text:='succeeded'; target_type text; transition timestamptz;
    native_value text; old_native text; identity_changed boolean:=false;
BEGIN
    IF p_actor IS NULL OR btrim(p_actor)='' OR length(p_actor)>200 OR p_actor ~ '[[:cntrl:]]'
       OR p_correlation IS NULL OR jsonb_typeof(p_body)<>'object' THEN
        RAISE EXCEPTION 'invalid command envelope' USING ERRCODE='22023';
    END IF;
    IF p_action NOT IN ('institution.create','institution.update','institution.delete',
        'account.upsert','channel.upsert','account.enable','account.disable','account.delete','channel.delete','account.native_id') THEN
        RAISE EXCEPTION 'unsupported catalog command' USING ERRCODE='22023';
    END IF;
    -- Lock order is shared by all catalog commands, including concurrent replay.
    PERFORM pg_advisory_xact_lock(782194601);
    request_digest:=encode(sha256(convert_to(jsonb_build_object('action',p_action,'target',p_target,
        'expected',p_expected,'body',p_body)::text,'UTF8')),'hex');
    SELECT * INTO receipt FROM ops_and_admin.catalog_command_receipt WHERE actor=p_actor AND correlation_id=p_correlation;
    IF FOUND THEN
        IF receipt.request_digest<>request_digest THEN RETURN jsonb_build_object('outcome','idempotency_conflict'); END IF;
        RETURN receipt.response;
    END IF;
    target_type:=CASE WHEN p_action LIKE 'institution.%' THEN 'institution' ELSE 'platform_account' END;
    IF p_action='institution.create' THEN
        IF btrim(coalesce(p_body->>'name',''))='' OR length(p_body->>'name')>1000 THEN
            RAISE EXCEPTION 'institution name is required' USING ERRCODE='22023'; END IF;
        INSERT INTO catalog.institution(canonical_name,short_name,status)
            VALUES(btrim(p_body->>'name'),coalesce(nullif(btrim(p_body->>'shortName'),''),btrim(p_body->>'name')),'active')
            RETURNING * INTO institution;
        target:=institution.id;
        alias_id:=ops_and_admin.allocate_catalog_alias('institutions',target);
        after_state:=to_jsonb(institution);
    ELSIF p_action LIKE 'institution.%' THEN
        SELECT * INTO institution FROM catalog.institution WHERE id=target AND deleted_at IS NULL FOR UPDATE;
        IF NOT FOUND THEN outcome:='not_found';
        ELSE
            before_state:=to_jsonb(institution);
            IF p_expected IS NULL OR p_expected<>institution.row_version THEN outcome:='version_conflict';
            ELSIF p_action='institution.update' THEN
                IF btrim(coalesce(p_body->>'name',''))='' OR btrim(coalesce(p_body->>'shortName',''))=''
                   OR length(p_body->>'name')>1000 OR length(p_body->>'shortName')>1000 THEN
                    RAISE EXCEPTION 'institution names are required' USING ERRCODE='22023'; END IF;
                UPDATE catalog.institution SET canonical_name=btrim(p_body->>'name'),short_name=btrim(p_body->>'shortName'),
                    row_version=row_version+1,updated_at=transaction_timestamp() WHERE id=target RETURNING * INTO institution;
            ELSE
                UPDATE catalog.platform_account SET deleted_at=transaction_timestamp(),enabled=false,
                    row_version=row_version+1,updated_at=transaction_timestamp() WHERE institution_id=target AND deleted_at IS NULL;
                UPDATE catalog.institution SET deleted_at=transaction_timestamp(),row_version=row_version+1,
                    updated_at=transaction_timestamp() WHERE id=target RETURNING * INTO institution;
            END IF;
            after_state:=to_jsonb(institution);
        END IF;
    ELSIF p_action IN ('account.upsert','channel.upsert') THEN
        parent:=(p_body->>'institutionId')::uuid;
        IF p_action='channel.upsert' THEN
            IF p_body->>'platform'<>'telegram' THEN RAISE EXCEPTION 'channel platform must be telegram' USING ERRCODE='22023'; END IF;
            SELECT institution_id INTO parent FROM catalog.platform_account WHERE platform='telegram' AND deleted_at IS NULL
                AND lower(current_username)=lower(p_body->>'username') ORDER BY id LIMIT 1 FOR UPDATE;
            IF parent IS NULL THEN
                INSERT INTO catalog.institution(canonical_name,short_name) VALUES('@'||(p_body->>'username'),'@'||(p_body->>'username'))
                    RETURNING id INTO parent;
                PERFORM ops_and_admin.allocate_catalog_alias('institutions',parent);
            END IF;
        END IF;
        SELECT * INTO institution FROM catalog.institution WHERE id=parent AND deleted_at IS NULL FOR UPDATE;
        IF NOT FOUND THEN outcome:='not_found';
        ELSIF p_body ? 'expectedInstitutionVersion' AND institution.row_version<>(p_body->>'expectedInstitutionVersion')::bigint
            THEN outcome:='version_conflict';
        ELSE
            SELECT * INTO account FROM catalog.platform_account WHERE deleted_at IS NULL
                AND platform=(p_body->>'platform')::catalog.platform_code
                AND (canonical_external_id=p_body->>'externalKey' OR lower(current_username)=lower(p_body->>'username'))
                ORDER BY id LIMIT 1 FOR UPDATE;
            IF FOUND THEN
                target:=account.id; before_state:=to_jsonb(account); previous_parent:=account.institution_id;
                IF (p_expected IS NOT NULL AND p_expected<>account.row_version)
                    OR (p_body ? 'expectedAccountVersions' AND (
                        NOT (p_body->'expectedAccountVersions' ? target::text)
                        OR (p_body->'expectedAccountVersions'->>target::text)::bigint<>account.row_version))
                    THEN outcome:='version_conflict';
                ELSE
                    identity_changed:=account.current_username IS DISTINCT FROM p_body->>'username'
                        OR (p_body->>'title' IS NOT NULL AND account.current_title IS DISTINCT FROM p_body->>'title')
                        OR (p_body->>'url' IS NOT NULL AND account.current_url IS DISTINCT FROM p_body->>'url');
                    UPDATE catalog.platform_account SET institution_id=parent,enabled=true,
                        current_username=p_body->>'username',current_title=coalesce(p_body->>'title',current_title),
                        current_url=coalesce(p_body->>'url',current_url),access_mode=(p_body->>'accessMode')::catalog.access_mode,
                        row_version=row_version+1,updated_at=transaction_timestamp() WHERE id=target RETURNING * INTO account;
                END IF;
            ELSIF p_expected IS NOT NULL THEN
                outcome:='version_conflict';
            ELSE
                INSERT INTO catalog.platform_account(institution_id,platform,canonical_external_id,current_username,
                    current_title,current_url,access_mode) VALUES(parent,(p_body->>'platform')::catalog.platform_code,
                    p_body->>'externalKey',p_body->>'username',p_body->>'title',p_body->>'url',(p_body->>'accessMode')::catalog.access_mode)
                    RETURNING * INTO account;
                target:=account.id; identity_changed:=true;
                alias_id:=ops_and_admin.allocate_catalog_alias('platform_accounts',target);
                IF account.platform='telegram' THEN PERFORM ops_and_admin.allocate_catalog_alias('channels',target); END IF;
            END IF;
            IF outcome='succeeded' AND identity_changed THEN
                SELECT greatest(transaction_timestamp(),max(valid_from)+interval '1 microsecond') INTO transition
                    FROM catalog.account_identity_history WHERE platform_account_id=target AND valid_to IS NULL;
                UPDATE catalog.account_identity_history SET valid_to=transition WHERE platform_account_id=target AND valid_to IS NULL;
                INSERT INTO catalog.account_identity_history(platform_account_id,username,title,url,valid_from)
                    VALUES(target,account.current_username,account.current_title,account.current_url,transition);
            END IF;
            -- Legacy moving a Telegram channel removes its now-empty auto institution.
            IF outcome='succeeded' AND account.platform='telegram' AND previous_parent IS DISTINCT FROM parent
               AND previous_parent IS NOT NULL AND NOT EXISTS(SELECT 1 FROM catalog.platform_account
                    WHERE institution_id=previous_parent AND deleted_at IS NULL) THEN
                UPDATE catalog.institution SET deleted_at=transaction_timestamp(),row_version=row_version+1,
                    updated_at=transaction_timestamp() WHERE id=previous_parent;
            END IF;
            after_state:=to_jsonb(account);
        END IF;
    ELSE
        SELECT * INTO account FROM catalog.platform_account WHERE id=target AND deleted_at IS NULL FOR UPDATE;
        IF NOT FOUND THEN outcome:='not_found';
        ELSE
            before_state:=to_jsonb(account);
            IF p_expected IS NULL OR p_expected<>account.row_version THEN outcome:='version_conflict';
            ELSE
                IF p_action='account.native_id' THEN
                    native_value:=nullif(btrim(p_body->>'nativeId'),'');
                    IF account.platform='max' AND native_value IS NOT NULL AND native_value !~ '^-?[0-9]+$' THEN
                        RAISE EXCEPTION 'MAX chat_id must be numeric' USING ERRCODE='22023'; END IF;
                    SELECT external_id INTO old_native FROM catalog.account_external_identity WHERE platform_account_id=target
                        AND identity_namespace=account.platform::text||':native_id' AND valid_to IS NULL FOR UPDATE;
                    IF old_native IS DISTINCT FROM native_value THEN
                        SELECT greatest(transaction_timestamp(),max(greatest(valid_from,valid_to))+interval '1 microsecond') INTO transition
                            FROM catalog.account_external_identity WHERE platform_account_id=target
                            AND identity_namespace=account.platform::text||':native_id';
                        UPDATE catalog.account_external_identity SET valid_to=transition WHERE platform_account_id=target
                            AND identity_namespace=account.platform::text||':native_id' AND valid_to IS NULL;
                        IF native_value IS NOT NULL THEN
                            INSERT INTO catalog.account_external_identity(platform_account_id,identity_namespace,external_id,valid_from,verified_at)
                                VALUES(target,account.platform::text||':native_id',native_value,transition,transition);
                        END IF;
                    END IF;
                    before_state:=before_state||jsonb_build_object('native_id',old_native);
                END IF;
                UPDATE catalog.platform_account SET enabled=CASE WHEN p_action='account.enable' THEN true
                        WHEN p_action IN ('account.disable','account.delete','channel.delete') THEN false ELSE enabled END,
                    deleted_at=CASE WHEN p_action IN ('account.delete','channel.delete') THEN transaction_timestamp() ELSE deleted_at END,
                    row_version=row_version+1,updated_at=transaction_timestamp() WHERE id=target RETURNING * INTO account;
                IF p_action='channel.delete' AND NOT EXISTS(SELECT 1 FROM catalog.platform_account
                    WHERE institution_id=account.institution_id AND deleted_at IS NULL) THEN
                    UPDATE catalog.institution SET deleted_at=transaction_timestamp(),row_version=row_version+1,
                        updated_at=transaction_timestamp() WHERE id=account.institution_id;
                END IF;
            END IF;
            after_state:=to_jsonb(account);
            IF p_action='account.native_id' THEN after_state:=after_state||jsonb_build_object('native_id',native_value); END IF;
        END IF;
    END IF;
    IF outcome='succeeded' THEN
        INSERT INTO analytics.dataset_revision(cause,correlation_id) VALUES('configuration',p_correlation) RETURNING id INTO revision;
        INSERT INTO ops_and_admin.outbox_event(
            dataset_revision_id, event_type, aggregate_type, aggregate_id,
            affected_tags, payload
        ) VALUES (
            revision, 'dataset.revision.changed', 'dataset', 'core',
            ARRAY['publications', 'overview', 'comparison'],
            jsonb_build_object('revision', revision, 'cause', 'configuration')
        )
        ON CONFLICT (dataset_revision_id, event_type, aggregate_type, aggregate_id)
        DO NOTHING;
        INSERT INTO ops_and_admin.outbox_event(dataset_revision_id,event_type,aggregate_type,aggregate_id,affected_tags,payload)
            VALUES(revision,p_action,target_type,target::text,ARRAY['catalog','institution:'||coalesce(account.institution_id,target)::text],
                jsonb_build_object('action',p_action,'rowVersion',after_state->'row_version'));
    END IF;
    INSERT INTO ops_and_admin.audit_log(subject,action,target_type,target_id,correlation_id,before_state,after_state,outcome)
        VALUES(p_actor,p_action,target_type,target,p_correlation,before_state,after_state,outcome);
    SELECT legacy_id INTO alias_id FROM catalog.legacy_entity_alias WHERE target_uuid=target
        AND entity_type=CASE WHEN target_type='institution' THEN 'institutions' ELSE 'platform_accounts' END;
    result:=jsonb_build_object('outcome',outcome,'targetId',target,'legacyId',alias_id,
        'datasetRevision',revision,'state',after_state,'correlationId',p_correlation);
    INSERT INTO ops_and_admin.catalog_command_receipt(actor,correlation_id,request_digest,response)
        VALUES(p_actor,p_correlation,request_digest,result);
    RETURN result;
END $_$;

-- ops_and_admin.claim_anomaly_candidates(integer, integer, uuid)
CREATE FUNCTION ops_and_admin.claim_anomaly_candidates(p_limit integer, p_lease_seconds integer, p_claim_token uuid) RETURNS TABLE(publication_id uuid, dirty_generation bigint, retry_count integer, config_backfill boolean)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ops_and_admin'
    SET statement_timeout TO '10s'
    AS $$
BEGIN
    IF p_limit<1 OR p_limit>100 OR p_lease_seconds<10 OR p_lease_seconds>900 OR p_claim_token IS NULL THEN
        RAISE EXCEPTION 'invalid anomaly claim bounds';
    END IF;
    UPDATE ops_and_admin.anomaly_analysis_candidate candidate
       SET claim_token=NULL,claimed_generation=NULL,leased_until=NULL,updated_at=transaction_timestamp()
     WHERE candidate.claim_token IS NOT NULL AND candidate.leased_until<transaction_timestamp();
    RETURN QUERY
    WITH selected AS (
        SELECT candidate.publication_id
          FROM ops_and_admin.anomaly_analysis_candidate candidate
         WHERE candidate.eligible_at<=transaction_timestamp()
           AND candidate.claim_token IS NULL
         ORDER BY candidate.priority DESC,candidate.eligible_at,candidate.publication_id
         FOR UPDATE SKIP LOCKED LIMIT p_limit
    ), claimed AS (
        UPDATE ops_and_admin.anomaly_analysis_candidate candidate
           SET claim_token=p_claim_token,claimed_generation=candidate.dirty_generation,
               leased_until=transaction_timestamp()+make_interval(secs=>p_lease_seconds),
               updated_at=transaction_timestamp()
          FROM selected WHERE candidate.publication_id=selected.publication_id
        RETURNING candidate.publication_id,candidate.dirty_generation,candidate.retry_count,candidate.config_backfill
    ) SELECT * FROM claimed;
END $$;

-- ops_and_admin.complete_anomaly_noop(uuid, uuid, bigint)
CREATE FUNCTION ops_and_admin.complete_anomaly_noop(p_publication_id uuid, p_claim_token uuid, p_generation bigint) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ops_and_admin'
    AS $$
BEGIN
    DELETE FROM ops_and_admin.anomaly_analysis_candidate
     WHERE publication_id=p_publication_id AND claim_token=p_claim_token
       AND claimed_generation=p_generation AND dirty_generation=p_generation;
    IF FOUND THEN RETURN true; END IF;
    UPDATE ops_and_admin.anomaly_analysis_candidate SET
        claim_token=NULL,claimed_generation=NULL,leased_until=NULL,eligible_at=transaction_timestamp(),
        retry_count=0,last_error_code=NULL,updated_at=transaction_timestamp()
     WHERE publication_id=p_publication_id AND claim_token=p_claim_token AND claimed_generation=p_generation;
    RETURN FOUND;
END $$;

-- ops_and_admin.drop_publication_metric_partition_v21(date, uuid)
CREATE FUNCTION ops_and_admin.drop_publication_metric_partition_v21(p_month date, p_manifest_id uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ingest', 'ops_and_admin'
    SET lock_timeout TO '10s'
    SET "TimeZone" TO 'UTC'
    AS $$
DECLARE month_end date:=(p_month+interval '1 month')::date;
 manifest ops_and_admin.archive_manifest%ROWTYPE; attestation ops_and_admin.archive_object_attestation%ROWTYPE;
 actual record; hot_days integer; fence text;
BEGIN
 IF p_month IS NULL OR p_month<>date_trunc('month',p_month)::date THEN RAISE EXCEPTION 'canonical month required'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('observation-partition:'||p_month::text,0));
 SELECT state INTO fence FROM ops_and_admin.publication_partition_fence WHERE published_month=p_month FOR UPDATE;
 IF fence IS DISTINCT FROM 'archiving' THEN RAISE EXCEPTION 'archive fence required' USING ERRCODE='55000'; END IF;
 SELECT * INTO manifest FROM ops_and_admin.archive_manifest WHERE id=p_manifest_id FOR UPDATE;
 SELECT * INTO attestation FROM ops_and_admin.archive_object_attestation WHERE manifest_id=p_manifest_id;
 SELECT rp.hot_days INTO hot_days FROM ops_and_admin.retention_policy rp WHERE rp.data_class='publication_metric_snapshot';
 IF hot_days IS NULL OR hot_days<70 OR current_date<month_end+hot_days THEN RAISE EXCEPTION 'hot retention gate failed'; END IF;
 IF manifest.id IS NULL OR manifest.dataset_type<>'publication_metric_snapshot' OR manifest.schema_version<>3
 OR manifest.partition_start IS DISTINCT FROM p_month::timestamp AT TIME ZONE 'UTC'
 OR manifest.partition_end IS DISTINCT FROM month_end::timestamp AT TIME ZONE 'UTC'
 OR manifest.status<>'verified' OR manifest.verified_at IS NULL OR manifest.canonical_sha256 IS NULL THEN
 RAISE EXCEPTION 'exact verified v3 manifest required'; END IF;
 IF attestation.manifest_id IS NULL OR attestation.sha256<>manifest.sha256
 OR attestation.canonical_sha256<>manifest.canonical_sha256 OR attestation.row_count<>manifest.row_count
 OR attestation.immutable_until<=transaction_timestamp() THEN RAISE EXCEPTION 'off-primary immutable object attestation required'; END IF;
 -- Exclusive relation locks also drain elevated direct writers and hold the
 -- catalog dimensions fixed through digest and DROP in this same transaction.
 LOCK TABLE ingest.publication_metric_snapshot,ingest.reaction_breakdown IN ACCESS EXCLUSIVE MODE;
 LOCK TABLE ingest.publication,catalog.platform_account IN SHARE MODE;
 SELECT * INTO actual FROM ops_and_admin.publication_partition_digest(p_month);
 IF ROW(actual.row_count,actual.min_observed_at,actual.max_observed_at,actual.canonical_sha256)
 IS DISTINCT FROM ROW(manifest.row_count,manifest.min_observed_at,manifest.max_observed_at,manifest.canonical_sha256)
 THEN RAISE EXCEPTION 'partition content changed since verified export'; END IF;
 EXECUTE format('DROP TABLE ingest.%I','reaction_breakdown_'||to_char(p_month,'YYYY_MM'));
 EXECUTE format('ALTER TABLE ingest.publication_metric_snapshot DETACH PARTITION ingest.%I','publication_metric_snapshot_'||to_char(p_month,'YYYY_MM'));
 EXECUTE format('DROP TABLE ingest.%I','publication_metric_snapshot_'||to_char(p_month,'YYYY_MM'));
 UPDATE ops_and_admin.archive_manifest SET status='hot_dropped',hot_dropped_at=transaction_timestamp() WHERE id=p_manifest_id;
 UPDATE ops_and_admin.publication_partition_fence SET state='archived',manifest_id=p_manifest_id,changed_at=transaction_timestamp() WHERE published_month=p_month;
END $$;

-- ops_and_admin.ensure_publication_legacy_alias(uuid)
CREATE FUNCTION ops_and_admin.ensure_publication_legacy_alias(p_publication uuid) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'catalog', 'ingest'
    AS $$
DECLARE entity text; result bigint; candidate bigint; alias_sequence regclass;
BEGIN
    SELECT CASE WHEN account.platform='telegram' THEN 'posts' ELSE 'platform_posts' END
      INTO entity
      FROM ingest.publication publication
      JOIN catalog.platform_account account
        ON account.id=publication.primary_account_id
     WHERE publication.id=p_publication;
    IF entity IS NULL THEN
        RAISE EXCEPTION 'publication not found' USING ERRCODE='22023';
    END IF;
    SELECT legacy_id INTO result
      FROM catalog.legacy_entity_alias
     WHERE entity_type=entity AND target_uuid=p_publication;
    IF result IS NOT NULL THEN RETURN result; END IF;
    alias_sequence := CASE entity
        WHEN 'posts' THEN 'catalog.legacy_alias_posts_seq'::regclass
        ELSE 'catalog.legacy_alias_platform_posts_seq'::regclass
    END;
    LOOP
        candidate := nextval(alias_sequence);
        INSERT INTO catalog.legacy_entity_alias(
            entity_type,legacy_id,target_uuid,legacy_route
        ) VALUES(
            entity,candidate,p_publication,
            '/'||replace(entity,'_','-')||'/'||candidate
        )
        ON CONFLICT DO NOTHING
        RETURNING legacy_id INTO result;
        IF result IS NOT NULL THEN RETURN result; END IF;
        SELECT legacy_id INTO result
          FROM catalog.legacy_entity_alias
         WHERE entity_type=entity AND target_uuid=p_publication;
        IF result IS NOT NULL THEN RETURN result; END IF;
    END LOOP;
END
$$;

-- ops_and_admin.ensure_publication_metric_partition(date)
CREATE FUNCTION ops_and_admin.ensure_publication_metric_partition(p_month date) RETURNS regclass
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ingest', 'ops_and_admin'
    SET lock_timeout TO '10s'
    AS $$
DECLARE
    month_start date := date_trunc('month', p_month)::date;
    month_end date := (date_trunc('month', p_month) + interval '1 month')::date;
    partition_name text := 'publication_metric_snapshot_' || to_char(month_start, 'YYYY_MM');
    reaction_partition_name text := 'reaction_breakdown_' || to_char(month_start, 'YYYY_MM');
    qualified_name text := format('ingest.%I', partition_name);
    reaction_qualified_name text := format('ingest.%I', reaction_partition_name);
    result regclass;
BEGIN
    IF p_month IS NULL THEN
        RAISE EXCEPTION 'partition month must not be NULL';
    END IF;

    result := to_regclass(qualified_name);
    IF result IS NOT NULL AND to_regclass(reaction_qualified_name) IS NOT NULL THEN
        RETURN result;
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(qualified_name, 0));
    result := to_regclass(qualified_name);
    IF result IS NULL THEN
        EXECUTE format(
            'CREATE TABLE ingest.%I PARTITION OF ingest.publication_metric_snapshot '
            'FOR VALUES FROM (%L) TO (%L)',
            partition_name, month_start, month_end
        );
        result := to_regclass(qualified_name);
    END IF;
    IF to_regclass(reaction_qualified_name) IS NULL THEN
        EXECUTE format(
            'CREATE TABLE ingest.%I PARTITION OF ingest.reaction_breakdown '
            'FOR VALUES FROM (%L) TO (%L)',
            reaction_partition_name, month_start, month_end
        );
    END IF;
    EXECUTE format(
        'GRANT SELECT ON TABLE ingest.%I TO maintenance',
        partition_name
    );
    EXECUTE format(
        'GRANT SELECT ON TABLE ingest.%I TO maintenance',
        reaction_partition_name
    );
    RETURN result;
END
$$;

-- ops_and_admin.mark_anomaly_candidate()
CREATE FUNCTION ops_and_admin.mark_anomaly_candidate() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ingest', 'ops_and_admin'
    AS $$
BEGIN
    INSERT INTO ops_and_admin.anomaly_analysis_candidate(
        publication_id,dirty_generation,eligible_at,priority,config_backfill,updated_at
    )
    SELECT NEW.publication_id,1,greatest(
        published_at+interval '15 minutes',
        transaction_timestamp()+CASE
          WHEN transaction_timestamp()-published_at<interval '6 hours' THEN interval '2 minutes'
          WHEN transaction_timestamp()-published_at<interval '1 day' THEN interval '5 minutes'
          WHEN transaction_timestamp()-published_at<interval '7 days' THEN interval '15 minutes'
          ELSE interval '1 hour' END
      ),100,false,transaction_timestamp()
      FROM ingest.publication WHERE id=NEW.publication_id
    ON CONFLICT(publication_id) DO UPDATE SET
        dirty_generation=ops_and_admin.anomaly_analysis_candidate.dirty_generation+1,
        eligible_at=least(ops_and_admin.anomaly_analysis_candidate.eligible_at,excluded.eligible_at),
        priority=greatest(ops_and_admin.anomaly_analysis_candidate.priority,100),
        config_backfill=false,updated_at=transaction_timestamp();
    RETURN NULL;
END $$;

-- ops_and_admin.pin_latest_anomaly_source_revision()
CREATE FUNCTION ops_and_admin.pin_latest_anomaly_source_revision() RETURNS TABLE(id bigint, committed_at timestamp with time zone)
    LANGUAGE sql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'analytics'
    AS $$
WITH latest AS MATERIALIZED (
  SELECT source.id,source.committed_at
    FROM analytics.latest_dataset_revision() source
), pinned AS (
  INSERT INTO analytics.anomaly_source_revision(dataset_revision_id,committed_at)
  SELECT latest.id,latest.committed_at FROM latest
  ON CONFLICT(dataset_revision_id) DO NOTHING
  RETURNING dataset_revision_id,anomaly_source_revision.committed_at
)
SELECT latest.id,latest.committed_at FROM latest
$$;

-- ops_and_admin.previous_official_rating(text, uuid)
CREATE FUNCTION ops_and_admin.previous_official_rating(p_actor text, p_correlation uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ops_and_admin'
    AS $$
DECLARE response jsonb;
BEGIN
    SELECT receipt.response INTO response FROM ops_and_admin.catalog_command_receipt receipt WHERE actor=p_actor AND correlation_id=p_correlation;
    IF response IS NOT NULL AND response->>'kind' IS DISTINCT FROM 'official_rating' THEN RETURN '{"outcome":"idempotency_conflict"}'::jsonb; END IF;
    RETURN response;
END $$;

-- ops_and_admin.public_health_snapshot()
CREATE FUNCTION ops_and_admin.public_health_snapshot() RETURNS jsonb
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    SET statement_timeout TO '3s'
    AS $_$
WITH keys(key) AS (
    VALUES ('last_poll'),('next_poll'),('poll_last_started_at'),('poll_last_completed_at'),
      ('poll_last_duration_seconds'),('poll_last_error_count'),('poll_last_channel_count'),
      ('telegram_web_last_success_at'),('telegram_web_last_error'),
      ('vk_poll_last_completed_at'),('vk_poll_last_duration_seconds'),('vk_poll_last_error_count'),('vk_poll_last_account_count'),
      ('max_poll_last_completed_at'),('max_poll_last_duration_seconds'),('max_poll_last_error_count'),('max_poll_last_account_count'),
      ('rutube_poll_last_completed_at'),('rutube_poll_last_duration_seconds'),('rutube_poll_last_error_count'),('rutube_poll_last_account_count')
), checkpoints AS (
    SELECT keys.key, CASE
      WHEN c.value IS NULL OR c.value='null'::jsonb THEN 'null'::jsonb
      WHEN keys.key='telegram_web_last_error' THEN
        CASE WHEN c.value='""'::jsonb OR c.value='false'::jsonb OR c.value->'present'='false'::jsonb
             THEN 'null'::jsonb ELSE '"upstream_error"'::jsonb END
      WHEN keys.key ~ '(count|seconds)$' AND c.value #>> '{}' ~ '^[0-9]{1,12}(\.[0-9]{1,6})?$' THEN to_jsonb(c.value #>> '{}')
      WHEN keys.key ~ '(_at|_poll)$' AND c.value #>> '{}' ~ '^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9:.+-]{5,30}Z?$' THEN c.value
      ELSE 'null'::jsonb END AS value
    FROM keys LEFT JOIN LATERAL (
      SELECT CASE WHEN jsonb_typeof(value)='object' AND value ? 'unparsed_text'
        THEN value->'unparsed_text' ELSE value END AS value
      FROM ops_and_admin.operational_checkpoint c
      WHERE c.checkpoint_key=keys.key AND c.scope_type IN ('system','platform')
      ORDER BY c.source_observed_at DESC NULLS LAST,c.updated_at DESC,c.id DESC LIMIT 1
    ) c ON true
), platforms(platform) AS (VALUES ('telegram'),('vk'),('max'),('rutube')),
run_states AS (
    SELECT p.platform, jsonb_build_object('started_at',started.started_at,'completed_at',r.completed_at,
      'duration_seconds',extract(epoch FROM r.completed_at-r.started_at),'status',r.status,
      'error_count',r.error_count,'account_count',r.account_count) AS value
    FROM platforms p LEFT JOIN LATERAL (
      SELECT started_at FROM ingest.collection_run r
      WHERE r.platform=p.platform::catalog.platform_code AND collector_version NOT LIKE 'sqlite-bridge/%'
      ORDER BY r.started_at DESC,r.id DESC LIMIT 1
    ) started ON true LEFT JOIN LATERAL (
      SELECT started_at,completed_at,status,error_count,account_count FROM ingest.collection_run r
      WHERE r.platform=p.platform::catalog.platform_code AND collector_version NOT LIKE 'sqlite-bridge/%' AND completed_at IS NOT NULL
      ORDER BY r.completed_at DESC,r.id DESC LIMIT 1
    ) r ON true
), published AS (
    -- Данные видны сразу после фиксации ревизии: материализованных проекций,
    -- которых нужно было дожидаться, больше нет.
    SELECT revision.id AS dataset_revision_id, revision.committed_at
      FROM analytics.dataset_revision AS revision
     ORDER BY revision.id DESC LIMIT 1
), outbox_class AS (
    SELECT 'cacheDelivery' AS class,
           count(*) FILTER (WHERE published_at IS NULL AND terminal_at IS NULL) AS pending,
           min(occurred_at) FILTER (WHERE published_at IS NULL AND terminal_at IS NULL) AS oldest_pending_at,
           max(publish_attempts) FILTER (WHERE published_at IS NULL AND terminal_at IS NULL) AS max_attempts,
           count(*) FILTER (WHERE terminal_at IS NOT NULL) AS terminal
      FROM ops_and_admin.outbox_event
     GROUP BY class
), outbox AS (
    SELECT jsonb_build_object(
        'classes', coalesce((SELECT jsonb_object_agg(class, jsonb_build_object(
            'pending', pending,
            'oldestPendingAt', oldest_pending_at,
            'maxAttempts', coalesce(max_attempts, 0),
            'terminal', terminal
        )) FROM outbox_class), '{}'::jsonb),
        'oldestDeliverableAt', (
            SELECT min(occurred_at)
              FROM ops_and_admin.outbox_event
             WHERE published_at IS NULL
               AND terminal_at IS NULL
        )
    ) AS value
), storage AS (
    SELECT current_sample.*,
           CASE WHEN previous_sample.observed_at IS NULL THEN NULL ELSE
             round((current_sample.database_size_bytes-previous_sample.database_size_bytes)::numeric
               * 86400 / nullif(extract(epoch FROM current_sample.observed_at-previous_sample.observed_at),0)) END
             AS growth_bytes_per_day,
           CASE WHEN previous_sample.observed_at IS NULL
                  OR current_sample.wal_bytes < previous_sample.wal_bytes THEN NULL ELSE
             round((current_sample.wal_bytes-previous_sample.wal_bytes)
               * 86400 / nullif(extract(epoch FROM current_sample.observed_at-previous_sample.observed_at),0)) END
             AS wal_bytes_per_day,
           CASE WHEN previous_sample.observed_at IS NULL
                  OR current_sample.temporary_bytes < previous_sample.temporary_bytes THEN NULL ELSE
             round((current_sample.temporary_bytes-previous_sample.temporary_bytes)::numeric
               * 86400 / nullif(extract(epoch FROM current_sample.observed_at-previous_sample.observed_at),0)) END
             AS temporary_bytes_per_day
      FROM LATERAL (
          SELECT * FROM ops_and_admin.storage_observation ORDER BY observed_at DESC LIMIT 1
      ) AS current_sample
      LEFT JOIN LATERAL (
          SELECT * FROM ops_and_admin.storage_observation
           WHERE observed_at < current_sample.observed_at ORDER BY observed_at DESC LIMIT 1
      ) AS previous_sample ON true
)
SELECT jsonb_build_object(
    'asOf',statement_timestamp(),
    'channels',(SELECT count(*) FROM catalog.platform_account WHERE platform='telegram' AND enabled),
    'checkpoints',(SELECT jsonb_object_agg(key,value) FROM checkpoints),
    'runs',(SELECT jsonb_object_agg(platform,value) FROM run_states),
    'rawRevision',coalesce((SELECT max(id) FROM analytics.dataset_revision),0),
    'publishedRevision',coalesce((SELECT dataset_revision_id FROM published),0),
    'publishedGenerationAgeSeconds',(
        SELECT greatest(0, extract(epoch FROM statement_timestamp()-committed_at))::bigint
          FROM published
    ),
    'revisionLag',greatest(0,
        coalesce((SELECT max(id) FROM analytics.dataset_revision),0)
        - coalesce((SELECT dataset_revision_id FROM published),0)),
    'outbox',(SELECT value FROM outbox),
    'storage',coalesce((SELECT jsonb_build_object(
        'sampledAt',observed_at,
        'databaseSizeBytes',database_size_bytes,
        'growthBytesPerDay',growth_bytes_per_day,
        'walBytesPerDay',wal_bytes_per_day,
        'temporaryBytesPerDay',temporary_bytes_per_day,
        'largestRelations',largest_relations,
        'rowEstimates',row_estimates
    ) FROM storage), '{}'::jsonb)
)
$_$;

-- ops_and_admin.publication_partition_digest(date)
CREATE FUNCTION ops_and_admin.publication_partition_digest(p_month date) RETURNS TABLE(row_count bigint, min_observed_at timestamp with time zone, max_observed_at timestamp with time zone, canonical_sha256 text)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ingest', 'ops_and_admin'
    SET "TimeZone" TO 'UTC'
    AS $$
DECLARE item record; chain bytea:=sha256(''::bytea);
BEGIN
 row_count:=0;
 FOR item IN SELECT id,observed_at FROM ingest.publication_metric_snapshot WHERE published_month=p_month ORDER BY id LOOP
   chain:=sha256(chain||sha256(convert_to(ops_and_admin.publication_archive_record(p_month,item.id),'UTF8')));
   row_count:=row_count+1;
   min_observed_at:=least(min_observed_at,item.observed_at);
   max_observed_at:=greatest(max_observed_at,item.observed_at);
 END LOOP;
 canonical_sha256:=encode(chain,'hex');
 RETURN NEXT;
END $$;

-- ops_and_admin.purge_expired_raw_payload(integer)
CREATE FUNCTION ops_and_admin.purge_expired_raw_payload(p_limit integer DEFAULT 10000) RETURNS bigint
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
          FROM ingest.raw_payload
         WHERE purge_after <= transaction_timestamp()
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
END
$$;

-- ops_and_admin.purge_raw_evidence_reference(text, timestamp with time zone)
CREATE FUNCTION ops_and_admin.purge_raw_evidence_reference(p_uri text, p_now timestamp with time zone) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ingest'
    AS $$
DECLARE removed bigint;
BEGIN
 DELETE FROM ingest.raw_payload WHERE external_ref=p_uri AND purge_after<=p_now;
 GET DIAGNOSTICS removed=ROW_COUNT;
 RETURN removed;
END $$;

-- ops_and_admin.record_anomaly_attempt_tombstone(uuid, uuid, text)
CREATE FUNCTION ops_and_admin.record_anomaly_attempt_tombstone(p_attempt_id uuid, p_superseded_by uuid, p_reason text) RETURNS void
    LANGUAGE sql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'analytics', 'ops_and_admin'
    AS $$
INSERT INTO ops_and_admin.audit_log(subject,action,target_type,target_id,correlation_id,before_state,outcome)
SELECT 'analytics_worker','anomaly.attempt.prune','publication_analysis_attempt',attempt.id,p_superseded_by,
       jsonb_build_object('attemptKey',attempt.attempt_key,'publicationId',attempt.publication_id,
         'status',attempt.status,'sourceDatasetRevision',attempt.source_dataset_revision_id,
         'inputHash',attempt.input_hash,'detectorManifestHash',attempt.detector_manifest_hash,
         'preprocessingVersion',attempt.preprocessing_version,'aggregatorVersion',attempt.aggregator_version,
         'errorCode',attempt.error_code,'completedAt',attempt.completed_at,'reason',p_reason),
       'pruned'
  FROM analytics.publication_analysis_attempt attempt WHERE attempt.id=p_attempt_id
$$;

-- ops_and_admin.refresh_storage_observation()
CREATE FUNCTION ops_and_admin.refresh_storage_observation() RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'ops_and_admin'
    SET lock_timeout TO '2s'
    SET statement_timeout TO '2min'
    AS $$
DECLARE
    sample ops_and_admin.storage_observation%ROWTYPE;
BEGIN
    INSERT INTO ops_and_admin.storage_observation (
        database_size_bytes, temporary_bytes, wal_bytes,
        largest_relations, row_estimates
    )
    SELECT pg_database_size(current_database()),
           database_stats.temp_bytes,
           wal_stats.wal_bytes,
           coalesce((
               SELECT jsonb_agg(to_jsonb(relation_size) ORDER BY relation_size.total_bytes DESC)
               FROM (
                   SELECT namespace.nspname AS schema,
                          relation.relname AS relation,
                          pg_total_relation_size(relation.oid) AS total_bytes,
                          pg_relation_size(relation.oid) AS heap_bytes,
                          pg_indexes_size(relation.oid) AS index_bytes
                   FROM pg_class AS relation
                   JOIN pg_namespace AS namespace
                     ON namespace.oid = relation.relnamespace
                   WHERE namespace.nspname IN ('ingest', 'analytics')
                     AND relation.relkind IN ('r', 'm')
                   ORDER BY total_bytes DESC
                   LIMIT 12
               ) AS relation_size
           ), '[]'::jsonb),
           coalesce((
               WITH observed_table(schema_name, relation_name) AS (VALUES
                   ('ingest', 'publication_metric_snapshot'),
                   ('ingest', 'account_metric_snapshot'),
                   ('ingest', 'reaction_breakdown'),
                   ('ingest', 'deletion_observation'),
                   ('ingest', 'publication_availability_event'),
                   ('analytics', 'publication_history')
               ), estimates AS (
                   SELECT concat(observed.schema_name, '.', observed.relation_name) AS relation,
                          coalesce(sum(table_stats.n_live_tup), 0)::bigint AS estimated_rows
                     FROM observed_table AS observed
                     JOIN pg_namespace AS namespace
                       ON namespace.nspname = observed.schema_name
                     JOIN pg_class AS root
                       ON root.relnamespace = namespace.oid
                      AND root.relname = observed.relation_name
                     LEFT JOIN LATERAL pg_partition_tree(root.oid) AS tree ON true
                     LEFT JOIN pg_stat_all_tables AS table_stats
                       ON table_stats.relid = coalesce(tree.relid, root.oid)
                    GROUP BY observed.schema_name, observed.relation_name
               )
               SELECT jsonb_object_agg(relation, estimated_rows)
                 FROM estimates
           ), '{}'::jsonb)
      FROM pg_stat_database AS database_stats
     CROSS JOIN pg_stat_wal AS wal_stats
     WHERE database_stats.datname = current_database()
    RETURNING * INTO sample;

    -- Hourly execution retains at most about 744 tiny rows. This bounded delete
    -- never touches collector facts or projection data.
    DELETE FROM ops_and_admin.storage_observation
     WHERE observed_at < sample.observed_at - interval '31 days';

    RETURN to_jsonb(sample);
END
$$;

-- ops_and_admin.reject_audit_mutation()
CREATE FUNCTION ops_and_admin.reject_audit_mutation() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    RAISE EXCEPTION 'admin audit is append-only' USING ERRCODE = '55000';
END
$$;

-- ops_and_admin.seed_anomaly_backfill(integer, text)
CREATE FUNCTION ops_and_admin.seed_anomaly_backfill(p_limit integer, p_manifest_hash text) RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'catalog', 'ingest', 'analytics', 'ops_and_admin'
    SET statement_timeout TO '15s'
    AS $_$
DECLARE inserted_count integer;
BEGIN
    IF p_limit<1 OR p_limit>1000 OR p_manifest_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'invalid bounded anomaly backfill request';
    END IF;
    WITH eligible AS (
        SELECT publication.id
          FROM ingest.publication publication
         WHERE publication.published_at>=transaction_timestamp()-interval '70 days'
           AND publication.published_at<=transaction_timestamp()-interval '15 minutes'
           AND NOT EXISTS (
               SELECT 1 FROM analytics.publication_analysis_state state
                WHERE state.publication_id=publication.id
                  AND state.detector_manifest_hash=p_manifest_hash
           )
           AND NOT EXISTS (
               SELECT 1 FROM ops_and_admin.anomaly_analysis_candidate candidate
                WHERE candidate.publication_id=publication.id
           )
           AND EXISTS (
               SELECT 1 FROM ingest.publication_metric_snapshot snapshot
                WHERE snapshot.publication_id=publication.id
           )
         ORDER BY publication.published_at DESC,publication.id
         LIMIT p_limit
    ), inserted AS (
        INSERT INTO ops_and_admin.anomaly_analysis_candidate(
            publication_id,dirty_generation,eligible_at,priority,config_backfill
        ) SELECT id,1,transaction_timestamp(),10,true FROM eligible
        ON CONFLICT(publication_id) DO NOTHING
        RETURNING 1
    ) SELECT count(*) INTO inserted_count FROM inserted;
    RETURN inserted_count;
END $_$;

-- rating.reject_published_component_mutation()
CREATE FUNCTION rating.reject_published_component_mutation() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'rating'
    AS $$
DECLARE parent record;
BEGIN
    -- Ordered parent row locks also serialize component edits against publication.
    FOR parent IN SELECT id, status FROM rating.formula_definition
       WHERE id IN (CASE WHEN TG_OP <> 'INSERT' THEN OLD.formula_definition_id END,
                    CASE WHEN TG_OP <> 'DELETE' THEN NEW.formula_definition_id END)
       ORDER BY id FOR UPDATE
    LOOP
        IF parent.status IN ('published', 'retired') THEN
            RAISE EXCEPTION 'components of a published or retired formula are immutable'
                USING ERRCODE = '55000';
        END IF;
    END LOOP;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END
$$;

-- rating.reject_published_formula_mutation()
CREATE FUNCTION rating.reject_published_formula_mutation() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'rating'
    AS $$
BEGIN
    IF TG_OP = 'DELETE' AND OLD.status IN ('published', 'retired') THEN
        RAISE EXCEPTION 'published formula % version % is immutable', OLD.formula_key, OLD.version;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.status = 'retired' THEN
        RAISE EXCEPTION 'retired formula % version % is immutable', OLD.formula_key, OLD.version;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.status = 'published' THEN
        IF NEW.status <> 'retired'
           OR NEW.formula_key IS DISTINCT FROM OLD.formula_key
           OR NEW.version IS DISTINCT FROM OLD.version
           OR NEW.effective_from IS DISTINCT FROM OLD.effective_from
           OR NEW.definition IS DISTINCT FROM OLD.definition
           OR NEW.source_hash IS DISTINCT FROM OLD.source_hash
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
           OR NEW.published_at IS DISTINCT FROM OLD.published_at THEN
            RAISE EXCEPTION 'published formula % version % is immutable except for retirement',
                OLD.formula_key, OLD.version;
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$$;
