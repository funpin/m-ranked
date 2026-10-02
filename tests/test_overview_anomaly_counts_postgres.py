"""Execute the overview query on an isolated local PostgreSQL read model."""
from datetime import datetime, timedelta, timezone
import os
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
import pytest

from api.dto import overview_row
from api.params import overview_query
from api.sql.overview import OVERVIEW

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
