"""Хранение анализа v2: чтение рядов, состояние поста, журнал смен, нормы.

Соединение живёт в автофиксации, а запись идёт явными транзакциями. Без
автофиксации psycopg открывает транзакцию на первом же операторе и не
закрывает её; висящий backend_xmin останавливает очистку во всей базе — так
было с публикатором outbox. idle_in_transaction_session_timeout — страховка.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from typing import Any, Mapping, Sequence
from uuid import UUID

from .detectors import SiblingActivity
from .domain import Metric, PostSeries, PostVerdict
from .levels import quality_payload, sign_payload
from .norms import NORM_MODEL_VERSION, Norm, NormSet, NormStatus, norm_from_payload, norm_to_payload
from .tail_ledger import READABLE_VERSIONS as TAIL_LEDGER_READABLE, VERSION as TAIL_LEDGER_VERSION

# Серия читается пачкой: 50 постов одним запросом (план, раздел 11).
SERIES_BATCH = 50
# Таймаут запроса — минута: почасовая активность аккаунтов пачки (ACTIVITY,
# ~4 тысячи постов за 31 день, окно 72 часа) и до упаковки шла 12–16 с при
# прежних 20 с, а 06.10 под нагрузкой догоняющего приёма перестала в них
# укладываться — воркер вставал целиком.
CONNECTION_OPTIONS = ("-c timezone=UTC -c statement_timeout=60000 -c lock_timeout=5000"
                      " -c idle_in_transaction_session_timeout=60000")

# Значение с такой отметкой качества — не замер счётчика, а сбой: в ряд оно
# идёт как «не получено», а не как точка.
UNUSABLE_QUALITY = frozenset({"invalid", "suspected_reset"})
# Telegram округляет показанное число только с тысячи («2,8K»). До 28.09.2026
# сборщик помечал «округлёнными» и меньшие значения — почти все реакции и
# просмотры постов Telegram того времени (25a3952c исправил сборщик, но не
# историю). Такое значение показано целиком и точно.
COMPACT_FROM = 1000


def effective_quality(platform: str, quality: str | None, count: int | None) -> str:
    if (platform == "telegram" and quality == "rounded" and count is not None
            and 0 <= count < COMPACT_FROM):
        return "exact"
    return quality or "unknown"

SERIES = """
WITH target AS (
    SELECT publication.id, publication.primary_account_id, account.platform::text AS platform,
           publication.published_at, publication.is_repost,
           date_trunc('month', publication.published_at AT TIME ZONE 'UTC')::date AS published_month
      FROM ingest.visible_publication publication
      JOIN catalog.visible_platform_account account ON account.id = publication.primary_account_id
     WHERE publication.id = ANY(%(ids)s::uuid[])
)
SELECT DISTINCT ON (target.id, snapshot.observed_at)
       target.id, target.primary_account_id, target.platform, target.published_at, target.is_repost,
       snapshot.observed_at, snapshot.interval_uncertain,
       snapshot.views_count, snapshot.views_quality::text AS views_quality,
       snapshot.reactions_count, snapshot.reactions_quality::text AS reactions_quality,
       snapshot.comments_count, snapshot.comments_quality::text AS comments_quality,
       snapshot.shares_count, snapshot.shares_quality::text AS shares_quality,
       CASE WHEN target.platform = 'telegram' AND snapshot.reactions_quality IN ('rounded', 'unknown')
            THEN coalesce(snapshot.reaction_breakdown,
                          coalesce(snapshot.metric_evidence,
                                   (SELECT evidence.payload FROM ingest.metric_evidence_dictionary evidence
                                     WHERE evidence.id = snapshot.metric_evidence_id)) -> 'reaction_breakdown',
                          CASE WHEN NOT snapshot.packed THEN
                              (SELECT jsonb_object_agg(reaction.reaction_key, reaction.reaction_count
                                                       ORDER BY reaction.reaction_key)
                                 FROM ingest.reaction_breakdown reaction
                                WHERE reaction.snapshot_published_month = snapshot.published_month
                                  AND reaction.snapshot_id = snapshot.id) END,
                          '{}'::jsonb)
       END AS reaction_breakdown
  FROM target
  -- Горячие строки — прямо из таблицы, видимость — проверкой преемника по
  -- индексу на строку: через представление точек по массиву постов
  -- планировщик сводил её к хеш-антисоединению со всей таблицей (06.10 —
  -- минута и предел временных файлов на 50 постах). Упакованные — одним
  -- вызовом packed_points_between (0068).
  JOIN (
    SELECT s.publication_id, s.published_month, s.id, false AS packed, s.observed_at, s.interval_uncertain,
           s.views_count, s.views_quality, s.reactions_count, s.reactions_quality, s.comments_count,
           s.comments_quality, s.shares_count, s.shares_quality, s.correction_sequence,
           -- Evidence читается (TOAST) только там, где нужна разбивка, — в CASE выше.
           s.metric_evidence, s.metric_evidence_id, NULL::jsonb AS reaction_breakdown
      FROM ingest.publication_metric_snapshot s
     WHERE s.publication_id = ANY(%(ids)s::uuid[]) AND s.published_month = ANY(%(months)s::date[])
       AND NOT s.synthetic
       -- Месяцы преемника — тоже константой: иначе каждая проверка в оценке
       -- планировщика идёт по всем партициям, и он выбирает хеш со всей таблицей.
       AND NOT EXISTS (SELECT 1 FROM ingest.publication_metric_snapshot successor
                        WHERE successor.published_month = ANY(%(months)s::date[])
                          AND successor.published_month = s.published_month
                          AND successor.publication_id = s.publication_id
                          AND successor.sampling_bucket = s.sampling_bucket
                          AND successor.correction_sequence > s.correction_sequence)
    UNION ALL
    SELECT p.publication_id, p.published_month, p.id, true, p.observed_at, p.interval_uncertain,
           p.views_count, p.views_quality, p.reactions_count, p.reactions_quality, p.comments_count,
           p.comments_quality, p.shares_count, p.shares_quality, p.correction_sequence,
           NULL::jsonb, NULL::bigint, p.reaction_breakdown
      FROM ingest.packed_points_between(%(ids)s::uuid[], '-infinity', 'infinity') p
     WHERE p.visible AND NOT p.synthetic
  ) snapshot
    ON snapshot.publication_id = target.id
   AND snapshot.published_month = target.published_month
 -- Месяцы известны заранее: предикат-константа отсекает партиции при планировании.
 WHERE snapshot.published_month = ANY(%(months)s::date[])
 ORDER BY target.id, snapshot.observed_at, snapshot.correction_sequence DESC
