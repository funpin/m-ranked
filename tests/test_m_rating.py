from app.m_rating import (
    CHANNEL_TO_M_RATING_CODE,
    latest_social_rankings,
    latest_telegram_ranking,
)


def test_latest_telegram_ranking_uses_last_month_with_data():
    payload = {
        "months": [
            {
                "name": "Июнь",
                "items": [
                    {"name": "Б", "code": "2", "scores": {"tg": 10}},
                    {"name": "А", "code": "1", "scores": {"tg": 20}},
                ],
            },
            {
                "name": "Июль",
                "items": [
                    {"name": "А", "code": "1", "scores": {"tg": 25}},
                    {"name": "Б", "code": "2", "scores": {"tg": 50}},
                    {"name": "В", "code": "3", "scores": {"tg": None}},
                ],
            },
            {"name": "Август", "items": []},
        ]
    }
    period, ranking = latest_telegram_ranking(payload, 2026)
    assert period == "Июль 2026"
    assert ranking["2"] == (1, 50.0)
    assert ranking["1"] == (2, 25.0)
    assert "3" not in ranking


def test_channel_codes_use_official_university_rows():
    assert CHANNEL_TO_M_RATING_CODE["marmgu"] == "236"
    assert CHANNEL_TO_M_RATING_CODE["stroganovuniversity"] == "107"
    assert CHANNEL_TO_M_RATING_CODE["bru_live"] == "2"
    assert CHANNEL_TO_M_RATING_CODE["rsukosygin"] == "152"
    assert CHANNEL_TO_M_RATING_CODE["unidubna_official"] == "230"
    assert CHANNEL_TO_M_RATING_CODE["rgsu_life"] == "151"
    assert CHANNEL_TO_M_RATING_CODE["novosti_au"] == "218"
    assert CHANNEL_TO_M_RATING_CODE["mpeiuniversity"] == "122"


def test_latest_social_rankings_builds_five_independent_tables():
    payload = {"months": [{"name": "Июль", "items": [
        {"name": "А", "code": "1", "scores": {
            "social": 50, "tg": 10, "vk": 40, "ok": 5, "rt": 20,
        }},
        {"name": "Б", "code": "2", "scores": {
            "social": 60, "tg": 30, "vk": 10, "ok": 15, "rt": 5,
        }},
    ]}]}
    period, rankings = latest_social_rankings(payload, 2026)
    assert period == "Июль 2026"
    assert set(rankings) == {"social", "tg", "vk", "max", "rutube"}
    assert rankings["social"]["2"] == (1, 60.0)
    assert rankings["tg"]["2"] == (1, 30.0)
    assert rankings["vk"]["1"] == (1, 40.0)
    assert rankings["max"]["2"] == (1, 15.0)
    assert rankings["rutube"]["1"] == (1, 20.0)
