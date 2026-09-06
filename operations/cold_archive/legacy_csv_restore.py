"""Verified cold Parquet → derived CSV facts. Never restores raw observations."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import unquote, urlparse
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
import pyarrow.parquet as pq

from .parquet import verify_archive, sha256_file


def restore_legacy_csv(dsn: str, archive_root: Path, *, manifest_ids: tuple[UUID,...] = (),
        batch_size: int = 64, max_seconds: int = 900) -> dict:
    if not 1<=batch_size<=1000 or not 1<=max_seconds<=3600: raise ValueError("invalid restore bounds")
    root=archive_root.resolve(strict=True)
    if not root.is_dir(): raise ValueError("archive root must be a directory")
    started=time.monotonic()
    def deadline():
        if time.monotonic()-started>max_seconds: raise TimeoutError("archive CSV restore duration exceeded")
    with psycopg.connect(dsn,autocommit=True,row_factory=dict_row) as connection:
        manifests=connection.execute("""SELECT archive.* FROM ops_and_admin.archive_manifest archive
            WHERE dataset_type='publication_metric_snapshot' AND hot_dropped_at IS NOT NULL
              AND (%s::uuid[]='{}'::uuid[] OR id=ANY(%s::uuid[]))
            ORDER BY partition_start,id LIMIT 2001""",(list(manifest_ids),list(manifest_ids))).fetchall()
        if len(manifests)>2000: raise ValueError("restore manifest bound exceeded")
        if manifest_ids and {str(row["id"]) for row in manifests}!={str(value) for value in manifest_ids}:
            raise ValueError("requested cold manifest is missing")
        objects=[]
        for manifest in manifests:
            deadline()
            uri=urlparse(manifest["object_uri"])
            candidate=Path(unquote(uri.path)) if uri.scheme=="file" and uri.netloc in ("","localhost") else root/(manifest["sha256"]+".parquet")
            path=candidate.resolve(strict=True);path.relative_to(root)
            if not path.is_file(): raise ValueError("archive object is not a regular file")
            verified=verify_archive(path,expected_row_count=manifest["row_count"],expected_sha256=manifest["sha256"],sample_size=batch_size,on_batch=deadline)
            if (verified.canonical_sha256!=manifest["canonical_sha256"] or
                verified.min_observed_at!=manifest["min_observed_at"] or verified.max_observed_at!=manifest["max_observed_at"]):
                raise ValueError("archive canonical manifest mismatch")
            objects.append((manifest,path))
        if not objects: return {"status":"no_cold_objects","manifests":0,"rows":0}
        total=0
        with connection.transaction():
            connection.execute("SELECT set_config('statement_timeout',%s,true)",(str(max_seconds)+'s',))
            anchor=connection.execute("SELECT analytics.begin_legacy_csv_restore() AS committed_at").fetchone()
            if anchor is None: raise ValueError("a published dataset revision is required")
            for manifest,path in objects:
                count=0
                for batch in pq.ParquetFile(path).iter_batches(batch_size=batch_size,columns=["canonical_record"]):
                    deadline()
                    # Arrays and Arrow batches remain bounded; a whole object is never materialized.
                    records=batch.column(0).to_pylist()
                    connection.execute("SELECT analytics.restore_legacy_csv_archive(%s,%s::text[],false)",(manifest["id"],records))
                    count+=len(records)
                if sha256_file(path,on_chunk=deadline)!=manifest["sha256"]: raise ValueError("archive object changed during restore")
                finished=connection.execute("SELECT analytics.restore_legacy_csv_archive(%s,'{}'::text[],true) AS rows",(manifest["id"],)).fetchone()["rows"]
                if finished!=count: raise ValueError("archive restore count mismatch")
                total+=count
            revision=connection.execute("""INSERT INTO analytics.dataset_revision(cause,correlation_id,committed_at,metadata)
                VALUES('configuration',gen_random_uuid(),%s,%s::jsonb) RETURNING id""",
                (anchor["committed_at"],json.dumps({"operation":"verifiedLegacyCsvArchiveRestore","manifests":[str(row[0]["id"]) for row in objects]}))).fetchone()["id"]
            connection.execute("SELECT analytics.rebuild_core_projections(%s)",(revision,))
        return {"status":"restored","manifests":len(objects),"rows":total,"datasetRevision":revision,
            "rawRowsRestored":0,"batchSize":batch_size}


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn-env",default="MRANKED_CSV_RESTORE_DSN")
    parser.add_argument("--archive-root",type=Path,required=True)
    parser.add_argument("--manifest",type=UUID,action="append",default=[])
    parser.add_argument("--batch-size",type=int,default=64)
    parser.add_argument("--max-seconds",type=int,default=900)
    arguments=parser.parse_args(argv)
    try:
        result=restore_legacy_csv(os.environ[arguments.dsn_env],arguments.archive_root,
            manifest_ids=tuple(arguments.manifest),batch_size=arguments.batch_size,max_seconds=arguments.max_seconds)
    except Exception as error:
        print(json.dumps({"status":"failed","errorCode":type(error).__name__}),file=sys.stderr)
        return 1
    print(json.dumps(result));return 0


if __name__=="__main__": raise SystemExit(main())
