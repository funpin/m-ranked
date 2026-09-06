"""Disposable DB archive gates for the original HTTP CSV byte fixture."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil

import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
import pyarrow.parquet as pq
from operations.cold_archive.model import MonthRange
from operations.cold_archive.parquet import verify_archive
from operations.cold_archive.service import ColdArchiveService
from operations.cold_archive.legacy_csv_restore import restore_legacy_csv


def maintenance_dsn(dsn):
    return make_conninfo(**(conninfo_to_dict(dsn)|{"user":"maintenance","password":os.environ["MRANKED_LEGACY_CSV_MAINTENANCE_PASSWORD"]}))


def archive(destination:Path,dsn:str):
    service=ColdArchiveService(maintenance_dsn(dsn),destination/"objects",batch_size=2,min_free_bytes=0)
    with psycopg.connect(dsn,autocommit=True) as connection:
        months=[row[0] for row in connection.execute("SELECT DISTINCT published_month FROM ingest.publication_metric_snapshot WHERE published_month<date_trunc('month',now()-interval '1 year')::date ORDER BY published_month")]
        assert months
        results=[]
        for month in months:
            result=service.archive(MonthRange(month))
            # A separate local test authority attests a fully read-back test
            # object. This is a fixture, not evidence of a production failure domain.
            copy=destination/"off-primary-test-copy"/result.object_path.name
            copy.parent.mkdir(exist_ok=True);shutil.copyfile(result.object_path,copy)
            checked=verify_archive(copy,expected_sha256=result.verification.sha256,expected_row_count=result.verification.row_count)
            assert checked.canonical_sha256==result.verification.canonical_sha256
            connection.execute("""INSERT INTO ops_and_admin.archive_object_attestation(manifest_id,object_uri,object_version,sha256,canonical_sha256,
                row_count,failure_domain,immutable_until,verifier_subject) VALUES(%s,%s,'fixture-v1',%s,%s,%s,'disposable-test-copy',now()+interval '1 day','local-test-bootstrap')""",
                (result.manifest_id,'s3://disposable-test-only/'+result.object_path.name,result.verification.sha256,result.verification.canonical_sha256,result.verification.row_count))
            if connection.execute("SELECT to_regclass('analytics.legacy_csv_snapshot_fact')").fetchone()[0]:
                # An extra/mismatched derived row cannot authorize DROP. Rollback
                # this deliberate owner-only corruption before the real operation.
                try:
                    with connection.transaction():
                        connection.execute("SELECT ops_and_admin.begin_publication_archive(%s)",(month,))
                        connection.execute("""INSERT INTO analytics.legacy_csv_snapshot_fact
                            SELECT published_month,9223372036854775806,publication_id,observed_at,age_seconds,9223372036854775806,
                                views_count,reactions_count,comments_count,shares_count,0
                            FROM analytics.legacy_csv_snapshot_fact WHERE published_month=%s LIMIT 1""",(month,))
                        connection.execute("SELECT ops_and_admin.drop_publication_metric_partition(%s,%s)",(month,result.manifest_id))
                    raise AssertionError("Bad CSV fact coverage authorized DROP")
                except psycopg.errors.CheckViolation: pass
                assert connection.execute("SELECT to_regclass(%s)",('ingest.publication_metric_snapshot_'+month.strftime('%Y_%m'),)).fetchone()[0] is not None
            service.archive(MonthRange(month),drop_hot_partition=True,drop_confirmation="DROP_HOT_PARTITION")
            assert connection.execute("SELECT to_regclass(%s)",('ingest.publication_metric_snapshot_'+month.strftime('%Y_%m'),)).fetchone()[0] is None
            results.append(result.as_dict())
        # Native observations must have crossed the actual DROP boundary too;
        # merely keeping newly collected rows hot would not exercise that gate.
        assert connection.execute("SELECT count(*) FROM ingest.publication_metric_snapshot").fetchone()[0]==0
        revision=connection.execute("SELECT max(dataset_revision_id) FROM analytics.projection_state").fetchone()[0]
        connection.execute("SELECT analytics.rebuild_core_projections(%s)",(revision,))
        fact_table=connection.execute("SELECT to_regclass('analytics.legacy_csv_snapshot_fact')").fetchone()[0]
        metrics={}
        if fact_table:
            metrics={"columns":connection.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='analytics' AND table_name='legacy_csv_snapshot_fact'").fetchone()[0],
                "facts":connection.execute("SELECT count(*) FROM analytics.legacy_csv_snapshot_fact").fetchone()[0],
                "tableAndIndexesBytes":connection.execute("SELECT pg_total_relation_size('analytics.legacy_csv_snapshot_fact')").fetchone()[0]}
            metrics["averageTupleBytes"]=float(connection.execute("SELECT avg(pg_column_size(fact)) FROM analytics.legacy_csv_snapshot_fact fact").fetchone()[0])
            metrics["correctionEvents"]=connection.execute("SELECT count(*) FROM analytics.legacy_csv_snapshot_fact WHERE correction_sequence>0").fetchone()[0]
            assert metrics["correctionEvents"]>0
            connection.execute("SET enable_seqscan=off")
            metrics["indexPlan"]=connection.execute("EXPLAIN (FORMAT JSON) SELECT * FROM analytics.legacy_csv_snapshot_fact_active WHERE published_month=%s",(months[0],)).fetchone()[0]
        report={"status":"dropped","objects":results,"storage":metrics}
        (destination/"archive-fixture.json").write_text(json.dumps(report,default=str,indent=2))
        return report


def restore(destination:Path,dsn:str):
    maintenance=maintenance_dsn(dsn)
    report=json.loads((destination/"archive-fixture.json").read_text())
    first=report["objects"][0];manifest=first["manifestId"];path=Path(first["objectPath"])
    with psycopg.connect(dsn,autocommit=True) as connection:
        before=connection.execute("SELECT count(*) FROM analytics.legacy_csv_snapshot_fact").fetchone()[0]
    records=next(pq.ParquetFile(path).iter_batches(batch_size=1,columns=["canonical_record"])).column(0).to_pylist()
    try:
        with psycopg.connect(maintenance) as connection:
            connection.execute("SELECT analytics.restore_legacy_csv_archive(%s,%s::text[],false)",(manifest,records))
        raise AssertionError("Partial restore transaction committed")
    except psycopg.errors.CheckViolation: pass
    try:
        with psycopg.connect(maintenance) as connection:
            changed=False
            for batch in pq.ParquetFile(path).iter_batches(batch_size=2,columns=["canonical_record"]):
                forged=batch.column(0).to_pylist()
                if not changed:
                    body=json.loads(forged[0]);body["views_count"]=(body.get("views_count") or 0)+999
                    forged[0]=json.dumps(body);changed=True
                connection.execute("SELECT analytics.restore_legacy_csv_archive(%s,%s::text[],false)",(manifest,forged))
            connection.execute("SELECT analytics.restore_legacy_csv_archive(%s,'{}'::text[],true)",(manifest,))
        raise AssertionError("Forged full canonical archive accepted")
    except psycopg.errors.CheckViolation: pass
    original=path.read_bytes() # tiny fixture corruption only; production importer never reads a whole object.
    path.write_bytes(original+b"corrupt")
    try:
        try: restore_legacy_csv(maintenance,destination/"objects",batch_size=2)
        except ValueError: pass
        else: raise AssertionError("Corrupt archive accepted")
    finally: path.write_bytes(original)
    with psycopg.connect(dsn,autocommit=True) as connection:
        assert connection.execute("SELECT count(*) FROM analytics.legacy_csv_snapshot_fact").fetchone()[0]==before
        assert connection.execute("SELECT count(*) FROM analytics.legacy_csv_restore_state").fetchone()[0]==0
    result=restore_legacy_csv(maintenance,destination/"objects",batch_size=2)
    assert result["rawRowsRestored"]==0
    with psycopg.connect(dsn,autocommit=True) as connection:
        for item in report["objects"]:
            assert connection.execute("SELECT count(*) FROM ingest.publication_metric_snapshot WHERE published_month=%s",(item["partitionStart"],)).fetchone()[0]==0
        assert connection.execute("SELECT count(*) FROM analytics.legacy_export_row WHERE blocked_reason='COLD_ARCHIVE_RESTORE_REQUIRED'").fetchone()[0]==0
    (destination/"archive-restore.json").write_text(json.dumps(result,indent=2));return result


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,required=True);parser.add_argument("--restore",action="store_true")
    args=parser.parse_args();print(json.dumps((restore if args.restore else archive)(args.output.resolve(),os.environ["MRANKED_LEGACY_CSV_DSN"]),default=str))
