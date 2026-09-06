"""Independent, disk-bounded reconciliation of canonical source and target facts.

The identity map may select the migration's scope; no stored source hash or
migration evidence is used as a target value. Digests are ordered by natural key
and canonical row bytes, so compensating counter changes cannot cancel out.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import sqlite3
import tempfile
from typing import Any

from app.telegram_identity import telegram_message_external_id, telegram_publication_external_id
from .normalize import as_utc, completeness, parse_json
from migration.reverse_sync_format import parse_reverse_snapshot_envelope, parse_reverse_publication_envelope

METRICS = ("views", "reactions", "comments", "shares")


def canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("canonical timestamp must have a timezone")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (Decimal, float)):
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError("non-finite canonical number")
        return format(number.normalize(), "f")
    if isinstance(value, Mapping):
        return {str(k): canonical_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical_value(v) for v in value]
    return value


def encode(value: Any) -> str:
    return json.dumps(canonical_value(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def compare_rows(expected: Iterable[tuple[Any, Mapping[str, Any]]],
                 actual: Iterable[tuple[Any, Mapping[str, Any]]]) -> dict[str, Any]:
    # SQLite supplies a bounded external sort even for millions of observations.
    with tempfile.TemporaryDirectory(prefix="mranked-reconcile-") as directory:
        db = sqlite3.connect(f"{directory}/digests.sqlite")
        try:
            db.execute("PRAGMA cache_size=-2048")
            db.execute("CREATE TABLE row_digest(side INTEGER,key TEXT,body TEXT)")
            for side, rows in enumerate((expected, actual)):
                db.executemany("INSERT INTO row_digest VALUES(?,?,?)",
                               ((side, encode(key), encode(row)) for key, row in rows))
                db.commit()
            db.execute("CREATE INDEX digest_order ON row_digest(side,key,body)")
            summaries = []
            for side in (0, 1):
                digest = hashlib.sha256()
                count = 0
                for key, body in db.execute(
                    "SELECT key,body FROM row_digest WHERE side=? ORDER BY key,body", (side,)
                ):
                    digest.update((key + "\t" + body + "\n").encode("utf-8"))
                    count += 1
                distinct = db.execute("SELECT count(DISTINCT key) FROM row_digest WHERE side=?", (side,)).fetchone()[0]
                summaries.append({"rows": count, "distinctKeys": distinct,
                                  "duplicateKeys": count-distinct, "sha256": digest.hexdigest()})
            differences = list(db.execute("""SELECT key FROM row_digest GROUP BY key
                HAVING sum(CASE WHEN side=0 THEN 1 ELSE -1 END)<>0
                    OR count(DISTINCT body)>1 ORDER BY key LIMIT 10"""))
            return {"expected": summaries[0], "actual": summaries[1],
                    "changedKeysSample": [json.loads(row[0]) for row in differences]}
        finally:
            db.close()


def _time(value: Any) -> datetime | None:
    return as_utc(value) if value else None


def _url(value: Any) -> str | None:
    return str(value).strip() if value and str(value).strip().startswith("https://") else None


def source_publications(service):
    for table in ("posts", "platform_posts"):
        for row in service._all_rows(table):
            telegram = table == "posts"
            channel = service.channel_rows[int(row["channel_id"])] if telegram else None
            yield (table, int(row["id"])), {
                "accountTable": "channels" if telegram else "platform_accounts",
                "accountId": int(row["channel_id"] if telegram else row["platform_account_id"]),
                "publishedAt": _time(row["published_at"]), "discoveredAt": _time(row["discovered_at"]),
                "type": row["post_type"], "repost": bool(row.get("is_repost")),
                "completeness": completeness(row), "syntheticAllowed": bool(row.get("baseline_from_publication")),
                "deletedAt": _time(row.get("deleted_at")),
                "album": row.get("telegram_grouped_id") is not None,
                "ambiguous": bool(row.get("ambiguous_album_reactions")),
                "joint": bool(row.get("is_joint")), "additionalAuthors": int(row.get("additional_author_count") or 0),
            }


def source_identities(service):
    for table in ("posts", "platform_posts"):
        for row in service._all_rows(table):
            telegram = table == "posts"
            envelope = None if telegram else parse_reverse_publication_envelope(row.get("raw_json"))
            if envelope:
                for identity in envelope.identities:
                    yield (table, int(row["id"]), identity["external_id"]), {
                        "role": identity["role"], "sourceExternalId": identity.get("source_external_id"),
                        "url": identity.get("public_url")}
                continue
            external = telegram_publication_external_id(row["telegram_message_id"], row.get("telegram_grouped_id")) if telegram else str(row["external_id"])
            url = f"https://t.me/{service.channel_rows[int(row['channel_id'])]['username']}/{row['telegram_message_id']}" if telegram else _url(row.get("url"))
            yield (table, int(row["id"]), external), {"role": "primary", "sourceExternalId": None if telegram else row.get("source_external_id"), "url": url}
    with service.source.connect() as connection:
        for row in connection.execute("""SELECT m.*,p.channel_id,p.telegram_grouped_id,p.telegram_message_id AS primary_message
            FROM post_messages m JOIN posts p ON p.id=m.post_id ORDER BY m.post_id,m.telegram_message_id"""):
            if row["telegram_grouped_id"] is None and row["telegram_message_id"] == row["primary_message"]:
                continue
            external = telegram_message_external_id(row["telegram_message_id"])
            url = f"https://t.me/{service.channel_rows[int(row['channel_id'])]['username']}/{row['telegram_message_id']}"
            yield ("posts", int(row["post_id"]), external), {"role": "album_member" if row["telegram_grouped_id"] is not None else "primary", "sourceExternalId": None, "url": url}


def source_snapshots(service, *, reactions_only=False):
    for table in ("reaction_snapshots", "platform_snapshots"):
        for row in service._all_rows(table):
            tg = table == "reaction_snapshots"
            key = ("posts" if tg else "platform_posts", int(row["post_id"] if tg else row["platform_post_id"]), int(row["measurement_bucket"]))
            raw = parse_json(row.get("raw_state_json") if tg else row.get("raw_json"), fallback={})
            envelope = parse_reverse_snapshot_envelope(raw)
            breakdown = parse_json(row.get("reactions_json"), fallback={}) if tg else raw.get("reaction_breakdown", {}) if isinstance(raw, Mapping) else {}
            if reactions_only:
                for name, count in (breakdown or {}).items():
                    yield (*key, str(name)), {"count": int(count)}
                continue
            yield key, {"observedAt": _time(row["measured_at"]), "ageSeconds": int(row["age_seconds"]),
                "views": row.get("views_count"), "reactions": row.get("total_reactions" if tg else "reactions_count"),
                "comments": row.get("comments_count"), "shares": None if tg else row.get("shares_count"),
                "synthetic": envelope.synthetic if envelope else bool(row.get("synthetic")),
                "uncertain": envelope.interval_uncertain if envelope else bool(row.get("interval_uncertain")),
                "quality": envelope.quality if envelope else "unknown",
                "metricQuality": (envelope.metric_quality if envelope else None) or {metric:(envelope.quality if envelope else "unknown") for metric in METRICS},
                "metricEvidence": envelope.metric_evidence if envelope else {}}


def source_ratings(service):
    for table in ("institutions", "channels"):
        for row in service._all_rows(table):
            categories = (("telegram", "m_rating_tg"),) if table == "channels" else (("social", "m_rating_social"), ("telegram", "m_rating_tg"), ("vk", "m_rating_vk"), ("max", "m_rating_max"), ("rutube", "m_rating_rutube"))
            for category, prefix in categories:
                rank, score = row.get(prefix+"_rank"), row.get(prefix+"_score")
                if rank is None and score is None:
                    continue
                yield (table, str(row["id"]), category), {"institutionId": int(row["institution_id"] if table == "channels" else row["id"]),
                    "period": row.get("m_rating_period") or "legacy-unknown", "rank": rank,
                    "score": Decimal(str(score)) if score is not None else None,
                    "fetchedAt": _time(row.get("m_rating_measured_at")) or service.source_snapshot_at}


# Only identity keys select scope. All bodies below come from actual canonical tables.
PUBLICATIONS = """
WITH owned AS (SELECT DISTINCT target_uuid FROM migration.legacy_identity_map
 WHERE source_namespace=%s AND target_type='platform_account')