"""


# Сколько точек добавилось у постов пачки после прошлого анализа — без чтения
# рядов. Семь из восьми просроченных постов оказываются отложенными: сборщик
# пишет только изменения, и у поста часто нет ни одной новой точки. Раньше это
# выяснялось лишь после чтения всего ряда. Выборка та же, что у SERIES
# (активные несинтетические снимки месяца публикации, точка — момент
# наблюдения), поэтому решение по ней совпадает с решением по полному ряду.
PROGRESS = """
SELECT due.publication_id, account.platform::text AS platform,
       fresh.new_points, fresh.first_new_at, latest.observed_at AS last_observed_at
  FROM unnest(%(ids)s::uuid[], %(published)s::timestamptz[], %(last)s::timestamptz[])
       AS due(publication_id, published_at, last_point_observed_at)
  JOIN ingest.visible_publication publication ON publication.id = due.publication_id
  JOIN catalog.visible_platform_account account ON account.id = publication.primary_account_id
 -- Горячие точки — по таблице снимков в партиции месяца поста, как до
 -- упаковки; упакованные (0059) — из массивов. Общие функции окна здесь
 -- на две пятых медленнее (проверка на проде 06.10).
 CROSS JOIN LATERAL (
    SELECT count(DISTINCT point.observed_at)::integer AS new_points,
           min(point.observed_at) AS first_new_at
      FROM (
        SELECT s.observed_at
          FROM ingest.publication_metric_snapshot s
         WHERE s.publication_id = due.publication_id
           AND s.published_month = date_trunc('month', due.published_at AT TIME ZONE 'UTC')::date
           -- Границу «после» окно не включает.
           AND s.observed_at > coalesce(due.last_point_observed_at, '-infinity')
           AND NOT s.synthetic
           AND NOT EXISTS (SELECT 1 FROM ingest.publication_metric_snapshot successor
                        WHERE successor.published_month = s.published_month
                          AND successor.publication_id = s.publication_id
                          AND successor.sampling_bucket = s.sampling_bucket
                          AND successor.correction_sequence > s.correction_sequence)
        UNION ALL
        SELECT packed.observed_at
          FROM ingest.packed_points_between(due.publication_id,
                 coalesce(due.last_point_observed_at + interval '1 microsecond', '-infinity'), 'infinity') packed
         WHERE packed.visible AND NOT packed.synthetic
           AND packed.published_month = date_trunc('month', due.published_at AT TIME ZONE 'UTC')::date
      ) point
 ) fresh
  -- Последняя видимая точка. Синтетическая стоит в момент публикации, раньше
  -- всех: если последней оказалась она, настоящих точек нет.
  LEFT JOIN LATERAL (
    SELECT CASE WHEN NOT candidate.synthetic THEN candidate.observed_at END AS observed_at
      FROM (
        (SELECT s.observed_at, s.id, s.synthetic
           FROM ingest.publication_metric_snapshot s
          WHERE s.publication_id = due.publication_id
            AND s.published_month = date_trunc('month', due.published_at AT TIME ZONE 'UTC')::date
            AND NOT EXISTS (SELECT 1 FROM ingest.publication_metric_snapshot successor
                        WHERE successor.published_month = s.published_month
                          AND successor.publication_id = s.publication_id
                          AND successor.sampling_bucket = s.sampling_bucket
                          AND successor.correction_sequence > s.correction_sequence)
          ORDER BY s.observed_at DESC, s.id DESC LIMIT 1)
        UNION ALL
        -- Упакованные старше всех горячих, кроме поздних строк: нашлась
        -- горячая — массивы не распаковываются.
        SELECT packed.observed_at, packed.id, packed.synthetic
          FROM ingest.publication_metric_history history
         CROSS JOIN LATERAL ingest.packed_point_at(history.publication_id, 'infinity') packed
         WHERE history.publication_id = due.publication_id
           AND history.published_month = date_trunc('month', due.published_at AT TIME ZONE 'UTC')::date
           AND (history.late_rows OR NOT EXISTS (
                 SELECT 1 FROM ingest.publication_metric_snapshot s
                  WHERE s.publication_id = due.publication_id AND s.published_month = date_trunc('month', due.published_at AT TIME ZONE 'UTC')::date))
      ) candidate
     ORDER BY candidate.observed_at DESC, candidate.id DESC LIMIT 1
 ) latest ON true
"""


@dataclass(frozen=True, slots=True)
class Progress:
    """Точки поста после прошлого анализа: сколько, первая из них и последняя вообще."""

    platform: str
    new_points: int
    first_new_at: datetime | None
    last_observed_at: datetime | None


@dataclass(frozen=True, slots=True)
class SeriesTarget:
    publication_id: UUID
    published_at: datetime


# Посты аккаунтов окна — отдельным запросом: массив их номеров уходит в
# оконные функции параметром. Переданный подзапросом (ARRAY(SELECT …)), он
# не даёт функциям встроиться, и они считали полные строки всех точек —
# с evidence и разбивкой — ради двух счётчиков (06.10 — таймаут воркера).
ACTIVITY_POSTS = """
SELECT publication.id
  FROM ingest.visible_publication publication
 WHERE publication.primary_account_id = ANY(%(accounts)s::uuid[])
   AND publication.published_at >= %(published_since)s
   AND publication.deleted_at IS NULL
