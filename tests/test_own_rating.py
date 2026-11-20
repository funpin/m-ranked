"""«Наш рейтинг»: чистый расчёт без базы."""
from __future__ import annotations

import math

import pytest

from api import own_rating as own

F = own.FORMULA_V1


def account(platform="vk", covered=30.0, posts=100, active=30, viewed=None, views=None, interactions=None, **extra):
    viewed = posts if viewed is None else viewed
    views = viewed * 1000 if views is None else views
    interactions = views // 50 if interactions is None else interactions
    return own.AccountMonth(platform=platform, covered_days=covered, posts=posts, active_days=active,
                            viewed_posts=viewed, views=views, interactions=interactions, **extra)


def institution(key, *accounts, students=10000, name=None):
    return own.InstitutionMonth(institution_id=key, name=name or key, students=students, accounts=tuple(accounts))


def four(**overrides):
    return [overrides.get(platform, account(platform)) for platform in own.PLATFORMS]


def score(platform, item, students=10000, elapsed=30.0, days=30, **kwargs):
    return own.platform_score(platform, own.combine([item]) if item else None, students, elapsed, days, **kwargs)


def test_log_subscore_is_clipped_between_anchors():
    assert own.log_subscore(0.108, 0.108, 1.33) == 0
    assert own.log_subscore(1.33, 0.108, 1.33) == pytest.approx(100)
    assert own.log_subscore(5, 0.108, 1.33) == 100
    assert own.log_subscore(0, 0.108, 1.33) == 0 and own.log_subscore(None, 0.108, 1.33) == 0
    assert own.log_subscore(math.sqrt(0.108 * 1.33), 0.108, 1.33) == pytest.approx(50)


def test_activity_counts_days_not_posts():
    # 300 постов за 12 дней — регулярность по дням, объём не засчитывается.
    spam = score("vk", account(posts=300, active=12))
    regular = score("vk", account(posts=30, active=24))
    assert spam.subscores["activity"] == pytest.approx(50)
    assert regular.subscores["activity"] == 100
    # Rutube: 100 баллов уже от 8 дней с загрузками из 30.
    assert score("rutube", account("rutube", posts=8, active=8)).subscores["activity"] == pytest.approx(100)
    assert score("rutube", account("rutube", posts=4, active=4)).subscores["activity"] == pytest.approx(50)


def test_activity_is_a_share_of_collected_days():
    """Площадку добавили в середине месяца: 12 дней с постами из 15 собранных = 80 % → 100."""
    item = score("max", account("max", covered=15, posts=40, active=12), elapsed=31, days=31)
    assert item.source == "partial" and item.subscores["activity"] == pytest.approx(100)


def test_reach_divides_by_actual_students_without_floor():
    # 0.42 просмотра поста на студента — верх шкалы Telegram; у вуза на 263 студента это 111 просмотров.
    small = score("telegram", account("telegram", views=100 * 111), students=263)
    assert small.subscores["reach"] == pytest.approx(100)
    assert small.metrics["reach"] == pytest.approx(111 / 263, abs=1e-5)


def test_platform_without_account_is_zero_and_without_data_is_skipped():
    assert own.platform_score("telegram", None, 10000, 30, 30).score == 0
    assert own.platform_score("telegram", None, 10000, 30, 30).source == "no_account"
    gap = score("max", account("max", covered=10), elapsed=31, days=31)
    assert gap.score is None and gap.source == "no_data"
    # Начало месяца: собрано 3 дня из 3 — площадка не «без данных».
    assert score("vk", account(covered=3, posts=10, active=3), elapsed=3, days=31).source == "formula"


def test_abandoned_channel_scores_zero():
    """Решение владельца 20.11: заброшенный Telegram — 0, а не «нет данных»."""
    dead = score("telegram", account("telegram", posts=0, active=0, viewed=0, views=0, interactions=0))
    assert (dead.score, dead.source) == (0.0, "no_posts")


