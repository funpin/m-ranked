"""Ограниченный импорт пяти срезов официального М-Рейтинга."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from .errors import ApiProblem

BASE = "https://www.m-rating.ru/"
CATEGORIES = {"social": "social", "telegram": "tg", "vk": "vk", "max": "ok",
              "rutube": "rt"}


def _resource() -> Path:
    return Path(__file__).with_name("data") / "official-m-rating-channel-codes.json"


def _allow(url: str) -> bool:
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.hostname in {"m-rating.ru", "www.m-rating.ru"}
            and parsed.username is None and parsed.password is None and parsed.port in (None, 443))


async def _fetch(client: httpx.AsyncClient, url: str, maximum: int) -> tuple[bytes, str]:
    current = url
    for redirects in range(4):
        if not _allow(current):
            raise ValueError("official rating redirect is not allowed")
        response = await client.get(current, follow_redirects=False)
        if response.status_code == 200:
            if len(response.content) > maximum:
                raise ValueError("official rating response is too large")
            return response.content, str(response.url)
        if response.status_code in (301, 302, 303, 307, 308) and redirects < 3:
            location = response.headers.get("location")
            if not location:
                raise ValueError("official rating redirect has no location")
            current = urljoin(current, location)
            continue
        response.raise_for_status()
    raise ValueError("official rating redirect limit")


def _filled_months(source: bytes) -> list[dict[str, Any]]:
    """Месяцы, за которые источник уже опубликовал оценки, от старых к новым.

    Источник держит весь год одним файлом: двенадцать месяцев, у будущих
    оценки пустые. Прежде отсюда брался только последний заполненный, и в базе
    лежал ровно один период — сравнивать место в рейтинге было не с чем. Теперь
    берутся все заполненные: на сегодня это семь месяцев вместо одного.
    """
    payload = json.loads(source)
    months = payload.get("months")
    if not isinstance(months, list) or len(months) > 120:
        raise ValueError("invalid official rating months")
    filled = [month for month in months
              if isinstance(month, dict)
              and isinstance(month.get("items"), list)
              and len(month["items"]) <= 10000
              and any(any((item.get("scores") or {}).get(key) is not None
                          for key in CATEGORIES.values())
                      for item in month["items"] if isinstance(item, dict))]
    if not filled:
        raise ValueError("official social rating is absent")
    return filled


def _parse_month(config: str, selected: dict[str, Any], source: bytes,
                 source_url: str) -> dict[str, Any]:
    """Разбирает один месяц источника в готовый к записи период."""
    year_match = re.search(r"\byear\s*:\s*(\d{4})", config)
    if not year_match:
        raise ValueError("official rating year is missing")
    name = str(selected.get("name"))
    if len(name) > 200:
        raise ValueError("invalid official period")
    rankings: dict[str, dict[str, tuple[int, float]]] = {}
    for category, key in CATEGORIES.items():
        candidates: list[tuple[str, str, float]] = []
        for item in selected["items"]:
            score = (item.get("scores") or {}).get(key)
            if score is None:
                continue
            numeric = float(score)
            if not math.isfinite(numeric):
                raise ValueError("invalid official score")
            code, title = str(item.get("code") or "").strip(), str(item.get("name") or "")
            if len(code) > 200 or len(title) > 1000:
                raise ValueError("invalid official institution")
            candidates.append((code, title, numeric))
        candidates.sort(key=lambda item: (-item[2], item[1].casefold()))
        rankings[category] = {code: (index, score)
                              for index, (code, _, score) in enumerate(candidates, 1) if code}
    evidence = []
    for item in selected["items"]:
        scores = {key: float(item["scores"][key]) for key in CATEGORIES.values()
                  if (item.get("scores") or {}).get(key) is not None}
        evidence.append({"code": str(item.get("code") or ""),
                         "name": str(item.get("name") or ""), "scores": scores})
    return {"period": f"{name} {int(year_match.group(1))}", "rankings": rankings,
            "sourceUrl": source_url, "sourceSha256": hashlib.sha256(source).hexdigest(),
            "fetchedAt": datetime.now(timezone.utc),
            "evidence": {"year": int(year_match.group(1)), "month": name, "items": evidence}}


async def refresh(request, actor: str, correlation: uuid.UUID) -> None:
    """Забирает официальный рейтинг и записывает все новые для базы периоды.

    Проверка идёт ежедневно, а источник обновляется раз в месяц, поэтому почти
    каждый прогон не находит ничего нового и заканчивается отметкой о проверке.
    """
    enabled = os.environ.get("MRANKED_ADMIN_OFFICIAL_RATING_ENABLED", "true").lower()
    if enabled not in ("true", "1", "yes"):
        raise RuntimeError("official rating source is disabled")
    database = request.app.state.db
    previous = await database.admin_fetch_one(
        "SELECT ops_and_admin.previous_official_rating(%(actor)s,%(id)s) AS result",
        {"actor": actor, "id": correlation})
    if previous and previous["result"] is not None:
        if previous["result"].get("outcome") == "idempotency_conflict":
            raise ApiProblem(409, "Conflict", "Корреляционный идентификатор уже использован")
        return
    try:
        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "m-ranked-api/1"}) as client:
            config_bytes, _ = await _fetch(client, urljoin(BASE, "js/config.js"), 1_000_000)
            config = config_bytes.decode("utf-8")
            path_match = re.search(r"\bratingsJson\s*:\s*[\"\']([^\"\']+)[\"\']", config)
            if not path_match or len(path_match.group(1)) > 2048:
                raise ValueError("official rating path is missing")
            source, source_url = await _fetch(client, urljoin(BASE, path_match.group(1)), 8*1024*1024)
        parsed = [_parse_month(config, month, source, source_url)
                  for month in _filled_months(source)]
        codes = json.loads(_resource().read_text(encoding="utf-8"))
        # Уже записанные периоды не переписываются: ежедневная проверка
        # приносит только новый месяц и молча проходит мимо прежних.
        known = {row["period"] for row in await database.admin_fetch_all(
            "SELECT DISTINCT period FROM rating.official_institution_rating_observation")}
        pending = [month for month in parsed if month["period"] not in known]
        for month in pending:
            # Каждому периоду свой корреляционный идентификатор: импорт
            # отвергает повторное использование одного и того же.
            await _import_month(database, codes, month, actor,
                                uuid.uuid5(correlation, month["period"]))
    except ApiProblem:
        raise
    except Exception:
        await _report_failure(database, actor, correlation)
        raise


async def _import_month(database: Any, codes: dict[str, Any], parsed: dict[str, Any],
                        actor: str, correlation: uuid.UUID) -> None:
    """Записывает один период официального рейтинга."""
    async with database.admin() as connection:
        async with connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock(782194601)")
            channels = await (await connection.execute("""
                SELECT account.id,account.institution_id,account.current_username
                FROM catalog.visible_platform_account account
                JOIN catalog.legacy_entity_alias alias ON alias.target_uuid=account.id
                  AND alias.entity_type='channels'
                WHERE account.platform='telegram' AND lower(account.current_username)=ANY(%(names)s)
                ORDER BY account.current_username COLLATE \"C\",alias.legacy_id LIMIT 10001
                """, {"names": list(codes)})).fetchall()
            if len(channels) > 10000:
                raise ValueError("official rating account limit")
            institutions, accounts, seen = [], [], set()
            for channel in channels:
                code = codes.get(channel["current_username"].casefold())
                telegram = parsed["rankings"]["telegram"].get(code)
                if telegram:
                    accounts.append({"accountId": str(channel["id"]), "rank": telegram[0],
                                     "score": telegram[1]})
                if channel["institution_id"] not in seen:
                    seen.add(channel["institution_id"])
                    for category in CATEGORIES:
                        rating = parsed["rankings"][category].get(code)
                        institutions.append({"institutionId": str(channel["institution_id"]),
                                             "category": category,
                                             "rank": rating[0] if rating else None,
                                             "score": rating[1] if rating else None})
            import_payload = {"period": parsed["period"], "sourceUrl": parsed["sourceUrl"],
                              "sourceSha256": parsed["sourceSha256"],
                              "fetchedAt": parsed["fetchedAt"].isoformat(),
                              "evidence": parsed["evidence"],
                              "available": len(parsed["rankings"]["social"]),
                              "institutions": institutions, "accounts": accounts}
            result = await (await connection.execute(
                "SELECT ops_and_admin.import_official_rating(%(payload)s::jsonb,%(actor)s,%(id)s) AS result",
                {"payload": json.dumps(import_payload, ensure_ascii=False),
                 "actor": actor, "id": correlation})).fetchone()
            if result["result"].get("outcome") == "idempotency_conflict":
                raise ApiProblem(409, "Conflict", "Корреляционный идентификатор уже использован")


async def _report_failure(database: Any, actor: str, correlation: uuid.UUID) -> None:
    """Наружу не выдаём сетевую или провайдерскую диагностику, но оставляем
    фиксированный операционный код и append-only аудит, как Java-сервис."""
    async with database.admin() as connection:
        async with connection.transaction():
            await connection.execute("""
                INSERT INTO ops_and_admin.operational_checkpoint(
                  checkpoint_key,scope_type,value,correlation_id)
                VALUES('admin.m_rating','system',jsonb_build_object('period',NULL,
                  'updatedAt',NULL,'error','official_source_unavailable'),%(id)s)
                ON CONFLICT(checkpoint_key,scope_type,scope_id,platform) DO UPDATE SET
                  value=ops_and_admin.operational_checkpoint.value||
                    jsonb_build_object('error','official_source_unavailable'),
                  updated_at=transaction_timestamp(),correlation_id=%(id)s
                """, {"id": correlation})
            await connection.execute("""
                INSERT INTO ops_and_admin.audit_log(subject,action,target_type,correlation_id,
                  after_state,outcome) VALUES(%(actor)s,'official_rating.refresh',
                  'official_rating_import',%(id)s,
                  jsonb_build_object('errorCode','official_source_unavailable'),'failed')
                """, {"actor": actor, "id": correlation})
