from datetime import datetime, timedelta, timezone
from dataclasses import replace
import importlib

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.database import Database
from app.web.app import create_app

web_app_module = importlib.import_module("app.web.app")


def settings(tmp_path):
    return Settings(
        telegram_api_id=None,
        telegram_api_hash=None,
        telegram_session_path=tmp_path / "telegram.session",
        database_path=tmp_path / "web.db",
        initial_channels=(),
        poll_interval_minutes=60,
        track_post_for_hours=336,
        complete_history_max_first_age_minutes=90,
        jump_min_abs=15,
        jump_min_ratio=2.0,
        web_host="127.0.0.1",
        web_port=8080,
        display_timezone="Europe/Vilnius",
        log_path=tmp_path / "app.log",
        discovery_limit=200,
        discovery_overlap=20,
    )


def test_dashboard_health_detail_compare_and_exports(tmp_path):
    cfg = settings(tmp_path)
    db = Database(cfg.database_path)
    db.migrate()
    channel_id = db.add_channel("example")
    now = datetime.now(timezone.utc) - timedelta(minutes=90)
    post_id = db.add_post(
        channel_id, "m:10", [10], None, now, now, 0, True, "text", False
    )
    db.insert_snapshot(post_id, now, 0, 2, {"👍": 2}, [], 60, 15, 2.0)
    db.insert_snapshot(
        post_id, now + timedelta(hours=1), 3600, 40, {"👍": 40}, [], 60, 15, 2.0
    )
    client = TestClient(create_app(cfg, db, lambda: True))

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["telegram_connected"] is True
    assert "poll_cycle" in health.json()
    for path in ("/", "/rating", f"/channels/{channel_id}", f"/posts/{post_id}", "/compare"):
        response = client.get(path)
        assert response.status_code == 200, response.text
    overview = client.get("/").text
    assert "m-ranked" in overview
    assert "Логотип m-ranked" in overview
    assert 'href="/static/favicon.png"' in overview
    assert "Telegram Reaction Monitor" not in overview
    assert "Монитор реакций" not in overview
    assert "медиана прироста реакций" in overview
    assert "медиана прироста просмотров" in overview
    assert "включая публикации, вышедшие раньше" in overview
    assert "не сумма текущих показателей только у новых постов" in overview
    assert ".overview-header{height:auto;min-height:0}" in overview
    assert ".has-tooltip.tooltip-open::after" in overview
    assert "event.target.closest('.has-tooltip[data-tooltip]')" in overview
    post_page = client.get(f"/posts/{post_id}").text
    assert "Масштаб по времени" in post_page
    assert "Мин. людей" in post_page
    assert "MAX_VISIBLE_POINTS=144" in post_page
    assert "Не отображено точек" in post_page
    assert "Накопление реакций и просмотров" in post_page
    assert 'id="accumulationLegend"' in post_page
    assert "Всего просмотров" in post_page
    assert "режиме 1:1 используется общая шкала" in post_page
    assert "fill:true,hidden:true" in post_page
    assert 'data-mode="shared"' in post_page
    assert 'data-mode="auto"' in post_page
    assert "totalChart.options.scales.yViews.display=auto" in post_page
    assert "POST_CHART_PREFERENCES_KEY='m-ranked:post-chart-preferences:v1'" in post_page
    assert "window.localStorage.setItem(POST_CHART_PREFERENCES_KEY" in post_page
    assert "applyScaleMode(postChartPreferences.scaleMode,false)" in post_page
    assert "postChartPreferences[index===0?'reactions':'views']=!visible" in post_page
    assert "общая шкала 1:1</small>" not in post_page
    assert 'id="snapshot-' in post_page
    assert "focusSnapshot(elements[0].index)" in post_page
    assert "snapshot-highlight" in post_page
    assert 'class="snapshot-jump"' in post_page
    assert "focusChart(button.dataset.snapshotId)" in post_page
    assert "setActiveElements" in post_page
    rating = client.get("/rating").text
    assert "Последний месяц" in rating
    assert 'id="rating-content"' in rating
    assert "Реакции / просмотры" in rating
    assert "Открыть пост в Telegram" in rating
    assert "Период: 30 дней" in rating
    assert 'name="post_sort" value="view_share"' in rating
    assert "example" in client.get("/export/posts.csv").text
    assert "40" in client.get("/export/snapshots.csv").text


