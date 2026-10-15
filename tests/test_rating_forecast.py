"""Прогноз М-Рейтинга по соцсетям: чистый расчёт без базы."""
from __future__ import annotations

import math

import pytest

from api import rating_forecast as rf


def month(posts=50, viewed=None, views=None, interactions=None, covered=True):
    viewed = posts if viewed is None else viewed
    views = viewed * 1000 if views is None else views
    interactions = views // 50 if interactions is None else interactions
    return rf.PlatformMonth(posts=posts, viewed_posts=viewed, views=views,
                            interactions=interactions, covered=covered)


def test_subscore_is_a_clipped_log_scale():
    assert rf.subscore(20, 20, 100) == 0
    assert rf.subscore(100, 20, 100) == 100
    assert rf.subscore(500, 20, 100) == 100
    assert rf.subscore(0, 20, 100) == 0 and rf.subscore(None, 20, 100) == 0
    assert rf.subscore(math.sqrt(20 * 100), 20, 100) == pytest.approx(50)


def test_vk_score_is_the_mean_of_three_subscores():
    # 100 постов → 100; 3 просмотра на студента → 100; ERV 4 % → 100.
    full = rf.platform_score("vk", month(100, views=100 * 3000, interactions=12000), 1000, None)
    assert full.score == pytest.approx(100) and full.source == "formula"
    # Те же посты и ERV, просмотры на нижней границе → (100 + 0 + 100) / 3.
    low_views = rf.platform_score("vk", month(100, views=100 * 100, interactions=400), 1000, None)
    assert low_views.score == pytest.approx(200 / 3)
    assert set(low_views.subscores) == {"posts", "views", "erv"}


def test_max_uses_its_own_thresholds():
    # 0.5 просмотра на студента — верх шкалы MAX, но середина шкалы VK.
    max_score = rf.platform_score("max", month(100, views=100 * 500, interactions=5000), 1000, None)
    vk_score = rf.platform_score("vk", month(100, views=100 * 500, interactions=5000), 1000, None)
    assert max_score.subscores["views"] == pytest.approx(100)
    assert vk_score.subscores["views"] < 60


def test_missing_students_zeroes_only_the_views_subscore():
    score = rf.platform_score("vk", month(100, views=100 * 3000, interactions=12000), None, None)
    assert score.subscores["views"] == 0
    assert score.subscores["posts"] == pytest.approx(100) and score.subscores["erv"] == pytest.approx(100)
    assert score.metrics["students"] is None


def test_rutube_threshold_and_official_blend():
    assert rf.platform_score("rutube", month(4), None, 60).score == 0
    own = min(100, 12 * math.log(10))
    assert rf.platform_score("rutube", month(10), None, None).score == pytest.approx(own)
    assert rf.platform_score("rutube", month(10), None, 0).score == pytest.approx(own)
    assert rf.platform_score("rutube", month(10), None, 60).score == pytest.approx(0.5 * own + 30)


def test_scale_extrapolates_posts_but_not_views_or_erv():
    plain = rf.platform_score("vk", month(30), 1000, None)
    scaled = rf.platform_score("vk", month(30), 1000, None, scale=2.0)
    assert scaled.subscores["posts"] > plain.subscores["posts"]
    assert scaled.subscores["views"] == plain.subscores["views"]
    assert scaled.subscores["erv"] == plain.subscores["erv"]
    assert scaled.metrics["posts"] == 30 and scaled.metrics["postsExtrapolated"] == 60
    # Порог Rutube проверяется по экстраполированному числу видео.
    assert rf.platform_score("rutube", month(3), None, None, scale=2.0).score > 0


def test_uncovered_platform_takes_the_base_official_score():
    score = rf.platform_score("vk", month(5, covered=False), 1000, 64.1)
    assert (score.score, score.source) == (64.1, "fallback")
    assert rf.platform_score("vk", month(5, covered=False), 1000, None).score == 0


def test_missing_account_scores_zero():
    score = rf.platform_score("max", None, 1000, 80)
    assert (score.score, score.source) == (0, "no_account")


def test_rank_in_pool_breaks_ties_by_name():
    ranks = rf.rank_in_pool({"a": 50, "b": 70, "c": 50}, {"a": "Яблоко", "b": "Б", "c": "Арбуз"})
    assert ranks == {"b": 1, "c": 2, "a": 3}


def test_rank_range_brackets_the_rank():
    pool = {"x": 60.0, "a": 70.0, "b": 64.0, "c": 58.0, "d": 40.0}
    assert rf.rank_range("x", 60.0, 5.0, pool) == (2, 4)
    assert rf.rank_range("x", 60.0, 0.0, pool) == (3, 3)


def base(scores, names=None):
    return rf.BaseMonth(period="Сентябрь 2026", scores=scores,
                        names=names or {code: f"Вуз {code}" for code in scores})


