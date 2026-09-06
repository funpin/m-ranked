"""Read-only original legacy endpoint oracle against published PostgreSQL projections.

This is deliberately separate from raw-fact reconciliation: neither an identity
map hash nor a successful rebuild can establish equality of a derived result.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from urllib.parse import quote

import psycopg
from starlette.requests import Request

from app.clock import CallableUtcClock
from app.config import Settings
from app.database import Database
from migration.legacy_reference import create_app, reference_metadata
from .reconciliation import compare_rows
from .source import sha256_file
from .projection_source import projection_source,ProjectionSourceError

PERIODS = ("3h", "1d", "7d", "30d")
HORIZONS = (24, 48, 72, 168, 336)
PLATFORMS = ("telegram", "vk", "max", "rutube")
REQUIRED_STATES = ("publication_latest", "publication_hourly", "institution_daily_metrics",
    "institution_monthly_metrics", "institution_period_metrics", "comparison",
    "publication_history", "publication_content", "legacy_exports")
COUNTS = {"total_post_count": "total_publication_count",
    "activity_post_count": "activity_publication_count", "post_count": "new_publication_count"}


class ReadOnlyLegacyDatabase(Database):
    @contextmanager
    def connect(self):
        # An accepted standalone SQLite artifact is never opened writable and
        # cannot silently consume a live WAL absent from its recorded SHA.
        connection = sqlite3.connect("file:" + quote(str(self.path)) + "?mode=ro&immutable=1", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        try:
            yield connection
        finally:
            connection.close()


def _number(value, *, ratio=False):
    if value is None:
        return None
    number = Decimal(str(value))
    if not number.is_finite():
        raise ProjectionSourceError("non-finite projection value")
    # PostgreSQL numeric and the original binary float ratio differ below the
    # public chart's precision. Counters and medians remain decimal-exact.
    if ratio:
        number = number.quantize(Decimal("0.00000001"))
    return format(number.normalize(), "f")


def _settings(source, work, first_age_limit_seconds):
    return Settings(telegram_api_id=None, telegram_api_hash=None,
        telegram_session_path=work/"unused-session", database_path=source,
        initial_channels=(), poll_interval_minutes=60, track_post_for_hours=336,
        complete_history_max_first_age_minutes=first_age_limit_seconds/60,
        jump_min_abs=100, jump_min_ratio=5, web_host="127.0.0.1", web_port=8080,
        display_timezone="Europe/Moscow", log_path=work/"unused.log",
        discovery_limit=200, discovery_overlap=20)


def _context(app, path, **parameters):
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", None) == path)
    request = Request({"type": "http", "method": "GET", "path": path,
        "raw_path": path.encode(), "query_string": b"", "headers": [],
        "scheme": "http", "server": ("localhost", 80), "client": ("localhost", 1),
        "root_path": "", "app": app, "router": app.router})
    return endpoint(request, **parameters).context


def _fields(platform):
    metrics = ("views", "reactions") if platform == "telegram" else ("views", "reactions", "comments", "shares")
    return tuple(COUNTS) + tuple(prefix + metric for metric in metrics
        for prefix in ("total_", "median_", "delta_total_", "delta_median_"))


def _source_overview(app):
    for platform in PLATFORMS:
        for period in PERIODS:
            context = _context(app, "/", platform=platform, period=period,
                sort="name", direction="asc", q="")
            for card in context["channels" if platform == "telegram" else "platform_cards"]:
                entity = card["id"] if platform == "telegram" else card["institution"]["id"]
                yield (platform, period, int(entity)), {field: _number(card[field]) for field in _fields(platform)}


def _target_overview(connection, revision):
    fields = tuple(dict.fromkeys(COUNTS.get(field,field) for field in _fields("vk")))
    with connection.cursor(name="projection_overview") as cursor:
        cursor.execute("SELECT platform::text,period_key,legacy_id," + ",".join(fields) +
            " FROM analytics.legacy_overview_card "
            "WHERE platform::text=ANY(%s) AND dataset_revision_id=%s", (list(PLATFORMS), revision))
        for platform, period, entity, *values in cursor:
            card = dict(zip(fields,values,strict=True))
            yield (platform, period, int(entity)), {
                field: _number(card[COUNTS.get(field, field)]) for field in _fields(platform)}


def _source_period_metrics(app):
    for platform in ("vk", "max", "rutube"):
        for period in PERIODS:
            context = _context(app, "/", platform=platform, period=period,
                sort="name", direction="asc", q="")
            for card in context["platform_cards"]:
                if card["accounts"]:
                    for metric in ("views", "reactions", "comments", "shares"):
                        for aggregation, prefix in (("sum", "total_"), ("median", "median_")):
                            yield (platform, period, int(card["institution"]["id"]), metric, aggregation), {
                                "value": _number(card[prefix+metric])}


def _target_period_metrics(connection, revision):
    with connection.cursor(name="projection_period_metrics") as cursor:
        cursor.execute("""SELECT metric.platform::text,metric.period_key,alias.legacy_id,
            metric.metric_key,metric.aggregation,metric.value
            FROM analytics.institution_period_metrics metric
            JOIN catalog.legacy_entity_alias alias ON alias.entity_type='institutions' AND alias.target_uuid=metric.institution_id
            WHERE metric.dataset_revision_id=%s AND metric.platform IN ('vk','max','rutube')
              AND metric.metric_key IN ('views','reactions','comments','shares') AND metric.aggregation IN ('sum','median')""", (revision,))
        for platform, period, entity, metric, aggregation, value in cursor:
            yield (platform, period, entity, metric, aggregation), {"value": _number(value)}


def _source_comparison(app, horizons):
    for platform in ("telegram", "vk", "rutube"):
        for horizon in horizons:
            for partial in (False, True):
                context = _context(app, "/compare", platform=platform, period=horizon,
                    include_partial=partial, submitted=False, channels=[], institutions=[])
                entities = context["channels" if platform == "telegram" else "entities"]
                datasets = json.loads(context["data_json"])["datasets"]
                if len(entities) != len(datasets):
                    raise ProjectionSourceError("legacy comparison entity ordering is not complete")
                for entity, dataset in zip(entities, datasets, strict=True):
                    for kind, prefix in (("reactions", ""), ("engagement", "conversion_")):
                        for hour, value in enumerate(dataset[prefix+"curve"]):
                            yield (platform, horizon, partial, int(entity["id"]), kind, hour), {
                                "value": _number(value, ratio=kind == "engagement"),
                                "sampleSize": _number(dataset[prefix+"sample_counts"][hour]),
                                "cohortSize": _number(dataset[prefix+"cohort_size"])}


COMPARISON_SQL = """
WITH entities AS (
    SELECT 'telegram'::text platform, alias.legacy_id, account.id entity_id
    FROM catalog.visible_platform_account account
    JOIN catalog.legacy_entity_alias alias ON alias.entity_type='channels' AND alias.target_uuid=account.id
    WHERE account.platform='telegram' AND account.enabled
    UNION ALL
    SELECT DISTINCT account.platform::text, alias.legacy_id, account.institution_id
    FROM catalog.visible_platform_account account
    JOIN catalog.visible_institution institution ON institution.id=account.institution_id
    JOIN catalog.legacy_entity_alias alias ON alias.entity_type='institutions' AND alias.target_uuid=institution.id
    WHERE account.platform IN ('vk','rutube') AND account.enabled
), cohorts AS (
    SELECT cohort.*, (filter_definition->>'include_partial')::boolean partial,
      (filter_definition->>'required_start_hour')::integer start_hour,
      horizon_seconds/3600 horizon
    FROM analytics.comparison_cohort cohort
    WHERE dataset_revision_id=%s AND horizon_seconds/3600=ANY(%s)
      AND platform IN ('telegram','vk','rutube')
), points AS (
    SELECT cohort.id cohort_id, entity.legacy_id, hourly.publication_id, hourly.hour_offset,
      metric.kind, metric.value, metric.start_hour, cohort.horizon
    FROM cohorts cohort JOIN entities entity ON entity.platform=cohort.platform::text
    JOIN analytics.comparison_cohort_member member ON member.cohort_id=cohort.id
    JOIN analytics.comparison_publication_hourly hourly ON hourly.publication_id=member.publication_id
      AND hourly.dataset_revision_id=cohort.dataset_revision_id
      AND hourly.hour_offset<=cohort.horizon
      AND CASE WHEN cohort.platform='telegram' THEN hourly.platform_account_id=entity.entity_id
               ELSE member.institution_id=entity.entity_id END
    CROSS JOIN LATERAL (VALUES
      ('reactions',hourly.reactions_count::numeric,cohort.start_hour),
      ('engagement',hourly.engagement_percent,
        CASE WHEN cohort.platform='telegram' THEN greatest(cohort.start_hour,1) ELSE cohort.start_hour END)
    ) metric(kind,value,start_hour)
), fixed AS (
    SELECT cohort_id,legacy_id,publication_id,kind FROM points
    GROUP BY cohort_id,legacy_id,publication_id,kind
    HAVING bool_or(hour_offset=start_hour AND value IS NOT NULL)
       AND bool_or(hour_offset=horizon AND value IS NOT NULL)
), sizes AS (
    SELECT cohort_id,legacy_id,kind,count(*) size FROM fixed GROUP BY cohort_id,legacy_id,kind
), aggregates AS (
    SELECT point.cohort_id,point.legacy_id,point.kind,point.hour_offset,
      percentile_cont(0.5) WITHIN GROUP(ORDER BY point.value) value,count(point.value) samples
    FROM points point JOIN fixed USING(cohort_id,legacy_id,publication_id,kind)
    WHERE point.hour_offset>=point.start_hour
    GROUP BY point.cohort_id,point.legacy_id,point.kind,point.hour_offset
)
SELECT entity.platform,cohort.horizon,cohort.partial,entity.legacy_id,kind.name,hour.value,
  aggregate.value,coalesce(aggregate.samples,0),coalesce(size.size,0)