SELECT a.entity_type::text,a.legacy_id,p.*,aa.entity_type::text AS account_table,aa.legacy_id AS account_legacy_id
FROM ingest.publication p JOIN owned ON owned.target_uuid=p.primary_account_id
LEFT JOIN catalog.legacy_entity_alias a ON a.target_uuid=p.id AND a.entity_type IN ('posts','platform_posts')
LEFT JOIN catalog.legacy_entity_alias aa ON aa.target_uuid=p.primary_account_id
 AND aa.entity_type=CASE WHEN a.entity_type='posts' THEN 'channels' ELSE 'platform_accounts' END
"""
SNAPSHOTS = """
WITH owned AS (SELECT DISTINCT target_uuid FROM migration.legacy_identity_map
 WHERE source_namespace=%s AND target_type='platform_account')
SELECT a.entity_type::text,a.legacy_id,s.* FROM ingest.publication_metric_snapshot_active s
JOIN ingest.publication p ON p.id=s.publication_id JOIN owned ON owned.target_uuid=p.primary_account_id
LEFT JOIN catalog.legacy_entity_alias a ON a.target_uuid=p.id AND a.entity_type IN ('posts','platform_posts')
"""


def _query(target, sql, params):
    from psycopg.rows import dict_row
    with target.connection.cursor(name="independent_reconciliation", row_factory=dict_row) as cursor:
        cursor.execute(sql, params)
        yield from cursor


def _publication_key(row):
    return (row["entity_type"], int(row["legacy_id"]) if row["legacy_id"] is not None else str(row["id"]))


def target_publications(service):
    for row in _query(service.target, PUBLICATIONS, (service.source_namespace_uuid,)):
        flags = row["quality_flags"]
        yield _publication_key(row), {"accountTable": row["account_table"], "accountId": row["account_legacy_id"],
            "publishedAt": row["published_at"], "discoveredAt": row["discovered_at"], "type": row["publication_type"],
            "repost": row["is_repost"], "completeness": row["history_completeness"], "syntheticAllowed": row["synthetic_baseline_allowed"],
            "deletedAt": row["deleted_at"], "album": row["content_group_id"] is not None,
            "ambiguous": bool(flags.get("ambiguous_album_reactions", flags.get("ambiguous_reactions", False))),
            "joint": bool(flags.get("joint_post", flags.get("legacy_is_joint", False))),
            "additionalAuthors": int(flags.get("additional_author_count", flags.get("legacy_additional_author_count", 0)) or 0)}


def target_identities(service):
    sql = "SELECT p.entity_type,p.legacy_id,i.* FROM ("+PUBLICATIONS+") p JOIN ingest.publication_identity i ON i.publication_id=p.id"
    for row in _query(service.target, sql, (service.source_namespace_uuid,)):
        yield (*_publication_key(row), row["external_id"]), {"role": row["role"], "sourceExternalId": row["source_external_id"], "url": row["public_url"]}


def target_snapshots(service, *, reactions_only=False):
    sql = "SELECT s.entity_type,s.legacy_id,s.sampling_bucket,r.* FROM ("+SNAPSHOTS+") s JOIN ingest.reaction_breakdown r ON r.snapshot_id=s.id AND r.snapshot_published_month=s.published_month" if reactions_only else SNAPSHOTS
    for row in _query(service.target, sql, (service.source_namespace_uuid,)):
        key = (row["entity_type"], row["legacy_id"], row["sampling_bucket"])
        if reactions_only:
            yield (*key, row["reaction_key"]), {"count": row["reaction_count"]}
        else:
            yield key, {"observedAt": row["observed_at"], "ageSeconds": row["age_seconds"],
                **{metric: row[metric+"_count"] for metric in METRICS}, "synthetic": row["synthetic"],
                "uncertain": row["interval_uncertain"], "quality": row["quality"],
                "metricQuality": {metric:row[metric+"_quality"] for metric in METRICS},
                "metricEvidence": row["metric_evidence"]}


def target_ratings(service):
    sql = """SELECT m.source_table,m.source_pk,r.*,a.legacy_id FROM migration.legacy_identity_map m
        JOIN rating.official_rating_observation r ON r.id=m.target_uuid
        LEFT JOIN catalog.legacy_entity_alias a ON a.target_uuid=r.institution_id AND a.entity_type='institutions'
        WHERE m.source_namespace=%s AND (m.last_seen_batch_id=%s OR """+PRESERVED_MAPPING+""")
          AND m.target_type LIKE 'official_rating_observation:%%'"""
    for row in _query(service.target, sql, (service.source_namespace_uuid, service.batch_id)):
        yield (row["source_table"], row["source_pk"], row["category"]), {"institutionId": row["legacy_id"],
            "period": row["period"], "rank": row["rank"], "score": row["score"], "fetchedAt": row["fetched_at"]}


def source_institutions(service):
    for row in service._all_rows("institutions"):
        yield int(row["id"]), {"name": str(row["name"]).strip(), "shortName": str(row["short_name"]).strip() if row.get("short_name") else None, "status": "active"}


def target_institutions(service):
    sql = """SELECT a.legacy_id,i.canonical_name,i.short_name,i.status::text FROM catalog.institution i
        JOIN migration.legacy_identity_map m ON m.target_uuid=i.id AND m.target_type='institution' AND m.source_namespace=%s
        LEFT JOIN catalog.legacy_entity_alias a ON a.target_uuid=i.id AND a.entity_type='institutions'"""
    for row in _query(service.target, sql, (service.source_namespace_uuid,)):
        yield row["legacy_id"], {"name": row["canonical_name"], "shortName": row["short_name"], "status": row["status"]}


def source_accounts(service):
    from .normalize import access_mode, observation_quality
    from urllib.parse import urlsplit
    for row in service.account_rows.values():
        aid = int(row["id"])
        channel = service.channels_by_account.get(aid)
        current = channel or row
        tg = channel is not None
        native = current.get("telegram_id" if tg else "native_id")
        # Independently normalize display links using legacy's HTTP(S) protocol
        # contract. This does not derive expected values from target metadata.
        display_url = str(current.get("url") or "").strip()
        try:
            parsed_url = urlsplit(display_url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname or parsed_url.username is not None or parsed_url.password is not None:
                display_url = None
        except ValueError:
            display_url = None
        yield aid, {"institutionId": int(current["institution_id"]), "platform": row["platform"],
            "username": current.get("username"), "title": current.get("title"),
            "url": f"https://t.me/{current['username']}" if tg else display_url,
            "nativeId": str(native) if native is not None else None,
            "accessMode": access_mode(row["platform"], ("mtproto" if native else "public_web") if tg else current.get("access_mode")),
            "enabled": bool(current["enabled"])}


def target_accounts(service):
    sql = """SELECT a.legacy_id,ia.legacy_id AS institution_legacy_id,p.*,n.external_id AS native
        FROM catalog.platform_account p
        JOIN migration.legacy_identity_map m ON m.target_uuid=p.id AND m.target_type='platform_account'
          AND m.source_table='platform_accounts' AND m.source_namespace=%s
        LEFT JOIN catalog.legacy_entity_alias a ON a.target_uuid=p.id AND a.entity_type='platform_accounts'
        LEFT JOIN catalog.legacy_entity_alias ia ON ia.target_uuid=p.institution_id AND ia.entity_type='institutions'
        LEFT JOIN catalog.account_external_identity n ON n.platform_account_id=p.id
          AND n.identity_namespace=p.platform::text||':native_id' AND n.valid_to IS NULL"""
    for row in _query(service.target, sql, (service.source_namespace_uuid,)):
        yield row["legacy_id"], {"institutionId": row["institution_legacy_id"], "platform": row["platform"],
            "username": row["current_username"], "title": row["current_title"], "url": row["current_url"],
            "nativeId": row["native"], "accessMode": row["access_mode"], "enabled": row["enabled"]}


def source_subscribers(service):
    from .normalize import observation_quality
    for row in service.account_rows.values():
        current = service.channels_by_account.get(int(row["id"]), row)
        if not current.get("subscriber_measured_at") or (current.get("subscriber_count") is None and current.get("subscriber_count_display") is None):
            continue
        yield int(row["id"]), {"observedAt": _time(current["subscriber_measured_at"]),
            "value": current.get("subscriber_count"), "display": current.get("subscriber_count_display"),
            "quality": observation_quality(current.get("data_quality"), default="unknown")}


def target_subscribers(service):
    sql = """SELECT a.legacy_id,s.* FROM migration.legacy_identity_map m
        JOIN ingest.account_metric_snapshot s ON s.id=m.target_bigint
        JOIN catalog.legacy_entity_alias a ON a.target_uuid=s.platform_account_id AND a.entity_type='platform_accounts'
        WHERE m.source_namespace=%s AND (m.last_seen_batch_id=%s OR """+PRESERVED_MAPPING+""")
          AND m.target_type='account_metric_snapshot'"""
    for row in _query(service.target, sql, (service.source_namespace_uuid, service.batch_id)):
        yield row["legacy_id"], {"observedAt": row["observed_at"], "value": row["subscriber_count"],
            "display": row["subscriber_display"], "quality": row["quality"]}


def ordered_series(service, *, target: bool):
    """Independent per-account/publication/metric series, sorted on disk.

    Negative changes are retained as signed facts. They are counted separately
    from zero and NULL and are never clamped or classified as a provider reset
    without evidence. Each digest includes timestamps, buckets and flags.
    """
    publications = target_publications(service) if target else with_preserved(service, "publications", source_publications(service))
    owners = {tuple(key): (row["accountTable"], row["accountId"]) for key, row in publications}
    snapshots = target_snapshots(service) if target else with_preserved(service, "observations", source_snapshots(service))
    with tempfile.TemporaryDirectory(prefix="mranked-series-") as directory:
        db = sqlite3.connect(f"{directory}/series.sqlite")
        try:
            db.execute("PRAGMA cache_size=-2048")
            db.execute("CREATE TABLE point(group_key TEXT,observed_at TEXT,bucket INTEGER,body TEXT)")
            def points():
                for key, row in snapshots:
                    owner = owners.get(tuple(key[:2]))
                    for metric in METRICS:
                        group = (*owner, *key[:2], metric) if owner else (None, None, *key[:2], metric)
                        body = {"value": row[metric], "observedAt": row["observedAt"], "bucket": key[2],
                                "synthetic": row["synthetic"], "uncertain": row["uncertain"], "quality": row["metricQuality"][metric]}
                        yield encode(group), encode(row["observedAt"]), key[2], encode(body)
            db.executemany("INSERT INTO point VALUES(?,?,?,?)", points())
            db.execute("CREATE INDEX series_order ON point(group_key,observed_at,bucket,body)")
            prior_group = None
            def start():
                return {"rows":0,"null":0,"zero":0,"sum":0,"negativeTransitions":0,
                        "synthetic":0,"uncertain":0,"minObservedAt":None,"maxObservedAt":None}
            summary, previous, digest = start(), None, hashlib.sha256()
            for group, at, bucket, body in db.execute("SELECT * FROM point ORDER BY group_key,observed_at,bucket,body"):
                if prior_group is not None and group != prior_group:
                    yield json.loads(prior_group), summary | {"sha256": digest.hexdigest()}
                    summary, previous, digest = start(), None, hashlib.sha256()
                prior_group = group
                value = json.loads(body)
                digest.update((body+"\n").encode("utf-8"))
                summary["rows"] += 1
                summary["minObservedAt"] = summary["minObservedAt"] or json.loads(at)
                summary["maxObservedAt"] = json.loads(at)
                summary["synthetic"] += int(value["synthetic"])
                summary["uncertain"] += int(value["uncertain"])
                count = value["value"]
                if count is None:
                    summary["null"] += 1
                else:
                    summary["zero"] += int(count == 0)
                    summary["sum"] += count
                    summary["negativeTransitions"] += int(previous is not None and count < previous)
                    previous = count
            if prior_group is not None:
                yield json.loads(prior_group), summary | {"sha256": digest.hexdigest()}
        finally:
            db.close()


PRESERVED_MAPPING = """EXISTS (
    SELECT 1 FROM migration.source_disappearance_decision d
    JOIN migration.preserved_source_decision verified ON verified.decision_id=d.id
    WHERE d.source_namespace=m.source_namespace AND d.source_table=m.source_table
      AND d.source_pk=m.source_pk AND d.target_type=m.target_type
      AND d.source_row_hash=m.source_row_hash AND d.decision='preserved_history')"""


def fact_pairs():
    return (("institutions", source_institutions, target_institutions),
             ("accounts", source_accounts, target_accounts),
             ("subscribers", source_subscribers, target_subscribers),
             ("publications", source_publications, target_publications),
             ("publication_identities", source_identities, target_identities),
             ("observations", source_snapshots, target_snapshots),
             ("reaction_keys", lambda s: source_snapshots(s, reactions_only=True), lambda s: target_snapshots(s, reactions_only=True)),
             ("official_rating_values", source_ratings, target_ratings))


def with_preserved(service, name, rows):
    """Merge absent source keys with previously verified source facts on disk."""
    with tempfile.TemporaryDirectory(prefix="mranked-preserved-keys-") as directory:
        db = sqlite3.connect(f"{directory}/keys.sqlite")
        try:
            db.execute("PRAGMA cache_size=-2048")
            db.execute("CREATE TABLE seen(key TEXT PRIMARY KEY,body TEXT,is_current INTEGER)")
            for key, body in rows:
                db.execute("INSERT OR IGNORE INTO seen VALUES(?,?,1)", (encode(key), encode(body)))
                yield key, body
            sql = """SELECT f.natural_key,f.body FROM migration.preserved_canonical_fact f
                JOIN migration.source_preservation p ON p.id=f.preservation_id
                WHERE p.source_namespace=%s AND f.fact_type=%s ORDER BY p.verified_at,p.id"""
            for row in _query(service.target, sql, (service.source_namespace_uuid, name)):
                key, body = row["natural_key"], row["body"]
                previous = db.execute("SELECT body,is_current FROM seen WHERE key=?", (encode(key),)).fetchone()
                if previous:
                    if not previous[1] and previous[0] != encode(body):
                        raise ValueError("conflicting immutable preserved source facts")
                    continue
                db.execute("INSERT INTO seen VALUES(?,?,0)", (encode(key), encode(body)))
                yield key, body
        finally:
            db.close()


def independent_checks(service):
    for name, source_rows, target_rows in fact_pairs():
        yield name, compare_rows(with_preserved(service, name, source_rows(service)), target_rows(service))
    yield "ordered_metric_series", compare_rows(ordered_series(service, target=False), ordered_series(service, target=True))
    yield "operational_checkpoint_text", compare_rows(source_checkpoints(service), target_checkpoints(service))
    yield "current_account_presentation", compare_rows(source_account_presentation(service), target_account_presentation(service))
    for preservation_id, expected, actual in preserved_ledger_digests(service):
        yield "preserved_ledger:"+str(preservation_id), {"expected":expected,"actual":actual,"changedKeysSample":[]}


def source_checkpoints(service):
    """Health checkpoint scalar types and lexical duration/UTC text are facts."""
    for row in service._all_rows("app_state"):
        key = str(row["key"])
        explicit = {"last_poll", "next_poll", "m_rating_last_period", "m_rating_last_updated", "m_rating_last_error"}
        known = key in explicit or key.startswith(("poll_last_", "telegram_web_last_", "vk_poll_last_", "max_poll_last_", "rutube_poll_last_", "telegram_poll_last_"))
        if not known or not (key in explicit or key.endswith(("_at", "_seconds", "_count", "_error"))):
            continue
        value = row["value"]
        if key.endswith("_error"):
            text = str(value or "")
            value = {"present": bool(text), "length": len(text), "sha256": hashlib.sha256(text.encode()).hexdigest() if text else None}
        yield key, {"value": value}


def target_checkpoints(service):
    query = """SELECT c.checkpoint_key,c.value FROM ops_and_admin.operational_checkpoint c
        JOIN migration.legacy_identity_map m ON m.source_pk=c.checkpoint_key
          AND m.source_namespace=%s AND m.source_table='app_state' AND m.target_type='legacy_evidence'
        WHERE c.checkpoint_key IN ('last_poll','next_poll','m_rating_last_period','m_rating_last_updated','m_rating_last_error') OR
          (c.checkpoint_key ~ '^(poll_last_|telegram_web_last_|(telegram|vk|max|rutube)_poll_last_)'
            AND c.checkpoint_key ~ '(_at|_seconds|_count|_error)$')"""
    for row in _query(service.target, query, (service.source_namespace_uuid,)):
        yield row["checkpoint_key"], {"value": row["value"]}


def source_account_presentation(service):
    # Independent of the writer: values are computed from the original SQLite
    # row, never copied from a migration hash or target representation.
    allowed = {"public", "public_api", "official_api", "public_web", "telegram_web", "user_session", "owner", "mtproto", "api", "official", "user", "user_api", "disabled"}
    for row in service._all_rows("platform_accounts"):
        error = str(row.get("last_error") or "")
        mode = row.get("access_mode")
        yield str(row["id"]), {"access_mode":mode if mode in allowed else None,
            "last_error":{"present":bool(error), "length":len(error),
                          "sha256":hashlib.sha256(error.encode()).hexdigest() if error else None}}


def target_account_presentation(service):
    query = """SELECT mapping.source_pk,presentation.evidence
        FROM migration.legacy_identity_map mapping
        JOIN migration.legacy_evidence presentation ON presentation.batch_id=mapping.last_seen_batch_id
            AND presentation.source_table=mapping.source_table AND presentation.source_pk=mapping.source_pk
            AND presentation.source_row_hash=mapping.source_row_hash
            AND presentation.evidence_kind='legacy_account_presentation' AND presentation.sanitized
        WHERE mapping.source_namespace=%s AND mapping.last_seen_batch_id=%s
            AND mapping.source_table='platform_accounts' AND mapping.target_type='platform_account'"""
    for row in _query(service.target, query, (service.source_namespace_uuid,service.batch_id)):
        yield row["source_pk"],row["evidence"]


def preserved_ledger_digests(service):
    records = service.target.connection.execute("""SELECT id,facts_sha256 FROM migration.source_preservation
        WHERE source_namespace=%s ORDER BY id""", (service.source_namespace_uuid,)).fetchall()
    for preservation_id, expected in records:
        with tempfile.TemporaryDirectory(prefix="mranked-ledger-hash-") as directory:
            db = sqlite3.connect(f"{directory}/ledger.sqlite")
            try:
                db.execute("PRAGMA cache_size=-2048")
                db.execute("CREATE TABLE fact(kind TEXT,key TEXT,body TEXT)")
                rows = _query(service.target, """SELECT fact_type,natural_key,body FROM migration.preserved_canonical_fact
                    WHERE preservation_id=%s""", (preservation_id,))
                db.executemany("INSERT INTO fact VALUES(?,?,?)", ((r["fact_type"],encode(r["natural_key"]),encode(r["body"])) for r in rows))
                digest = hashlib.sha256()
                for row in db.execute("SELECT * FROM fact ORDER BY kind,key,body"):
                    digest.update(("\t".join(row)+"\n").encode())
                yield preservation_id, expected, digest.hexdigest()
            finally:
                db.close()
