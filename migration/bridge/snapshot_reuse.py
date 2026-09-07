"""Reuse byte-identical immutable snapshots during catch-up, in one batch.

Only lineage/evidence is advanced. Changed, missing, or incompletely preserved
rows fall back to the normal importer. Canonical reconciliation remains required.
The caller owns the same transaction as the stream checkpoint.
"""
import json

from .model import row_hash


def reuse_snapshots(target, namespace, batch_id, stream, rows, publication_ids, contexts):
    if stream not in {'platform_snapshots', 'reaction_snapshots'}:
        raise ValueError('Only immutable snapshot streams can be reused')
    inputs = []
    for row, publication_id in zip(rows, publication_ids, strict=True):
        published_at, _ = contexts[publication_id]
        required = ['legacy_derived_metrics'] if stream == 'reaction_snapshots' else []
        raw_kind = 'raw_state_json' if stream == 'reaction_snapshots' else 'raw_json'
        if row.get(raw_kind):
            required.append(raw_kind)
        inputs.append({'pk': str(row['id']),
                       'digest': row_hash({k: v for k, v in row.items() if not k.startswith('__')}),
                       'publication': str(publication_id),
                       'month': published_at.date().replace(day=1).isoformat(),
                       'bucket': int(row['measurement_bucket']), 'required': required})
    eligible = target.fetchall('''
        WITH input AS (SELECT * FROM jsonb_to_recordset(%s::jsonb)
            AS i(pk text,digest text,publication uuid,month date,bucket bigint,required jsonb))
        SELECT m.source_pk
          FROM input i
          JOIN migration.legacy_identity_map m
            ON m.source_namespace=%s AND m.source_table=%s AND m.source_pk=i.pk
           AND m.target_type='publication_metric_snapshot' AND m.source_row_hash=i.digest
          JOIN ingest.publication_metric_snapshot s
            ON s.published_month=i.month AND s.id=m.target_bigint
           AND s.publication_id=i.publication AND s.sampling_bucket=i.bucket
          JOIN migration.legacy_export_lexeme l
            ON l.source_namespace=m.source_namespace AND l.source_table=m.source_table
           AND l.source_pk=m.source_pk AND l.source_row_hash=m.source_row_hash
         WHERE NOT EXISTS (
             SELECT 1 FROM jsonb_array_elements_text(i.required) kind
              WHERE NOT EXISTS (
                  SELECT 1 FROM migration.legacy_evidence e
                   WHERE e.batch_id=m.last_seen_batch_id AND e.source_table=m.source_table
                     AND e.source_pk=m.source_pk AND e.source_row_hash=m.source_row_hash
                     AND e.evidence_kind=kind.value AND e.sanitized))
        FOR UPDATE OF m
        ''', (json.dumps(inputs), namespace, stream))
    keys = [r[0] for r in eligible]
    if not keys:
        return set()
    target.execute('''
        INSERT INTO migration.legacy_evidence
            (batch_id,source_table,source_pk,source_row_hash,evidence_kind,evidence,sanitized)
        SELECT %s,e.source_table,e.source_pk,e.source_row_hash,e.evidence_kind,e.evidence,e.sanitized
          FROM migration.legacy_identity_map m
          JOIN migration.legacy_evidence e
            ON e.batch_id=m.last_seen_batch_id AND e.source_table=m.source_table
           AND e.source_pk=m.source_pk AND e.source_row_hash=m.source_row_hash
         WHERE m.source_namespace=%s AND m.source_table=%s AND m.source_pk=ANY(%s)
           AND m.target_type='publication_metric_snapshot' AND m.last_seen_batch_id<>%s
        ON CONFLICT (batch_id,source_table,source_pk,evidence_kind,source_row_hash) DO NOTHING
        ''', (batch_id, namespace, stream, keys, batch_id))
    # The ordinary immutable-lineage trigger still runs for every changed tip.
    target.execute('''UPDATE migration.legacy_identity_map SET last_seen_batch_id=%s
        WHERE source_namespace=%s AND source_table=%s AND source_pk=ANY(%s)
          AND target_type='publication_metric_snapshot' AND last_seen_batch_id<>%s''',
        (batch_id, namespace, stream, keys, batch_id))
    return set(keys)
