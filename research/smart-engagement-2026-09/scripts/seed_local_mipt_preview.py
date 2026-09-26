"""Load the frozen MIPT case into an EMPTY disposable local database.

Only ten nearby September posts and effective *view* observations from
neighbor_study_snapshots.sql are available here. This is a partial research
snapshot, never a production mirror. PostgreSQL must be bound to loopback.
The external number 11340 is inferred from posting order and is not linked.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import uuid
from collections import defaultdict
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb


ACCOUNT_ID = "bd9c960e-1a76-5a72-a6a0-5a301e8e390a"
INSTITUTION_ID = "3685d0b1-ba88-5bf2-9a19-bf6d627e38db"
TARGET_ID = "26782437-05ec-5040-8313-3cb8fbf5eaff"
RUN_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "m-ranked/local-mipt-2026-09-12-15"))
POSTS = {
    "2026-09-11 14:05:02+00": 11340,
    "2026-09-11 15:03:04+00": 11341,
    "2026-09-12 08:30:46+00": 11342,
    "2026-09-14 12:21:08+00": 11343,
    "2026-09-14 13:40:25+00": 11344,
    "2026-09-14 16:32:04+00": 11345,
    "2026-09-15 10:01:16+00": 11346,
    "2026-09-15 11:34:39+00": 11347,
    "2026-09-15 13:00:51+00": 11348,
    "2026-09-15 14:32:59+00": 11349,
}


def read_rows(path: Path) -> dict[str, list[list[str]]]:
    posts: dict[str, list[list[str]]] = defaultdict(list)
    with path.open(newline="") as stream:
        for row in csv.reader(stream):
            if len(row) == 17 and row[1] == ACCOUNT_ID and row[3] in POSTS:
                posts[row[0]].append(row)
    if len(posts) != len(POSTS) or TARGET_ID not in posts:
        raise ValueError("The local CSV lacks one of the ten frozen MIPT posts")
    return posts


def seed(conn: psycopg.Connection, rows: dict[str, list[list[str]]], analysis: dict) -> None:
    if analysis.get("publicationId") != TARGET_ID:
        raise ValueError("Analysis file is not for MIPT №11342")
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '120s'")
            cur.execute("SELECT id::text FROM ingest.publication")
            existing = {row[0] for row in cur.fetchall()}
            if existing - rows.keys():
                raise RuntimeError("The local database contains unrelated posts; refusing to mix snapshots")
            cur.execute(
                "INSERT INTO catalog.institution(id,canonical_name,short_name) "
                "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (INSTITUTION_ID, "Московский физико-технический институт", "МФТИ"),
            )
            cur.execute(
                "INSERT INTO catalog.platform_account"
                "(id,institution_id,platform,canonical_external_id,current_username,"
                "current_title,current_url,access_mode) "
                "VALUES (%s,%s,'telegram','miptru','miptru','МФТИ — Физтех',"
                "'https://t.me/miptru','telegram_web') ON CONFLICT DO NOTHING",
                (ACCOUNT_ID, INSTITUTION_ID),
            )
            cur.executemany(
                "INSERT INTO catalog.legacy_entity_alias(entity_type,legacy_id,target_uuid,legacy_route) "
                "VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                [
                    ("institutions", 11, INSTITUTION_ID, "/institutions/11"),
                    ("channels", 11, ACCOUNT_ID, "/channels/11"),
                ],
            )
            all_observed = [row[8] for group in rows.values() for row in group if row[8]]
            cur.execute(
                "INSERT INTO ingest.collection_run"
                "(id,platform,partition_key,collector_version,started_at,completed_at,"
                "status,correlation_id) VALUES (%s,'telegram','local-snapshot',"
                "'local-research-snapshot/1',%s,%s,'succeeded',gen_random_uuid()) "
                "ON CONFLICT DO NOTHING",
                (RUN_ID, min(all_observed), max(all_observed)),
            )
            for publication_id, observations in rows.items():
                if publication_id in existing:
                    continue
                first = observations[0]
                external = POSTS[first[3]]
                cur.execute(
                    "INSERT INTO ingest.publication"
                    "(id,primary_account_id,published_at,discovered_at,"
                    "first_observation_age_seconds,publication_type,history_completeness) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (publication_id, ACCOUNT_ID, first[3], first[8] or first[3],
                     int(first[6]) if first[6] else None, first[4], "incomplete"),
                )
                legacy_id = 18615 if external == 11342 else 18543 if external == 11341 else 1_000_000 + external
                cur.execute(
                    "INSERT INTO catalog.legacy_entity_alias"
                    "(entity_type,legacy_id,target_uuid,legacy_route) "
                    "VALUES ('posts',%s,%s,%s)",
                    (legacy_id, publication_id, f"/posts/{legacy_id}"),
                )
                cur.execute(
                    "INSERT INTO ingest.publication_identity"
                    "(publication_id,platform_account_id,external_id,role,public_url) "
                    "VALUES (%s,%s,%s,'primary',%s)",
                    (publication_id, ACCOUNT_ID, f"m:{external}",
                     None if external == 11340 else f"https://t.me/miptru/{external}"),
                )
            count = 0
            for publication_id, observations in rows.items():
                if publication_id in existing:
                    continue
                for row in observations:
                    if not row[8]:
                        continue
                    fingerprint = hashlib.sha256(
                        "|".join((publication_id, row[10], row[8], row[11])).encode()
                    ).hexdigest()
                    cur.execute(
                        "INSERT INTO ingest.publication_metric_snapshot"
                        "(published_month,publication_id,collection_run_id,observed_at,"
                        "age_seconds,sampling_bucket,views_count,quality,interval_uncertain,"
                        "synthetic,source_fingerprint,views_quality,reactions_quality,"
                        "comments_quality,shares_quality,metric_evidence) "
                        "VALUES ('2026-09-01',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                        "'unknown','unknown','unknown',%s)",
                        (publication_id, RUN_ID, row[8], int(row[9]), int(row[10]),
                         int(row[11]) if row[11] else None, row[12], row[13] == "t",
                         row[14] == "t", fingerprint, row[12],
                         Jsonb({"localSnapshot": "2026-09-12/15", "originalRunId": row[16],
                                "originalCorrectionSequence": int(row[15])})),
                    )
                    count += 1
            target_rows = rows[TARGET_ID]
            cur.execute(
                "INSERT INTO analytics.post_anomaly_state"
                "(publication_id,published_at,level,signals,quality,analyzed_at,"
                "analyzed_points,last_point_observed_at,detector_versions,next_due_at,"
                "frozen,review_status,lag_seconds) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),true,%s,%s) "
                "ON CONFLICT DO NOTHING",
                (TARGET_ID, target_rows[0][3], analysis["level"],
                 Jsonb(analysis["signals"]), Jsonb(analysis["quality"]),
                 analysis["analyzedAt"], len(target_rows),
                 max(row[8] for row in target_rows if row[8]),
                 Jsonb(analysis["detectorVersions"]), analysis["reviewStatus"],
                 analysis["lagSeconds"]),
            )
            cur.execute(
                "INSERT INTO analytics.dataset_revision(cause,correlation_id,metadata) "
                "VALUES ('migration',gen_random_uuid(),%s) RETURNING id",
                (Jsonb({"localPreview": "MIPT-2026-09-12/15", "viewSnapshots": count}),),
            )
            revision = cur.fetchone()[0]
    print(f"Local snapshot: {len(rows)} posts, {count} newly inserted view observations, revision {revision}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--analysis", required=True, type=Path)
    parser.add_argument("--port", type=int, default=55432)
    args = parser.parse_args()
    if args.port not in range(1, 65536):
        parser.error("invalid local port")
    rows = read_rows(args.csv)
    analysis = json.loads(args.analysis.read_text())
    # Hard-coded loopback and disposable DB: never accept a production DSN.
    with psycopg.connect(host="127.0.0.1", port=args.port,
                         dbname="mranked_review10", user="mranked_bootstrap",
                         password="local-demo-bootstrap") as conn:
        seed(conn, rows, analysis)


if __name__ == "__main__":
    main()
