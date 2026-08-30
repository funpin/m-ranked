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
    assert 'name="platform" value="telegram" checked' in overview
    assert 'name="platform" value="all"' in overview
    assert 'href="/?platform=telegram"' in overview
    assert 'href="/channels/' in overview and "?platform=telegram" in overview
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
    assert 'id="deltaLegend"' in post_page
    assert "Прирост просмотров" in post_page
    assert "borderColor:'#16a085'" in post_page
    assert "postChartPreferences.deltaViews" in post_page
    assert "applyDeltaScaleMode(postChartPreferences.deltaScaleMode,false)" in post_page
    assert 'class="snapshot-history-table"' in post_page
    assert 'class="reaction-cell"' in post_page
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

    assert f'href="/posts/{post_ids[0]}?platform=telegram" rel="prev"' in page
    assert "№101" in page
    assert f'href="/posts/{post_ids[2]}?platform=telegram" rel="next"' in page
    assert "№103" in page


def test_platform_context_never_falls_back_to_telegram_data(tmp_path):
    cfg = settings(tmp_path)
    db = Database(cfg.database_path)
    db.migrate()
    channel_id = db.add_channel("platform_context")
    channel = db.channel(channel_id)
    institution_id = int(channel["institution_id"])
    db.add_platform_account(
        institution_id, "vk", "platform_context_vk",
        username="platform_context_vk", title="Официальный VK",
        url="https://vk.com/platform_context_vk",
    )
    db.update_institution_m_rating(
        institution_id, {"vk": (7, 42.0)}, "Июль 2026",
        datetime.now(timezone.utc),
    )
    published = datetime.now(timezone.utc) - timedelta(hours=1)
    post_id = db.add_post(
        channel_id, "m:20", [20], None, published, published,
        0, True, "text", False,
    )
    db.insert_snapshot(
        post_id, published, 0, 999, {"👍": 999}, [], 60, 15, 2.0,
        views_count=9999,
    )
    client = TestClient(create_app(cfg, db, lambda: True))

    vk_overview = client.get("/?platform=vk").text
    assert "Обзор каналов" in vk_overview
    assert 'name="platform" value="vk" checked' in vk_overview
    assert "@platform_context_vk" in vk_overview
    assert "М‑Рейтинг ВК · №7" in vk_overview
    assert "9999" not in vk_overview
    assert "Данные других соцсетей в расчёт не попадают" in vk_overview
    assert 'href="/rating?platform=vk"' in vk_overview
    assert 'href="/compare?platform=vk"' in vk_overview
    assert 'href="/export/snapshots.csv?platform=vk"' in vk_overview

    rating = client.get("/rating?platform=vk").text
    assert "Рейтинг · ВКонтакте" in rating
    assert "Только публикации и замеры ВКонтакте" in rating
    assert "999" not in rating
    comparison = client.get("/compare?platform=vk").text
    assert "Сравнение · ВКонтакте" in comparison
    assert "Типичное накопление лайков" in comparison
    assert "999" not in comparison
    assert 'href="/?platform=vk"' in comparison

    redirect = client.get(
        f"/channels/{channel_id}?platform=vk", follow_redirects=False,
    )
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "/?platform=vk"
    assert client.get("/export/snapshots.csv?platform=vk").status_code == 200
    assert client.get("/export/posts.csv?platform=vk").status_code == 200

    fallback = client.get("/?platform=unknown").text
    assert "Обзор каналов" in fallback
    assert 'name="platform" value="telegram" checked' in fallback


