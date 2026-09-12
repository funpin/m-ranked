from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from uuid import UUID, uuid4

import pytest

from anomaly_analysis.config import default_manifest
from anomaly_analysis.coordinator import AnalysisCoordinator, WorkerConfig
from anomaly_analysis.metrics import TextfileMetrics
from anomaly_analysis.postgres import PostgresAnalysisRepository

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row

PUBLICATION = uuid4()
INSTITUTION = uuid4()
ACCOUNT = uuid4()
RUN = uuid4()
HASH_A = "a" * 64
HASH_B = "b" * 64


@pytest.fixture(scope="module")
def databases():
    names = {
        "admin": "MRANKED_ANOMALY_TEST_ADMIN_DSN",
        "worker": "MRANKED_ANOMALY_TEST_WORKER_DSN",
        "api": "MRANKED_ANOMALY_TEST_API_DSN",
        "admin_api": "MRANKED_ANOMALY_TEST_ADMIN_API_DSN",
    }
    values = {name: os.environ.get(key, "") for name, key in names.items()}
    if not all(values.values()):
        pytest.skip("disposable anomaly PostgreSQL role DSNs are required")
    if "anomaly_it" not in values["admin"] or not any(host in values["admin"] for host in ("127.0.0.1", "localhost")):
        raise AssertionError("anomaly integration test requires the dedicated disposable local anomaly_it database")
    with psycopg.connect(values["admin"], autocommit=True) as connection:
        # The local suite is deliberately re-runnable against the same disposable
        # database; keep older fixture candidates out of this module's claim race.
        connection.execute("UPDATE ops_and_admin.anomaly_analysis_candidate SET eligible_at=now()+interval '1 day'")
        connection.execute("INSERT INTO catalog.institution(id,canonical_name) VALUES (%s,'Anomaly fixture')", (INSTITUTION,))
        connection.execute("""
            INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode)
            VALUES (%s,%s,'vk',%s,'public_web')
            """, (ACCOUNT, INSTITUTION, f"anomaly-fixture-{ACCOUNT}"))
        connection.execute("""
            INSERT INTO ingest.collection_run(id,platform,partition_key,collector_version,started_at,status,correlation_id)
            VALUES (%s,'vk','anomaly','integration',now()-interval '3 hours','succeeded',gen_random_uuid())
            """, (RUN,))
        connection.execute("""
            INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness)
            VALUES (%s,%s,now()-interval '2 hours',now()-interval '2 hours','post','complete')
            """, (PUBLICATION, ACCOUNT))
    yield values


def _admin(dsn):
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)


def _insert_snapshot(connection, bucket: int, fingerprint: str, views: int, *, offset_minutes: int = 0):
    return connection.execute("""
        INSERT INTO ingest.publication_metric_snapshot(
          published_month,publication_id,collection_run_id,observed_at,age_seconds,sampling_bucket,
          views_count,reactions_count,comments_count,shares_count,quality,source_fingerprint,collected_at)
        SELECT date_trunc('month',published_at)::date,id,%s,published_at+make_interval(mins=>%s),
               greatest(0,(extract(epoch FROM make_interval(mins=>%s)))::integer),%s,%s,10,2,1,'exact',%s,
               published_at+make_interval(mins=>%s)
          FROM ingest.publication WHERE id=%s
        RETURNING id,correction_sequence
        """, (RUN, offset_minutes, offset_minutes, bucket, views, fingerprint, offset_minutes, PUBLICATION)).fetchone()


def _publish_core(connection) -> int:
    revision = connection.execute("""
        INSERT INTO analytics.dataset_revision(cause,correlation_id)
        VALUES ('ingestion',gen_random_uuid()) RETURNING id
        """).fetchone()["id"]
    connection.execute("SELECT analytics.rebuild_core_projections(%s)", (revision,))
    return revision


def _pin(worker_dsn) -> dict:
    with psycopg.connect(worker_dsn, autocommit=True, row_factory=dict_row) as connection:
        return connection.execute("SELECT * FROM ops_and_admin.pin_latest_anomaly_source_revision()").fetchone()


