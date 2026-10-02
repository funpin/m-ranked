"""Хранилище v2 на живой одноразовой базе стенда; без стенда пропускается.

Схема стенда применяется целиком, 0001–0036 подряд, поэтому сама применимость
0036 поверх предыдущих проверяется наличием её объектов.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

import pytest

from anomaly_analysis.v2.domain import (
    DataQuality, Family, Interval, Level, Metric, PostVerdict, Sign,
)
from anomaly_analysis.v2.store import DueRow, PostgresAnomalyStore, SeriesTarget, StateWrite

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row  # noqa: E402 — только после importorskip

NEW_TABLES = ("anomaly_norm_version", "anomaly_norm", "post_anomaly_state", "post_anomaly_log")
PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
INSTITUTION, ACCOUNT, RUN = uuid4(), uuid4(), uuid4()


@pytest.fixture(scope="module")
def databases():
    names = {"admin": "MRANKED_ANOMALY_TEST_ADMIN_DSN", "worker": "MRANKED_ANOMALY_TEST_WORKER_DSN",
             "api": "MRANKED_ANOMALY_TEST_API_DSN"}
    values = {name: os.environ.get(key, "") for name, key in names.items()}
    if not all(values.values()):
        pytest.skip("disposable anomaly PostgreSQL role DSNs are required")
    if "anomaly_it" not in values["admin"] or not any(host in values["admin"] for host in ("127.0.0.1", "localhost")):
        raise AssertionError("anomaly integration test requires the dedicated disposable local anomaly_it database")
    # The live ingestion contract creates a revision before its first snapshot.
    # A fresh database has no prior batch whose revision a fixture can inherit.
    with psycopg.connect(values["admin"], autocommit=True) as connection:
        connection.execute("INSERT INTO analytics.dataset_revision(cause,correlation_id) "
                           "VALUES ('ingestion',gen_random_uuid())")
    with _admin(values["admin"]) as connection:
        connection.execute("INSERT INTO catalog.institution(id,canonical_name) VALUES (%s,'Anomaly v2 fixture')",
                           (INSTITUTION,))
        connection.execute("""
            INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode)
            VALUES (%s,%s,'vk',%s,'public_web')""", (ACCOUNT, INSTITUTION, f"anomaly-v2-{ACCOUNT}"))
        connection.execute("""
            INSERT INTO ingest.collection_run(id,platform,partition_key,collector_version,started_at,status,correlation_id)
            VALUES (%s,'vk','anomaly-v2','integration',now()-interval '1 day','succeeded',gen_random_uuid())""", (RUN,))
    yield values


def _admin(dsn):
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)


def _publication(admin_dsn, published_at: datetime, points: int, *, bad_readings=False):
    publication = uuid4()
    with _admin(admin_dsn) as connection:
        month = published_at.astimezone(timezone.utc).date().replace(day=1)
        connection.execute("SELECT ops_and_admin.ensure_publication_metric_partition(%s)", (month,))
        connection.execute("""
            INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness)
            VALUES (%s,%s,%s,%s,'post','complete')""", (publication, ACCOUNT, published_at, published_at))
        for index in range(points):
            observed = published_at + timedelta(minutes=5 * (index + 1))
            connection.execute("""
                INSERT INTO ingest.publication_metric_snapshot(
                  published_month,publication_id,collection_run_id,observed_at,age_seconds,sampling_bucket,
                  views_count,reactions_count,comments_count,shares_count,quality,source_fingerprint,collected_at,
                  views_quality,reactions_quality,interval_uncertain)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'exact',%s,%s,%s,'exact',%s)""",
                (month, publication, RUN, observed, 300 * (index + 1), index, 100 * (index + 1), 3 * index,
                 index // 4, index // 8, uuid4().hex, observed,
                 "rounded" if bad_readings and index==14 else "exact",bad_readings and index==26))
    return SeriesTarget(publication, published_at)


def test_migration_objects_exist_on_top_of_the_previous_schema(databases):
    with _admin(databases["admin"]) as connection:
        present = {row["table_name"] for row in connection.execute(
            """SELECT table_name FROM information_schema.tables
                WHERE table_schema='analytics' AND table_name = ANY(%s)""", (list(NEW_TABLES),))}
        assert present == set(NEW_TABLES)
        # Контракт схемы сборщиков и API прежний: новые таблицы им не видны.
        contract = connection.execute("SELECT contract_id FROM ops_and_admin.schema_contract").fetchone()
        assert contract["contract_id"] == "live-read-2026-09-13-text-fingerprint"


def test_roles_receive_exactly_the_listed_privileges(databases):
    expected = {
        ("analytics_worker", "anomaly_norm_version"): {"SELECT", "INSERT", "UPDATE"},
        ("analytics_worker", "anomaly_norm"): {"SELECT", "INSERT", "UPDATE"},
        ("analytics_worker", "post_anomaly_state"): {"SELECT", "INSERT", "UPDATE"},
        ("analytics_worker", "post_anomaly_log"): {"INSERT"},
        ("api_read", "post_anomaly_state"): {"SELECT"},
        ("api_write_admin", "post_anomaly_state"): {"SELECT"},
    }
    with _admin(databases["admin"]) as connection:
        roles = [row["rolname"] for row in connection.execute(
            "SELECT rolname FROM pg_roles WHERE rolname NOT LIKE 'pg\\_%' AND NOT rolsuper").fetchall()]
        for role in roles:
            for table in NEW_TABLES:
                granted = {privilege for privilege in PRIVILEGES if connection.execute(
                    "SELECT has_table_privilege(%s, %s, %s) AS ok",
                    (role, f"analytics.{table}", privilege)).fetchone()["ok"]}
                owner = connection.execute(
                    "SELECT tableowner FROM pg_tables WHERE schemaname='analytics' AND tablename=%s",
                    (table,)).fetchone()["tableowner"]
                if role == owner:
                    continue
                assert granted == expected.get((role, table), set()), (role, table, granted)


def test_batched_series_equal_single_reads(databases):
    base = datetime.now(timezone.utc) - timedelta(hours=6)
    targets = [_publication(databases["admin"], base + timedelta(minutes=index), 12 + index) for index in range(3)]
    store = PostgresAnomalyStore(databases["worker"])
    batched = store.read_series(targets)
    single = {}
    for target in targets:
        single.update(store.read_series([target]))
    assert batched == single and set(batched) == {item.publication_id for item in targets}
    series = batched[targets[0].publication_id]
    assert series.platform == "vk" and len(series.observed_at) == 12
    assert series.values[Metric.VIEWS][:3] == (100, 200, 300)


@pytest.mark.parametrize('quality', ['rounded', 'unknown'])
def test_reaction_evidence_survives_database_worker_export_and_api(databases, quality):
    import json
    from pathlib import Path
    from anomaly_analysis.tools.export_reference import export
    from anomaly_analysis.tools.reference_format import parse_case
    from anomaly_analysis.v2.levels import assess
    from anomaly_analysis.v2.schedule import ScheduleConfig
    from anomaly_analysis.v2.series import CollectionCadence
    from anomaly_analysis.v2.worker import Worker
    from api.routes.analysis import analysis_body
    from api.sql.analysis import STATE

    fixture, index = ('anomaly_reaction_bursts.json', 1) if quality == 'rounded' else ('anomaly_reported_shapes.json', 2)
    case = json.loads((Path(__file__).parent / 'fixtures' / fixture).read_text())[index]
    source_start = datetime.fromisoformat(case['publication']['publishedAt'])
    published = datetime.now(timezone.utc) - timedelta(days=1)
    month = published.date().replace(day=1)
    account, publication, run = uuid4(), uuid4(), uuid4()
    # The database requires reaction rows and their snapshot in one transaction.
    with psycopg.connect(databases['admin'],row_factory=dict_row) as connection:
        assert connection.execute("SELECT has_table_privilege('analytics_worker',"
                                  "'ingest.reaction_breakdown','SELECT') AS ok").fetchone()['ok']
        assert not connection.execute("SELECT has_table_privilege('analytics_worker',"
                                      "'ingest.reaction_breakdown','UPDATE') AS ok").fetchone()['ok']
        connection.execute("INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode) "
                           "VALUES (%s,%s,'telegram',%s,'public_web')", (account,INSTITUTION,str(account)))
        connection.execute("INSERT INTO ingest.collection_run(id,platform,partition_key,collector_version,started_at,status,correlation_id) "
                           "VALUES (%s,'telegram','bounded','integration',%s,'succeeded',gen_random_uuid())",(run,published))
        connection.execute("SELECT ops_and_admin.ensure_publication_metric_partition(%s)",(month,))
        connection.execute("INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness) "
                           "VALUES (%s,%s,%s,%s,'post','complete')",(publication,account,published,published))
        for index, point in enumerate(case['points']):
            age = datetime.fromisoformat(point['observed_at']) - source_start
            observed = published + age
            snapshot = connection.execute("INSERT INTO ingest.publication_metric_snapshot("
                "published_month,publication_id,collection_run_id,observed_at,age_seconds,sampling_bucket,"
                "views_count,reactions_count,quality,views_quality,reactions_quality,interval_uncertain,source_fingerprint,collected_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,%s,%s) RETURNING id",
                (month,publication,run,observed,int(age.total_seconds()),index,point['v'],point['r'],
                 quality,quality,quality,uuid4().hex,observed)).fetchone()['id']
            for key, count in point['breakdown'].items():
                connection.execute("INSERT INTO ingest.reaction_breakdown VALUES (%s,%s,%s,%s)",
                                   (month,snapshot,key,count))
    store = PostgresAnomalyStore(databases['worker'])
    series = store.read_series([SeriesTarget(publication,published)])[publication]
    assert series.reaction_breakdowns[0] == case['points'][0]['breakdown']
    assert all(q == quality for q in series.qualities[Metric.REACTIONS])
    now = series.observed_at[-1]
    Worker(store,ScheduleConfig(),CollectionCadence(),clock=lambda:now)._analyze(
        [DueRow(publication,published,now,None,None,None,0,())],now,1.)
    with psycopg.connect(databases['api'],row_factory=dict_row) as connection:
        body = analysis_body(str(publication),1,connection.execute(STATE,{'publication':publication}).fetchone())
        restored = parse_case(export(connection,(publication,))[publication]).subject
    assert body['level'] >= 2 if quality == 'rounded' else body['level'] == 1
    assert any(s['render']['kind'] == 'bounded_burst' for s in body['signals'])
    from anomaly_analysis.v2.detectors.bounded_reaction_burst import VERSION
    assert body['detectorVersions']['bounded_reaction_burst'] == VERSION
    if quality == 'unknown':
        assert any(s['render'].get('reportedOnly') for s in body['signals'])
    assert restored.interval_uncertain == series.interval_uncertain
    assert restored.reaction_breakdowns == series.reaction_breakdowns
    assert assess(restored).level >= 2 if quality == 'rounded' else assess(restored).level == 1


def test_progress_matches_the_series_it_stands_in_for(databases):
    base = datetime.now(timezone.utc) - timedelta(hours=6)
    targets = [_publication(databases["admin"], base + timedelta(minutes=index), 8 + index) for index in range(2)]
    store = PostgresAnomalyStore(databases["worker"])
    series = store.read_series(targets)
    rows = []
    for target, back in zip(targets, (1, 4)):
        points = series[target.publication_id].observed_at
        rows.append(DueRow(target.publication_id, target.published_at, base, base, points[-back], None, 0, ()))
    progress = store.read_progress(rows)
    for row in rows:
        points = series[row.publication_id].observed_at
        new = [at for at in points if at > row.last_point_observed_at]
        item = progress[row.publication_id]
        assert (item.platform, item.new_points, item.first_new_at, item.last_observed_at) == (
            series[row.publication_id].platform, len(new), new[0] if new else None, points[-1])


def test_log_is_written_only_when_the_verdict_changes(databases):
    target = _publication(databases["admin"], datetime.now(timezone.utc) - timedelta(hours=3), 6)
    store = PostgresAnomalyStore(databases["worker"])
    moment = datetime.now(timezone.utc)
    sign = Sign(1, Family.VELOCITY, Metric.VIEWS, 0.9, Interval(moment - timedelta(hours=2), moment),
                timedelta(hours=1), "CV = 0.03")

    def write(level, signs):
        verdict = PostVerdict(target.publication_id, level, signs, DataQuality(1.0), {"linear_feed": "1"})
        return store.write_states([StateWrite(target.publication_id, target.published_at, moment,
                                              moment + timedelta(minutes=15), verdict=verdict)])

    assert write(Level.PRONOUNCED_ANOMALY, (sign,)) == 1
    assert write(Level.PRONOUNCED_ANOMALY, (sign,)) == 0
    assert write(Level.WEAK_SIGNAL, (sign,)) == 1
    store.write_states([StateWrite(target.publication_id, target.published_at, moment,
                                   moment + timedelta(minutes=30), error_code="series_unavailable")])
    with _admin(databases["admin"]) as connection:
        changes = [row["change"] for row in connection.execute(
            "SELECT change FROM analytics.post_anomaly_log WHERE publication_id=%s ORDER BY id",
            (target.publication_id,)).fetchall()]
        state = connection.execute(
            "SELECT level, attempts, error_code FROM analytics.post_anomaly_state WHERE publication_id=%s",
            (target.publication_id,)).fetchone()
    assert changes == ["appeared", "level_changed"]
    # Неудачный анализ не стирает прежний вывод.
    assert state == {"level": 1, "attempts": 1, "error_code": "series_unavailable"}


def test_actual_sql_excludes_rounded_and_uncertain_reads_per_metric(databases):
    import numpy as np
    base=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)-timedelta(hours=12)
    target=_publication(databases["admin"],base,36,bad_readings=True)
    # A bad read inside hour 1 must poison that metric's hourly aggregate;
    # reactions in the same hour remain independently usable.
    store=PostgresAnomalyStore(databases["worker"])
    series=store.read_series([target])[target.publication_id]
    assert series.exact_values(Metric.VIEWS)[14] is None
    assert series.exact_values(Metric.REACTIONS)[14] is not None
    assert series.exact_values(Metric.REACTIONS)[26] is None
    activity=store.read_activity([ACCOUNT],base,base+timedelta(hours=4),base-timedelta(hours=1))[ACCOUNT]
    i=activity.publications.index(target.publication_id)
    assert np.isnan(activity.views[i,1]) and np.isnan(activity.views[i,2])
    assert np.isfinite(activity.reactions[i,1]) and np.isnan(activity.reactions[i,2])


def test_new_signs_survive_worker_database_and_public_api(databases):
    from anomaly_analysis.v2.mature_reference import bundled_reference
    from anomaly_analysis.v2.schedule import ScheduleConfig
    from anomaly_analysis.v2.series import CollectionCadence
    from anomaly_analysis.v2.worker import Worker
    from api.routes.analysis import analysis_body
    from api.sql.analysis import STATE
    reference=bundled_reference();account=next(iter(reference.account_counts))
    publication,run=uuid4(),uuid4()
    published=reference.available_at+timedelta(days=1);now=published+timedelta(hours=73)
    month=published.date().replace(day=1)
    with _admin(databases["admin"]) as connection:
        connection.execute("INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode) "
                           "VALUES (%s,%s,'max',%s,'public_web') ON CONFLICT(id) DO NOTHING",
                           (account,INSTITUTION,f"reference-{account}"))
        connection.execute("INSERT INTO ingest.collection_run(id,platform,partition_key,collector_version,started_at,status,correlation_id) "
                           "VALUES (%s,'max','reference','integration',%s,'succeeded',gen_random_uuid())",(run,published))
        connection.execute("SELECT ops_and_admin.ensure_publication_metric_partition(%s)",(month,))
        connection.execute("INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness) "
                           "VALUES (%s,%s,%s,%s,'post','complete')",(publication,account,published,published))
        for hour,v,r in ((24,100,10),(72,10000000,100000)):
            observed=published+timedelta(hours=hour)
            connection.execute("INSERT INTO ingest.publication_metric_snapshot("
                "published_month,publication_id,collection_run_id,observed_at,age_seconds,sampling_bucket,"
                "views_count,reactions_count,quality,views_quality,reactions_quality,interval_uncertain,source_fingerprint,collected_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'exact','exact','exact',false,%s,%s)",
                (month,publication,run,observed,hour*3600,hour,v,r,uuid4().hex,observed))
    store=PostgresAnomalyStore(databases["worker"])
    worker=Worker(store,ScheduleConfig(),CollectionCadence(),clock=lambda:now)
    row=DueRow(publication,published,now,None,None,None,0,())
    worker._analyze([row],now,1.)
    with psycopg.connect(databases["api"],row_factory=dict_row) as connection:
        stored=connection.execute(STATE,{"publication":publication}).fetchone()
    body=analysis_body(str(publication),1,stored)
    assert {11,12}<={s["pattern"] for s in body["signals"]}
    assert body["level"]==1 and body["levelLabel"]=="слабый сигнал"
    assert body["detectorVersions"]["mature_reference_model"]==next(
        item.version for item in reversed(reference.references) if item.available_at<=published<item.expires_at)
    assert all(s["render"]["observed"]>s["render"]["upper"] for s in body["signals"] if s["pattern"] in (11,12))


def test_research_endpoint_sql_matches_active_corrections_as_of_cutoff(databases):
    import json
    import pathlib
    import re
    base=datetime(2026,9,21,tzinfo=timezone.utc)
    target=_publication(databases["admin"],base,1)
    month=base.date().replace(day=1)
    with _admin(databases["admin"]) as connection:
        old=connection.execute("INSERT INTO ingest.publication_metric_snapshot("
            "published_month,publication_id,collection_run_id,observed_at,age_seconds,sampling_bucket,"
            "views_count,reactions_count,quality,source_fingerprint,collected_at) "
            "VALUES (%s,%s,%s,%s,%s,72,1000,10,'exact',%s,%s) RETURNING id,created_at",
            (month,target.publication_id,RUN,base+timedelta(hours=71),71*3600,uuid4().hex,base+timedelta(hours=71))).fetchone()
        correction=connection.execute("INSERT INTO ingest.publication_metric_snapshot("
            "published_month,publication_id,collection_run_id,observed_at,age_seconds,sampling_bucket,"
            "views_count,reactions_count,quality,source_fingerprint,collected_at,"
            "correction_sequence,supersedes_snapshot_id,correction_reason) "
            "VALUES (%s,%s,%s,%s,%s,72,1100,11,'exact',%s,%s,1,%s,'provider_payload_changed') RETURNING created_at",
            (month,target.publication_id,RUN,base+timedelta(hours=73),73*3600,uuid4().hex,base+timedelta(hours=73),old['id'])).fetchone()
        query=(pathlib.Path(__file__).resolve().parents[1]/'research/smart-engagement-2026-09/sql/release_endpoints.sql').read_text()
        query=query[query.index('WITH accounts'):query.rindex('COMMIT;')]
        query=re.sub(r"jsonb_array_elements_text\(\s*'[^']+'::jsonb\)",
                     'jsonb_array_elements_text(%(accounts)s::jsonb)',query,count=1)
        query=query.replace("'2026-09-28 03:18:11+00'::timestamptz",'%(cutoff)s::timestamptz')
        def endpoint_at(cutoff):
            result=connection.execute(query,{'accounts':json.dumps([str(ACCOUNT)]),'cutoff':cutoff}).fetchall()
            row=next(next(iter(r.values())) for r in result if next(iter(r.values()))['id']==str(target.publication_id))
            return next(p for p in row['points'] if p['hours']==72)
        before=endpoint_at(correction['created_at']-timedelta(microseconds=1))
        after=endpoint_at(correction['created_at']+timedelta(microseconds=1))
        assert before['v']==1000 and after['v'] is None
    series=PostgresAnomalyStore(databases['worker']).read_series([target])[target.publication_id]
    assert base+timedelta(hours=71) not in series.observed_at
    assert base+timedelta(hours=73) in series.observed_at


def test_tail_ledgers_and_account_profiles_flow_from_worker_to_public_api(databases):
    """Сводка поста пишется работником, профиль — ночным заданием, читает — api_read."""
    from datetime import date
    from anomaly_analysis.account_tail_job import run
    from anomaly_analysis.v2.levels import assess
    from anomaly_analysis.v2.tail_ledger import VERSION, build_ledger
    from api.routes.analysis import tail_profile_body
    from api.sql.analysis import TAIL_PROFILE
    base = datetime.now(timezone.utc) - timedelta(days=12)
    target = _publication(databases["admin"], base, 20)
    store = PostgresAnomalyStore(databases["worker"])
    series = store.read_series([target])[target.publication_id]
    now = datetime.now(timezone.utc)
    ledger = build_ledger(series, now).payload()
    store.write_states([StateWrite(target.publication_id, target.published_at, now, now + timedelta(hours=1),
                                   verdict=assess(series, analyzed_at=now), analyzed_points=20,
                                   last_point_observed_at=series.observed_at[-1], tail_ledger=ledger)])
    with _admin(databases["admin"]) as connection:
        row = connection.execute("SELECT tail_ledger, tail_ledger_version FROM analytics.post_anomaly_state "
                                 "WHERE publication_id=%s", (target.publication_id,)).fetchone()
    assert row["tail_ledger"] == ledger and row["tail_ledger_version"] == VERSION
    # A write without a ledger (analysis error path aside) keeps the stored one.
    store.write_states([StateWrite(target.publication_id, target.published_at, now, now + timedelta(hours=2),
                                   verdict=assess(series, analyzed_at=now), analyzed_points=20,
                                   last_point_observed_at=series.observed_at[-1])])
    [due] = [item for item in store.backfill_targets(ACCOUNT, base - timedelta(days=1))
             if item.publication_id == target.publication_id]
    assert due.tail_ledger_version == VERSION and not due.tail_ledger_stale

    today = datetime.now(timezone.utc).date()
    old = today - timedelta(days=120)
    with _admin(databases["admin"]) as connection:
        connection.execute("INSERT INTO analytics.account_tail_profile(account_id,computed_for,platform,status,"
                           "abstain_reason,metrics,method_version) VALUES (%s,%s,'vk',NULL,'few_posts','{}','old')",
                           (ACCOUNT, old))
    profiles, posts = run(store, today)
    assert posts >= 1 and any(item.account_id == ACCOUNT for item in profiles)
    with psycopg.connect(databases["api"], row_factory=dict_row) as connection:
        rows = connection.execute(TAIL_PROFILE, {"account": ACCOUNT, "limit": 28}).fetchall()
        # The public role reads, but never writes, the profile.
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("DELETE FROM analytics.account_tail_profile")
    assert [row["computed_for"] for row in rows] == [today]
    body = tail_profile_body(str(ACCOUNT), 1, rows)
    assert body["status"] == "computed" and body["platform"] == "vk"
    assert body["metrics"]["methodVersion"] == "account-tail-v1"
    # Rerunning the same day replaces the row instead of adding one.
    run(store, today)
    with _admin(databases["admin"]) as connection:
        count = connection.execute("SELECT count(*) AS n FROM analytics.account_tail_profile "
                                   "WHERE account_id=%s", (ACCOUNT,)).fetchone()["n"]
    assert count == 1
    assert isinstance(today, date)