def test_small_samples_shrink_reach_and_engagement():
    two = score("rutube", account("rutube", posts=2, active=2, views=2 * 1000, interactions=2 * 1000 // 20))
    four_videos = score("rutube", account("rutube", posts=4, active=2, views=4 * 1000, interactions=4 * 1000 // 20))
    assert two.subscores["reach"] == pytest.approx(four_videos.subscores["reach"] / 2)
    assert two.subscores["engagement"] == pytest.approx(four_videos.subscores["engagement"] / 2)


def test_post_packs_are_removed_before_scoring():
    raw = account(views=100_000, interactions=4000, pack_views=20_000, pack_reactions=3000)
    clean = score("vk", raw)
    dirty = score("vk", raw, clean=False)
    assert clean.metrics["erv"] == pytest.approx(1000 / 80_000)
    assert dirty.metrics["erv"] == pytest.approx(0.04)
    assert clean.subscores["engagement"] < dirty.subscores["engagement"]
    # Пакет больше счётчика обрезается счётчиком поста.
    assert own.combine([account(views=100, interactions=10, pack_views=500, pack_reactions=50)]).pack_reactions == 10


def test_late_excess_and_packs_take_the_larger_not_the_sum():
    month = own.combine([account(interactions=1000, pack_reactions=300, late_share=0.2)])
    assert month.late_reactions == 200
    assert own.removed_interactions(month) == 300
    month = own.combine([account(interactions=1000, pack_reactions=100, late_share=0.5)])
    assert own.removed_interactions(month) == 500


def test_even_response_with_long_tail_caps_engagement_at_platform_median():
    even = dict(evenness=0.03, median_reactions=120, residuals=40)
    smart = account("max", interactions=27_000, late_share=0.13, **even)
    assert own.even_account(smart)
    # Ровный отклик без уверенного хвоста не ограничивается (мобилизованная аудитория).
    assert not own.even_account(account("max", interactions=27_000, **even))
    # Rutube правила ровности нет.
    assert not own.even_account(account("rutube", late_share=0.5, **even))
    capped = score("max", smart, erv_cap=0.02)
    assert capped.metrics["erv"] == 0.02 and capped.metrics["evenCapped"]
    assert score("max", smart, erv_cap=0.02, clean=False).metrics["evenCapped"] is False


def test_null_pack_sizes_do_not_write_off_whole_posts():
    """Регресс: least(NULL, x) в Postgres даёт x и списывает весь пост; здесь пакет 0 — это 0."""
    month = own.combine([account(views=10_000, interactions=500, pack_views=0, pack_reactions=0)])
    assert own.removed_interactions(month) == 0 and own.clean_erv(month) == pytest.approx(0.05)


def test_compute_ranks_equal_weights_and_reports_raw_rank():
    honest = institution("a", *four(), name="Альфа")
    packed = institution("b", *four(vk=account(views=100_000, interactions=6000, pack_reactions=4500),
                                    max=account("max", views=100_000, interactions=6000, pack_reactions=4500)), name="Бета")
    rows = own.compute([honest, packed], elapsed_days=30, days_in_month=30)
    by = {row["institutionId"]: row for row in rows}
    assert by["a"]["rank"] == 1 and by["b"]["rank"] == 2
    assert by["b"]["explanation"]["rawRank"] == 1
    assert set(by["a"]["explanation"]["platforms"]) == set(own.PLATFORMS)


def test_compute_skips_institutions_with_fewer_than_three_platforms():
    thin = institution("c", account("vk"), account("max", covered=5), account("telegram", covered=5),
                       account("rutube", covered=5))
    rows = own.compute([thin, institution("a", *four())], elapsed_days=30, days_in_month=30)
    assert [row["institutionId"] for row in rows] == ["a"]


def test_missing_platform_counts_zero_and_marks_partial_only_for_gaps():
    no_rutube = institution("d", *[account(platform) for platform in ("telegram", "vk", "max")])
    gap = institution("e", *four(telegram=account("telegram", covered=16)))
    rows = {row["institutionId"]: row for row in own.compute([no_rutube, gap], elapsed_days=31, days_in_month=31)}
    assert rows["d"]["explanation"]["platforms"]["rutube"]["source"] == "no_account"
    assert rows["d"]["explanation"]["partial"] is False
    assert rows["e"]["explanation"]["partial"] is True


def test_ties_are_ordered_by_name():
    rows = own.compute([institution("x", *four(), name="Яблоко"), institution("y", *four(), name="Арбуз")],
                       elapsed_days=30, days_in_month=30)
    assert [row["institutionId"] for row in rows] == ["y", "x"]


def test_formula_weights_are_equal():
    assert set(F["weights"].values()) == {0.25}
    assert set(F["weights"]) == set(own.PLATFORMS)
