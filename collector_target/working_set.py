"""Small, replaceable collector state; canonical history belongs to the receiver.

The buffer preserves the last 24 effective observations (including NULLs and
zeros) and never stores observations older than 31 days. It does not expire a
publication, its identity, its tracking cursor, or an undelivered envelope.
"""
from __future__ import annotations

from typing import Any, Sequence


PUBLICATION_TABLE = "ingest.collector_publication_working_set"
ACCOUNT_TABLE = "ingest.collector_account_working_set"


def store_publications(connection: Any, payload: str) -> list[Any]:
    return connection.execute(
        """WITH raw AS (
               SELECT value,ordinality FROM jsonb_array_elements(%s::jsonb) WITH ORDINALITY
           ), input AS (
               SELECT DISTINCT ON (item.publication_id,item.sampling_bucket) item.*
               FROM raw CROSS JOIN LATERAL jsonb_to_record(raw.value) AS item(
                   publication_id uuid, published_month date,
                   sampling_bucket bigint, observed_at timestamptz,
                   collected_at timestamptz, synthetic boolean,
                   views_count bigint, reactions_count bigint,
                   comments_count bigint, shares_count bigint,
                   source_fingerprint text, semantic_fingerprint text
               )
               ORDER BY item.publication_id,item.sampling_bucket,
                        item.observed_at DESC,item.collected_at DESC,raw.ordinality DESC
           )
           INSERT INTO ingest.collector_publication_working_set AS current (
               publication_id, published_month, sampling_bucket, observed_at,
               collected_at, synthetic, views_count, reactions_count,
               comments_count, shares_count, source_fingerprint, semantic_fingerprint
           ) SELECT publication_id, published_month, sampling_bucket, observed_at,
                    collected_at, synthetic, views_count, reactions_count,
                    comments_count, shares_count, source_fingerprint,
                    decode(semantic_fingerprint,'hex')
               FROM input WHERE observed_at >= transaction_timestamp()-interval '31 days'
           ON CONFLICT (publication_id, sampling_bucket) DO UPDATE SET
               id=DEFAULT, published_month=excluded.published_month,
               observed_at=excluded.observed_at, collected_at=excluded.collected_at,
               synthetic=excluded.synthetic, views_count=excluded.views_count,
               reactions_count=excluded.reactions_count,
               comments_count=excluded.comments_count, shares_count=excluded.shares_count,
               source_fingerprint=excluded.source_fingerprint,
               semantic_fingerprint=excluded.semantic_fingerprint
           WHERE (excluded.observed_at,excluded.collected_at)
                     >= (current.observed_at,current.collected_at)
             AND excluded.source_fingerprint IS DISTINCT FROM current.source_fingerprint
           RETURNING publication_id, published_month, synthetic, sampling_bucket,
                     source_fingerprint, id, 0::bigint AS correction_sequence""",
        (payload,),
    ).fetchall()


def prune(connection: Any, publication_ids: Sequence[Any]) -> None:
    """Bound per-publication state and progress through global expiry by index."""
    if publication_ids:
        connection.execute(
            """DELETE FROM ingest.collector_publication_working_set AS current
                USING (
                    SELECT old.publication_id, old.sampling_bucket
                      FROM unnest(%s::uuid[]) AS scope(publication_id)
                      CROSS JOIN LATERAL (
                          SELECT publication_id, sampling_bucket
                            FROM ingest.collector_publication_working_set
                           WHERE publication_id=scope.publication_id
                           ORDER BY observed_at DESC,id DESC OFFSET 24
                      ) old
                ) expired
                WHERE current.publication_id=expired.publication_id
                  AND current.sampling_bucket=expired.sampling_bucket""",
            (list(dict.fromkeys(publication_ids)),),
        )
    connection.execute(
        """DELETE FROM ingest.collector_publication_working_set current
            USING (
                SELECT publication_id,sampling_bucket
                  FROM ingest.collector_publication_working_set
                 WHERE observed_at < transaction_timestamp()-interval '31 days'
                 ORDER BY observed_at LIMIT 1000 FOR UPDATE SKIP LOCKED
            ) expired
            WHERE current.publication_id=expired.publication_id
              AND current.sampling_bucket=expired.sampling_bucket""",
    )
    connection.execute(
        """DELETE FROM ingest.collector_account_working_set current
            USING (
                SELECT platform_account_id FROM ingest.collector_account_working_set
                 WHERE observed_at < transaction_timestamp()-interval '31 days'
                 ORDER BY observed_at LIMIT 100 FOR UPDATE SKIP LOCKED
            ) expired
            WHERE current.platform_account_id=expired.platform_account_id""",
    )
