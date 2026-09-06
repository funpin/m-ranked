"""Deterministic CSV representation for target-native observations.

This is explicitly target-generated-v1, not a claim that pre-existing source
bytes existed. The raw cell carries the reversible typed envelope and the exact
sanitized evidence object already durably stored by the collector.
"""
from __future__ import annotations

import json
from psycopg.rows import dict_row
from app.telegram_identity import parse_telegram_external_id
from migration.reverse_sync_format import ReverseSnapshotEnvelope
from .normalize import sanitize_evidence


def persist_native_csv(connection, publication_id, month, snapshot_id, evidence):
    if sanitize_evidence(evidence) != evidence:
        raise ValueError("native export evidence must already be sanitized")
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("""SELECT snapshot.*,account.platform::text AS platform,publication.published_at,
            publication.publication_type FROM ingest.publication_metric_snapshot snapshot
            JOIN ingest.publication publication ON publication.id=snapshot.publication_id
            JOIN catalog.platform_account account ON account.id=publication.primary_account_id
            WHERE snapshot.published_month=%s AND snapshot.id=%s AND snapshot.publication_id=%s""",
            (month,snapshot_id,publication_id))
        row=cursor.fetchone()
        if row is None:
            raise ValueError("native export observation is missing")
        cursor.execute("SELECT external_id,role,public_url FROM ingest.publication_identity WHERE publication_id=%s ORDER BY id",(publication_id,))
        identities=cursor.fetchall()
        cursor.execute("SELECT reaction_key,reaction_count FROM ingest.reaction_breakdown WHERE snapshot_published_month=%s AND snapshot_id=%s",(month,snapshot_id))
        breakdown={item['reaction_key']:item['reaction_count'] for item in cursor.fetchall()}
    telegram=row['platform']=='telegram'
    primary=next(item for item in identities if item['role']=='primary')
    public={'published_at':row['published_at'].isoformat(),'post_type':row['publication_type'],
            'url':primary['public_url'],'external_id':primary['external_id']}
    if telegram:
        members=[parse_telegram_external_id(item['external_id'])[1] for item in identities
                 if item['role'] in ('primary','album_member') and item['external_id'].startswith('m:')]
        if not members:
            raise ValueError("native Telegram publication has no message identity")
        public['telegram_message_id']=min(members)
    envelope=ReverseSnapshotEnvelope(
        legacy_table='reaction_snapshots' if telegram else 'platform_snapshots',publication_id=publication_id,
        published_month=month,snapshot_id=snapshot_id,collected_at=row['collected_at'],quality=row['quality'],
        interval_uncertain=row['interval_uncertain'],synthetic=row['synthetic'],metric_semantics_version=row['metric_semantics_version'],
        capability_version=row['capability_version'],source_fingerprint=row['source_fingerprint'],created_at=row['created_at'],
        metric_quality={metric:row[metric+'_quality'] for metric in ('views','reactions','comments','shares')},
        metric_evidence=dict(row['metric_evidence']),reaction_breakdown=breakdown)
    raw=envelope.as_payload()
    raw['_source_payload']=evidence
    fields={'measured_at':row['observed_at'].isoformat(),'age_seconds':row['age_seconds'],
        'age_hours':str(row['age_seconds']/3600.0),
        'reactions_json':json.dumps(breakdown,ensure_ascii=False,sort_keys=True,separators=(',',':')),
        'raw_json':json.dumps(raw,ensure_ascii=False,sort_keys=True)}
    connection.execute("SELECT ops_and_admin.ensure_publication_legacy_alias(%s)",(publication_id,))
    connection.execute("""INSERT INTO analytics.legacy_native_export_lexeme
        (published_month,snapshot_id,publication_id,fields,public_fields,evidence_sha256)
        VALUES(%s,%s,%s,%s::jsonb,%s::jsonb,%s) ON CONFLICT DO NOTHING""",
        (month,snapshot_id,publication_id,json.dumps(fields,ensure_ascii=False,sort_keys=True),
         json.dumps(public,ensure_ascii=False,sort_keys=True),row['source_fingerprint']))