"""
ACTIVITY = """
WITH posts AS (
    SELECT publication.id, publication.primary_account_id, publication.published_at,
           date_trunc('month', publication.published_at AT TIME ZONE 'UTC')::date AS published_month,
           account.platform::text = 'telegram' AS telegram
      FROM ingest.visible_publication publication
      -- Роль работника читает аккаунты только через представление (как SERIES).
      JOIN catalog.visible_platform_account account ON account.id = publication.primary_account_id
     WHERE publication.id = ANY(%(ids)s::uuid[])
), observed AS (
    SELECT posts.primary_account_id, posts.id AS publication_id, posts.published_at,
           floor(extract(epoch FROM snapshot.observed_at) / 3600)::bigint AS hour,
           -- Округлённое Telegram меньше тысячи показано точно (store.effective_quality).
           CASE WHEN (snapshot.reactions_quality = 'exact' OR posts.telegram
                      AND snapshot.reactions_quality = 'rounded' AND snapshot.reactions_count < 1000)
                     AND NOT snapshot.interval_uncertain
                THEN snapshot.reactions_count END AS reactions_count,
           CASE WHEN (snapshot.views_quality = 'exact' OR posts.telegram
                      AND snapshot.views_quality = 'rounded' AND snapshot.views_count < 1000)
                     AND NOT snapshot.interval_uncertain
                THEN snapshot.views_count END AS views_count
      FROM posts
      JOIN ingest.publication_points_between(%(ids)s::uuid[], %(since)s, %(until)s) snapshot
        ON snapshot.publication_id = posts.id AND snapshot.published_month = posts.published_month
     WHERE snapshot.published_month = ANY(%(months)s::date[])
       AND snapshot.visible
       AND NOT snapshot.synthetic
    UNION ALL
    -- Keep the real time of the last reading before the window. A stale
    -- reading is not a confirmed level at the start of the window.
    SELECT posts.primary_account_id, posts.id, posts.published_at,
           floor(extract(epoch FROM before.observed_at) / 3600)::bigint,
           CASE WHEN (before.reactions_quality = 'exact' OR posts.telegram
                      AND before.reactions_quality = 'rounded' AND before.reactions_count < 1000)
                     AND NOT before.interval_uncertain
                THEN before.reactions_count END,
           CASE WHEN (before.views_quality = 'exact' OR posts.telegram
                      AND before.views_quality = 'rounded' AND before.views_count < 1000)
                     AND NOT before.interval_uncertain
                THEN before.views_count END
      FROM posts
      -- Последняя видимая точка строго до окна; синтетическая — самая ранняя,
      -- и если последней оказалась она, настоящего чтения до окна нет.
      JOIN (
          SELECT snapshot.publication_id, snapshot.published_month, snapshot.observed_at,
                 snapshot.reactions_quality::text AS reactions_quality, snapshot.reactions_count,
                 snapshot.views_quality::text AS views_quality, snapshot.views_count,
                 snapshot.interval_uncertain
            FROM ingest.publication_point_at(%(ids)s::uuid[],
                                             %(since)s::timestamptz - interval '1 microsecond') snapshot
           WHERE NOT snapshot.synthetic
      ) before ON before.publication_id = posts.id AND before.published_month = posts.published_month
)
SELECT primary_account_id, publication_id, published_at, hour,
       CASE WHEN count(reactions_count) = count(*) THEN max(reactions_count) END AS reactions,
       CASE WHEN count(views_count) = count(*) THEN max(views_count) END AS views
  FROM observed
 GROUP BY 1, 2, 3, 4
 ORDER BY 1, 2, 4
"""


# Успешные циклы сбора аккаунтов: по ним «не менялось» отличается от «нет
# данных» (сборщик пишет замер только при изменении). Читается одна колонка по
# индексу (аккаунт, начало цикла).
COLLECTED = """
SELECT result.platform_account_id, result.started_at
  FROM ingest.collection_account_result result
 WHERE result.platform_account_id = ANY(%(accounts)s::uuid[])
   AND result.status = 'succeeded'
   AND result.started_at > %(since)s AND result.started_at <= %(until)s
 ORDER BY result.platform_account_id, result.started_at
