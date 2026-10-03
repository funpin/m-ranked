"""Execute the overview query on an isolated local PostgreSQL read model."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
import pytest

from api.dto import overview_row
from api.params import overview_query
from api.sql.overview import OVERVIEW
from api.sql.compare import DASHBOARD_INSTITUTIONS

AS_OF = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
INSTITUTION, OTHER, TG, VK, VK_SECOND = map(UUID, [f"00000000-0000-4000-8000-{i:012}" for i in range(1, 6)])


@pytest.fixture(scope="module")
def connection():
    dsn = os.environ.get("MRANKED_OVERVIEW_TEST_DSN")
    if not dsn:
        pytest.skip("dedicated local overview_it PostgreSQL is required")
    info = psycopg.conninfo.conninfo_to_dict(dsn)
    assert info.get("host") in ("127.0.0.1", "localhost") and info.get("dbname") == "overview_it"
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as db:
        db.execute("CREATE SCHEMA catalog; CREATE SCHEMA ingest; CREATE SCHEMA analytics; CREATE SCHEMA rating")
        db.execute("CREATE TYPE ingest.run_status AS ENUM ('running','failed','partial','succeeded')")
        db.execute("CREATE TABLE catalog.visible_institution(id uuid PRIMARY KEY, canonical_name text, short_name text)")
        db.execute("""CREATE TABLE catalog.visible_platform_account(
            id uuid PRIMARY KEY,institution_id uuid,platform text,canonical_external_id text,
            current_username text,current_title text,current_url text,access_mode text,enabled boolean)""")
        db.execute("CREATE TABLE catalog.legacy_entity_alias(target_uuid uuid,entity_type text,legacy_id bigint,legacy_route text)")
        db.execute("""CREATE TABLE ingest.publication(id uuid PRIMARY KEY,primary_account_id uuid,
            published_at timestamptz,created_at timestamptz,deleted_at timestamptz);
            CREATE VIEW ingest.visible_publication AS SELECT * FROM ingest.publication WHERE deleted_at IS NULL""")
        db.execute("""CREATE TABLE ingest.account_metric_snapshot_active(
            id bigint,platform_account_id uuid,subscriber_count bigint,subscriber_display text,
            observed_at timestamptz,collected_at timestamptz,quality text)""")
        db.execute("""CREATE TABLE ingest.collection_account_result(id bigint,platform_account_id uuid,
            started_at timestamptz,completed_at timestamptz,status ingest.run_status,sanitized_error_code text)""")
        db.execute("CREATE TABLE analytics.publication_latest(platform_account_id uuid,observed_at timestamptz)")
        columns = ["scope_platform text", "entity_id uuid", "period text", "publication_count integer",
                   "previous_publication_count integer"]
        for metric in ("views", "reactions", "comments", "shares"):
            columns.extend([f"total_{metric} numeric",f"median_{metric} numeric",f"{metric}_samples integer",
                            f"previous_total_{metric} numeric",f"previous_median_{metric} numeric"])
        db.execute("CREATE TABLE analytics.overview_card_metrics("+",".join(columns)+")")
        db.execute("""CREATE TABLE rating.official_institution_rating_observation(
            id bigint,institution_id uuid,category text,rank integer,score numeric,period text,fetched_at timestamptz)""")
        db.execute("""CREATE TABLE analytics.post_anomaly_state(publication_id uuid PRIMARY KEY,
            level integer,analyzed_at timestamptz,review_status text,signals jsonb);
            CREATE TABLE analytics.post_anomaly_context_recheck(publication_id uuid PRIMARY KEY,
            source_level integer,source_analyzed_at timestamptz,effective_level integer)""")
        for index, institution in enumerate((INSTITUTION,OTHER),1):
            db.execute("INSERT INTO catalog.visible_institution VALUES (%s,%s,NULL)",(institution,f"University {index}"))
            db.execute("INSERT INTO catalog.legacy_entity_alias VALUES (%s,'institutions',%s,NULL)",(institution,index))
        for index, (account,platform,institution) in enumerate(((TG,"telegram",INSTITUTION),
                    (VK,"vk",INSTITUTION),(VK_SECOND,"vk",INSTITUTION),
                    (UUID(int=100),"vk",OTHER)),1):
            db.execute("INSERT INTO catalog.visible_platform_account VALUES (%s,%s,%s,'external',NULL,'Account',NULL,'public',true)",
                       (account,institution,platform))
            db.execute("INSERT INTO catalog.legacy_entity_alias VALUES (%s,%s,%s,NULL)",
                       (account,"channels" if platform=="telegram" else "platform_accounts",index))

        def post(index, account, hours, level, *, analyzed=True, recheck=None, stale=False, deleted=False, created_future=False):
            id = UUID(int=1000+index)
            analyzed_at = AS_OF-timedelta(minutes=5) if analyzed else None
            db.execute("INSERT INTO ingest.publication VALUES (%s,%s,%s,%s,%s)",
                (id,account,AS_OF-timedelta(hours=hours),AS_OF+timedelta(minutes=1) if created_future else AS_OF-timedelta(days=50),AS_OF if deleted else None))
            if level is not None:
                db.execute("INSERT INTO analytics.post_anomaly_state VALUES (%s,%s,%s,'unreviewed','[{\"pattern\":1},{\"pattern\":2}]')",
                           (id,level,analyzed_at))
            if recheck is not None:
                db.execute("INSERT INTO analytics.post_anomaly_context_recheck VALUES (%s,%s,%s,%s)",
                    (id,level,analyzed_at-timedelta(minutes=1) if stale else analyzed_at,recheck))
        post(1,TG,2,3)
        post(2,TG,3,2)  # Exact lower boundary is excluded from the 3h window.
        post(3,TG,24,3)  # Exact 1d boundary.
        post(4,TG,8*24,3)
        post(5,VK,2,3,recheck=2)  # A valid cap moves the post into orange.
        post(6,VK_SECOND,2,3)
        post(7,VK,2,3,analyzed=False)  # Pending state is not a verdict.
        post(8,VK,2,3,recheck=1,stale=True)  # Stale cap must not hide red.
        post(9,VK,8*24,2)
        post(10,UUID(int=100),2,3)  # Another institution.
        post(11,VK,-1,3)  # Future publication.
        post(12,VK,2,3,deleted=True)
        post(13,VK,2,3,created_future=True)
        post(14,VK,2,1)  # Weak signal is neither red nor orange.
        post(15,VK,2,None)  # No analysis yet.
        yield db


def test_comparison_subscribers_use_last_valid_snapshot_without_turning_unknown_into_zero(connection):
    with connection.transaction(force_rollback=True):
        connection.execute("ALTER TABLE ingest.account_metric_snapshot_active ADD subscriber_quality text NOT NULL DEFAULT 'exact'")
        def snapshot(index, account, count, *, observed=None, collected=None, quality="exact", subscriber_quality="exact"):
            connection.execute("INSERT INTO ingest.account_metric_snapshot_active VALUES (%s,%s,%s,NULL,%s,%s,%s,%s)",
                (index,account,count,observed or AS_OF-timedelta(hours=1),
                 collected or AS_OF-timedelta(minutes=30),quality,subscriber_quality))
        snapshot(1,TG,123,observed=AS_OF-timedelta(hours=2))
        snapshot(2,TG,None)
        snapshot(3,TG,999,quality="invalid")
        snapshot(4,TG,999,subscriber_quality="invalid")
        snapshot(5,TG,999,observed=AS_OF+timedelta(minutes=1))
        snapshot(6,TG,999,collected=AS_OF+timedelta(minutes=1))
        snapshot(7,VK,100)
        snapshot(8,VK_SECOND,200)
        max_account=UUID(int=101)
        connection.execute("INSERT INTO catalog.visible_platform_account VALUES (%s,%s,'max','external',NULL,'Account',NULL,'public',true)", (max_account,INSTITUTION))
        snapshot(9,max_account,0)
        disabled_account=UUID(int=102)
        connection.execute("INSERT INTO catalog.visible_platform_account VALUES (%s,%s,'vk','external',NULL,'Account',NULL,'public',false)", (disabled_account,INSTITUTION))
        snapshot(10,disabled_account,999)
        rows={row["id"]:row for row in connection.execute(DASHBOARD_INSTITUTIONS,{"as_of":AS_OF}).fetchall()}
        assert rows[INSTITUTION]["telegram"] == 123
        assert rows[INSTITUTION]["vk"] == 300
        assert rows[INSTITUTION]["max"] == 0
        assert rows[INSTITUTION]["rutube"] is None
        assert rows[OTHER]["vk"] is None


@pytest.mark.parametrize("platform,period,entity,expected", [
    ("telegram","3h",TG,(0,1)),("telegram","1d",TG,(1,1)),
    ("telegram","7d",TG,(1,2)),("telegram","30d",TG,(1,3)),
    ("vk","3h",INSTITUTION,(1,2)),("vk","7d",INSTITUTION,(1,2)),
    ("vk","30d",INSTITUTION,(2,2)),("all","7d",INSTITUTION,(2,4)),
    ("vk","7d",OTHER,(0,1)),
])
def test_counts_follow_platform_period_and_effective_publication_level(connection,platform,period,entity,expected):
    rows = connection.execute(OVERVIEW,dict(as_of=AS_OF,platform=platform,period=period,
        sort="name",direction="asc",search="",after_id=None,fetch_limit=50)).fetchall()
    selected = [row for row in rows if row["entity_id"] == entity]
    assert selected
    # The account join may repeat a card row; it must not multiply its counts.
    for row in selected:
        assert (row["anomaly_level2_count"],row["anomaly_level3_count"]) == expected
        assert overview_row(row,[],1)["anomalyCounts"] == {"level2":expected[0],"level3":expected[1]}


@pytest.mark.parametrize("platform", ["all", "telegram", "vk", "max", "rutube"])
def test_default_sort_is_descending_anomalies(platform):
    query = overview_query(platform, "7d", "", None, None)
    assert (query.sort, query.direction) == ("anomalies", "desc")


@pytest.mark.parametrize("direction,order", [("desc",[INSTITUTION,OTHER]),("asc",[OTHER,INSTITUTION])])
def test_anomaly_sort_and_cursor_cover_the_whole_cohort(connection,direction,order):
    params=dict(as_of=AS_OF,platform="vk",period="7d",sort="anomalies",direction=direction,search="",after_id=None,fetch_limit=1)
    for entity in order:
        rows=connection.execute(OVERVIEW,params).fetchall()
        assert {row["entity_id"] for row in rows} == {entity}
        params["after_id"] = entity
    assert connection.execute(OVERVIEW,params).fetchall() == []


@pytest.mark.parametrize("sort", ["views", "reactions", "posts", "subscribers"])
def test_all_platform_totals_are_supported_sort_keys(sort):
    assert overview_query("all","1d","",sort,"asc").sort == sort


def test_all_platform_read_model_sums_accounts_and_pools_medians_without_filling_missing_metrics(connection):
    # Exercise the real refresh and read SQL together in a rollback-only local transaction.
    with connection.transaction(force_rollback=True):
        connection.execute("CREATE TABLE analytics.dataset_revision(committed_at timestamptz)")
        connection.execute("INSERT INTO analytics.dataset_revision VALUES (%s)",(AS_OF,))
        connection.execute("ALTER TABLE analytics.overview_card_metrics ADD computed_as_of timestamptz")
        connection.execute("""ALTER TABLE analytics.publication_latest
            ADD publication_id uuid, ADD institution_id uuid, ADD platform text,
            ADD synthetic boolean DEFAULT false, ADD quality text DEFAULT 'exact'""")
        for name in ("views", "reactions", "comments", "shares"):
            connection.execute(f"ALTER TABLE analytics.publication_latest ADD {name}_count bigint, ADD {name}_quality text DEFAULT 'exact'")
        connection.execute("""CREATE TABLE ingest.publication_metric_snapshot(
            id bigint,publication_id uuid,published_month date,observed_at timestamptz,
            synthetic boolean,quality text,views_count bigint,reactions_count bigint,
            comments_count bigint,shares_count bigint)""")
        for index,account,platform,institution,views,reactions,comments in [
            (1,TG,"telegram",INSTITUTION,10,2,0),
            (2,TG,"telegram",INSTITUTION,100,20,None),
            (5,VK,"vk",INSTITUTION,1000,200,4),
            (6,VK_SECOND,"vk",INSTITUTION,10000,2000,None),
            (10,UUID(int=100),"vk",OTHER,20000,4000,None),
        ]:
            connection.execute("""INSERT INTO analytics.publication_latest(
                platform_account_id,observed_at,publication_id,institution_id,platform,
                views_count,reactions_count,comments_count,shares_count) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NULL)""",
                (account,AS_OF,UUID(int=1000+index),institution,platform,views,reactions,comments))
        for index,(account,subscribers) in enumerate(((TG,100),(VK,200),(VK_SECOND,300),(UUID(int=100),999)),1):
            connection.execute("INSERT INTO ingest.account_metric_snapshot_active VALUES (%s,%s,%s,NULL,%s,%s,'exact')",
                               (index,account,subscribers,AS_OF,AS_OF))
        refresh = (Path(__file__).parents[1]/"db/tools/refresh-overview-card-metrics.sql").read_text()
        connection.execute(refresh.replace("BEGIN;","").replace("COMMIT;",""))
        params=dict(as_of=AS_OF,platform="all",period="1d",sort="views",direction="desc",search="",after_id=None,fetch_limit=1)
        first = connection.execute(OVERVIEW,params).fetchall()
        assert {row["entity_id"] for row in first} == {OTHER}
        params["after_id"] = OTHER
        rows = connection.execute(OVERVIEW,params).fetchall()
        assert len(rows) == 3  # Three accounts repeat the card, never its aggregate values.
        for row in rows:
            assert row["entity_id"] == INSTITUTION
            card = overview_row(row,[],1)
            assert card["views"]["total"] == 11110
            assert card["reactions"]["total"] == 2222
            assert card["views"]["median"] == 550  # Pooled posts, not 55 + 5500.
            assert card["comments"]["total"] == 4
            assert card["comments"]["totalMetadata"]["coverage"] == 0.5
            assert card["shares"]["total"] is None
            assert card["shares"]["totalTrend"] is None
            assert card["subscriberCount"] == 600
            assert card["accountCount"] == 3 and card["connectedPlatformCount"] == 2