def _claim(worker_dsn, token: UUID):
    with psycopg.connect(worker_dsn, autocommit=True, row_factory=dict_row) as connection:
        return connection.execute("SELECT * FROM ops_and_admin.claim_anomaly_candidates(1,30,%s)", (token,)).fetchall()


def test_trigger_exact_replay_correction_and_future_as_of_isolation(databases):
    with _admin(databases["admin"]) as connection:
        original = _insert_snapshot(connection, 0, "original", 100)
        generation = connection.execute("SELECT dirty_generation FROM ops_and_admin.anomaly_analysis_candidate WHERE publication_id=%s", (PUBLICATION,)).fetchone()["dirty_generation"]
        assert _insert_snapshot(connection, 0, "original", 100) is None
        assert connection.execute("SELECT dirty_generation FROM ops_and_admin.anomaly_analysis_candidate WHERE publication_id=%s", (PUBLICATION,)).fetchone()["dirty_generation"] == generation
        first_revision = _publish_core(connection)
    assert _pin(databases["worker"])["id"] == first_revision

    with _admin(databases["admin"]) as connection:
        corrected = _insert_snapshot(connection, 0, "corrected", 250)
        assert corrected["correction_sequence"] == 1
        assert connection.execute("SELECT dirty_generation FROM ops_and_admin.anomaly_analysis_candidate WHERE publication_id=%s", (PUBLICATION,)).fetchone()["dirty_generation"] == generation + 1
        second_revision = _publish_core(connection)
    assert _pin(databases["worker"])["id"] == second_revision

    with psycopg.connect(databases["worker"], autocommit=True, row_factory=dict_row) as connection:
        old = connection.execute("SELECT views_count,correction_sequence FROM analytics.extract_publication_history_as_of(ARRAY[%s]::uuid[],%s,100)", (PUBLICATION, first_revision)).fetchall()
        new = connection.execute("SELECT views_count,correction_sequence FROM analytics.extract_publication_history_as_of(ARRAY[%s]::uuid[],%s,100)", (PUBLICATION, second_revision)).fetchall()
    assert old == [{"views_count": 100, "correction_sequence": 0}]
    assert new == [{"views_count": 250, "correction_sequence": 1}]
    assert original["id"] != corrected["id"]