def test_post_page_links_adjacent_channel_posts(tmp_path):
    cfg = settings(tmp_path)
    db = Database(cfg.database_path)
    db.migrate()
    channel_id = db.add_channel("adjacent")
    published = datetime.now(timezone.utc) - timedelta(hours=3)
    post_ids = [
        db.add_post(
            channel_id, f"m:{message_id}", [message_id], None,
            published + timedelta(hours=index), published + timedelta(hours=index),
            0, True, "text", False,
        )
        for index, message_id in enumerate((101, 102, 103))
    ]
    client = TestClient(create_app(cfg, db, lambda: True))

    page = client.get(f"/posts/{post_ids[1]}").text

    assert f'href="/posts/{post_ids[0]}" rel="prev"' in page
    assert "№101" in page
    assert f'href="/posts/{post_ids[2]}" rel="next"' in page
    assert "№103" in page


def test_overview_period_keeps_channels_without_posts_and_labels_new_medians(tmp_path):
    cfg = settings(tmp_path)
    db = Database(cfg.database_path)
    db.migrate()
    active_channel = db.add_channel("active_channel")
    db.add_channel("empty_channel")
    now = datetime.now(timezone.utc) - timedelta(minutes=10)
    post_id = db.add_post(
        active_channel, "m:20", [20], None, now, now, 0, True, "text", False,
    )
    db.insert_snapshot(post_id, now, 0, 0, {}, [], 60, 15, 2.0)
    db.insert_snapshot(
        post_id, now + timedelta(minutes=5), 300, 12, {"👍": 12}, [], 60, 15, 2.0,
    )
    second_post_id = db.add_post(
        active_channel, "m:21", [21], None, now + timedelta(minutes=1),
        now + timedelta(minutes=1), 0, True, "text", False,
    )
    db.insert_snapshot(
        second_post_id, now + timedelta(minutes=1), 0, 11, {"👍": 11}, [], 61, 15, 2.0,
    )
    client = TestClient(create_app(cfg, db, lambda: True))

    overview = client.get("/?period=3h&sort=median_reactions&direction=desc").text

    assert "active_channel" in overview
    assert "empty_channel" in overview
    assert 'class="grid section overview-grid"' in overview
    assert 'class="trend neutral"' not in overview
    assert "без изменений" not in overview
    assert "чел." not in overview
    assert "медиана прироста реакций" in overview
    assert "медиана прироста просмотров" in overview
    assert "11.5" not in overview
    assert 'class="post-stat-badges"' in overview
    assert "Всего постов в базе" in overview
    assert "<b>2</b>" in overview
    assert "Посты с двумя замерами за 3 часа" in overview
    assert "Прирост реакций всех постов за 3 часа" in overview
    assert "отслеживаются</span>" not in overview
    assert "новых</span>" not in overview


def test_overview_counts_activity_of_previously_published_posts(tmp_path):
    cfg = settings(tmp_path)
    db = Database(cfg.database_path)
    db.migrate()
    channel_id = db.add_channel("activity_channel")
    now = datetime.now(timezone.utc)
    post_id = db.add_post(
        channel_id, "m:30", [30], None, now - timedelta(days=2),
        now - timedelta(days=2), 0, True, "text", False,
    )
    db.insert_snapshot(
        post_id, now - timedelta(hours=4), 0, 10, {"👍": 10}, [], 60, 15, 2.0,
        views_count=100,
    )
    db.insert_snapshot(
        post_id, now - timedelta(hours=2), 0, 12, {"👍": 12}, [], 60, 15, 2.0,
        views_count=110,
    )
    db.insert_snapshot(
        post_id, now - timedelta(minutes=5), 0, 16, {"👍": 16}, [], 60, 15, 2.0,
        views_count=140,
    )
    client = TestClient(create_app(cfg, db, lambda: True))

    overview = client.get("/?period=3h&sort=reactions&direction=desc").text

    assert "activity_channel" in overview
    assert ">4</b><small>реакций за 3 часа" in overview
    assert ">30</b><small>просмотров за 3 часа" in overview
    assert ">+4</b>" not in overview
    assert ">+30</b>" not in overview


