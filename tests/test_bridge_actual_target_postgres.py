"""Fault injection is restricted to a caller-provisioned disposable database.

Each corruption is rolled back. Superuser replication mode deliberately bypasses
write protection to test reconciliation independently of the ingestion guards.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from migration.bridge.fixture import build_golden_fixture
from migration.bridge.model import BridgeOptions
from migration.bridge.service import BridgeService
from migration.bridge.source import LegacySource, create_online_backup
from migration.bridge.target import PostgresTarget


ADMIN_DSN = os.getenv("MRANKED_TEST_POSTGRES_ADMIN_DSN")


@pytest.mark.skipif(not ADMIN_DSN, reason="requires disposable PostgreSQL admin DSN")
def test_reconciliation_detects_actual_canonical_corruption(tmp_path: Path):
    path = tmp_path / "source.sqlite"
    build_golden_fixture(path, revision=2)
    with PostgresTarget(str(ADMIN_DSN)) as target:
        service = BridgeService(
            BridgeOptions(source=path, source_namespace="pytest-golden-integration", batch_size=2),
            LegacySource(path), target, snapshot_kind="catch_up",
        )
        _, baseline = service.run()
        assert baseline["gate"]["status"] == "pass", baseline["mismatches"]
        faults = {
            "compensating_plus_minus": """WITH chosen AS (
                SELECT published_month,id,row_number() OVER(ORDER BY id) AS n
                FROM ingest.publication_metric_snapshot WHERE views_count>0 LIMIT 2)
                UPDATE ingest.publication_metric_snapshot s SET views_count=s.views_count+CASE c.n WHEN 1 THEN 1 ELSE -1 END
                FROM chosen c WHERE s.published_month=c.published_month AND s.id=c.id""",
            "rating_rank_swap": """UPDATE rating.official_rating_observation SET rank=CASE rank WHEN 1 THEN 3 WHEN 3 THEN 1 ELSE rank END
                WHERE rank IN(1,3)""",
            "reaction_key": """UPDATE ingest.reaction_breakdown SET reaction_key='corrupt-key'
                WHERE reaction_key='👍'""",
            "null_to_zero": """UPDATE ingest.publication_metric_snapshot SET shares_count=0 WHERE shares_count IS NULL""",
            "timezone_shift": """UPDATE ingest.publication_metric_snapshot
                SET observed_at=observed_at+interval '3 hours',collected_at=collected_at+interval '3 hours'""",
            "negative_transition": """UPDATE ingest.publication_metric_snapshot SET views_count=1
                WHERE id=(SELECT id FROM ingest.publication_metric_snapshot WHERE views_count=140 LIMIT 1)""",
            "missing_row": """DELETE FROM ingest.publication_metric_snapshot
                WHERE id=(SELECT id FROM ingest.publication_metric_snapshot WHERE views_count=140 LIMIT 1)""",
            "extra_row": """INSERT INTO ingest.publication_metric_snapshot
                SELECT (jsonb_populate_record(NULL::ingest.publication_metric_snapshot,
                    to_jsonb(s)||jsonb_build_object('id',900000000000001,'sampling_bucket',999999,
                    'source_fingerprint',repeat('a',64)))).*
                FROM ingest.publication_metric_snapshot s LIMIT 1""",
            "changed_identity": """UPDATE ingest.publication_identity SET external_id=external_id||'-tampered' WHERE role='primary'""",
            "publication_flags": """UPDATE ingest.publication SET is_repost=NOT is_repost""",
            "account_native_identity": """UPDATE catalog.account_external_identity SET external_id=external_id||'-tampered'
                WHERE valid_to IS NULL AND identity_namespace LIKE '%%:native_id'""",
            "admin_display_mode": """UPDATE migration.legacy_evidence SET evidence=jsonb_set(evidence,'{access_mode}','\"owner\"')
                WHERE evidence_kind='legacy_account_presentation'""",
            "health_checkpoint_type": """UPDATE ops_and_admin.operational_checkpoint SET value='0'::jsonb
                WHERE checkpoint_key='last_poll'""",
        }
        for name, sql in faults.items():
            with target.connection.transaction(force_rollback=True):
                target.execute("SET LOCAL session_replication_role=replica")
                assert target.execute(sql).rowcount > 0, name
                report = service.reconcile()
                assert report["gate"]["status"] == "fail", name
                assert any(row["check"] == "canonical_target_digest" for row in report["mismatches"]), name
            assert service.reconcile()["gate"]["status"] == "pass", name


@pytest.mark.skipif(not ADMIN_DSN, reason="requires disposable PostgreSQL admin DSN")
def test_changed_legacy_fact_appends_correction_and_preserves_original_bytes(tmp_path: Path):
    initial = tmp_path / "initial.sqlite"
    changed = tmp_path / "changed.sqlite"
    frozen = tmp_path / "correction.sqlite"
    build_golden_fixture(initial, revision=2)
    def service(path, target):
        return BridgeService(BridgeOptions(source=path,source_namespace="pytest-golden-integration",batch_size=2),
                             LegacySource(path),target,snapshot_kind="catch_up")
    with PostgresTarget(str(ADMIN_DSN)) as target:
        _, before = service(initial,target).run()
        assert before["gate"]["status"] == "pass", before["mismatches"]
        old_id, old_bytes = target.fetchone("""SELECT id,to_jsonb(s)::text FROM ingest.publication_metric_snapshot_active s
            WHERE views_count=140""")
        create_online_backup(initial,changed)
        with closing(sqlite3.connect(changed)) as connection:
            with connection:
                assert connection.execute("UPDATE reaction_snapshots SET views_count=147 WHERE views_count=140").rowcount == 1
        create_online_backup(changed,frozen)
        stats, report = service(frozen,target).run()
        assert report["gate"]["status"] == "pass", report["mismatches"]
        assert stats.rows_written > 0
        tip = target.fetchone("""SELECT id,supersedes_snapshot_id,correction_sequence,correction_reason
            FROM ingest.publication_metric_snapshot_active WHERE views_count=147""")
        assert tip and tip[0] != old_id and tip[1] == old_id and tip[2] > 0 and tip[3]
        assert target.fetchone("SELECT to_jsonb(s)::text FROM ingest.publication_metric_snapshot s WHERE id=%s",(old_id,))[0] == old_bytes
        repeated, report = service(frozen,target).run()
        assert report["gate"]["status"] == "pass" and repeated.rows_written == 0
        assert target.fetchone("SELECT count(*) FROM ingest.publication_metric_snapshot WHERE supersedes_snapshot_id=%s",(old_id,))[0] == 1


@pytest.mark.skipif(not ADMIN_DSN, reason="requires disposable PostgreSQL admin DSN")
def test_cleared_native_identity_closes_history_and_reenrollment_appends(tmp_path: Path):
    import json
    from app.database import Database
    initial = tmp_path / "native-initial.sqlite"
    build_golden_fixture(initial, revision=2)
    def bridge(path, target):
        return BridgeService(BridgeOptions(source=path,source_namespace="pytest-golden-integration",batch_size=2),
                             LegacySource(path),target,snapshot_kind="catch_up")
    with PostgresTarget(str(ADMIN_DSN)) as target:
        _, baseline = bridge(initial,target).run()
        assert baseline["gate"]["status"] == "pass", baseline["mismatches"]
        # The generic Telegram row is a mirror. Clearing only its native_id
        # does not erase the authoritative channel identity or its protocol.
        mirror = tmp_path / "mirror-live.sqlite"
        create_online_backup(initial,mirror)
        with Database(mirror).connect() as connection:
            connection.execute("UPDATE platform_accounts SET native_id=NULL WHERE platform='telegram'")
        frozen_mirror = tmp_path / "mirror-frozen.sqlite"
        create_online_backup(mirror,frozen_mirror)
        native_before=target.fetchone("SELECT id FROM catalog.account_external_identity WHERE identity_namespace='telegram:native_id' AND valid_to IS NULL")[0]
        try:
            _, mirror_report=bridge(frozen_mirror,target).run()
            assert mirror_report["gate"]["status"]=="pass",mirror_report["mismatches"]
            assert target.fetchone("SELECT id FROM catalog.account_external_identity WHERE identity_namespace='telegram:native_id' AND valid_to IS NULL")[0]==native_before
        finally:
            _, restored=bridge(initial,target).run()
            assert restored["gate"]["status"]=="pass",restored["mismatches"]
        for platform in ("telegram","vk","max","rutube"):
            cleared = tmp_path / f"{platform}-cleared.sqlite"
            create_online_backup(initial,cleared)
            with Database(cleared).connect() as connection:
                connection.execute("UPDATE platform_accounts SET native_id=NULL WHERE platform=?",(platform,))
                if platform == "telegram":
                    connection.execute("UPDATE channels SET telegram_id=NULL")
            frozen = tmp_path / f"{platform}-frozen.sqlite"
            create_online_backup(cleared,frozen)
            cleared = frozen
            prior = target.fetchone("""SELECT identity.id,to_jsonb(identity)::text,account.canonical_external_id
                FROM catalog.account_external_identity identity JOIN catalog.platform_account account
                    ON account.id=identity.platform_account_id
                WHERE account.platform=%s AND identity.identity_namespace=%s AND identity.valid_to IS NULL""",
                (platform,platform+":native_id"))
            assert prior is not None
            try:
                _, report = bridge(cleared,target).run()
                assert report["gate"]["status"] == "pass", report["mismatches"]
                history = target.fetchone("SELECT to_jsonb(identity)::text FROM catalog.account_external_identity identity WHERE id=%s",(prior[0],))
                before,after = json.loads(prior[1]),json.loads(history[0])
                assert before["valid_to"] is None and after["valid_to"] is not None
                assert {k:v for k,v in before.items() if k!="valid_to"} == {k:v for k,v in after.items() if k!="valid_to"}
                assert target.fetchone("SELECT count(*) FROM catalog.account_external_identity WHERE platform_account_id=%s AND identity_namespace=%s AND valid_to IS NULL",
                    (before["platform_account_id"],platform+":native_id"))[0] == 0
                repeated, report = bridge(cleared,target).run()
                assert repeated.rows_written == 0 and report["gate"]["status"] == "pass"
            finally:
                _, restored = bridge(initial,target).run()
                assert restored["gate"]["status"] == "pass", restored["mismatches"]
            active = target.fetchone("""SELECT identity.id,account.canonical_external_id FROM catalog.account_external_identity identity
                JOIN catalog.platform_account account ON account.id=identity.platform_account_id
                WHERE account.platform=%s AND identity.identity_namespace=%s AND identity.valid_to IS NULL""",
                (platform,platform+":native_id"))
            assert active[0] != prior[0] and active[1] == prior[2]


@pytest.mark.skipif(not ADMIN_DSN, reason="requires disposable PostgreSQL admin DSN")
def test_missing_source_row_requires_verified_owner_ledger_and_remains_checked(tmp_path: Path):
    from migration.bridge.preservation import preserve_disappeared
    import psycopg
    from uuid import uuid4
    prior, live, final = (tmp_path/name for name in ("prior.sqlite","live.sqlite","s-final.sqlite"))
    build_golden_fixture(prior, revision=2)
    namespace = "preservation-test-"+str(uuid4())
    def bridge(path, target, kind):
        return BridgeService(BridgeOptions(source=path,source_namespace=namespace,batch_size=2),
                             LegacySource(path),target,snapshot_kind=kind)
    with PostgresTarget(str(ADMIN_DSN)) as target:
        _, initial = bridge(prior,target,"s0").run()
        assert initial["gate"]["status"] == "pass", initial["mismatches"]
        create_online_backup(prior,live)
        with closing(sqlite3.connect(live)) as connection, connection:
            assert connection.execute("DELETE FROM reaction_snapshots WHERE views_count=140").rowcount == 1
        create_online_backup(live,final)
        current = bridge(final,target,"s_final")
        _, failed = current.run()
        assert failed["gate"]["status"] == "fail"
        assert any(row["check"]=="source_rows_missing_since_prior_batch" for row in failed["mismatches"])
        args = dict(operator="test-owner",ticket="LOCAL-PRESERVE-1",reason="Verified frozen history retained after legacy hard delete")
        target.execute("SET ROLE migration_bridge")
        try:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                preserve_disappeared(current,prior,**args)
        finally:
            target.execute("RESET ROLE")
        assert target.fetchone("SELECT count(*) FROM migration.source_preservation WHERE source_namespace=%s",(current.source_namespace_uuid,))[0] == 0
        wrong = tmp_path/"unknown-prior.sqlite"
        build_golden_fixture(wrong,revision=1)
        with pytest.raises(ValueError,match="prior source artifact"):
            preserve_disappeared(current,wrong,**args)
        accepted = preserve_disappeared(current,prior,**args)
        assert accepted["gate"]["status"] == "pass", accepted["mismatches"]
        history = accepted["identity_history_verification"]
        assert history["status"] == "pass" and history["sourceUnchanged"]
        assert accepted["preservation"]["priorSourceSha256"] in history["sourceArtifacts"]
        assert all(check["expected"] == check["actual"] for check in history["checks"])
        assert accepted["preservation"]["decisions"] >= 1
        assert accepted["preservation"]["facts"] >= 1
        assert accepted["projection_verification"]["status"] == "pass"
        overlay = accepted["projection_verification"]["oracleSource"]
        assert overlay["mode"] == "verified-preserved-source-overlay"
        assert overlay["restoredRows"] == 1
        assert overlay["priorSourceSha256"] == [LegacySource(prior).inventory().source_sha256]
        without_prior = bridge(final,target,"s_final").reconcile()
        assert without_prior["gate"]["status"] == "fail"
        assert without_prior["projection_verification"]["errorCode"] == "PRESERVED_HISTORY_ORACLE_RECONSTRUCTION_REQUIRED"
        from dataclasses import replace
        correct_options=current.options
        current.options=replace(current.options,preserved_source_paths=(wrong,))
        unverified_prior=current.reconcile()
        assert unverified_prior["gate"]["status"] == "fail"
        assert unverified_prior["projection_verification"]["errorCode"] == "PRESERVED_SOURCE_ARTIFACT_NOT_VERIFIED"
        current.options=correct_options
        assert preserve_disappeared(current,prior,**args)["gate"]["status"] == "pass"
        pid = accepted["preservation"]["id"]
        for table, column, where in (
            ("source_preservation","reason","id"),
            ("preserved_canonical_fact","body","preservation_id"),
            ("preserved_source_decision","decision_id","preservation_id")):
            with target.connection.transaction(force_rollback=True):
                with pytest.raises(psycopg.Error,match="append-only"):
                    target.execute(f"UPDATE migration.{table} SET {column}={column} WHERE {where}=%s",(pid,))
        with target.connection.transaction(force_rollback=True):
            target.execute("SET LOCAL session_replication_role=replica")
            target.execute("""UPDATE ingest.publication_metric_snapshot SET views_count=views_count+1
                WHERE id IN (SELECT m.target_bigint FROM migration.legacy_identity_map m
                WHERE m.source_namespace=%s AND m.last_seen_batch_id<>%s AND m.target_type='publication_metric_snapshot')""",
                (current.source_namespace_uuid,current.batch_id))
            report = current.reconcile()
            assert any(row["check"]=="canonical_target_digest" and row["scope"]=="observations" for row in report["mismatches"])
            target.execute("""UPDATE migration.preserved_canonical_fact SET body=jsonb_set(body,'{views}',to_jsonb((body->>'views')::bigint+1))
                WHERE preservation_id=%s AND fact_type='observations'""",(pid,))
            report = current.reconcile()
            assert any(row["scope"].startswith("preserved_ledger:") for row in report["mismatches"])
        assert current.reconcile()["gate"]["status"] == "pass"
