"""М-Рейтинг без накрутки: чистый расчёт, тело ответа по контракту."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from api import rating_clean as rc, rating_forecast as rf
from api.routes import rating
from test_rating_routes import validate


def month(posts=120, views=120 * 2000, interactions=None, covered=True):
    return rf.PlatformMonth(posts=posts, viewed_posts=posts, views=views,
                            interactions=views * 3 // 100 if interactions is None else interactions, covered=covered)


def institution(code, platforms, students=10000):
    return rf.InstitutionMonth(institution_id=f"00000000-0000-0000-0000-{int(code):012d}", code=code, name=code,
                               students=students, platforms=platforms)


def basis(**scores):
    return {code: {"social": value, "max": value, "vk": value, "rutube": 30.0} for code, value in scores.items()}


NAMES = {"1": "А", "2": "Б", "3": "В", "4": "Г"}


def test_reaction_packs_lower_the_score_and_the_place():
    # «1» на месте 1, но 60 % его реакций — пакеты: ERV VK 3 % → 1.2 %.
    institutions = [institution("1", {"vk": month(), "max": month()})]
    rows = rc.clean_month(institutions, {("1", "vk"): rc.Inflation(reactions=int(0.6 * 120 * 2000 * 0.03))},
                          basis(**{"1": 70.0, "2": 69.0, "3": 60.0}), NAMES, basis_kind="fact", formula=rf.FORMULA_V2)
    social = rows[0]["explanation"]["categories"]["social"]
    vk = rows[0]["explanation"]["platforms"]["vk"]
    assert vk["cleanScore"] < vk["rawScore"] and vk["removedReactions"] == 4320
    assert social["baseRank"] == 1 and social["rank"] == 2
    assert social["score"] == pytest.approx(70.0 - 0.3 * (vk["rawScore"] - vk["cleanScore"]), abs=0.01)
    # MAX без накрутки не меняется; Rutube не трогается.
    cells = rows[0]["explanation"]["categories"]
    assert cells["max"]["score"] == 70.0 and cells["rutube"]["score"] == 30.0


def test_views_alone_can_raise_the_engagement_share():
    # Только накрученные просмотры: ERV растёт, балл может не упасть — так и задумано.
    institutions = [institution("1", {"vk": month(views=120 * 2000, interactions=120 * 2000 // 50)})]
    rows = rc.clean_month(institutions, {("1", "vk"): rc.Inflation(views=120 * 1000)},
                          basis(**{"1": 50.0}), NAMES, basis_kind="fact", formula=rf.FORMULA_V2)
    vk = rows[0]["explanation"]["platforms"]["vk"]
    assert vk["removedViews"] == 120000 and vk["cleanScore"] >= vk["rawScore"] - 5


def test_uncovered_or_absent_platforms_keep_their_base():
    institutions = [institution("1", {"vk": month(covered=False)}), institution("4", {"vk": month()})]
    rows = rc.clean_month(institutions, {("1", "vk"): rc.Inflation(reactions=10_000)},
                          basis(**{"1": 50.0, "2": 40.0}), NAMES, basis_kind="fact", formula=rf.FORMULA_V2)
    # «4» нет в официальном рейтинге — не показывается; «1» без полной истории — без сдвига.
    assert [row["explanation"]["code"] for row in rows] == ["1"]
    assert rows[0]["score"] == 50.0 and rows[0]["explanation"]["platforms"] == {}


def smart_row(**changes):
    row = {"residuals": 150, "evenness": 0.02, "median_reactions": 250.0, "tail_ratio": 1.4, "tail_p90": 0.75,
           "tail_median": 0.24, "late_reactions": 4000.0, "early_reactions": 21000.0, "late_views": 12000.0,
           "early_rate": 0.25}
    row.update(changes)
    return row


def test_smart_inflation_needs_an_even_response_and_a_long_tail():
    found = rc.smart_account(smart_row(), "max", interactions=50_000)
    # Ожидаемый хвост: 12000 × 0.25 × 0.24 = 720; лишние 3280 из 25000 реакций окна = 13.1 %.
    assert found is not None and found.reactions == round(3280 / 25000 * 50_000)
    assert rc.smart_account(smart_row(evenness=0.3), "max", 50_000) is None      # обычный разброс
    assert rc.smart_account(smart_row(evenness=0.2), "vk", 50_000) is not None    # у VK порог выше
    assert rc.smart_account(smart_row(tail_ratio=0.5), "max", 50_000) is None    # короткий хвост
    assert rc.smart_account(smart_row(median_reactions=12.0), "max", 50_000) is None  # мало реакций для оценки
    assert rc.smart_account(smart_row(residuals=4), "max", 50_000) is None
    assert rc.smart_account(smart_row(tail_ratio=None), "max", 50_000) is None


def test_removed_reactions_never_exceed_the_month():
    item = rc.Inflation(reactions=900, smart=rc.Smart(0.0, 300.0, 1.5, 0.75, reactions=500))
    assert rc.cleaned(month(interactions=1000), item).interactions == 0


def test_forecast_basis_takes_our_forecast_and_the_base_for_the_rest():
    base = rf.BaseMonth(period="Сентябрь 2026", names={"1": "А", "2": "Б"},
                        scores={"1": {"social": 40.0, "max": 1.0, "vk": 1.0, "rutube": 1.0},
                                "2": {"social": 55.0, "max": 1.0, "vk": 1.0, "rutube": 1.0}})
    forecast = [{"explanation": {"code": "1", "categories": {key: {"score": 60.0} for key in rf.CATEGORIES}}}]
    result = rc.forecast_basis(forecast, base)
    assert result["1"]["social"] == 60.0 and result["2"]["social"] == 55.0


RUN = {"id": "run", "as_of": datetime(2026, 11, 17, 20, tzinfo=timezone.utc),
       "window_start": datetime(2026, 9, 30, 21, tzinfo=timezone.utc), "version": 1,
       "parameters": {"status": "retrospective", "period": "Октябрь 2026", "basis": "fact",
                      "basisPeriod": "Октябрь 2026", "postsScale": 1.0, "formulaVersion": 1, "baseFormulaVersion": 2}}


def test_clean_body_matches_the_contract():
    rows = rc.clean_month([institution("1", {"vk": month(), "max": month()})],
                          {("1", "max"): rc.Inflation(reactions=3000, smart=rc.Smart(0.01, 250.0, 1.4, 0.75, 400))},
                          basis(**{"1": 70.0, "2": 69.0}), NAMES, basis_kind="fact", formula=rf.FORMULA_V2)
    stored = [{"institution_id": rows[0]["institutionId"], "legacy_id": 7, "name": "Вуз", "short_name": None,
               "explanation": rows[0]["explanation"]}]
    body = rating.clean_body(RUN, stored)
    validate(body, "RatingClean")
    row = body["rows"][0]
    assert body["month"] == "2026-10" and body["basis"] == "fact"
    assert row["platforms"]["max"]["smart"]["tailRatio"] == 1.4 and row["platforms"]["vk"]["smart"] is None
    assert row["categories"]["social"]["baseRank"] == 1