@pytest.mark.parametrize(
    ("period", "window", "period_short"),
    (("3h", timedelta(hours=3), "за 3 часа"),
     ("1d", timedelta(days=1), "за сутки"),
     ("7d", timedelta(days=7), "за неделю"),
     ("30d", timedelta(days=30), "за месяц")),
)
def test_overview_period_windows_use_fixed_open_left_boundary(
    tmp_path, monkeypatch, period, window, period_short,
):
    fixed_now = datetime(2026, 8, 29, 12, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(web_app_module, "datetime", FrozenDateTime)
    cfg = settings(tmp_path)
    db = Database(cfg.database_path)
    db.migrate()
    channel_id = db.add_channel(f"period_{period}")
    post_id = db.add_post(
        channel_id, "m:700", [700], None, fixed_now - timedelta(days=39),
        fixed_now - timedelta(days=39), 0, True, "text", False,
    )
    cutoff = fixed_now - window
    for measured_at, reactions, views in (
        (cutoff, 100, 1000),
        (cutoff + window / 2, 130, 1300),
        (fixed_now, 170, 1700),
    ):
        db.insert_snapshot(
            post_id, measured_at, 0, reactions, {"👍": reactions}, [],
            1, 15, 2.0, views_count=views,
        )
    page = TestClient(create_app(cfg, db, lambda: True)).get(
        f"/?period={period}&sort=reactions"
    ).text
    # The point exactly at the cutoff belongs to the previous window.  The
    # current delta therefore starts at the first point strictly after it.
    assert ">40</b><small>реакций" in page
    assert ">400</b><small>просмотров" in page
    assert f"Прирост реакций всех постов {period_short}." in page
    assert f"Посты, вышедшие {period_short}." in page


def test_overview_previous_period_and_even_median_are_compared_after_rounding(
    tmp_path, monkeypatch,
):
    fixed_now = datetime(2026, 8, 29, 12, tzinfo=timezone.utc)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(web_app_module, "datetime", FrozenDateTime)
    cfg = settings(tmp_path)
    db = Database(cfg.database_path)
    db.migrate()
    channel_id = db.add_channel("median_window")
    for index, (previous_delta, current_delta) in enumerate(((1, 2), (2, 3)), 1):
        post_id = db.add_post(
            channel_id, f"m:{800 + index}", [800 + index], None,
            fixed_now - timedelta(days=5), fixed_now - timedelta(days=5),
            0, True, "text", False,
        )
        values = (
            (fixed_now - timedelta(hours=47), 10),
            (fixed_now - timedelta(hours=25), 10 + previous_delta),
            (fixed_now - timedelta(hours=23), 20),
            (fixed_now, 20 + current_delta),
        )
        for measured_at, reactions in values:
            db.insert_snapshot(
                post_id, measured_at, 0, reactions, {"👍": reactions}, [],
                1, 15, 2.0, views_count=reactions * 10,
            )
    page = TestClient(create_app(cfg, db, lambda: True)).get("/?period=1d").text
    assert ">3</b><small>медиана прироста реакций" in page
    assert "+1 за сутки" in page


def test_comparison_exposes_one_fixed_sample_count_per_curve(tmp_path):
    cfg = settings(tmp_path)
    db = Database(cfg.database_path)
    db.migrate()
    channel_id = db.add_channel("fixed_cohort")
    published = datetime.now(timezone.utc) - timedelta(hours=25)
    for message_id, final in ((901, 20), (902, 40)):
        post_id = db.add_post(
            channel_id, f"m:{message_id}", [message_id], None,
            published, published, 0, True, "text", False,
        )
        db.insert_snapshot(post_id, published, 0, 0, {}, [], 1, 15, 2.0, views_count=0)
        db.insert_snapshot(
            post_id, published + timedelta(hours=24), 24 * 3600, final,
            {"👍": final}, [], 1, 15, 2.0, views_count=final * 10,
        )
    page = TestClient(create_app(cfg, db, lambda: True)).get(
        f"/compare?submitted=true&channels={channel_id}&period=24"
    ).text
    assert '"cohort_size": 2' in page
    assert '"sample_counts": [2, 2' in page
    assert "Выборка:" in page
    assert "dataset.cohortSize" in page


def test_overview_filters_keep_valid_values_and_reject_removed_period(tmp_path):
    cfg = settings(tmp_path)
    db = Database(cfg.database_path)
    db.migrate()
    db.add_channel("filters_channel")
    client = TestClient(create_app(cfg, db, lambda: True))

    for period in ("3h", "1d", "7d", "30d"):
        response = client.get(
            f"/?period={period}&sort=views&direction=asc",
        )
        assert response.status_code == 200
        assert f'value="{period}" selected' in response.text
        assert 'value="views" selected' in response.text
        assert 'value="asc" selected' in response.text
        assert 'value="40d"' not in response.text

    removed = client.get("/?period=40d&sort=unknown&direction=sideways")
    assert removed.status_code == 200
    assert 'value="1d" selected' in removed.text
    assert 'value="median_reactions" selected' in removed.text
    assert 'value="desc" selected' in removed.text


def test_overview_ascending_sort_keeps_missing_values_last(tmp_path):
    cfg = settings(tmp_path)
    db = Database(cfg.database_path)
    db.migrate()
    measured_channel = db.add_channel("measured_channel")
    db.add_channel("missing_channel")
    now = datetime.now(timezone.utc)
    post_id = db.add_post(
        measured_channel, "m:40", [40], None, now - timedelta(hours=2),
        now - timedelta(hours=2), 0, True, "text", False,
    )
    db.insert_snapshot(
        post_id, now - timedelta(hours=2), 0, 1, {"👍": 1}, [], 60, 15, 2.0,
        views_count=10,
    )
    db.insert_snapshot(
        post_id, now - timedelta(minutes=5), 0, 3, {"👍": 3}, [], 60, 15, 2.0,
        views_count=20,
    )
    client = TestClient(create_app(cfg, db, lambda: True))

    overview = client.get("/?period=3h&sort=views&direction=asc").text

    assert overview.index("measured_channel") < overview.index("missing_channel")


def test_overview_comparison_badge_keeps_sign_but_main_value_does_not(tmp_path):
    cfg = settings(tmp_path)
    db = Database(cfg.database_path)
    db.migrate()
    channel_id = db.add_channel("trend_channel")
    now = datetime.now(timezone.utc)
    post_id = db.add_post(
        channel_id, "m:50", [50], None, now - timedelta(days=2),
        now - timedelta(days=2), 0, True, "text", False,
    )
    for measured_at, reactions in (
        (now - timedelta(hours=5, minutes=30), 2),
        (now - timedelta(hours=3, minutes=30), 4),
        (now - timedelta(hours=2, minutes=30), 5),
        (now - timedelta(minutes=30), 9),
    ):
        db.insert_snapshot(
            post_id, measured_at, 0, reactions, {"👍": reactions}, [],
            60, 15, 2.0, views_count=reactions * 10,
        )
    client = TestClient(create_app(cfg, db, lambda: True))

    overview = client.get("/?period=3h").text

    assert ">4</b><small>медиана прироста реакций" in overview
    assert ">+4</b><small>медиана прироста реакций" not in overview
    assert overview.count("+2 за 3 часа") >= 2


def test_deleted_post_uses_tgstat_links(tmp_path):
    cfg = settings(tmp_path)
    db = Database(cfg.database_path)
    db.migrate()
    channel_id = db.add_channel("gubkin_university")
    now = datetime.now(timezone.utc)
    post_id = db.add_post(
        channel_id, "m:13850", [13850], None, now - timedelta(hours=1),
        now - timedelta(hours=1), 0, True, "text", False,
    )
    db.insert_snapshot(
        post_id, now - timedelta(minutes=50), 600, 2, {"👍": 2}, [],
        5, 15, 2.0, views_count=100,
    )
    db.insert_snapshot(
        post_id, now - timedelta(minutes=5), 3300, 4, {"👍": 4}, [],
        5, 15, 2.0, views_count=150,
    )
    db.mark_post_deleted(post_id, now)
    client = TestClient(create_app(cfg, db, lambda: True))
    tgstat_url = "https://tgstat.ru/channel/@gubkin_university/13850"

    channel_page = client.get(f"/channels/{channel_id}").text
    post_page = client.get(f"/posts/{post_id}").text
    rating_page = client.get("/rating?period=1d").text
    compare_page = client.get(
        f"/compare?submitted=true&channels={channel_id}&include_partial=true",
    ).text

    for page in (channel_page, post_page, rating_page):
        assert tgstat_url in page
        assert "удален" in page
    assert "Тепловая карта почасового прироста" not in compare_page
    assert "https://t.me/gubkin_university/13850" not in channel_page
    assert "https://t.me/gubkin_university/13850" not in post_page
    assert "https://t.me/gubkin_university/13850" not in rating_page
    assert "Темп набора результата" not in compare_page
    assert 'id="medianChart"' in compare_page
    assert 'id="conversionChart"' in compare_page
    assert 'id="channel-legend"' in compare_page
    assert "Тепловая карта почасового прироста" not in compare_page
    assert "Конверсия просмотров в реакции" in compare_page


def test_management_accepts_public_preview_link_and_deletes_channel(tmp_path):
    cfg = replace(settings(tmp_path), admin_password="test-password", admin_csrf_secret="test-csrf")
    db = Database(cfg.database_path)
    db.migrate()
    client = TestClient(create_app(cfg, db))
    auth = (cfg.admin_username, "test-password")

    added = client.post(
        "/manage/channels",
        data={"channel": "https://t.me/s/naukamsu", "csrf_token": "test-csrf"},
        auth=auth,
    )
    assert added.status_code == 200
    assert "Канал добавлен" in added.text
    assert 'class="channel-count-badge"' in added.text
    assert ">1</b><span>канал добавлен</span>" in added.text
    assert "Использование хранилища" in added.text
    assert "База результатов парсинга" in added.text
    assert 'role="progressbar"' in added.text
    channel = db.list_channels()[0]
    assert channel["username"] == "naukamsu"

    deleted = client.post(
        f"/manage/channels/{channel['id']}/delete",
        data={"csrf_token": "test-csrf"},
        auth=auth,
    )
    assert deleted.status_code == 200
    assert not db.list_channels()


def test_management_links_non_telegram_account_to_institution(tmp_path):
    cfg = replace(settings(tmp_path), admin_password="test-password", admin_csrf_secret="test-csrf")
    db = Database(cfg.database_path)
    db.migrate()
    client = TestClient(create_app(cfg, db))
    auth = (cfg.admin_username, "test-password")

    institution = client.post(
        "/manage/institutions",
        data={"name": "Тестовый университет", "short_name": "Тестовый вуз", "csrf_token": "test-csrf"},
        auth=auth,
    )
    assert institution.status_code == 200
    institution_id = int(db.list_institutions()[0]["id"])

    account = client.post(
        "/manage/platform-accounts",
        data={
            "institution_id": institution_id, "platform": "vk",
            "reference": "https://vk.com/test_university", "title": "Тестовый VK",
            "url": "", "csrf_token": "test-csrf",
        },
        auth=auth,
    )
    assert account.status_code == 200
    assert "Аккаунты привязаны к вузу" in account.text
    assert "ожидает токен" in account.text
    linked = db.list_platform_accounts(institution_id)
    assert len(linked) == 1
    assert linked[0]["external_key"] == "test_university"
    assert linked[0]["url"] == "https://vk.com/test_university"


def test_management_edits_institution_and_bulk_links_social_accounts(tmp_path):
    cfg = replace(settings(tmp_path), admin_password="test-password", admin_csrf_secret="test-csrf")
    db = Database(cfg.database_path)
    db.migrate()
    institution_id = db.add_institution("Старое полное название", "Старое")
    client = TestClient(create_app(cfg, db))
    auth = (cfg.admin_username, "test-password")

    updated = client.post(
        f"/manage/institutions/{institution_id}",
        data={"name": "Новое полное название", "short_name": "НПН", "csrf_token": "test-csrf"},
        auth=auth,
    )
    assert updated.status_code == 200
    assert "Названия вуза обновлены" in updated.text

    linked = client.post(
        f"/manage/institutions/{institution_id}/accounts",
        data={
            "telegram": "https://t.me/s/new_tg", "vk": "https://vk.com/new_vk",
            "max_account": "", "rutube": "", "csrf_token": "test-csrf",
        },
        auth=auth,
    )
    assert linked.status_code == 200
    assert "Аккаунты привязаны к вузу" in linked.text
    assert {row["platform"] for row in db.list_platform_accounts(institution_id)} == {
        "telegram", "vk",
    }
    channel = db.list_channels_with_institutions()[0]
    assert channel["institution_short_name"] == "НПН"
    overview = client.get("/").text
    assert 'data-tooltip="Новое полное название"' in overview
    assert '<span class="title-text">НПН</span><span class="title-info info-mark has-tooltip"' in overview
    assert ".m-rating-badge.has-tooltip{position:absolute}" in overview
    assert ".m-rating-badge.has-tooltip::after{top:calc(100% + 8px)" in overview
    assert ".overview-header .institution-title{display:inline-flex" in overview
    assert "Старое полное название" not in overview
    assert 'id="accountMatrix"' in linked.text
    assert linked.text.index('id="accountMatrix"') < linked.text.index('class="platform-form institution-create"')
    assert "Добавьте полное название для подсказок" in linked.text
    assert "Редактировать название" in linked.text
    db.add_platform_account(
        institution_id, "max", "max_without_username",
        url="https://max.ru/max_without_username",
    )
    management = client.get("/manage", auth=auth).text
    assert "max_without_username ↗" in management
    assert "@None" not in management
    assert "3 аккаунта · 1 вуз" in management

    rejected = client.post(
        f"/manage/institutions/{institution_id}/accounts",
        data={
            "telegram": "", "vk": "", "max_account": "javascript://unsafe",
            "rutube": "", "csrf_token": "test-csrf",
        },
        auth=auth,
    )
    assert rejected.status_code == 400