def test_claim_lease_recovery_atomic_publication_retention_and_core_independence(databases):
    with _admin(databases["admin"]) as connection:
        connection.execute("UPDATE ops_and_admin.anomaly_analysis_candidate SET eligible_at=now()-interval '1 second' WHERE publication_id=%s", (PUBLICATION,))
    first_token, second_token = uuid4(), uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda token: _claim(databases["worker"], token), (first_token, second_token)))
    assert sorted(map(len, claims)) == [0, 1]
    winning_token = first_token if claims[0] else second_token
    claim = (claims[0] or claims[1])[0]

    with _admin(databases["admin"]) as connection:
        connection.execute("UPDATE ops_and_admin.anomaly_analysis_candidate SET leased_until=now()-interval '1 second' WHERE publication_id=%s", (PUBLICATION,))
    recovered_token = uuid4()
    recovered = _claim(databases["worker"], recovered_token)
    assert len(recovered) == 1
    claim = recovered[0]
    source = _pin(databases["worker"])["id"]
    attempt = uuid4()
    finding = [{
        "id": str(uuid4()), "metric": "views", "detector_id": "delayed_spike_after_plateau",
        "detector_version": "1.0.0", "score": 0.82, "severity": "high",
        "explanation_code": "large_rate_jump_after_plateau",
        "start_at": "2026-09-08T10:00:00Z", "end_at": "2026-09-08T10:05:00Z",
        "start_snapshot_id": "1", "end_snapshot_id": "2", "evidence": {"rateRatio": 12},
        "quality_codes": [], "alternative_codes": ["external_referral"],
    }]
    with psycopg.connect(databases["worker"], autocommit=True, row_factory=dict_row) as connection:
        revision = connection.execute("""
          SELECT analytics.publish_anomaly_success(%s,%s,%s,%s,%s,%s,%s,'1.0.0','1.0.0',1,1,now(),'ready',0.82,'high',%s::jsonb)
          """, (PUBLICATION, recovered_token, claim["dirty_generation"], attempt, source, HASH_A, HASH_A, json.dumps(finding))).fetchone()["publish_anomaly_success"]
        repeated = connection.execute("""
          SELECT analytics.publish_anomaly_success(%s,%s,%s,%s,%s,%s,%s,'1.0.0','1.0.0',1,1,now(),'ready',0.82,'high',%s::jsonb)
          """, (PUBLICATION, uuid4(), claim["dirty_generation"], attempt, source, HASH_A, HASH_A, json.dumps(finding))).fetchone()["publish_anomaly_success"]
    assert repeated == revision

    with _admin(databases["admin"]) as connection:
        _insert_snapshot(connection, 1, "later", 300, offset_minutes=5)
        newer_core = _publish_core(connection)
        connection.execute("UPDATE ops_and_admin.anomaly_analysis_candidate SET eligible_at=now()-interval '1 second' WHERE publication_id=%s", (PUBLICATION,))
    assert _pin(databases["worker"])["id"] == newer_core
    failure_token = uuid4()
    failure_claim = _claim(databases["worker"], failure_token)[0]
    with psycopg.connect(databases["worker"], autocommit=True, row_factory=dict_row) as connection:
        connection.execute("""
          SELECT analytics.publish_anomaly_failure(%s,%s,%s,%s,%s,%s,'1.0.0','1.0.0',1,1,now(),'detector_failed',1)
          """, (PUBLICATION, failure_token, failure_claim["dirty_generation"], uuid4(), newer_core, HASH_A))
    with psycopg.connect(databases["api"], autocommit=True, row_factory=dict_row) as connection:
        state = connection.execute("SELECT status FROM analytics.publication_analysis_state_public WHERE publication_id=%s", (PUBLICATION,)).fetchone()
        public_count = connection.execute("SELECT count(*) AS n FROM analytics.publication_anomaly_finding_public WHERE publication_id=%s AND active", (PUBLICATION,)).fetchone()["n"]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT input_hash FROM analytics.publication_analysis_state LIMIT 1")
    assert state["status"] == "stale"
    assert public_count == 1

    with _admin(databases["admin"]) as connection:
        connection.execute("UPDATE ops_and_admin.anomaly_analysis_candidate SET eligible_at=now()-interval '1 second' WHERE publication_id=%s", (PUBLICATION,))
    success_token = uuid4()
    success_claim = _claim(databases["worker"], success_token)[0]
    with psycopg.connect(databases["worker"], autocommit=True) as connection:
        connection.execute("""
          SELECT analytics.publish_anomaly_success(%s,%s,%s,%s,%s,%s,%s,'1.0.0','1.0.0',1,1,now(),'ready',0,'low','[]'::jsonb)
          """, (PUBLICATION, success_token, success_claim["dirty_generation"], uuid4(), newer_core, HASH_B, HASH_A))
    with _admin(databases["admin"]) as connection:
        retained = connection.execute("SELECT status,count(*) AS n FROM analytics.publication_analysis_attempt WHERE publication_id=%s GROUP BY status ORDER BY status", (PUBLICATION,)).fetchall()
        newest_revision = _publish_core(connection)
    assert retained == [{"status": "failed", "n": 1}, {"status": "succeeded", "n": 1}]
    assert _pin(databases["worker"])["id"] == newest_revision
    # Analyzer state/failure has no role in the unchanged core publication barrier
    # (the seven projections required by JdbcDatasetRevisionProvider).
    with _admin(databases["admin"]) as connection:
        ready = {row["projection_name"] for row in connection.execute(
            "SELECT projection_name FROM analytics.projection_state WHERE dataset_revision_id=%s AND status='ready'",
            (newest_revision,)).fetchall()}
    assert {"publication_latest", "publication_hourly", "institution_daily_metrics", "institution_monthly_metrics",
            "institution_period_metrics", "comparison", "publication_history"} <= ready