FROM cohorts cohort JOIN entities entity ON entity.platform=cohort.platform::text
CROSS JOIN (VALUES ('reactions'),('engagement')) kind(name)
CROSS JOIN LATERAL generate_series(0,cohort.horizon) hour(value)
LEFT JOIN sizes size ON size.cohort_id=cohort.id AND size.legacy_id=entity.legacy_id AND size.kind=kind.name
LEFT JOIN aggregates aggregate ON aggregate.cohort_id=cohort.id AND aggregate.legacy_id=entity.legacy_id
  AND aggregate.kind=kind.name AND aggregate.hour_offset=hour.value
"""


def _target_comparison(connection, revision, horizons):
    with connection.cursor(name="projection_comparison") as cursor:
        cursor.itersize = 500
        cursor.execute(COMPARISON_SQL, (revision, list(horizons)))
        for platform, horizon, partial, entity, kind, hour, value, samples, size in cursor:
            yield (platform, horizon, partial, entity, kind, hour), {
                "value": _number(value, ratio=kind == "engagement"),
                "sampleSize": _number(samples), "cohortSize": _number(size)}


def verify_projections(source: Path, connection, *, source_name: str, expected_sha256: str,
        first_age_limit_seconds: int = 360, horizons=HORIZONS, max_source_rows=250_000,
        max_source_entities=5_000, preserved_source_paths=()) -> dict:
    """Requires an idle connection or an existing repeatable-read transaction.

    Owner-preserved missing rows require explicit verified prior artifacts. A
    private source-only overlay restores their exact original rows; current
    artifact bytes and the PostgreSQL observation anchor remain unchanged.
    """
    source = source.resolve(strict=True)
    if (not 0 <= first_age_limit_seconds <= 86400 or not horizons
            or len(horizons)!=len(set(horizons)) or not set(horizons).issubset(HORIZONS)):
        raise ProjectionSourceError("invalid legacy projection oracle configuration")
    before = sha256_file(source)
    if before != expected_sha256:
        raise ProjectionSourceError("source artifact SHA-256 mismatch")
    if any(source.with_name(source.name+suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ProjectionSourceError("projection oracle requires a standalone accepted SQLite artifact")
    database = ReadOnlyLegacyDatabase(source)
    with database.connect() as sqlite:
        rows = sum(sqlite.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in
            ("institutions", "channels", "platform_accounts", "posts", "platform_posts", "reaction_snapshots", "platform_snapshots"))
        if rows > max_source_rows:
            raise ProjectionSourceError("SOURCE_ORACLE_ROW_BOUND_EXCEEDED")
        entities = sum(sqlite.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("institutions", "channels"))
        if entities > max_source_entities:
            raise ProjectionSourceError("SOURCE_ORACLE_ENTITY_BOUND_EXCEEDED")
    idle = connection.info.transaction_status.name == "IDLE"
    with connection.transaction():
        if idle:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        elif connection.execute("SHOW transaction_isolation").fetchone()[0] not in ("repeatable read", "serializable"):
            raise ProjectionSourceError("projection reconciliation requires a repeatable-read snapshot")
        accepted = connection.execute("SELECT id FROM migration.import_batch WHERE source_name=%s AND source_sha256=%s AND NOT dry_run ORDER BY started_at DESC LIMIT 1",
            (source_name, expected_sha256)).fetchone()
        if not accepted:
            raise ProjectionSourceError("source artifact has no recorded import")
        revision = connection.execute("""SELECT revision.id,revision.committed_at FROM analytics.dataset_revision revision
            JOIN analytics.projection_state state ON state.dataset_revision_id=revision.id AND state.status='ready'
            WHERE state.projection_name=ANY(%s) GROUP BY revision.id,revision.committed_at
            HAVING count(*)=%s ORDER BY revision.id DESC LIMIT 1""", (list(REQUIRED_STATES),len(REQUIRED_STATES))).fetchone()
        if not revision:
            return {"status": "fail", "errorCode": "PUBLISHED_REVISION_UNAVAILABLE", "sourceSha256": before}
        revision_id, anchor = revision
        try:
            with projection_source(source,connection,source_name=source_name,current_batch_id=accepted[0],
                    preserved_source_paths=preserved_source_paths) as (oracle_path,source_metadata):
                database=ReadOnlyLegacyDatabase(oracle_path)
                with database.connect() as sqlite:
                    overlay_rows=sum(sqlite.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in
                        ("institutions", "channels", "platform_accounts", "posts", "platform_posts", "reaction_snapshots", "platform_snapshots"))
                    overlay_entities=sum(sqlite.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("institutions","channels"))
                    if overlay_rows>max_source_rows or overlay_entities>max_source_entities:
                        raise ProjectionSourceError('PRESERVED_SOURCE_OVERLAY_BOUND_EXCEEDED')
                with tempfile.TemporaryDirectory(prefix="legacy-projection-oracle-") as work:
                    app = create_app(_settings(oracle_path,Path(work),first_age_limit_seconds), database,
                        clock=CallableUtcClock(lambda: anchor))
                    checks = {"overview": compare_rows(_source_overview(app), _target_overview(connection,revision_id)),
                        "periodMetrics": compare_rows(_source_period_metrics(app), _target_period_metrics(connection,revision_id)),
                        "fixedCohort": compare_rows(_source_comparison(app,horizons), _target_comparison(connection,revision_id,horizons))}
        except ProjectionSourceError as error:
            return {'status':'fail','errorCode':str(error),'sourceSha256':before,
                'datasetRevision':revision_id,'asOf':anchor.isoformat()}
        after = sha256_file(source)
        if after != before:
            raise ProjectionSourceError("source artifact changed during projection reconciliation")
        for check in checks.values():
            check["status"] = "pass" if check["expected"] == check["actual"] else "fail"
        return {"status": "pass" if all(check["status"] == "pass" for check in checks.values()) else "fail",
            "sourceSha256": before, "sourceUnchanged": True, "sourceRows": rows,
            "oracleSource":source_metadata,
            "datasetRevision": revision_id, "asOf": anchor.isoformat(),
            "firstAgeLimitSeconds": first_age_limit_seconds, "horizons": list(horizons),
            "oracle": "external legacy release endpoints with injected clock",
            "oracleImplementation": reference_metadata(),
            "serialization": "NULL-distinct; exact decimal counters; engagement rounded to 8 decimal places",
            "checks": checks}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--source-name",required=True)
    parser.add_argument("--source-sha256",required=True)
    parser.add_argument("--dsn-env",default="MRANKED_PROJECTION_VERIFY_DSN")
    parser.add_argument("--first-age-limit-seconds",type=int,default=360)
    parser.add_argument("--preserved-source",type=Path,action="append",default=[])
    arguments = parser.parse_args(argv)
    with psycopg.connect(os.environ[arguments.dsn_env],autocommit=True) as connection:
        report = verify_projections(arguments.source,connection,source_name=arguments.source_name,
            expected_sha256=arguments.source_sha256,first_age_limit_seconds=arguments.first_age_limit_seconds,
            preserved_source_paths=tuple(arguments.preserved_source))
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