def test_vk_vertical_pages_and_exports_use_only_vk_snapshots(tmp_path):
    cfg = replace(settings(tmp_path), vk_access_token="token")
    db = Database(cfg.database_path); db.migrate()
    institution_id = db.add_institution("Полное название", "ВУЗ")
    account_id = db.add_platform_account(
        institution_id, "vk", "official", title="VK вуза",
        url="https://vk.com/official",
    )
    now = datetime.now(timezone.utc).replace(microsecond=0)
    platform_post_id = db.upsert_platform_post(
        account_id, "-10_20", now - timedelta(hours=2), now - timedelta(hours=2),
        "photo", "https://vk.com/wall-10_20", {"id": 20},
    )
    db.insert_platform_snapshot(
        platform_post_id, now - timedelta(hours=1), 3600, 5,
        views_count=100, reactions_count=10, comments_count=2, shares_count=1, raw={},
    )
    db.insert_platform_snapshot(
        platform_post_id, now, 7200, 5,
        views_count=160, reactions_count=15, comments_count=4, shares_count=3, raw={},
    )
    client = TestClient(create_app(cfg, db))

    overview = client.get("/?platform=vk&period=3h").text
    assert "Публикации из БД с активностью за 3 часа" in overview
    assert "60" in overview
    assert f'/institutions/{institution_id}?platform=vk' in overview
    institution = client.get(f"/institutions/{institution_id}?platform=vk").text
    assert "публикаций в базе" in institution
    assert "с полной историей" in institution
    assert "медиана лайков" in institution
    assert f'/platform-posts/{platform_post_id}?platform=vk' in institution
    account = client.get(f"/platform-accounts/{account_id}?platform=vk").text
    assert f'/platform-posts/{platform_post_id}?platform=vk' in account
    publication = client.get(f"/platform-posts/{platform_post_id}?platform=vk").text
    assert "Накопление метрик" in publication
    assert "wall-10_20" in publication
    assert client.get(
        f"/platform-posts/{platform_post_id}?platform=max",
    ).status_code == 404
    assert "-10_20" in client.get("/export/posts.csv?platform=vk").text
    assert "160" in client.get("/export/snapshots.csv?platform=vk").text

    rating = client.get("/rating?platform=vk&period=1d").text
    assert "Рейтинг · ВКонтакте" in rating
    assert "ВУЗ" in rating
    assert f'/platform-posts/{platform_post_id}?platform=vk' in rating
    assert "Открыть публикацию VK" in rating


def test_vk_comparison_uses_fixed_platform_cohort_and_interactions(tmp_path):
    cfg = replace(settings(tmp_path), vk_access_token="token")
    db = Database(cfg.database_path); db.migrate()
    institution_id = db.add_institution("Полный тестовый вуз", "ТВУЗ")
    account_id = db.add_platform_account(
        institution_id, "vk", "test_vk", title="VK тестового вуза",
    )
    published = datetime.now(timezone.utc) - timedelta(days=2)
    for index, values in enumerate(((10, 20), (30, 50)), start=1):
        platform_post_id = db.upsert_platform_post(
            account_id, f"-1_{index}", published, published,
            "text", f"https://vk.com/wall-1_{index}", {},
        )
        db.insert_platform_snapshot(
            platform_post_id, published, 0, 5,
            views_count=100, reactions_count=values[0],
            comments_count=2, shares_count=1, raw={},
        )
        db.insert_platform_snapshot(
            platform_post_id, published + timedelta(hours=24), 24 * 3600, 60,
            views_count=200, reactions_count=values[1],
            comments_count=4, shares_count=2, raw={},
        )
    telegram_channel = db.add_channel("telegram_only")
    telegram_post = db.add_post(
        telegram_channel, "m:999", [999], None, published, published,
        0, True, "text", False,
    )
    db.insert_snapshot(
        telegram_post, published + timedelta(hours=24), 24 * 3600,
        9999, {"👍": 9999}, [], 60, 15, 2.0, views_count=10000,
    )
    client = TestClient(create_app(cfg, db))

    page = client.get(
        f"/compare?platform=vk&submitted=true&institutions={institution_id}&period=24",
    ).text

    assert "Сравнение · ВКонтакте" in page
    assert "ТВУЗ" in page
    assert '"cohort_size": 2' in page
    assert '"sample_counts": [2, 2' in page
    assert "9999" not in page
    assert "Взаимодействия / просмотры, медиана" in page