def institution(code, platforms, students=1000):
    return rf.InstitutionMonth(institution_id=f"id-{code}", code=code, name=f"Вуз {code}",
                               students=students, platforms=platforms)


ERRORS = {"social": 7, "max": 10, "vk": 9, "rutube": 8}


def test_balanced_institution_ranks_above_single_platform_leaders():
    """Пункт A: СКФУ — 8-й по соцсетям при 27/38/13 местах на площадках.

    Соцсети — взвешенная сумма баллов: ровно сильный вуз обходит лидеров
    одной площадки. Места не выводятся из мест на площадках.
    """
    others = {
        "max-leader": {"social": 0.4 * 95 + 0.3 * 40 + 0.3 * 0, "max": 95, "vk": 40, "rutube": 0},
        "vk-leader": {"social": 0.4 * 50 + 0.3 * 95 + 0.3 * 0, "max": 50, "vk": 95, "rutube": 0},
        "rt-leader": {"social": 0.4 * 40 + 0.3 * 40 + 0.3 * 95, "max": 40, "vk": 40, "rutube": 95},
    }
    balanced = institution("balanced", {
        "max": month(70, views=70 * 300, interactions=70 * 300 // 25),
        "vk": month(70, views=70 * 1500, interactions=70 * 1500 // 40),
        "rutube": month(40)})
    rows = rf.forecast([balanced], base({**others, "balanced": {"social": 50, "max": 70, "vk": 70, "rutube": 50}}), ERRORS)
    categories = rows[0]["explanation"]["categories"]
    assert categories["social"]["rank"] == 1
    assert all(categories[p]["rank"] > 1 for p in ("max", "vk", "rutube"))
    assert rows[0]["rank"] == categories["social"]["rank"]
    assert rows[0]["score"] == pytest.approx(0.4 * categories["max"]["score"] + 0.3 * categories["vk"]["score"]
                                             + 0.3 * categories["rutube"]["score"], abs=0.01)


def test_forecast_ranks_among_the_whole_official_pool():
    pool = {f"o{i}": {"social": 90 - i, "max": 90 - i, "vk": 90 - i, "rutube": 90 - i} for i in range(10)}
    ours = institution("us", {"max": month(1), "vk": month(1), "rutube": month(0)})
    rows = rf.forecast([ours], base({**pool, "us": {"social": 99, "max": 99, "vk": 99, "rutube": 99}}), ERRORS)
    # Наш прогноз заменяет наш же официальный балл; прочие 10 вузов — выше.
    assert rows[0]["rank"] == 11
    assert rows[0]["explanation"]["categories"]["social"]["baseRank"] == 1


def test_fallback_marks_social_as_partial_and_keeps_platform_source():
    ours = institution("us", {"max": month(60), "vk": month(60, covered=False), "rutube": month(10)})
    rows = rf.forecast([ours], base({"us": {"social": 50, "max": 60, "vk": 64.1, "rutube": 20}}), ERRORS)
    explanation = rows[0]["explanation"]
    assert explanation["categories"]["social"]["source"] == "partial"
    assert explanation["categories"]["vk"]["source"] == "fallback"
    assert explanation["categories"]["vk"]["score"] == pytest.approx(64.1)
    assert explanation["platforms"]["vk"]["source"] == "fallback"


def test_base_consolidated_rank_is_kept_when_present():
    scores = {"a": {"social": 1, "max": 1, "vk": 1, "rutube": 1, "consolidated": 30},
              "us": {"social": 1, "max": 1, "vk": 1, "rutube": 1, "consolidated": 40}}
    rows = rf.forecast([institution("us", {})], base(scores), ERRORS)
    assert rows[0]["explanation"]["baseConsolidatedRank"] == 1
    rows = rf.forecast([institution("us", {})], base({"us": {"social": 1, "max": 1, "vk": 1, "rutube": 1}}), ERRORS)
    assert rows[0]["explanation"]["baseConsolidatedRank"] is None


def test_typical_errors_need_twenty_pairs():
    predicted = {str(i): {"social": 50.0, "max": 50.0, "vk": 50.0, "rutube": 50.0} for i in range(20)}
    actual = {str(i): {"social": 54.0, "max": 40.0, "vk": None, "rutube": 50.0} for i in range(20)}
    errors = rf.typical_errors(predicted, actual, ERRORS)
    assert errors == {"social": 4.0, "max": 10.0, "vk": 9, "rutube": 0.0}
    assert rf.typical_errors(dict(list(predicted.items())[:5]), actual, ERRORS) == ERRORS


def test_evaluate_reports_errors_and_top20():
    predicted = {str(i): float(100 - i) for i in range(30)}
    actual = dict(predicted)
    ranks = {str(i): i + 1 for i in range(30)}
    result = rf.evaluate(predicted, actual, ranks, ranks)
    assert result["mae"] == 0 and result["rankMedian"] == 0 and result["spearman"] == pytest.approx(1)
    assert (result["top20Hits"], result["top20Total"]) == (20, 20)