def test_newer_generation_survives_success_and_admin_review_is_private(databases):
    with _admin(databases["admin"]) as connection:
        _insert_snapshot(connection, 2, "generation-a", 320, offset_minutes=10)
        source = _publish_core(connection)
        connection.execute("UPDATE ops_and_admin.anomaly_analysis_candidate SET eligible_at=now()-interval '1 second' WHERE publication_id=%s", (PUBLICATION,))
    assert _pin(databases["worker"])["id"] == source
    token = uuid4()
    claim = _claim(databases["worker"], token)[0]
    with _admin(databases["admin"]) as connection:
        _insert_snapshot(connection, 3, "generation-b", 340, offset_minutes=15)
    with psycopg.connect(databases["worker"], autocommit=True) as connection:
        connection.execute("""
          SELECT analytics.publish_anomaly_success(%s,%s,%s,%s,%s,%s,%s,'1.0.0','1.0.0',1,1,now(),'ready',0,'low','[]'::jsonb)
          """, (PUBLICATION, token, claim["dirty_generation"], uuid4(), source, "c" * 64, HASH_A))
    with _admin(databases["admin"]) as connection:
        candidate = connection.execute("SELECT dirty_generation,claim_token FROM ops_and_admin.anomaly_analysis_candidate WHERE publication_id=%s", (PUBLICATION,)).fetchone()
    assert candidate["dirty_generation"] > claim["dirty_generation"] and candidate["claim_token"] is None

    command_key, correlation = uuid4(), uuid4()
    with psycopg.connect(databases["admin_api"], autocommit=True, row_factory=dict_row) as connection:
        manual = connection.execute("""
          SELECT analytics.create_manual_anomaly_signal(%s,'comments','medium','operator_context',
            now()-interval '10 minutes',now(),'{}'::jsonb,'admin',%s,%s,%s)
          """, (PUBLICATION, correlation, command_key, "d" * 64)).fetchone()["create_manual_anomaly_signal"]
        if isinstance(manual, str): manual = json.loads(manual)
        review = connection.execute("SELECT analytics.append_anomaly_review(%s,'explained','private note','admin',%s,%s,%s)",
                                    (manual["findingId"], correlation, uuid4(), "e" * 64)).fetchone()["append_anomaly_review"]
        assert review
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT private_comment FROM analytics.publication_anomaly_review LIMIT 1")
    with psycopg.connect(databases["api"], autocommit=True, row_factory=dict_row) as connection:
        public = connection.execute("SELECT origin,suspicion_score,review_state,active FROM analytics.publication_anomaly_finding_public WHERE id=%s", (manual["findingId"],)).fetchone()
        assert public == {"origin": "manual", "suspicion_score": None, "review_state": "explained", "active": True}
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("INSERT INTO analytics.publication_analysis_state(publication_id) VALUES (%s)", (PUBLICATION,))
    for decision, active in (("data_error", False), ("dismissed", False), ("unresolved", True)):
        with psycopg.connect(databases["admin_api"], autocommit=True) as connection:
            connection.execute("SELECT analytics.append_anomaly_review(%s,%s,NULL,'admin',%s,%s,%s)",
                               (manual["findingId"], decision, correlation, uuid4(), "f" * 64))
        with psycopg.connect(databases["api"], autocommit=True, row_factory=dict_row) as connection:
            effective = connection.execute(
                "SELECT review_state,active FROM analytics.publication_anomaly_finding_public WHERE id=%s",
                (manual["findingId"],)).fetchone()
            assert effective == {"review_state": decision, "active": active}
    with psycopg.connect(databases["worker"], autocommit=True) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT * FROM ingest.publication LIMIT 1")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT analytics.rebuild_core_projections(%s)", (source,))