"""
# Журнал сбора держится в памяти процесса на столько назад: окно отслеживания
# и запас на финальный анализ. Дальше пост анализируется без журнала.
COLLECTED_HORIZON = timedelta(days=45)


@dataclass(frozen=True, slots=True)
class DueRow:
    publication_id: UUID
    published_at: datetime
    next_due_at: datetime
    analyzed_at: datetime | None
    last_point_observed_at: datetime | None
    norm_version_id: int | None
    attempts: int
    signals: tuple[Mapping[str, Any], ...]
    # Строка из базы несёт версию сводки поста; по умолчанию — текущая.
    tail_ledger_version: int | None = TAIL_LEDGER_VERSION

    @property
    def tail_ledger_stale(self) -> bool:
        return self.tail_ledger_version != TAIL_LEDGER_VERSION


@dataclass(frozen=True, slots=True)
class StoredState:
    publication_id: UUID
    level: int
    sign_keys: frozenset[tuple[int, str]]
    attempts: int


@dataclass(frozen=True, slots=True)
class StateWrite:
    """Итог одного анализа поста. `verdict` None — анализ не удался, `error_code` задан."""

    publication_id: UUID
    published_at: datetime
    analyzed_at: datetime
    next_due_at: datetime
    verdict: PostVerdict | None = None
    analyzed_points: int = 0
    last_point_observed_at: datetime | None = None
    norm_version_id: int | None = None
    frozen: bool = False
    lag_seconds: int | None = None
    error_code: str | None = None
    reason: str = "scheduled"
    tail_ledger: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if (self.verdict is None) == (self.error_code is None):
            raise ValueError("a state write carries either a verdict or an error code")


def series_from_rows(rows: Sequence[Mapping[str, Any]],
                     collected: Sequence[datetime] = ()) -> PostSeries:
    """Ряд поста из строк замеров одного поста, упорядоченных по времени.

    `collected` — начала успешных циклов сбора аккаунта."""
    first = rows[0]
    values: dict[Metric, tuple[int | None, ...]] = {}
    for metric in Metric:
        column = tuple(None if row[f"{metric.value}_quality"] in UNUSABLE_QUALITY
                       else row[f"{metric.value}_count"] for row in rows)
        # Метрика, которой площадка не отдаёт вовсе, отсутствует, а не ноль.
        if any(item is not None for item in column):
            values[metric] = column
    return PostSeries(first["id"], first["primary_account_id"], first["platform"],
                      first["published_at"], bool(first["is_repost"]),
                      tuple(row["observed_at"] for row in rows), values,
                      tuple(item for item in collected if item >= first["published_at"]),
                      qualities={metric: tuple(effective_quality(first["platform"], row[f"{metric.value}_quality"],
                                                                 row[f"{metric.value}_count"]) for row in rows)
                                 for metric in values},
                      interval_uncertain=tuple(row.get("interval_uncertain", True) for row in rows),
                      reaction_breakdowns=tuple(row.get("reaction_breakdown") for row in rows))


def change_kind(previous: StoredState | None, level: int,
                sign_keys: frozenset[tuple[int, str]]) -> str | None:
    """Вид смены вывода для журнала; None — вывод не изменился и журнал молчит."""
    before_level = previous.level if previous else 0
    before_keys = previous.sign_keys if previous else frozenset()
    if level == before_level and sign_keys == before_keys:
        return None
    if before_level == 0 and not before_keys:
        return "appeared"
    if level != before_level:
        return "level_changed"
    return "sign_added" if sign_keys - before_keys else "sign_removed"


def norm_rows(norm: Norm) -> list[dict[str, Any]]:
    """Норма в строки analytics.anomaly_norm: затухание — строка без интервала."""
    payload = norm_to_payload(norm)
    common = {"platform": norm.platform, "account_id": norm.account_id,
              "norm_posts": norm.posts, "confidence": payload["confidence"]}
    rows = [{**common, "metric": metric, "age_band": None, "sample_size": norm.posts,
             "params": {"decay": values, "basis": norm.basis}}
            for metric, values in payload["decay"].items()]
    for cell in payload["cells"]:
        params = {key: cell[key] for key in ("rate", "share", "erv", "confidence") if key in cell}
        rows.append({**common, "metric": cell["m"], "age_band": cell["band"],
                     "sample_size": cell["n"], "params": params})
    return rows


def norm_from_rows(rows: Sequence[Mapping[str, Any]]) -> Norm:
    first = rows[0]
    basis = next((row["params"]["basis"] for row in rows if row["age_band"] is None),
                 "platform" if first["account_id"] is None else "account")
    return norm_from_payload({
        "platform": first["platform"],
        "account_id": None if first["account_id"] is None else str(first["account_id"]),
        "basis": basis, "posts": first["norm_posts"], "confidence": first["confidence"],
        "decay": {row["metric"]: row["params"]["decay"] for row in rows if row["age_band"] is None},
        "cells": [{"m": row["metric"], "band": row["age_band"], "n": row["sample_size"], **row["params"]}
                  for row in rows if row["age_band"] is not None],
    })


class PostgresAnomalyStore:
    def __init__(self, dsn: str, *, connection_factory=None) -> None:
        self._dsn = dsn
        self._factory = connection_factory or self._connect
        # Журнал сбора по аккаунтам: (начала циклов, до какого момента прочитан).
        # Дочитывается только хвост — догонка по десяткам тысяч постов иначе
        # перечитывала бы один и тот же журнал на каждой пачке.
        self._collected: dict[UUID, tuple[list[datetime], datetime]] = {}

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self._dsn, autocommit=True, row_factory=dict_row,
                               options=CONNECTION_OPTIONS)

    def read_series(self, targets: Sequence[SeriesTarget]) -> dict[UUID, PostSeries]:
        result: dict[UUID, PostSeries] = {}
        with self._factory() as connection:
            for start in range(0, len(targets), SERIES_BATCH):
                batch = targets[start:start + SERIES_BATCH]
                months = sorted({item.published_at.astimezone(timezone.utc).date().replace(day=1)
                                 for item in batch})
                rows = connection.execute(SERIES, {
                    "ids": [item.publication_id for item in batch], "months": months}).fetchall()
                grouped: dict[UUID, list[Mapping[str, Any]]] = {}
                for row in rows:
                    grouped.setdefault(row["id"], []).append(row)
                collected = self._read_collected(connection, {items[0]["primary_account_id"]
                                                              for items in grouped.values()})
                result.update({key: series_from_rows(items, collected.get(items[0]["primary_account_id"], ()))
                               for key, items in grouped.items()})
        return result

    def read_runtime_policy(self, name: str) -> dict[str, Any] | None:
        """Политика из панели (ADR-016); None — её нет или таблица недоступна."""
        try:
            with self._factory() as connection:
                row = connection.execute("SELECT value FROM ops_and_admin.runtime_policy WHERE name = %s",
                                         (name,)).fetchone()
        except Exception:  # noqa: BLE001 — без миграции 0057 работают значения окружения
            return None
        return dict(row["value"]) if row and isinstance(row["value"], dict) else None

    def read_progress(self, rows: Sequence[DueRow]) -> dict[UUID, Progress]:
        """Новые точки постов с прошлого анализа; посты без прошлой точки не передаются."""
        if not rows:
            return {}
        with self._factory() as connection:
            found = connection.execute(PROGRESS, {
                "ids": [row.publication_id for row in rows],
                "published": [row.published_at for row in rows],
                "last": [row.last_point_observed_at for row in rows]}).fetchall()
        return {row["publication_id"]: Progress(row["platform"], int(row["new_points"]), row["first_new_at"],
                                                row["last_observed_at"]) for row in found}

    def read_collected(self, accounts: Sequence[UUID]) -> dict[UUID, Sequence[datetime]]:
        with self._factory() as connection:
            return self._read_collected(connection, set(accounts))

    def _read_collected(self, connection: Any, accounts: set[UUID]) -> dict[UUID, Sequence[datetime]]:
        """Начала успешных циклов сбора аккаунтов за горизонт, с дочитыванием хвоста."""
        if not accounts:
            return {}
        now = datetime.now(timezone.utc)
        horizon = now - COLLECTED_HORIZON
        # Аккаунты группируются по моменту, с которого дочитывать: новые — с
        # горизонта, известные — с последнего прочитанного.
        groups: dict[datetime, list[UUID]] = {}
        for account in accounts:
            known = self._collected.get(account)
            groups.setdefault(known[1] if known else horizon, []).append(account)
        for since, members in groups.items():
            fresh: dict[UUID, list[datetime]] = {account: [] for account in members}
            for row in connection.execute(COLLECTED, {"accounts": members, "since": since, "until": now}):
                fresh[row["platform_account_id"]].append(row["started_at"])
            for account, items in fresh.items():
                previous = self._collected.get(account, ([], horizon))[0]
                merged = [item for item in previous if item > horizon] + items
                self._collected[account] = (merged, now)
        return {account: self._collected[account][0] for account in accounts}

    def write_states(self, writes: Sequence[StateWrite]) -> int:
        """Записать итоги пачкой; вернуть число записей журнала."""
        if not writes:
            return 0
        logged = 0
        with self._factory() as connection, connection.transaction():
            ids = [item.publication_id for item in writes]
            previous = {row["publication_id"]: StoredState(
                row["publication_id"], int(row["level"]),
                frozenset((int(item["pattern"]), str(item["metric"])) for item in row["signals"]),
                int(row["attempts"]),
            ) for row in connection.execute(
                """SELECT publication_id, level, signals, attempts
                     FROM analytics.post_anomaly_state
                    WHERE publication_id = ANY(%s::uuid[]) ORDER BY publication_id FOR UPDATE""",
                (ids,)).fetchall()}
            for item in writes:
                before = previous.get(item.publication_id)
                if item.verdict is None:
                    self._write_failure(connection, item, before)
                    continue
                verdict = item.verdict
                # Признаки хранятся уже со словами: API читает их, не зная о модуле анализа.
                signals = [sign_payload(sign) for sign in verdict.signs]
                versions = dict(verdict.detector_versions)
                connection.execute(
                    """INSERT INTO analytics.post_anomaly_state AS state(
                           publication_id, published_at, level, signals, quality, analyzed_at,
                           analyzed_points, last_point_observed_at, norm_version_id,
                           detector_versions, next_due_at, frozen, error_code, attempts,
                           lag_seconds, tail_ledger, tail_ledger_version, updated_at)
                       VALUES (%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s::jsonb,%s,%s,NULL,0,%s,
                               %s::jsonb,%s,transaction_timestamp())
                       ON CONFLICT (publication_id) DO UPDATE SET
                           published_at=excluded.published_at, level=excluded.level,
                           signals=excluded.signals, quality=excluded.quality,
                           analyzed_at=excluded.analyzed_at, analyzed_points=excluded.analyzed_points,
                           last_point_observed_at=excluded.last_point_observed_at,
                           norm_version_id=excluded.norm_version_id,
                           detector_versions=excluded.detector_versions,
                           next_due_at=excluded.next_due_at, frozen=excluded.frozen,
                           error_code=NULL, attempts=0, lag_seconds=excluded.lag_seconds,
                           tail_ledger=coalesce(excluded.tail_ledger, state.tail_ledger),
                           tail_ledger_version=coalesce(excluded.tail_ledger_version, state.tail_ledger_version),
                           updated_at=excluded.updated_at""",
                    (item.publication_id, item.published_at, int(verdict.level), _json(signals),
                     _json(quality_payload(verdict.quality)), item.analyzed_at, item.analyzed_points,
                     item.last_point_observed_at, item.norm_version_id, _json(versions),
                     item.next_due_at, item.frozen, item.lag_seconds,
                     None if item.tail_ledger is None else _json(item.tail_ledger),
                     None if item.tail_ledger is None else TAIL_LEDGER_VERSION))
                keys = frozenset((sign.pattern, sign.metric.value) for sign in verdict.signs)
                kind = change_kind(before, int(verdict.level), keys)
                if kind is None:
                    continue
                connection.execute(
                    """INSERT INTO analytics.post_anomaly_log(
                           publication_id, change, previous_level, level, signals,
                           detector_versions, norm_version_id, reason)
                       VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s)""",
                    (item.publication_id, kind, before.level if before else None, int(verdict.level),
                     _json(signals), _json(versions), item.norm_version_id, item.reason))
                logged += 1
        return logged

    def _write_failure(self, connection, item: StateWrite, before: StoredState | None) -> None:
        # Неудача не трогает прежний вывод: страница поста продолжает показывать
        # последний удачный анализ, а счётчик попыток растёт.
        connection.execute(
            """INSERT INTO analytics.post_anomaly_state AS state(
                   publication_id, published_at, next_due_at, frozen, error_code, attempts, updated_at)
               VALUES (%s,%s,%s,%s,%s,1,transaction_timestamp())
               ON CONFLICT (publication_id) DO UPDATE SET
                   next_due_at=excluded.next_due_at, error_code=excluded.error_code,
                   attempts=state.attempts+1, updated_at=excluded.updated_at""",
            (item.publication_id, item.published_at, item.next_due_at, item.frozen, item.error_code))

    def seed_new(self, now: datetime, window_seconds: float, limit: int) -> int:
        """Поставить в очередь посты окна, у которых ещё нет состояния.

        Выборка по окну публикаций, без триггеров на таблицах сборщиков:
        анализ не вмешивается в их путь записи.
        """
        with self._factory() as connection:
            rows = connection.execute(
                """INSERT INTO analytics.post_anomaly_state(publication_id, published_at, next_due_at)
                   SELECT publication.id, publication.published_at, %(now)s
                     FROM ingest.visible_publication publication
                    WHERE publication.published_at >= %(since)s AND publication.deleted_at IS NULL
                      AND NOT EXISTS (SELECT 1 FROM analytics.post_anomaly_state state
                                       WHERE state.publication_id = publication.id)
                    ORDER BY publication.published_at DESC
                    LIMIT %(limit)s
                   ON CONFLICT (publication_id) DO NOTHING
                   RETURNING publication_id""",
                {"now": now, "since": now - timedelta(seconds=window_seconds), "limit": limit}).fetchall()
        return len(rows)

    def backfill_accounts(self, since: datetime) -> list[UUID]:
        """Аккаунты с постами окна — единица разовой перепроверки."""
        with self._factory() as connection:
            rows = connection.execute(
                """SELECT DISTINCT publication.primary_account_id AS account
                     FROM ingest.visible_publication publication
                    WHERE publication.published_at >= %s AND publication.deleted_at IS NULL
                    ORDER BY 1""", (since,)).fetchall()
        return [row["account"] for row in rows]

    def backfill_targets(self, account: UUID, since: datetime) -> list[DueRow]:
        """Посты аккаунта за окно с их текущим состоянием (если оно есть)."""
        with self._factory() as connection:
            rows = connection.execute(
                """SELECT publication.id AS publication_id, publication.published_at,
                          coalesce(state.next_due_at, %(now)s) AS next_due_at, state.analyzed_at,
                          state.last_point_observed_at, state.norm_version_id,
                          coalesce(state.attempts, 0) AS attempts, coalesce(state.signals, '[]'::jsonb) AS signals,
                          state.tail_ledger_version
                     FROM ingest.visible_publication publication
                     LEFT JOIN analytics.post_anomaly_state state ON state.publication_id = publication.id
                    WHERE publication.primary_account_id = %(account)s AND publication.published_at >= %(since)s
                      AND publication.deleted_at IS NULL
                    ORDER BY publication.published_at DESC""",
                {"account": account, "since": since, "now": datetime.now(timezone.utc)}).fetchall()
        return [DueRow(row["publication_id"], row["published_at"], row["next_due_at"], row["analyzed_at"],
                       row["last_point_observed_at"], row["norm_version_id"], int(row["attempts"]),
                       tuple(row["signals"] or ()), row["tail_ledger_version"]) for row in rows]

    def claim_due(self, now: datetime, limit: int) -> list[DueRow]:
        """Просроченные незамороженные посты, свежие первыми."""
        with self._factory() as connection:
            rows = connection.execute(
                """SELECT publication_id, published_at, next_due_at, analyzed_at, last_point_observed_at,
                          norm_version_id, attempts, signals, tail_ledger_version
                     FROM analytics.post_anomaly_state
                    WHERE NOT frozen AND next_due_at <= %s
                    ORDER BY published_at DESC
                    LIMIT %s""", (now, limit)).fetchall()
        return [DueRow(row["publication_id"], row["published_at"], row["next_due_at"], row["analyzed_at"],
                       row["last_point_observed_at"], row["norm_version_id"], int(row["attempts"]),
                       tuple(row["signals"] or ()), row["tail_ledger_version"]) for row in rows]

    def queue_state(self, now: datetime) -> tuple[float, int]:
        """Отставание самой старой просрочки и размер очереди."""
        with self._factory() as connection:
            row = connection.execute(
                """SELECT coalesce(extract(epoch FROM %(now)s - min(next_due_at)), 0) AS lag, count(*) AS due
                     FROM analytics.post_anomaly_state
                    WHERE NOT frozen AND next_due_at <= %(now)s""", {"now": now}).fetchone()
        return max(0.0, float(row["lag"])), int(row["due"])

    def postpone(self, items: Sequence[tuple[UUID, datetime]]) -> None:
        """Срок наступил, но новых замеров не хватает: только сдвиг срока."""
        if not items:
            return
        with self._factory() as connection, connection.transaction(), connection.cursor() as cursor:
            cursor.executemany(
                """UPDATE analytics.post_anomaly_state
                      SET next_due_at = %s, updated_at = transaction_timestamp()
                    WHERE publication_id = %s""", [(due, publication_id) for publication_id, due in items])

    def read_tail_accounts(self) -> dict[UUID, str]:
        """Видимые аккаунты площадок: у каждого будет профиль позднего отклика."""
        with self._factory() as connection:
            rows = connection.execute(
                """SELECT id, platform::text AS platform FROM catalog.visible_platform_account""").fetchall()
        return {row["id"]: row["platform"] for row in rows}

    def read_tail_ledgers(self, published_after: datetime, published_until: datetime) -> list[dict[str, Any]]:
        """Сводки позднего отклика постов окна — без чтения замеров."""
        with self._factory() as connection:
            return connection.execute(
                """SELECT state.publication_id, publication.primary_account_id AS account_id,
                          state.published_at, state.tail_ledger
                     FROM analytics.post_anomaly_state state
                     JOIN ingest.visible_publication publication ON publication.id = state.publication_id
                    WHERE state.published_at > %s AND state.published_at <= %s
                      AND state.tail_ledger_version = ANY(%s) AND NOT publication.is_repost
                      AND publication.deleted_at IS NULL""",
                (published_after, published_until, list(TAIL_LEDGER_READABLE))).fetchall()

    def write_tail_profiles(self, profiles: Sequence[Any], keep_since: date) -> None:
        """Профили суток одной транзакцией; строки старше `keep_since` удаляются."""
        with self._factory() as connection, connection.transaction(), connection.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO analytics.account_tail_profile(
                       account_id, computed_for, platform, status, abstain_reason, metrics, method_version)
                   VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s)
                   ON CONFLICT (account_id, computed_for) DO UPDATE SET
                       platform=excluded.platform, status=excluded.status,
                       abstain_reason=excluded.abstain_reason, metrics=excluded.metrics,
                       method_version=excluded.method_version, computed_at=transaction_timestamp()""",
                [(item.account_id, item.computed_for, item.platform, item.status, item.abstain_reason,
                  _json(item.metrics), item.metrics["methodVersion"]) for item in profiles])
            cursor.execute("DELETE FROM analytics.account_tail_profile WHERE computed_for < %s", (keep_since,))

    def read_finding_ledgers(self, published_after: datetime, published_until: datetime) -> list[dict[str, Any]]:
        """Сводки постов окна аккаунтных находок, включая репосты (их просмотры собственные)."""
        with self._factory() as connection:
            return connection.execute(
                """SELECT state.publication_id, publication.primary_account_id AS account_id,
                          account.platform::text AS platform, state.published_at, publication.is_repost,
                          state.tail_ledger
                     FROM analytics.post_anomaly_state state
                     JOIN ingest.visible_publication publication ON publication.id = state.publication_id
                     JOIN catalog.visible_platform_account account ON account.id = publication.primary_account_id
                    WHERE state.published_at >= %s AND state.published_at < %s
                      AND state.tail_ledger_version = ANY(%s) AND publication.deleted_at IS NULL""",
                (published_after, published_until, list(TAIL_LEDGER_READABLE))).fetchall()

    def read_late_members(self, accounts: Sequence[UUID], published_after: datetime,
                          published_until: datetime) -> dict[UUID, list[UUID]]:
        """Посты окна с признаком позднего отклика (13) или позднего запуска реакций (14)."""
        if not accounts:
            return {}
        with self._factory() as connection:
            rows = connection.execute(
                """SELECT publication.primary_account_id AS account_id, state.publication_id
                     FROM analytics.post_anomaly_state state
                     JOIN ingest.visible_publication publication ON publication.id = state.publication_id
                    WHERE publication.primary_account_id = ANY(%s::uuid[])
                      AND state.published_at >= %s AND state.published_at < %s
                      AND EXISTS (SELECT 1 FROM jsonb_array_elements(state.signals) signal
                                   WHERE (signal->>'pattern')::int = 13
                                      OR (signal->>'pattern')::int = 14
                                         AND signal->'render'->>'mode' = 'start'
                                         AND (signal->'render'->>'startAge')::numeric >= 259200)""",
                (list(accounts), published_after, published_until)).fetchall()
        members: dict[UUID, list[UUID]] = {}
        for row in rows:
            members.setdefault(row["account_id"], []).append(row["publication_id"])
        return members

    def read_synchrony_events(self, published_after: datetime,
                              published_until: datetime) -> list[dict[str, Any]]:
        """Признаки синхронного подъёма реакций (8) у постов окна: час подъёма по посту."""
        with self._factory() as connection:
            return connection.execute(
                """SELECT publication.primary_account_id AS account_id, account.platform::text AS platform,
                          state.publication_id, (signal->'render'->>'hour')::timestamptz AS hour
                     FROM analytics.post_anomaly_state state
                     JOIN ingest.visible_publication publication ON publication.id = state.publication_id
                     JOIN catalog.visible_platform_account account ON account.id = publication.primary_account_id
                    CROSS JOIN LATERAL jsonb_array_elements(state.signals) signal
                    WHERE state.published_at >= %s AND state.published_at < %s
                      AND publication.deleted_at IS NULL
                      AND (signal->>'pattern')::int = 8 AND signal->>'metric' = 'reactions'
                      AND signal->'render'->>'hour' IS NOT NULL""",
                (published_after, published_until)).fetchall()

    def write_account_findings(self, findings: Sequence[Any], method_version: str) -> None:
        """Находки целиком одной транзакцией: неподтвердившиеся удаляются."""
        with self._factory() as connection, connection.transaction(), connection.cursor() as cursor:
            cursor.execute("DELETE FROM analytics.account_anomaly_finding")
            cursor.executemany(
                """INSERT INTO analytics.account_anomaly_finding(
                       account_id, kind, platform, status, window_start, window_end, metrics, members,
                       method_version)
                   VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::uuid[],%s)""",
                [(item.account_id, item.kind, item.platform, item.status, item.window_start, item.window_end,
                  _json(item.metrics), list(item.members), method_version) for item in findings])

    def read_activity(self, accounts: Sequence[UUID], since: datetime, until: datetime,
                      published_since: datetime) -> dict[UUID, SiblingActivity]:
        """Почасовые максимумы счётчиков постов аккаунтов — агрегаты для синхронности."""
        if not accounts:
            return {}
        first = int(since.timestamp() // 3600)
        last = int(until.timestamp() // 3600) + 1
        months = _months(published_since, until)
        with self._factory() as connection:
            ids = [row["id"] for row in connection.execute(ACTIVITY_POSTS, {
                "accounts": list(accounts), "published_since": published_since}).fetchall()]
            rows = connection.execute(ACTIVITY, {
                "ids": ids, "months": months,
                # Час до окна нужен, чтобы посчитать прирост первого часа.
                "since": datetime.fromtimestamp((first - 1) * 3600, tz=timezone.utc), "until": until,
            }).fetchall()
            collected = self._read_collected(connection, set(accounts))
        grouped: dict[UUID, list[Mapping[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row["primary_account_id"], []).append(row)
        result = {}
        for account, items in grouped.items():
            hours = {int(item.timestamp() // 3600) for item in collected.get(account, ())}
            activity = SiblingActivity.from_hourly(items, first, last, hours)
            if activity is not None:
                result[account] = activity
        return result

    def read_subscribers(self, accounts: Sequence[UUID], since: datetime,
                         until: datetime) -> dict[UUID, list[tuple[datetime, int]]]:
        if not accounts:
            return {}
        with self._factory() as connection:
            rows = connection.execute(
                """SELECT platform_account_id, observed_at, subscriber_count
                     FROM ingest.account_metric_snapshot_active
                    WHERE platform_account_id = ANY(%s::uuid[]) AND subscriber_count IS NOT NULL
                      AND observed_at BETWEEN %s AND %s
                    ORDER BY platform_account_id, observed_at""", (list(accounts), since, until)).fetchall()
        result: dict[UUID, list[tuple[datetime, int]]] = {}
        for row in rows:
            result.setdefault(row["platform_account_id"], []).append(
                (row["observed_at"], int(row["subscriber_count"])))
        return result

    def schedule_norm_recheck(self, version_id: int, now: datetime, window_seconds: int) -> int:
        """Перепроверить незамороженные посты под новой нормой, растянув по окну.

        Доля окна — первые 32 бита md5 от идентификатора поста, как в
        schedule.recheck_offset: срок детерминирован, всплеска нет.
        """
        with self._factory() as connection:
            rows = connection.execute(
                """UPDATE analytics.post_anomaly_state
                      SET next_due_at = least(next_due_at, %(now)s + make_interval(secs =>
                              (('x' || substr(md5(publication_id::text), 1, 8))::bit(32)::bigint
                               %% %(window)s)::double precision)),
                          updated_at = transaction_timestamp()
                    WHERE NOT frozen AND norm_version_id IS DISTINCT FROM %(version)s
                   RETURNING publication_id""",
                {"now": now, "window": window_seconds, "version": version_id}).fetchall()
        return len(rows)

    def norm_candidates(self, since: datetime, until: datetime) -> list[dict[str, Any]]:
        """Посты окна для нормы — с их текущим выводом, по площадкам и аккаунтам.

        Репосты сюда не попадают вовсе: их просмотры — аудитория источника.
        """
        with self._factory() as connection:
            return connection.execute(
                """SELECT publication.id AS publication_id, publication.published_at,
                          publication.primary_account_id AS account_id, account.platform::text AS platform,
                          coalesce(state.level, 0) AS level, coalesce(state.signals, '[]'::jsonb) AS signals
                     FROM ingest.visible_publication publication
                     JOIN catalog.visible_platform_account account ON account.id = publication.primary_account_id
                     LEFT JOIN analytics.post_anomaly_state state ON state.publication_id = publication.id
                    WHERE publication.published_at >= %s AND publication.published_at < %s
                      AND publication.deleted_at IS NULL AND NOT publication.is_repost
                    ORDER BY account.platform, publication.primary_account_id, publication.published_at""",
                (since, until)).fetchall()

    def latest_accepted_norm_version(self) -> int | None:
        with self._factory() as connection:
            row = connection.execute(
                """SELECT id FROM analytics.anomaly_norm_version
                    WHERE status='accepted' AND model_version=%s ORDER BY id DESC LIMIT 1""",
                (NORM_MODEL_VERSION,)).fetchone()
        return None if row is None else int(row["id"])

    def write_norm_version(self, model_version: str, status: NormStatus, norms: Sequence[NormSet], *,
                           reference_failures: Sequence[str] = (), drift: Mapping[str, float] | None = None,
                           previous_version_id: int | None = None) -> int:
        with self._factory() as connection, connection.transaction():
            version = int(connection.execute(
                """INSERT INTO analytics.anomaly_norm_version(
                       model_version, status, reference_failures, drift, previous_version_id, decided_at)
                   VALUES (%s,%s,%s::jsonb,%s::jsonb,%s,
                           CASE WHEN %s='drift_review' THEN NULL ELSE transaction_timestamp() END)
                   RETURNING id""",
                (model_version, status.value, _json(list(reference_failures)), _json(dict(drift or {})),
                 previous_version_id, status.value)).fetchone()["id"])
            rows = [row for norm_set in norms
                    for norm in (norm_set.platform, *norm_set.accounts.values())
                    for row in norm_rows(norm)]
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO analytics.anomaly_norm(
                           norm_version_id, platform, account_id, metric, age_band, params,
                           sample_size, norm_posts, confidence)
                       VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)""",
                    [(version, row["platform"], row["account_id"], row["metric"], row["age_band"],
                      _json(row["params"]), row["sample_size"], row["norm_posts"], row["confidence"])
                     for row in rows])
        return version

    def read_norms(self, version_id: int, platform: str) -> NormSet | None:
        with self._factory() as connection:
            rows = connection.execute(
                """SELECT platform, account_id, metric, age_band, params, sample_size, norm_posts, confidence
                     FROM analytics.anomaly_norm
                    WHERE norm_version_id=%s AND platform=%s
                    ORDER BY account_id NULLS FIRST, metric, age_band NULLS FIRST""",
                (version_id, platform)).fetchall()
        grouped: dict[UUID | None, list[Mapping[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row["account_id"], []).append(row)
        if None not in grouped:
            return None
        platform_norm = norm_from_rows(grouped.pop(None))
        return NormSet(platform_norm, {account: norm_from_rows(items) for account, items in grouped.items()})


def _months(start: datetime, end: datetime) -> list:
    """Первые числа месяцев от start до end — предикат отсечения партиций."""
    current = start.astimezone(timezone.utc).date().replace(day=1)
    last = end.astimezone(timezone.utc).date().replace(day=1)
    months = []
    while current <= last:
        months.append(current)
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
    return months


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