def test_rutube_rating_and_comparison_use_views_only(tmp_path):
    cfg = settings(tmp_path)
    db = Database(cfg.database_path); db.migrate()
    institution_id = db.add_institution("Полный видео-вуз", "ВИДЕОВУЗ")
    account_id = db.add_platform_account(
        institution_id, "rutube", "video-channel", title="Rutube видео-вуза",
        url="https://rutube.ru/channel/123/",
    )
    published = datetime.now(timezone.utc) - timedelta(days=2)
    post_ids = []
    for index, values in enumerate(((100, 300), (200, 500)), start=1):
        post_id = db.upsert_platform_post(
            account_id, f"video-{index}", published, published,
            "video", f"https://rutube.ru/video/{index}/", {},
        )
        post_ids.append(post_id)
        db.insert_platform_snapshot(
            post_id, published, 0, 5, views_count=values[0],
            reactions_count=None, comments_count=None, shares_count=None, raw={},
        )
        db.insert_platform_snapshot(
            post_id, published + timedelta(hours=24), 24 * 3600, 60,
            views_count=values[1], reactions_count=None,
            comments_count=None, shares_count=None, raw={},
        )
    telegram_channel = db.add_channel("telegram_not_rutube")
    telegram_post = db.add_post(
        telegram_channel, "m:777", [777], None, published, published,
        0, True, "text", False,
    )
    db.insert_snapshot(
        telegram_post, published + timedelta(hours=24), 24 * 3600,
        7777, {"👍": 7777}, [], 60, 15, 2.0, views_count=77777,
    )
    client = TestClient(create_app(cfg, db))

    rating = client.get("/rating?platform=rutube&period=7d").text
    assert "Рейтинг · Rutube" in rating
    assert "Среднее просмотров" in rating
    assert "Просмотры всего" in rating
    assert "Rutube публично отдаёт просмотры" in rating
    assert "Вовлечённость:" not in rating
    assert f"/platform-posts/{post_ids[0]}?platform=rutube" in rating
    assert "77777" not in rating

    comparison = client.get(
        f"/compare?platform=rutube&submitted=true&institutions={institution_id}&period=24",
    ).text
    assert "Сравнение · Rutube" in comparison
    assert "Типичное накопление просмотров" in comparison
    assert "metricAxis" in comparison
    assert '"cohort_size": 2' in comparison
    assert '"sample_counts": [2, 2' in comparison
    assert "Вовлечённость от просмотров" not in comparison
    assert "77777" not in comparison


@pytest.mark.parametrize(("platform", "token_field"), (
    ("max", "max_access_token"),
    ("rutube", None),
))
def test_non_telegram_platforms_reuse_overview_and_channel_layout(
    tmp_path, platform, token_field,
):
    cfg = settings(tmp_path)
    if token_field:
        cfg = replace(cfg, **{token_field: "token"})
    db = Database(cfg.database_path); db.migrate()
    institution_id = db.add_institution("Единый дизайн университета", "ЕДУ")
    account_id = db.add_platform_account(
        institution_id, platform, f"{platform}-official",
        username=f"{platform}_official", title=f"{platform.upper()} вуза",
        url=f"https://example.test/{platform}",
    )
    now = datetime.now(timezone.utc).replace(microsecond=0)
    post_id = db.upsert_platform_post(
        account_id, f"{platform}-post", now - timedelta(hours=2),
        now - timedelta(hours=2), "video", f"https://example.test/{platform}/post", {},
    )
    db.insert_platform_snapshot(
        post_id, now - timedelta(hours=1), 3600, 5,
        views_count=100, reactions_count=None,
        comments_count=2 if platform == "max" else None,
        shares_count=1 if platform == "max" else None, raw={},
    )
    db.insert_platform_snapshot(
        post_id, now, 7200, 5, views_count=160, reactions_count=None,
        comments_count=4 if platform == "max" else None,
        shares_count=2 if platform == "max" else None, raw={},
    )
    client = TestClient(create_app(cfg, db))

    overview = client.get(f"/?platform={platform}&period=3h").text
    assert "Обзор каналов" in overview
    assert f'href="/institutions/{institution_id}?platform={platform}"' in overview
    assert f"@{platform}_official" in overview
    assert 'aria-label="Публикации за 3 часа"' in overview
    assert "медиана прироста просмотров" in overview
    assert '<div class="platform-card-accounts">' not in overview

    institution = client.get(
        f"/institutions/{institution_id}?platform={platform}",
    ).text
    assert "ЕДУ" in institution
    assert f"@{platform}_official" in institution
    assert 'class="metrics channel-metrics"' in institution
    assert "публикаций в базе" in institution
    assert f'/platform-posts/{post_id}?platform={platform}' in institution
    assert "Опубликовано, МСК" in institution
    assert "Возраст" in institution
    assert "История" in institution


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
    assert "Посты из БД с активностью за 3 часа" in overview
    assert "Прирост реакций всех постов из БД за 3 часа" in overview
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
    assert f"Прирост реакций всех постов из БД {period_short}." in page
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