def test_required_indexes_and_bounded_set_based_contract(databases):
    with _admin(databases["admin"]) as connection:
        definitions = connection.execute("""
          SELECT pg_get_functiondef('analytics.extract_publication_history_as_of(uuid[],bigint,integer)'::regprocedure) AS extraction,
                 pg_get_functiondef('ops_and_admin.claim_anomaly_candidates(integer,integer,uuid)'::regprocedure) AS claim
          """).fetchone()
        assert "ANY(p_publication_ids)" in definitions["extraction"]
        assert "p_max_points+1" in definitions["extraction"].replace(" ", "")
        assert "SKIP LOCKED" in definitions["claim"]
        indexes = {row["indexname"] for row in connection.execute("""
          SELECT indexname FROM pg_indexes WHERE schemaname IN ('analytics','ops_and_admin')
            AND indexname LIKE '%anomaly%'
          """).fetchall()}
    assert {"anomaly_analysis_candidate_claim_idx", "publication_anomaly_finding_public_idx"} <= indexes


def test_representative_history_bound_and_query_plans_use_anomaly_indexes(databases):
    with _admin(databases["admin"]) as connection:
        with connection.transaction():
            for bucket in range(4, 124):
                _insert_snapshot(connection, bucket, f"plan-{bucket}", 340 + bucket, offset_minutes=bucket)
        source = _publish_core(connection)
    assert _pin(databases["worker"])["id"] == source
    with psycopg.connect(databases["worker"], autocommit=True, row_factory=dict_row) as connection:
        rows = connection.execute(
            "SELECT point_ordinal,total_points FROM analytics.extract_publication_history_as_of(ARRAY[%s]::uuid[],%s,50)",
            (PUBLICATION, source)).fetchall()
    assert len(rows) == 51 and rows[-1]["point_ordinal"] == 51 and rows[-1]["total_points"] >= 120

    with _admin(databases["admin"]) as connection:
        connection.execute("SET enable_seqscan=off")
        claim_plan = connection.execute("""
          EXPLAIN (FORMAT JSON)
          SELECT publication_id FROM ops_and_admin.anomaly_analysis_candidate
           WHERE eligible_at<=transaction_timestamp()
             AND claim_token IS NULL
           ORDER BY priority DESC,eligible_at,publication_id FOR UPDATE SKIP LOCKED LIMIT 20
          """).fetchone()["QUERY PLAN"]
        finding_plan = connection.execute("""
          EXPLAIN (FORMAT JSON)
          SELECT id FROM analytics.publication_anomaly_finding
           WHERE publication_id=%s ORDER BY created_analysis_revision_id DESC,id LIMIT 25
          """, (PUBLICATION,)).fetchone()["QUERY PLAN"]
    plans = json.dumps([claim_plan, finding_plan])
    assert "anomaly_analysis_candidate_claim_idx" in plans
    assert "publication_anomaly_finding_public_idx" in plans


def test_real_worker_processes_a_candidate_end_to_end(databases):
    with _admin(databases["admin"]) as connection:
        connection.execute("""
          UPDATE ops_and_admin.anomaly_analysis_candidate
             SET eligible_at=now()-interval '1 second',priority=100,
                 claim_token=NULL,claimed_generation=NULL,leased_until=NULL
           WHERE publication_id=%s
          """, (PUBLICATION,))
    repository = PostgresAnalysisRepository(databases["worker"])
    coordinator = AnalysisCoordinator(
        repository, default_manifest(),
        WorkerConfig(batch_size=1, lease_seconds=30, max_points_per_publication=4096),
        TextfileMetrics(None),
    )

    assert coordinator.run_once() == 1
    with _admin(databases["admin"]) as connection:
        state = connection.execute("""
          SELECT status,source_dataset_revision_id,analysis_revision_id
            FROM analytics.publication_analysis_state
           WHERE publication_id=%s
          """, (PUBLICATION,)).fetchone()
        attempt = connection.execute("""
          SELECT status,error_code FROM analytics.publication_analysis_attempt
           WHERE publication_id=%s ORDER BY analysis_revision_id DESC LIMIT 1
          """, (PUBLICATION,)).fetchone()
        candidate = connection.execute("""
          SELECT 1 FROM ops_and_admin.anomaly_analysis_candidate WHERE publication_id=%s
          """, (PUBLICATION,)).fetchone()
    assert state["status"] in {"ready", "partial"}
    assert state["source_dataset_revision_id"] > 0
    assert state["analysis_revision_id"] > 0
    assert attempt == {"status": "succeeded", "error_code": None}
    assert candidate is None


