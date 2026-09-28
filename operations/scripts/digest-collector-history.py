#!/usr/bin/env python3
"""Digest a frozen collector month, preserving complete facts and reactions.

Version 2 sorts SHA256 hashes of normalized records, then hashes that stream.
Local IDs are normalized, order and target IDs do not affect comparison. Sorting
uses 64 MiB RAM and a bounded on-host work directory, not a second database.
This command never installs a certificate, fences writers, or deletes facts.
"""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile


def digest(connection, month: date, cutoff: datetime, work_dir: Path, *, exclude_keys: list[dict] | None = None, lineage_equivalences: list[dict] | None = None) -> dict:
    compare_path=Path(__file__).with_name('compare-retention-month.py')
    spec=importlib.util.spec_from_file_location('month_query',compare_path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    query=module.QUERY[:module.QUERY.rindex(' ORDER BY')]
    query=query.replace('WHERE s.published_month=%s', 'WHERE s.published_month=%s AND s.observed_at<%s')
    # A fixed month also prunes the joined partition trees at planning time.
    # The equality through s otherwise opens every historic reaction/parent
    # partition repeatedly for each fetched observation on a small collector.
    literal = "DATE '" + month.isoformat() + "'"
    query=query.replace('prior.published_month=s.published_month', 'prior.published_month='+literal)
    query=query.replace('r.snapshot_published_month=s.published_month', 'r.snapshot_published_month='+literal)
    params=(month,cutoff)
    if exclude_keys:
        if len(exclude_keys)>1000:
            raise ValueError('too many individually verified target extras')
        query+=''' AND NOT EXISTS (
          SELECT 1 FROM jsonb_to_recordset(%s::jsonb) AS extra(
            publication_id uuid,sampling_bucket bigint,source_fingerprint text)
          WHERE (extra.publication_id,extra.sampling_bucket,extra.source_fingerprint)
            =(s.publication_id,s.sampling_bucket,s.source_fingerprint))'''
        params+=(json.dumps(exclude_keys),)
    if lineage_equivalences:
        query=query.replace(' FROM ingest.publication_metric_snapshot s',
                            ', s.source_fingerprint FROM ingest.publication_metric_snapshot s')
    return _digest_normalized(connection, query, params, work_dir, lineage_equivalences=lineage_equivalences)


def digest_auxiliary(connection, cutoff: datetime, work_dir: Path, kind: str) -> dict:
    """Compare the frozen account history or availability log independently."""
    if kind == 'accounts':
        query="""SELECT jsonb_build_object(
          'snapshot',to_jsonb(s)-ARRAY['id','created_at','supersedes_snapshot_id'],
          'supersedes',CASE WHEN prior.id IS NULL THEN NULL ELSE
             jsonb_build_array(prior.platform_account_id,prior.observed_at,prior.source_fingerprint) END
          )::text,0,(s.supersedes_snapshot_id IS NOT NULL AND prior.id IS NULL)
          FROM ingest.account_metric_snapshot s
          LEFT JOIN ingest.account_metric_snapshot prior ON prior.id=s.supersedes_snapshot_id
          WHERE s.observed_at<%s"""
    elif kind == 'availability':
        query="""SELECT (to_jsonb(s)-'created_at')::text,0,false
          FROM ingest.publication_availability_event s WHERE observed_at<%s"""
    else:
        raise ValueError('unknown auxiliary history')
    return _digest_normalized(connection, query, (cutoff,), work_dir)


def _lineage_equivalences(connection, pairs: list[dict]) -> dict:
    """Allow only individually reviewed local correction ordering differences.

    Every fact field, timestamp, provenance, evidence and reaction must match.
    The actual target record is checked again during the full streaming read.
    This never changes target data or ignores correction metadata globally.
    """
    if len(pairs)>1000:
        raise ValueError('too many individually reviewed lineage equivalences')
    result={}
    for pair in pairs:
        source,target=pair['source'],pair['target']
        def fact(record):
            normalized=dict(record)
            normalized.pop('supersedes',None)
            normalized['snapshot']={key:value for key,value in record['snapshot'].items()
                                    if key not in {'correction_sequence','correction_reason'}}
            return normalized
        if fact(source)!=fact(target):
            raise ValueError('lineage equivalence changes canonical facts')
        item=source['snapshot']
        key=(item['publication_id'],item['sampling_bucket'],item['source_fingerprint'])
        if key in result:
            raise ValueError('duplicate lineage equivalence')
        fingerprint=connection.execute("SELECT encode(sha256(convert_to(%s::jsonb::text,'UTF8')),'hex')",
                                       (json.dumps(source),)).fetchone()[0]
        result[key]=(target,fingerprint)
    return result


def _digest_normalized(connection, query: str, params: tuple, work_dir: Path, *, lineage_equivalences: list[dict] | None = None) -> dict:
    equivalences=_lineage_equivalences(connection,lineage_equivalences or [])
    extra=""
    columns="payload,reactions,incomplete"
    if equivalences:
        extra=",CASE WHEN %s::jsonb ? source_fingerprint THEN payload ELSE NULL END"
        columns+=",source_fingerprint"
        params=(json.dumps({key[2]:True for key in equivalences}),)+params
    query="SELECT encode(sha256(convert_to(payload,'UTF8')),'hex'),reactions,incomplete"+extra+" FROM ("+query+") AS normalized("+columns+")"
    sha=hashlib.sha256();snapshots=reactions=0
    checked=set()
    work_dir.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='coverage-',dir=work_dir) as temporary:
        work=Path(temporary); hashes=work/'hashes'
        with hashes.open('w') as output, connection.cursor(name='coverage_v2') as cursor:
            cursor.itersize=1000
            cursor.execute(query,params)
            for row in cursor:
                fingerprint,count,incomplete=row[:3]
                if incomplete:
                    raise RuntimeError('unresolved evidence or correction lineage; no coverage')
                if equivalences and row[3] is not None:
                    actual=json.loads(row[3]);item=actual['snapshot']
                    key=(item['publication_id'],item['sampling_bucket'],item['source_fingerprint'])
                    if key in equivalences:
                        expected,replacement=equivalences[key]
                        if actual!=expected or key in checked:
                            raise RuntimeError('reviewed target lineage changed; no coverage')
                        fingerprint=replacement;checked.add(key)
                output.write(fingerprint+'\n');snapshots+=1;reactions+=count
        if checked!=set(equivalences):
            raise RuntimeError('reviewed target lineage record missing; no coverage')
        with subprocess.Popen(['sort','-S','64M','-T',str(work),str(hashes)],stdout=subprocess.PIPE,env={'LC_ALL':'C','PATH':'/usr/bin:/bin'}) as sorter:
            for block in iter(lambda:sorter.stdout.read(1024*1024),b''):
                sha.update(block)
            if sorter.wait()!=0:
                raise RuntimeError('coverage sort failed')
    return {'sha256':sha.hexdigest(),'snapshot_rows':snapshots,'reaction_rows':reactions,'comparison_version':2}
