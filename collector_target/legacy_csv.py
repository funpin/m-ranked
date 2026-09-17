"""Deterministic CSV representation for target-native observations.

This is explicitly target-generated-v1, not a claim that pre-existing source
bytes existed. The raw cell carries the reversible typed envelope and the exact
sanitized evidence object already durably stored by the collector.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Iterable

from psycopg.rows import dict_row
from collector_runtime.telegram_identity import parse_telegram_external_id
from .normalize import sanitize_evidence


def persist_native_csv(connection, publication_id, month, snapshot_id, evidence):
    persist_native_csv_batch(
        connection, [(publication_id, month, snapshot_id, evidence)],
    )


def persist_native_csv_batch(
    connection: Any,
    observations: Iterable[tuple[Any, Any, int, Any]],
) -> None:
    observations = list(observations)
    if not observations:
        return
    for _publication_id, _month, _snapshot_id, evidence in observations:
        if sanitize_evidence(evidence) != evidence:
            raise ValueError("native export evidence must already be sanitized")
    input_rows = [
        {
            "publication_id": publication_id,
            "published_month": month,
            "snapshot_id": snapshot_id,
        }
        for publication_id, month, snapshot_id, _evidence in observations
    ]
    evidence_by_key = {
        (str(publication_id), month, int(snapshot_id)): evidence
        for publication_id, month, snapshot_id, evidence in observations
    }
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("""WITH input AS (
            SELECT * FROM jsonb_to_recordset(%s::jsonb) AS item(
                publication_id uuid, published_month date, snapshot_id bigint
            )
        )
        SELECT snapshot.*,account.platform::text AS platform,publication.published_at,
            publication.publication_type FROM ingest.publication_metric_snapshot_resolved snapshot
            JOIN ingest.publication publication ON publication.id=snapshot.publication_id
            JOIN catalog.platform_account account ON account.id=publication.primary_account_id
            JOIN input ON input.published_month=snapshot.published_month
              AND input.snapshot_id=snapshot.id
              AND input.publication_id=snapshot.publication_id""",
            (json.dumps(input_rows, default=str),))
        rows = cursor.fetchall()
        cursor.execute("""SELECT publication_id,external_id,role,public_url
            FROM ingest.publication_identity
            WHERE publication_id=ANY(%s::uuid[]) ORDER BY publication_id,id""",
            ([row[0] for row in observations],))
        identities_by_publication = defaultdict(list)
        for identity in cursor.fetchall():
            identities_by_publication[str(identity['publication_id'])].append(identity)
        cursor.execute("""WITH input AS (
            SELECT * FROM jsonb_to_recordset(%s::jsonb) AS item(
                published_month date, snapshot_id bigint
            )
        )
        SELECT breakdown.snapshot_published_month,breakdown.snapshot_id,
               breakdown.reaction_key,breakdown.reaction_count
          FROM ingest.reaction_breakdown breakdown
          JOIN input ON input.published_month=breakdown.snapshot_published_month
            AND input.snapshot_id=breakdown.snapshot_id""",
            (json.dumps(input_rows, default=str),))
        breakdown_by_snapshot = defaultdict(dict)
        for reaction in cursor.fetchall():
            breakdown_by_snapshot[
                (reaction['snapshot_published_month'], reaction['snapshot_id'])
            ][reaction['reaction_key']] = reaction['reaction_count']
    if len(rows) != len(observations):
        raise ValueError("native export observation is missing")

    lexemes = []
    for row in rows:
        publication_id = row['publication_id']
        month = row['published_month']
        snapshot_id = row['id']
        identities = identities_by_publication[str(publication_id)]
        breakdown = breakdown_by_snapshot[(month, snapshot_id)]
        telegram = row['platform'] == 'telegram'
        primary = next(item for item in identities if item['role'] == 'primary')
        public = {
            'published_at': row['published_at'].isoformat(),
            'post_type': row['publication_type'],
            'url': primary['public_url'],
            'external_id': primary['external_id'],
        }
        if telegram:
            members = [
                parse_telegram_external_id(item['external_id'])[1]
                for item in identities
                if item['role'] in ('primary', 'album_member')
                and item['external_id'].startswith('m:')
            ]
            if not members:
                raise ValueError("native Telegram publication has no message identity")
            public['telegram_message_id'] = min(members)
        raw = {
            '_mranked_reverse_sync': {
                'version': 2,
                'legacy_table': 'reaction_snapshots' if telegram else 'platform_snapshots',
                'publication_id': str(publication_id),
                'published_month': month.isoformat(),
                'snapshot_id': snapshot_id,
                'collected_at': row['collected_at'].isoformat(),
                'quality': row['quality'],
                'interval_uncertain': row['interval_uncertain'],
                'synthetic': row['synthetic'],
                'metric_semantics_version': row['metric_semantics_version'],
                'capability_version': row['capability_version'],
                'source_fingerprint': row['source_fingerprint'],
                'created_at': row['created_at'].isoformat(),
                'metric_quality': {
                    metric: row[metric + '_quality']
                    for metric in ('views', 'reactions', 'comments', 'shares')
                },
                'metric_evidence': dict(row['metric_evidence']),
            },
            'reaction_breakdown': breakdown,
            '_source_payload': evidence_by_key[
                (str(publication_id), month, int(snapshot_id))
            ],
        }
        fields = {
            'measured_at': row['observed_at'].isoformat(),
            'age_seconds': row['age_seconds'],
            'age_hours': str(row['age_seconds'] / 3600.0),
            'reactions_json': json.dumps(
                breakdown, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
            ),
            'raw_json': json.dumps(raw, ensure_ascii=False, sort_keys=True),
        }
        lexemes.append({
            'published_month': month,
            'snapshot_id': snapshot_id,
            'publication_id': publication_id,
            'fields': fields,
            'public_fields': public,
            'evidence_sha256': row['source_fingerprint'],
        })
    connection.execute(
        "SELECT ops_and_admin.ensure_publication_legacy_alias(publication_id) "
        "FROM unnest(%s::uuid[]) AS publications(publication_id)",
        (list(dict.fromkeys(row[0] for row in observations)),),
    )
    connection.execute("""INSERT INTO analytics.legacy_native_export_lexeme
        (published_month,snapshot_id,publication_id,fields,public_fields,evidence_sha256)
        SELECT item.published_month,item.snapshot_id,item.publication_id,
               item.fields,item.public_fields,item.evidence_sha256
          FROM jsonb_to_recordset(%s::jsonb) AS item(
              published_month date,snapshot_id bigint,publication_id uuid,
              fields jsonb,public_fields jsonb,evidence_sha256 text
          ) ON CONFLICT DO NOTHING""",
        (json.dumps(lexemes, ensure_ascii=False, sort_keys=True, default=str),),
    )