def _finding_envelope(start: str, end: str, score: float = 0.9) -> list[dict]:
    return [{
        "metric": "views", "detector_id": "delayed_spike_after_plateau", "detector_version": "1.0.0",
        "score": score, "severity": "high", "explanation_code": "large_rate_jump_after_plateau",
        "start_at": "2026-09-08T11:00:00Z", "end_at": "2026-09-08T11:05:00Z",
        "start_snapshot_id": start, "end_snapshot_id": end, "evidence": {"rateRatio": 15},
        "quality_codes": [], "alternative_codes": ["external_referral"],
    }]


def _reclaim(databases, bucket: int, fingerprint: str, views: int, offset_minutes: int):
    with _admin(databases["admin"]) as connection:
        _insert_snapshot(connection, bucket, fingerprint, views, offset_minutes=offset_minutes)
        source = _publish_core(connection)
        connection.execute("""
          UPDATE ops_and_admin.anomaly_analysis_candidate
             SET eligible_at=now()-interval '1 second',claim_token=NULL,claimed_generation=NULL,leased_until=NULL
           WHERE publication_id=%s
          """, (PUBLICATION,))
    assert _pin(databases["worker"])["id"] == source
    token = uuid4()
    return source, token, _claim(databases["worker"], token)[0]


def test_reviewed_automatic_finding_is_pruned_safely_and_keeps_effective_state_by_key(databases):
    source, token, claim = _reclaim(databases, 200, "keyed-a", 900, 130)
    with psycopg.connect(databases["worker"], autocommit=True) as connection:
        connection.execute("""
          SELECT analytics.publish_anomaly_success(%s,%s,%s,%s,%s,%s,%s,'1.0.0','1.0.0',1,1,now(),'ready',0.9,'high',%s::jsonb)
          """, (PUBLICATION, token, claim["dirty_generation"], uuid4(), source, "1" * 64, HASH_A,
                json.dumps(_finding_envelope("7", "8"))))
    with psycopg.connect(databases["api"], autocommit=True, row_factory=dict_row) as connection:
        first = connection.execute(
            "SELECT id,review_state,active FROM analytics.publication_anomaly_finding_public WHERE publication_id=%s AND origin='automatic'",
            (PUBLICATION,)).fetchall()
    assert len(first) == 1 and first[0]["review_state"] == "unreviewed" and first[0]["active"]
    with psycopg.connect(databases["admin_api"], autocommit=True) as connection:
        connection.execute("SELECT analytics.append_anomaly_review(%s,'dismissed','bot-like burst explained by newsletter','admin',%s,%s,%s)",
                           (first[0]["id"], uuid4(), uuid4(), "9" * 64))
    with psycopg.connect(databases["api"], autocommit=True, row_factory=dict_row) as connection:
        assert connection.execute(
            "SELECT active FROM analytics.publication_anomaly_finding_public WHERE id=%s", (first[0]["id"],)
        ).fetchone()["active"] is False

    # A newer success re-fires the same interval: retention prunes the reviewed
    # row without violating any constraint and the decision follows the key.
    source, token, claim = _reclaim(databases, 201, "keyed-b", 950, 135)
    with psycopg.connect(databases["worker"], autocommit=True) as connection:
        connection.execute("""
          SELECT analytics.publish_anomaly_success(%s,%s,%s,%s,%s,%s,%s,'1.0.0','1.0.0',1,1,now(),'ready',0.9,'high',%s::jsonb)
          """, (PUBLICATION, token, claim["dirty_generation"], uuid4(), source, "2" * 64, HASH_A,
                json.dumps(_finding_envelope("7", "8") + _finding_envelope("9", "10", 0.6))))
    with _admin(databases["admin"]) as connection:
        assert connection.execute("SELECT count(*) AS n FROM analytics.publication_analysis_attempt WHERE publication_id=%s AND status='succeeded'", (PUBLICATION,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) AS n FROM analytics.publication_anomaly_review WHERE publication_id=%s", (PUBLICATION,)).fetchone()["n"] >= 1
        tombstone = connection.execute("""
          SELECT before_state,outcome FROM ops_and_admin.audit_log
           WHERE action='anomaly.attempt.prune' AND before_state->>'publicationId'=%s
           ORDER BY occurred_at DESC LIMIT 1
          """, (str(PUBLICATION),)).fetchone()
        assert tombstone["outcome"] == "pruned"
        assert tombstone["before_state"]["reason"] == "superseded_by_success" and tombstone["before_state"]["inputHash"] == "1" * 64
        assert "evidence" not in json.dumps(tombstone["before_state"]) and "findings" not in json.dumps(tombstone["before_state"])
    with psycopg.connect(databases["api"], autocommit=True, row_factory=dict_row) as connection:
        rows = connection.execute("""
          SELECT id,start_snapshot_id,review_state,active FROM analytics.publication_anomaly_finding_public
           WHERE publication_id=%s AND origin='automatic' ORDER BY start_snapshot_id
          """, (PUBLICATION,)).fetchall()
    by_start = {row["start_snapshot_id"]: row for row in rows}
    assert set(by_start) == {"7", "9"}
    assert by_start["7"]["id"] != first[0]["id"]
    assert by_start["7"] | {"review_state": "dismissed", "active": False} == by_start["7"]
    assert by_start["9"] | {"review_state": "unreviewed", "active": True} == by_start["9"]


def test_unchanged_input_never_shortcuts_a_stale_publication(databases):
    with _admin(databases["admin"]) as connection:
        state = connection.execute("SELECT status,input_hash,detector_manifest_hash FROM analytics.publication_analysis_state WHERE publication_id=%s", (PUBLICATION,)).fetchone()
    assert state["status"] == "ready"
    with psycopg.connect(databases["worker"], autocommit=True, row_factory=dict_row) as connection:
        assert connection.execute("SELECT analytics.anomaly_input_is_unchanged(%s,%s,%s) AS v", (PUBLICATION, state["input_hash"], state["detector_manifest_hash"])).fetchone()["v"] is True
    source, token, claim = _reclaim(databases, 202, "stale-a", 960, 140)
    with psycopg.connect(databases["worker"], autocommit=True) as connection:
        connection.execute("""
          SELECT analytics.publish_anomaly_failure(%s,%s,%s,%s,%s,%s,'1.0.0','1.0.0',1,1,now(),'detector_failed',1)
          """, (PUBLICATION, token, claim["dirty_generation"], uuid4(), source, HASH_A))
    with _admin(databases["admin"]) as connection:
        assert connection.execute("SELECT status FROM analytics.publication_analysis_state WHERE publication_id=%s", (PUBLICATION,)).fetchone()["status"] == "stale"
    with psycopg.connect(databases["worker"], autocommit=True, row_factory=dict_row) as connection:
        assert connection.execute("SELECT analytics.anomaly_input_is_unchanged(%s,%s,%s) AS v", (PUBLICATION, state["input_hash"], state["detector_manifest_hash"])).fetchone()["v"] is False


def test_backfill_seed_is_bounded_and_never_resets_existing_candidates(databases):
    with _admin(databases["admin"]) as connection:
        connection.execute("""
          INSERT INTO ops_and_admin.anomaly_analysis_candidate(publication_id,eligible_at,retry_count)
          VALUES (%s,now()+interval '2 hours',3)
          ON CONFLICT(publication_id) DO UPDATE SET eligible_at=now()+interval '2 hours',retry_count=3,
            claim_token=NULL,claimed_generation=NULL,leased_until=NULL
          """, (PUBLICATION,))
    with psycopg.connect(databases["worker"], autocommit=True, row_factory=dict_row) as connection:
        seeded = connection.execute("SELECT ops_and_admin.seed_anomaly_backfill(100,%s) AS n", ("f" * 64,)).fetchone()["n"]
        assert seeded >= 0
        with pytest.raises(psycopg.errors.RaiseException):
            connection.execute("SELECT ops_and_admin.seed_anomaly_backfill(0,%s)", ("f" * 64,))
    with _admin(databases["admin"]) as connection:
        candidate = connection.execute("SELECT retry_count,eligible_at>now()+interval '1 hour' AS deferred,config_backfill FROM ops_and_admin.anomaly_analysis_candidate WHERE publication_id=%s", (PUBLICATION,)).fetchone()
    assert candidate == {"retry_count": 3, "deferred": True, "config_backfill": False}


def test_admin_command_functions_are_denied_to_api_read_and_worker(databases):
    for name in ("api", "worker"):
        with psycopg.connect(databases[name], autocommit=True) as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("""
                  SELECT analytics.create_manual_anomaly_signal(%s,'views','low','operator_context',
                    now()-interval '1 minute',now(),'{}'::jsonb,'intruder',gen_random_uuid(),gen_random_uuid(),%s)
                  """, (PUBLICATION, "a" * 64))
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT analytics.append_anomaly_review(gen_random_uuid(),'dismissed',NULL,'intruder',gen_random_uuid(),gen_random_uuid(),%s)", ("a" * 64,))
    with psycopg.connect(databases["api"], autocommit=True) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT ops_and_admin.claim_anomaly_candidates(1,30,gen_random_uuid())")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT * FROM analytics.extract_publication_history_as_of(ARRAY[%s]::uuid[],1,10)", (PUBLICATION,))


