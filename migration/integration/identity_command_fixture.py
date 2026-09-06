"""Original-source fixture around actual Java catalog commands and reverse sync."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import argparse
import json
import hashlib
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from collector_target.repository import PostgresCollectorRepository
from collector_target.evidence import ImmutableEvidenceStore
from collector_target.model import Platform, CollectionContext, RawCollectionBatch, RawAccountObservation, ObservationQuality
from collector_target.normalize import CanonicalNormalizer

from app.database import Database
from migration.bridge.model import BridgeOptions
from migration.bridge.source import LegacySource, create_online_backup
from migration.bridge.service import BridgeService
from migration.bridge.target import PostgresTarget
from migration.bridge.identity_history_reconciliation import verify_identity_history, IdentityHistorySourceError
from operations.reverse_sync.postgres import PostgresReverseSource
from operations.reverse_sync.sqlite_target import LegacySqliteTarget
from operations.reverse_sync.journal import ReverseSyncJournal
from operations.reverse_sync.service import ReverseSyncService


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("phase",choices=("prepare","collector-gap","verify"))
    parser.add_argument("--directory",type=Path,required=True)
    args=parser.parse_args()
    root=args.directory
    source=root/"first-final.sqlite"
    reverse=root/"reverse.sqlite"
    namespace="original-admin-identity-inputs"
    dsn=os.environ["BRIDGE_DATABASE_URL"]
    def collector():
        repository=PostgresCollectorRepository(os.environ["COLLECTOR_DATABASE_URL"],evidence_store=ImmutableEvidenceStore(root/"provider-raw"))
        account=next(iter(repository.enabled_accounts(Platform.MAX,"all")))
        return repository,account
    def input_batch(repository,account,at,native,username=None,title=None,url=None):
        context=CollectionContext.create(Platform.MAX,"identity-command-fixture","identity-v29",at,at)
        repository.start_run(context)
        assert repository.begin_account(context,account,at)
        raw=RawCollectionBatch(account,RawAccountObservation(at,at,321,"321",ObservationQuality.EXACT,
            username=username,title=title,url=url,native_external_id=native,source={}),(),"fixture-original-provider","29")
        return context,CanonicalNormalizer().normalize(raw,context)
    def canonical_state(connection):
        # Actual values, not retained digests, prove the rejected transaction
        # cannot commit its earlier presentation update or any metric fact.
        tables=("catalog.platform_account","catalog.account_identity_history","catalog.account_external_identity","ingest.account_metric_snapshot","analytics.dataset_revision")
        return {table:connection.execute("SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb) FROM "+table+" t").fetchone()[0] for table in tables}
    def reverse_service():
        return ReverseSyncService(PostgresReverseSource(dsn,namespace),LegacySqliteTarget(reverse,namespace,min_free_bytes=0),ReverseSyncJournal(root/"journal.sqlite"))
    if args.phase=="prepare":
        live=root/"live.sqlite"
        database=Database(live);database.migrate()
        institution=database.add_institution("Identity input university","Identity")
        database.add_platform_account(institution,"max","history_input",username="before_input",title="Before",url="http://max.ru/history_input",access_mode="user_session")
        with closing(sqlite3.connect(live)) as connection,connection:
            connection.execute("UPDATE platform_accounts SET native_id=NULL,added_at='2026-01-01T00:00:00+00:00'")
            connection.execute("UPDATE institutions SET created_at='2026-01-01T00:00:00+00:00'")
        create_online_backup(live,source)
        with PostgresTarget(dsn) as target:
            service=BridgeService(BridgeOptions(source,namespace),LegacySource(source),target,snapshot_kind="s_final")
            _,report=service.run()
            assert report["gate"]["status"]=="pass",report["mismatches"]
        create_online_backup(source,reverse)
        with closing(sqlite3.connect(reverse)) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
        assert reverse_service().start(rollback_window_hours=24,operator="java-command-fixture",ticket="local-identity-receipts")["status"]=="active"
        repository,account=collector()
        at=datetime.now(timezone.utc)+timedelta(hours=1)
        context,batch=input_batch(repository,account,at,"-19000","future_input","Future source title","https://max.ru/history_input")
        assert repository.persist_account_batch(batch).revision_id is not None
        repository.finish_run(context,at)
        with PostgresTarget(dsn) as target:
            row=target.connection.execute("SELECT id,institution_id,row_version FROM catalog.platform_account").fetchone()
            (root/"controls.json").write_text(json.dumps({"accountId":str(row[0]),"institutionId":str(row[1]),"rowVersion":row[2]}))
        return
    if args.phase=="collector-gap":
        repository,account=collector()
        with PostgresTarget(dsn) as target:
            closed=target.connection.execute("SELECT max(valid_to) FROM catalog.account_external_identity WHERE platform_account_id=%s",(account.id,)).fetchone()[0]
            before=canonical_state(target.connection)
            for at in (closed-timedelta(microseconds=1),closed):
                context,batch=input_batch(repository,account,at,"-20004","must_rollback","Must roll back",None)
                try:
                    repository.persist_account_batch(batch)
                except RuntimeError as error:
                    assert str(error)=="account native identity time collision",str(error)
                else:
                    raise AssertionError("stale native identity was accepted")
                repository.record_account_failure(context,account,at,"IDENTITY_TIME_COLLISION")
                repository.finish_run(context,at)
                failure=target.connection.execute("SELECT status,sanitized_error_code FROM ingest.collection_account_result WHERE collection_run_id=%s AND platform_account_id=%s",(context.run_id,account.id)).fetchone()
                assert failure==("failed","IDENTITY_TIME_COLLISION"),failure
                assert canonical_state(target.connection)==before
            retry_at=closed+timedelta(microseconds=1)
            context,batch=input_batch(repository,account,retry_at,"-20004")
            accepted=repository.persist_account_batch(batch)
            assert accepted.revision_id is not None
            repository.finish_run(context,retry_at)
            row=target.connection.execute("SELECT external_id,valid_from FROM catalog.account_external_identity WHERE platform_account_id=%s AND valid_to IS NULL",(account.id,)).fetchone()
            assert row==("-20004",retry_at),row
            assert target.connection.execute("SELECT count(*) FROM ingest.account_metric_snapshot WHERE platform_account_id=%s",(account.id,)).fetchone()[0]==2
            (root/"collector-gap.json").write_text(json.dumps({"status":"pass","olderAndEqualRejected":True,"canonicalValuesUnchangedAfterReject":True,
                "failureRecorded":True,"retryAcceptedOriginalObservedAt":retry_at.isoformat(),"closedBoundary":closed.isoformat(),"acceptedRevision":accepted.revision_id},default=str,indent=2))
        return
    with PostgresTarget(dsn) as target:
        original=BridgeService(BridgeOptions(source,namespace),LegacySource(source),target,snapshot_kind="s_final")
        proof=verify_identity_history(original)
        assert proof["status"]=="pass",proof
    service=reverse_service()
    assert service.drain(operator="java-command-fixture",ticket="local-identity-receipts")["status"]=="drained"
    assert service.verify()["status"]=="verified"
    assert service.stop()["status"]=="stopped"
    second=root/"second-final.sqlite"
    create_online_backup(reverse,second)
    with PostgresTarget(dsn) as target:
        options=BridgeOptions(second,namespace,historical_source_paths=(source,))
        final=BridgeService(options,LegacySource(second),target,snapshot_kind="s_final")
        stats,report=final.run()
        assert report["gate"]["status"]=="pass",report["mismatches"]
        # A repeat cutover is a fresh CLI/service invocation with fresh counters.
        replay=BridgeService(options,LegacySource(second),target,snapshot_kind="s_final")
        again,repeat=replay.run()
        assert repeat["gate"]["status"]=="pass",repeat["mismatches"]
        assert again.batch_id==stats.batch_id and again.rows_written==0,(str(again.batch_id),str(stats.batch_id),again.rows_written)
        receipts=report["identity_history_verification"]["identitySourceReceipts"]
        assert len([row for row in receipts if row["kind"]=="admin"])>=5
        original_root=Path(os.environ["MRANKED_IDENTITY_RECEIPT_DIR"])
        restored_root=root/"restored-identity-receipts"
        inventory=[]
        for receipt in receipts:
            relative=Path(receipt["kind"])/(receipt["sha256"]+".json") if receipt["kind"]=="admin" else Path("collector")/receipt["platform"]/(receipt["sha256"]+".json")
            original_bytes=(original_root/relative).read_bytes()
            assert hashlib.sha256(original_bytes).hexdigest()==receipt["sha256"]
            destination=restored_root/relative
            destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            with destination.open("xb") as stream:
                stream.write(original_bytes);stream.flush();os.fchmod(stream.fileno(),0o400);os.fsync(stream.fileno())
            descriptor=os.open(destination.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(descriptor)
            finally:os.close(descriptor)
            inventory.append({"relativePath":str(relative),"sha256":receipt["sha256"],"bytes":len(original_bytes)})
        unavailable_root=original_root.with_name("original-receipts-unavailable")
        original_root.rename(unavailable_root)
        os.environ["MRANKED_IDENTITY_RECEIPT_DIR"]=str(restored_root)
        try:
            restored=final.reconcile()
            assert restored["gate"]["status"]=="pass",restored["mismatches"]
            assert restored["identity_history_verification"]==report["identity_history_verification"]
            path=restored_root/inventory[0]["relativePath"]
            original_bytes=path.read_bytes();path.unlink()
            missing=final.reconcile()
            assert missing["gate"]["status"]=="fail" and missing["identity_history_verification"]["status"]=="fail"
            try:
                path.write_bytes(b'{"body":{"nativeId":"forged"}}');path.chmod(0o400)
                forged=final.reconcile()
                assert forged["gate"]["status"]=="fail" and forged["identity_history_verification"]["status"]=="fail"
            finally:
                path.unlink();path.write_bytes(original_bytes);path.chmod(0o400)
            assert final.reconcile()["gate"]["status"]=="pass"
        finally:
            os.environ["MRANKED_IDENTITY_RECEIPT_DIR"]=str(original_root)
            unavailable_root.rename(original_root)
        (root/"proof.json").write_text(json.dumps({"status":"pass","secondSFinal":report["gate"],"repeat":repeat["gate"],
            "history":report["identity_history_verification"],"receiptRestore":{"status":"pass","originalRootUnavailable":True,"inventory":inventory},
            "futureObservationClearReenroll":"pass","collectorGap":json.loads((root/"collector-gap.json").read_text()),
            "missingReceipt":"fail-closed","forgedReceipt":"fail-closed"},default=str,indent=2))


if __name__=="__main__":
    main()
