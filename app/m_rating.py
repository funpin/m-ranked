from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin

import httpx

from .database import Database


BASE_URL = "https://www.m-rating.ru/"
CONFIG_URL = urljoin(BASE_URL, "js/config.js")

# Stable university codes published by M-Рейтинг. The Telegram usernames are
# deliberately mapped explicitly: similarly named universities must never be
# matched by a fuzzy guess during an administrative import.
CHANNEL_TO_M_RATING_CODE = {
    "mephi_of": "19",
    "kbsu1957": "84",
    "mslu_official": "111",
    "zgu_university": "75",
    "ksu_kaluga": "90",
    "vvsu_dv": "53",
    "kchgulife": "92",
    "rosbiotech_official": "115",
    "maiuniversity": "108",
    "nust_misis": "14",
    "miptru": "12",
    "marmgu": "236",
    "demidyarsu": "214",
    "gubkin_university": "21",
    "bmstu1830": "112",
    "ncfulife": "30",
    "stroganovuniversity": "107",
    "bru_live": "2",
    "rsukosygin": "152",
    "unidubna_official": "230",
    "rgsu_life": "151",
    "novosti_au": "218",
    "mpeiuniversity": "122",
}


@dataclass(frozen=True)
class MRatingImportResult:
    period: str
    updated: int
    available: int
    fetched_at: datetime


def _config_value(source: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}\s*:\s*[\"']([^\"']+)[\"']", source)
    if not match:
        raise ValueError(f"В конфигурации М-Рейтинга нет поля {name}")
    return match.group(1)


def _config_year(source: str) -> int:
    match = re.search(r"\byear\s*:\s*(\d{4})", source)
    if not match:
        raise ValueError("В конфигурации М-Рейтинга не найден год")
    return int(match.group(1))


def latest_telegram_ranking(payload: dict, year: int) -> tuple[str, dict[str, tuple[int, float]]]:
    months = payload.get("months") or []
    selected: dict | None = None
    for month in reversed(months):
        items = month.get("items") or []
        if any((item.get("scores") or {}).get("tg") is not None for item in items):
            selected = month
            break
    if selected is None:
        raise ValueError("В М-Рейтинге пока нет данных Telegram")

    ranked = sorted(
        selected.get("items") or [],
        key=lambda item: (
            -float((item.get("scores") or {}).get("tg"))
            if (item.get("scores") or {}).get("tg") is not None
            else float("inf"),
            str(item.get("name") or "").casefold(),
        ),
    )
    by_code: dict[str, tuple[int, float]] = {}
    for index, item in enumerate(ranked, start=1):
        score = (item.get("scores") or {}).get("tg")
        code = str(item.get("code") or "").strip()
        if code and score is not None:
            by_code[code] = (index, float(score))
    return f"{selected.get('name')} {year}", by_code


async def refresh_m_rating(db: Database, client: httpx.AsyncClient | None = None) -> MRatingImportResult:
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "m-ranked/1.0 (manual M-Rating import)"},
        )
    try:
        config_response = await client.get(CONFIG_URL)
        config_response.raise_for_status()
        year = _config_year(config_response.text)
        ratings_path = _config_value(config_response.text, "ratingsJson")
        ratings_response = await client.get(urljoin(BASE_URL, ratings_path))
        ratings_response.raise_for_status()
        period, ranking = latest_telegram_ranking(ratings_response.json(), year)
        fetched_at = datetime.now(timezone.utc)
        updated = 0
        for channel in db.list_channels():
            code = CHANNEL_TO_M_RATING_CODE.get(str(channel["username"]).casefold())
            match = ranking.get(code or "")
            if not match:
                continue
            rank, score = match
            db.update_channel_m_rating(int(channel["id"]), rank, score, period, fetched_at)
            updated += 1
        db.set_state("m_rating_last_period", period)
        db.set_state("m_rating_last_updated", fetched_at.isoformat())
        db.set_state("m_rating_last_error", "")
        return MRatingImportResult(period, updated, len(ranking), fetched_at)
    except Exception as exc:
        db.set_state("m_rating_last_error", str(exc))
        raise
    finally:
        if owns_client:
            await client.aclose()
