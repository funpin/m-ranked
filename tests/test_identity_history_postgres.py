"""Closed-history corruption bypasses guards only inside disposable rollbacks."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import os
import json
import sqlite3

import pytest

from app.database import Database
from migration.bridge.identity_history_reconciliation import IdentityHistorySourceError, verify_identity_history
from migration.bridge.model import BridgeOptions
from migration.bridge.service import BridgeService
from migration.bridge.source import LegacySource, create_online_backup, sha256_file
from migration.bridge.target import PostgresTarget

ADMIN_DSN = os.getenv("MRANKED_TEST_POSTGRES_ADMIN_DSN")


@pytest.mark.skipif(not ADMIN_DSN,reason="requires disposable PostgreSQL admin DSN")
def test_complete_identity_history_is_independent_and_replayable(tmp_path: Path,monkeypatch):
    live = tmp_path/"live.sqlite"
    database = Database(live)
    database.migrate()
    institution = database.add_institution("History oracle university","History")
    database.add_platform_account(institution,"vk","club100",username="first",title="First",url="http://example.org/first",access_mode="official_api")
    with closing(sqlite3.connect(live)) as connection,connection:
        connection.execute("UPDATE platform_accounts SET native_id='100',added_at='2026-01-01T00:00:00+00:00'")
        connection.execute("UPDATE institutions SET created_at='2026-01-01T00:00:00+00:00'")
    def freeze(name,at):
        path = tmp_path/name
        create_online_backup(live,path)
        os.utime(path,(at,at))
        return path
    initial = freeze("s0.sqlite",1785585600)
    def bridge(path,target):
        return BridgeService(BridgeOptions(path,"identity-history-test",batch_size=1),LegacySource(path),target,snapshot_kind="catch_up")
    with PostgresTarget(str(ADMIN_DSN)) as target:
        first = bridge(initial,target)
        assert first.run()[1]["gate"]["status"] == "pass"
        baseline = verify_identity_history(first)
        assert baseline["status"] == "pass",baseline
        with pytest.raises(IdentityHistorySourceError,match="HISTORY_SOURCE_ACCOUNT_LIMIT"):
            verify_identity_history(first,max_accounts=0)
        with pytest.raises(IdentityHistorySourceError,match="HISTORY_EVENT_LIMIT"):
            verify_identity_history(first,max_events=0)
        with pytest.raises(IdentityHistorySourceError,match="HISTORY_OPERATION_LIMIT"):
            verify_identity_history(first,max_account_operations=0)
        with pytest.raises(IdentityHistorySourceError,match="HISTORY_TRANSITION_LIMIT"):
            verify_identity_history(first,max_transitions=0)
        # Even an unrelated source change requires its prior artifact: absence
        # of closed target rows is not independent proof of unchanged history.
        with closing(sqlite3.connect(live)) as connection,connection:
            connection.execute("UPDATE institutions SET short_name='Unrelated update'")
        unchanged = freeze("unchanged-identity.sqlite",1785585601)
        same = bridge(unchanged,target)
        assert same.run()[1]["gate"]["status"] == "pass"
        with pytest.raises(IdentityHistorySourceError,match="HISTORY_PRIOR_SOURCE_REQUIRED"):
            verify_identity_history(same)
        assert verify_identity_history(same,historical_source_paths=(initial,))["status"] == "pass"
        with closing(sqlite3.connect(live)) as connection,connection:
            connection.execute("UPDATE platform_accounts SET username='second',title='Second',url='https://example.org/second',native_id='200'")
        changed = freeze("catch-up.sqlite",1785585602)
        latest = bridge(changed,target)
        assert latest.run()[1]["gate"]["status"] == "pass"
        artifacts = (initial,unchanged)
        latest.options = replace(latest.options,verify_identity_history=True,historical_source_paths=artifacts)
        proof = verify_identity_history(latest,historical_source_paths=artifacts)
        assert proof["status"] == "pass",proof
        with pytest.raises(IdentityHistorySourceError,match="HISTORY_PRIOR_SOURCE_REQUIRED"):
            verify_identity_history(latest)
        # All canonical fields, closed interval edges, and whole missing rows
        # are compared to actual original source values, without a rebuild.
        faults = {
            "closed_username":"UPDATE catalog.account_identity_history SET username='corrupt' WHERE valid_to IS NOT NULL",
            "closed_title":"UPDATE catalog.account_identity_history SET title='corrupt' WHERE valid_to IS NOT NULL",
            "closed_url":"UPDATE catalog.account_identity_history SET url='https://example.org/corrupt' WHERE valid_to IS NOT NULL",
            "closed_from":"UPDATE catalog.account_identity_history SET valid_from=valid_from+interval '1 second' WHERE valid_to IS NOT NULL",
            "closed_to":"UPDATE catalog.account_identity_history SET valid_to=valid_to-interval '1 second' WHERE valid_to IS NOT NULL",
            "closed_native":"UPDATE catalog.account_external_identity SET external_id='corrupt' WHERE valid_to IS NOT NULL",
            "closed_namespace":"UPDATE catalog.account_external_identity SET identity_namespace='vk:wrong' WHERE valid_to IS NOT NULL",
            "closed_native_from":"UPDATE catalog.account_external_identity SET valid_from=valid_from+interval '1 second' WHERE valid_to IS NOT NULL",
            "closed_native_to":"UPDATE catalog.account_external_identity SET valid_to=valid_to-interval '1 second' WHERE valid_to IS NOT NULL",
            "closed_verified":"UPDATE catalog.account_external_identity SET verified_at=verified_at+interval '1 second' WHERE valid_to IS NOT NULL",
            "closed_provenance":"UPDATE catalog.account_identity_history SET source_run_id=(SELECT source_run_id FROM catalog.account_identity_history WHERE valid_to IS NULL) WHERE valid_to IS NOT NULL",
            "missing_presentation":"DELETE FROM catalog.account_identity_history WHERE valid_to IS NOT NULL",
            "missing_native":"DELETE FROM catalog.account_external_identity WHERE valid_to IS NOT NULL",
            "extra_closed":"""INSERT INTO catalog.account_identity_history(platform_account_id,username,title,url,valid_from,valid_to,source_run_id)
                SELECT platform_account_id,username,title,url,'2025-01-01Z','2025-01-02Z',source_run_id
                FROM catalog.account_identity_history WHERE valid_to IS NULL""",
        }
        for name,sql in faults.items():
            with target.connection.transaction(force_rollback=True):
                target.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                target.execute("SET LOCAL session_replication_role=replica")
                assert target.execute(sql).rowcount == 1,name
                result = verify_identity_history(latest,historical_source_paths=artifacts)
                assert result["status"] == "fail",(name,result)
                overall = latest.reconcile()
                assert overall["gate"]["status"] == "fail",name
                assert any(check["check"] == "canonical_identity_history" and check["critical"] for check in overall["mismatches"]),name
            assert verify_identity_history(latest,historical_source_paths=artifacts)["status"] == "pass",name
        with target.connection.transaction(force_rollback=True):
            target.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            target.execute("SET LOCAL session_replication_role=replica")
            for table in ("account_identity_history","account_external_identity"):
                assert target.execute(f"DELETE FROM catalog.{table} WHERE valid_to IS NOT NULL").rowcount == 1
                target.execute(f"UPDATE catalog.{table} SET valid_from='2026-01-01Z',source_run_id=%s",(first.runs["vk"],))
            target.execute("UPDATE catalog.account_external_identity SET verified_at=%s",(first.source_snapshot_at,))
            with pytest.raises(IdentityHistorySourceError,match="HISTORY_PRIOR_SOURCE_REQUIRED"):
                verify_identity_history(latest)
            assert verify_identity_history(latest,historical_source_paths=artifacts)["status"] == "fail"
            assert latest.reconcile()["gate"]["status"] == "fail"
        with target.connection.transaction(force_rollback=True):
            target.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            target.execute("SET LOCAL session_replication_role=replica")
            target.execute("UPDATE catalog.account_identity_history SET source_run_id=NULL WHERE valid_to IS NOT NULL")
            with pytest.raises(IdentityHistorySourceError,match="HISTORY_NON_MIGRATION_AUTHORITY_REQUIRED"):
                verify_identity_history(latest,historical_source_paths=artifacts)
        # Clearing and reenrollment is a real gap, and replaying an old accepted
        # file appends transitions even though its batch UUID was already used.
        with closing(sqlite3.connect(live)) as connection,connection:
            connection.execute("UPDATE platform_accounts SET native_id=NULL")
        cleared = freeze("cleared.sqlite",1785585603)
        empty = bridge(cleared,target)
        assert empty.run()[1]["gate"]["status"] == "pass"
        assert verify_identity_history(empty,historical_source_paths=(*artifacts,changed))["status"] == "pass"
        restored = bridge(initial,target)
        assert restored.run()[1]["gate"]["status"] == "pass"
        proof = verify_identity_history(restored,historical_source_paths=(unchanged,changed,cleared))
        assert proof["status"] == "pass",proof
        assert proof["checks"][0]["expected"]["rows"] == 3
        assert proof["checks"][1]["expected"]["rows"] == 3
        assert proof["sourceUnchanged"] and proof["sourceSha256"] == sha256_file(initial)
        final = BridgeService(replace(restored.options,historical_source_paths=(unchanged,changed,cleared)),
            LegacySource(initial),target,snapshot_kind="s_final")
        _,report = final.run()
        assert report["gate"]["status"] == "pass",report["mismatches"]
        assert report["identity_history_verification"]["status"] == "pass"
        target.execute("SET ROLE migration_bridge")
        try:
            assert final.reconcile()["gate"]["status"] == "pass"
        finally:
            target.execute("RESET ROLE")
        final.options = replace(final.options,historical_source_paths=())
        missing = final.reconcile()
        assert missing["gate"]["status"] == "fail"
        assert missing["identity_history_verification"]["errorCode"] == "HISTORY_PRIOR_SOURCE_REQUIRED"
        # Accepted collector source receipts outlive provider raw retention.
        # Reusing a stale account reference cannot restore old fallback fields.
        from datetime import datetime,timedelta,timezone
        from collector_target.repository import PostgresCollectorRepository
        from collector_target.evidence import ImmutableEvidenceStore
        from collector_target.model import Platform,CollectionContext,RawCollectionBatch,RawAccountObservation,ObservationQuality
        from collector_target.normalize import CanonicalNormalizer
        monkeypatch.setenv("MRANKED_IDENTITY_RECEIPT_DIR",str(tmp_path/"identity-receipts"))
        repository=PostgresCollectorRepository(str(ADMIN_DSN),evidence_store=ImmutableEvidenceStore(tmp_path/"provider-raw"))
        account=next(iter(repository.enabled_accounts(Platform.VK,"all")))
        observed=datetime.now(timezone.utc)
        for index in range(2):
            at=observed+timedelta(seconds=index)
            context=CollectionContext.create(Platform.VK,"identity-input-test","identity-v1",at,at)
            repository.start_run(context);assert repository.begin_account(context,account,at)
            raw=RawCollectionBatch(account,RawAccountObservation(at,at,100,"100",ObservationQuality.EXACT,
                username="collector_name" if index==0 else None,title="Collector title" if index==0 else "Second title",
                url="HTTPS://example.org/collector" if index==0 else "http://ignored.example.org/",native_external_id="600" if index==0 else None,
                source={"api_token":"must-not-enter-retained-receipt"}),(),"fixture-original-provider","1")
            assert repository.persist_account_batch(CanonicalNormalizer().normalize(raw,context)).revision_id is not None
            repository.finish_run(context,at)
        assert target.connection.execute("SELECT current_username,current_title,current_url FROM catalog.platform_account WHERE id=%s",(account.id,)).fetchone()==("collector_name","Second title","HTTPS://example.org/collector")
        final.options=replace(final.options,historical_source_paths=(unchanged,changed,cleared))
        collector_proof=verify_identity_history(final,historical_source_paths=final.options.historical_source_paths)
        assert collector_proof["status"]=="pass",collector_proof
        assert len(collector_proof["identitySourceReceipts"])==2
        assert repository.evidence_store.purge_expired(target.connection,now=observed+timedelta(days=8))==2
        assert not list((tmp_path/"provider-raw").glob("*.json"))
        assert verify_identity_history(final,historical_source_paths=final.options.historical_source_paths)["status"]=="pass"
        row=collector_proof["identitySourceReceipts"][0]
        receipt=tmp_path/"identity-receipts"/"collector"/"vk"/(row["sha256"]+".json")
        original=receipt.read_bytes()
        assert b"must-not-enter-retained-receipt" not in original and b"subscriber" not in original
        receipt.unlink()
        with pytest.raises(IdentityHistorySourceError,match="RECEIPT_MISSING"):
            verify_identity_history(final,historical_source_paths=final.options.historical_source_paths)
        receipt.write_bytes(b'{"nativeId":"forged"}');receipt.chmod(0o400)
        with pytest.raises(IdentityHistorySourceError,match="HASH_MISMATCH"):
            verify_identity_history(final,historical_source_paths=final.options.historical_source_paths)
        receipt.unlink();receipt.write_bytes(original);receipt.chmod(0o400)
        assert verify_identity_history(final,historical_source_paths=final.options.historical_source_paths)["status"]=="pass"
        if output := os.environ.get("MRANKED_HISTORY_ORACLE_REPORT"):
            Path(output).write_text(json.dumps({"status":"pass","proof":report["identity_history_verification"],
                "tamperCases":list(faults),"eachTamperOverallNoGo":True,"migrationBridgeRole":"pass",
                "clearReenrollOldBatchReplay":"pass","missingPrior":"fail-closed",
                "compoundDeletedClosedAndBackdatedCurrent":"fail-closed with and without prior artifacts",
                "nonMigrationAuthority":"fail-closed","requiredSFinal":"pass","boundedLimits":"pass",
                "collectorOriginalReceipt":collector_proof,"collectorRawRetentionExpired":"pass",
                "collectorMissingForgedReceipt":"fail-closed","collectorStaleReferenceFallback":"pass"},indent=2))