def test_extraction_reports_seeded_capabilities_and_indexed_plans_with_optional_evidence(databases, tmp_path):
    source = _pin(databases["worker"])["id"]
    with psycopg.connect(databases["worker"], autocommit=True, row_factory=dict_row) as connection:
        started = time.perf_counter()
        rows = connection.execute(
            "SELECT supported_metrics,total_points FROM analytics.extract_publication_history_as_of(ARRAY[%s]::uuid[],%s,4096)",
            (PUBLICATION, source)).fetchall()
        extraction_seconds = time.perf_counter() - started
    assert rows and rows[0]["supported_metrics"] == ["comments", "reactions", "shares", "views"]
    with _admin(databases["admin"]) as connection:
        connection.execute("SET enable_seqscan=off")
        plans = {
            "extraction": connection.execute("""
              EXPLAIN (FORMAT JSON)
              SELECT id FROM ingest.publication_metric_snapshot snapshot
               WHERE snapshot.publication_id=ANY(ARRAY[%s]::uuid[]) AND snapshot.created_at<=now()
              """, (PUBLICATION,)).fetchone()["QUERY PLAN"],
            "state": connection.execute(
                "EXPLAIN (FORMAT JSON) SELECT * FROM analytics.publication_analysis_state WHERE publication_id=%s",
                (PUBLICATION,)).fetchone()["QUERY PLAN"],
            "review": connection.execute("""
              EXPLAIN (FORMAT JSON)
              SELECT decision FROM analytics.publication_anomaly_review
               WHERE publication_id=%s AND finding_key=%s ORDER BY reviewed_at DESC,id DESC LIMIT 1
              """, (PUBLICATION, uuid4())).fetchone()["QUERY PLAN"],
        }
    serialized = json.dumps(plans)
    assert "publication_metric_snapshot" in serialized and "Seq Scan" not in serialized
    assert "publication_analysis_state_pkey" in serialized
    assert "publication_anomaly_review_effective_idx" in serialized
    report = os.environ.get("MRANKED_ANOMALY_PLAN_REPORT")
    if report:
        destination = Path(report)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps({
            "reportVersion": 1, "generatedAt": datetime.now(timezone.utc).isoformat(),
            "sourceDatasetRevision": source, "totalPoints": int(rows[0]["total_points"]),
            "extractionSeconds": round(extraction_seconds, 6), "plans": plans,
        }, indent=2, sort_keys=True) + "\n")