def test_comparison_partial_history_uses_one_fixed_sample(tmp_path):
    cfg = settings(tmp_path)
    db = Database(cfg.database_path)
    db.migrate()
    channel_id = db.add_channel("partial_curve")
    published = datetime.now(timezone.utc) - timedelta(hours=25)
    complete_horizon = db.add_post(
        channel_id, "m:903", [903], None, published, published,
        30 * 60, False, "text", False,
    )
    db.insert_snapshot(
        complete_horizon, published + timedelta(minutes=30), 30 * 60, 5,
        {"👍": 5}, [], 1, 15, 2.0, views_count=50,
    )
    db.insert_snapshot(
        complete_horizon, published + timedelta(hours=24), 24 * 3600, 25,
        {"👍": 25}, [], 1, 15, 2.0, views_count=250,
    )
    ends_early = db.add_post(
        channel_id, "m:904", [904], None, published, published,
        30 * 60, False, "text", False,
    )
    db.insert_snapshot(
        ends_early, published + timedelta(minutes=30), 30 * 60, 100,
        {"👍": 100}, [], 1, 15, 2.0, views_count=500,
    )
    db.insert_snapshot(
        ends_early, published + timedelta(hours=3), 3 * 3600, 300,
        {"👍": 300}, [], 1, 15, 2.0, views_count=1000,
    )

    client = TestClient(create_app(cfg, db, lambda: True))
    partial_page = client.get(
        f"/compare?submitted=true&channels={channel_id}&period=24&include_partial=true"
    ).text
    assert '"cohort_size": 1' in partial_page
    assert '"curve": [null, 5.0, 5.0' in partial_page
    assert '"sample_counts": [0, 1, 1, 1' in partial_page
    assert '25.0]' in partial_page
    assert '300.0' not in partial_page
    assert "Неполная история включена:" in partial_page
    assert "Выборка внутри линии не меняется." in partial_page
    assert "недостаточно замеров" not in partial_page

    full_page = client.get(
        f"/compare?submitted=true&channels={channel_id}&period=24"
    ).text
    assert '"cohort_size": 0' in full_page
    assert "недостаточно замеров" in full_page


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


