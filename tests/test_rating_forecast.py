"""Прогноз М-Рейтинга по соцсетям: чистый расчёт без базы."""
from __future__ import annotations

import math
from datetime import date, datetime, timezone

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

def test_period_month_round_trip():
    assert rf.period_month("Сентябрь 2026") == date(2026, 9, 1)
    assert rf.period_label(date(2026, 1, 1)) == "Январь 2026"
    with pytest.raises(ValueError):
        rf.period_month("September 2026")


def test_month_window_is_moscow_time():
    start, end = rf.month_window(date(2026, 9, 1))
    assert start == datetime(2026, 8, 31, 21, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 30, 21, tzinfo=timezone.utc)


def test_running_scale_mid_month_and_after_the_end():
    # 15 октября 12:00 по Москве: прошло 14.5 суток.
    assert rf.running_scale(date(2026, 10, 1), datetime(2026, 10, 15, 9, tzinfo=timezone.utc)) == (31 / 14.5, False)
    assert rf.running_scale(date(2026, 9, 1), datetime(2026, 10, 2, tzinfo=timezone.utc)) == (1.0, False)


def test_running_scale_on_the_first_day():
    # 00:30 по Москве 1-го числа: прошло полчаса, масштаб ограничен сутками, «слишком рано».
    scale, early = rf.running_scale(date(2026, 11, 1), datetime(2026, 10, 31, 21, 30, tzinfo=timezone.utc))
    assert (scale, early) == (30.0, True)


@pytest.mark.parametrize("day", [2, 8])
def test_running_scale_counts_elapsed_time_at_the_nightly_run(day):
    """Задание идёт в 01:47 по Москве: за d-е число данных ещё почти нет. Масштаб по
    целым суткам (÷ d) занижал публикации на ~50 % 2-го числа и на ~12 % 8-го."""
    as_of = datetime(2026, 10, day, 1, 47, tzinfo=rf.MOSCOW)
    elapsed = (day - 1) + (1 * 60 + 47) / 1440
    scale, _ = rf.running_scale(date(2026, 10, 1), as_of)
    assert scale == pytest.approx(31 / elapsed)
    assert rf.running_scale(date(2026, 11, 1), datetime(2026, 11, 7, 9, tzinfo=timezone.utc))[1] is False


def test_months_to_forecast_adds_the_unpublished_previous_month():
    as_of = datetime(2026, 11, 3, 22, 50, tzinfo=timezone.utc)  # 4 ноября по Москве
    published = {date(2026, 9, 1)}
    assert rf.months_to_forecast(as_of, published) == [(date(2026, 10, 1), "final"), (date(2026, 11, 1), "running")]
    published.add(date(2026, 10, 1))
    assert rf.months_to_forecast(as_of, published) == [(date(2026, 11, 1), "running")]


def test_base_month_is_the_latest_published_before():
    published = {date(2026, 8, 1), date(2026, 9, 1)}
    assert rf.base_month_for(date(2026, 11, 1), published) == date(2026, 9, 1)
    assert rf.base_month_for(date(2026, 9, 1), published) == date(2026, 8, 1)
    assert rf.base_month_for(date(2026, 8, 1), published) is None


def test_source_ignored_channel_two_months_in_a_row_predicts_zero():
    """Орловский ГАУ: MAX у источника 0 с июня при живом канале. Два опубликованных
    месяца подряд с нулём — источник канал не учитывает, прогноз тоже 0."""
    ours = institution("orel", {"max": month(100, views=100 * 500, interactions=5000), "vk": month(60),
                                "rutube": month(10)})
    scores = {"orel": {"social": 40, "max": 0, "vk": 60, "rutube": 30}}
    prior = {"orel": {"social": 41, "max": 0, "vk": 58, "rutube": 30}}
    base_month = rf.BaseMonth(period="Сентябрь 2026", scores=scores, names={"orel": "Вуз orel"}, prior=prior)
    row = rf.forecast([ours], base_month, ERRORS)[0]
    cell = row["explanation"]["categories"]["max"]
    assert (cell["score"], cell["source"]) == (0, "source_zero")
    assert row["explanation"]["platforms"]["max"]["subscores"]["posts"] == pytest.approx(100)
    assert row["score"] == pytest.approx(0.3 * row["explanation"]["categories"]["vk"]["score"]
                                         + 0.3 * row["explanation"]["categories"]["rutube"]["score"], abs=0.01)


def test_a_single_zero_month_keeps_the_formula():
    """БГТУ им. Шухова: MAX 0 только в сентябре — может быть разовый сбой, прогноз по формуле."""
    ours = institution("bstu", {"max": month(100, views=100 * 500, interactions=5000)})
    base_month = rf.BaseMonth(period="Сентябрь 2026", scores={"bstu": {"social": 30, "max": 0, "vk": 50, "rutube": 0}},
                              names={"bstu": "Вуз bstu"}, prior={"bstu": {"social": 50, "max": 57, "vk": 50, "rutube": 0}})
    cell = rf.forecast([ours], base_month, ERRORS)[0]["explanation"]["categories"]["max"]
    assert cell["source"] == "formula" and cell["score"] > 50


def test_source_zero_needs_our_active_channel():
    """Нет постов за месяц — это наш ноль по формуле, а не «источник не учитывает»."""
    ours = institution("quiet", {"max": month(0, viewed=0, views=0, interactions=0)})
    base_month = rf.BaseMonth(period="Сентябрь 2026", scores={"quiet": {"max": 0}}, names={},
                              prior={"quiet": {"max": 0}})
    cell = rf.forecast([ours], base_month, ERRORS)[0]["explanation"]["categories"]["max"]
    assert (cell["score"], cell["source"]) == (0, "formula")


def test_rutube_zeros_are_the_video_threshold_not_an_ignored_channel():
    """КГУ (Курск): Rutube 0 в августе (видео загружены в июле) и в сентябре (видео не
    было) — это порог «меньше 5 видео», а не неучтённый канал. В октябре 11 видео,
    прогноз должен остаться по формуле."""
    ours = institution("kursk", {"rutube": month(11)})
    base_month = rf.BaseMonth(period="Сентябрь 2026", scores={"kursk": {"rutube": 0}}, names={},
                              prior={"kursk": {"rutube": 0}})
    cell = rf.forecast([ours], base_month, ERRORS)[0]["explanation"]["categories"]["rutube"]
    assert cell["source"] == "formula" and cell["score"] > 0
