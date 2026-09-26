#!/usr/bin/env python3
"""Compare a frozen S1 month to S2; output attestation input, never delete.

Credentials in SOURCE_DATABASE_URL/TARGET_DATABASE_URL, never command args.
Uses one ordered streaming cursor per host, bounded work_mem and statement time.
Both snapshots and reactions are covered; local serial IDs are normalized away.
"""
import argparse
from datetime import date
import hashlib
import json
import os
import psycopg

QUERY = """SELECT jsonb_build_object(
 'snapshot',to_jsonb(s)-ARRAY['id','created_at','ingested_xid','metric_evidence_id','supersedes_snapshot_id','metric_evidence'],
 'evidence',coalesce(d.payload,s.metric_evidence,'{}'::jsonb),
 'supersedes',CASE WHEN prior.id IS NULL THEN NULL ELSE jsonb_build_array(prior.publication_id,prior.sampling_bucket,prior.source_fingerprint) END,
 'reactions',coalesce((SELECT jsonb_object_agg(r.reaction_key,r.reaction_count ORDER BY r.reaction_key)
   FROM ingest.reaction_breakdown r WHERE r.snapshot_published_month=s.published_month AND r.snapshot_id=s.id),'{}'::jsonb)
)::text,
 (SELECT count(*) FROM ingest.reaction_breakdown r WHERE r.snapshot_published_month=s.published_month AND r.snapshot_id=s.id),
 (s.metric_evidence_id IS NOT NULL AND d.id IS NULL) OR (s.supersedes_snapshot_id IS NOT NULL AND prior.id IS NULL)
 FROM ingest.publication_metric_snapshot s
 LEFT JOIN ingest.metric_evidence_dictionary d ON d.id=s.metric_evidence_id
 LEFT JOIN ingest.publication_metric_snapshot prior ON prior.published_month=s.published_month AND prior.id=s.supersedes_snapshot_id
 WHERE s.published_month=%s
 ORDER BY s.publication_id,s.sampling_bucket,s.source_fingerprint COLLATE "C"
"""


def digest(connection,month):
    sha=hashlib.sha256(); snapshots=reactions=0
    with connection.cursor(name='coverage') as cursor:
        cursor.itersize=1000
        cursor.execute(QUERY,(month,))
        for payload, count, incomplete in cursor:
            if incomplete:
                raise RuntimeError('unresolved evidence or correction lineage; no coverage')
            sha.update(payload.encode());sha.update(b'\n')
            snapshots+=1;reactions+=count
    return sha.hexdigest(),snapshots,reactions


def main():
    parser=argparse.ArgumentParser();parser.add_argument('month',type=date.fromisoformat)
    args=parser.parse_args()
    if args.month.day!=1:parser.error('canonical first-of-month required')
    with psycopg.connect(os.environ['SOURCE_DATABASE_URL']) as source, psycopg.connect(os.environ['TARGET_DATABASE_URL']) as target:
        for connection in [source,target]:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            connection.execute("SET LOCAL statement_timeout='120s'")
            connection.execute("SET LOCAL lock_timeout='1s'")
            connection.execute("SET LOCAL work_mem='8MB'")
            connection.execute("SET LOCAL timezone='UTC'")
        source_identity=source.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0]
        identity=target.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0]
        if source_identity == identity:
            raise SystemExit('source and target must be independent database clusters')
        fence=source.execute("SELECT changed_at FROM ops_and_admin.publication_partition_fence WHERE published_month=%s AND state='retiring'",(args.month,)).fetchone()
        if not fence:raise SystemExit('source month must first be fenced by approved operation')
        left=digest(source,args.month);right=digest(target,args.month)
        if left!=right:raise SystemExit('month coverage mismatch; no attestation')
        print(json.dumps(dict(published_month=str(args.month),fence_at=fence[0].isoformat(),
          source_sha256=left[0],target_sha256=right[0],snapshot_rows=left[1],reaction_rows=left[2],
          destination_system_identifier=identity,comparison_version=1)))

if __name__=='__main__':main()