def test_management_uses_unified_account_controls_for_telegram(tmp_path):
    cfg = replace(settings(tmp_path), admin_password="test-password", admin_csrf_secret="test-csrf")
    db = Database(cfg.database_path)
    db.migrate()
    client = TestClient(create_app(cfg, db))
    auth = (cfg.admin_username, "test-password")

    client.post(
        "/manage/institutions",
        data={"name": "МГУ имени М.В. Ломоносова", "short_name": "МГУ", "csrf_token": "test-csrf"},
        auth=auth,
    )
    institution_id = int(db.list_institutions()[0]["id"])
    added = client.post(
        f"/manage/institutions/{institution_id}/accounts",
        data={
            "telegram": "https://t.me/s/naukamsu", "vk": "",
            "max_account": "", "rutube": "", "csrf_token": "test-csrf",
        },
        auth=auth,
    )
    assert added.status_code == 200
    assert "Аккаунты сохранены" in added.text
    assert 'class="channel-count-badge"' in added.text
    assert ">1</b><span>канал добавлен</span>" in added.text
    assert "Использование хранилища" in added.text
    assert "База результатов парсинга" in added.text
    assert 'role="progressbar"' in added.text
    assert "МГУ (МГУ имени М.В. Ломоносова)" in added.text
    assert "Общий М‑Рейтинг —" in added.text
    assert "М‑Рейтинг TELEGRAM —" in added.text
    assert 'data-telegram="https://t.me/naukamsu"' in added.text
    assert "Быстро добавить отдельный Telegram-канал" not in added.text
    assert '<th>Название</th><th>Подписчики</th>' not in added.text
    channel = db.list_channels()[0]
    assert channel["username"] == "naukamsu"
    account_id = int(channel["platform_account_id"])

    disabled = client.post(
        f"/manage/platform-accounts/{account_id}/disable",
        data={"csrf_token": "test-csrf"},
        auth=auth,
    )
    assert disabled.status_code == 200
    assert "История сохранена" in disabled.text
    assert not db.channel(int(channel["id"]))["enabled"]

    deleted = client.post(
        f"/manage/platform-accounts/{account_id}/delete",
        data={"csrf_token": "test-csrf"}, auth=auth,
    )
    assert deleted.status_code == 200
    assert not db.list_channels()
    assert len(db.list_institutions()) == 1


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
    assert "Аккаунты сохранены" in account.text
    assert "нужен токен" in account.text
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
    assert "Аккаунты сохранены" in linked.text
    assert {row["platform"] for row in db.list_platform_accounts(institution_id)} == {
        "telegram", "vk",
    }
    channel = db.list_channels_with_institutions()[0]
    assert channel["institution_short_name"] == "НПН"
    overview = client.get("/").text
    assert 'data-floating-tooltip="Новое полное название"' in overview
    assert 'class="institution-title"' in overview
    assert '<span class="title-text">НПН</span><span class="title-info info-mark"' in overview
    assert ".m-rating-badge.has-tooltip{position:absolute}" in overview
    assert ".m-rating-badge.has-tooltip::after{top:calc(100% + 8px)" in overview
    assert ".overview-header .institution-title{display:inline-flex" in overview
    assert 'id="floatingTooltip"' in overview
    assert "target.dataset.floatingTooltip" in overview
    assert "Старое полное название" not in overview
    assert 'id="accountMatrix"' in linked.text
    assert linked.text.index('id="accountMatrix"') < linked.text.index('class="platform-form institution-create"')
    assert "Полное название показывается в подсказках" in linked.text
    assert "Редактировать название" in linked.text
    db.add_platform_account(
        institution_id, "max", "max_without_username",
        url="https://max.ru/max_without_username",
    )
    management = client.get("/manage", auth=auth).text
    assert "max_without_username ↗" in management
    assert "@None" not in management
    assert "3 аккаунта · 1 вуз" in management
    assert "НПН (Новое полное название)" in management
    assert 'data-telegram="https://t.me/new_tg"' in management
    assert 'data-vk="https://vk.com/new_vk"' in management
    assert "Быстро добавить отдельный Telegram-канал" not in management
    assert "/manage/platform-accounts/" in management
    assert ">Удалить</button>" in management

    rejected = client.post(
        f"/manage/institutions/{institution_id}/accounts",
        data={
            "telegram": "", "vk": "", "max_account": "javascript://unsafe",
            "rutube": "", "csrf_token": "test-csrf",
        },
        auth=auth,
    )
    assert rejected.status_code == 400
