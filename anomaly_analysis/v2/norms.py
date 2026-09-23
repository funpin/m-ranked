"""Нормы площадки и аккаунта: затухание, скорости и ERV по возрасту поста.

Норма строится так, чтобы не выучить искусственную активность
(docs/research/anomaly-detection.md, раздел 8):

1. посты, помеченные абсолютными детекторами или получившие средний и высокий
   уровень, и посты эталона в расчёт не входят — это входной параметр;
2. форма задана литературой: скорость `r(t) = a·(t + c)^(−b)` обязана убывать,
   данные подбирают только параметры в границах, и прямая не может стать нормой;
3. норма площадки — медиана норм аккаунтов, а не пул постов;
4. норма аккаунта якорится к окрестности нормы площадки, а при короткой
   истории заменяется ею;
5. новая норма площадки сверяется с предыдущей принятой: резкий сдвиг уходит
   на ручной разбор, анализ остаётся на прежней версии.

Модуль чистый и детерминированный: ни базы, ни случайности.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import timedelta
from enum import Enum
from typing import Iterable, Mapping, Protocol, Sequence
from uuid import UUID

import numpy as np
from scipy.optimize import least_squares

from .domain import Level, Metric, PostSeries
from .series import AGE_BAND_EDGES, DAY, HOUR, PreparedSeries, age_band

NORM_MODEL_VERSION = "2.0.0"

# Показатель затухания. Crane и Sornette (PNAS 2008) различают три класса
# релаксации с показателями 1−2θ, 1−θ и 1+θ; на YouTube θ ≈ 0.4, то есть около
# 0.2, 0.6 и 1.4. Нижняя граница 0.2 — самый пологий литературный класс, и
# ровная скорость (b = 0), которую даёт механическая подача, за ней остаётся.
# Верхняя 2.0 — запас на крутой спад хронологической ленты Telegram: норма не
# должна упираться в границу на честной кривой (исследование, разделы 2 и 8).
DECAY_EXPONENT_BOUNDS = (0.2, 2.0)
# Сдвиг времени c в часах: от трёх минут (мгновенный пик Telegram) до двух
# суток (медленный разгон видео RuTube).
DECAY_SHIFT_BOUNDS = (0.05, 48.0)

# Скорости нормируются на значение в сутки: оно есть у любого поста старше
# суток, в отличие от итога за тридцать дней.
NORMALIZATION_AGE = DAY
RATE_GRID = HOUR

# Меньше двадцати чистых постов — своей нормы у аккаунта нет, берётся норма
# площадки (план, раздел 2). Уверенность растёт до полной к пятидесяти постам.
MIN_ACCOUNT_POSTS = 20
FULL_CONFIDENCE_POSTS = 50
# В медиану площадки входят аккаунты хотя бы с тремя чистыми постами: норма из
# одного поста — это шум, а не голос аккаунта.
MIN_POSTS_FOR_PLATFORM = 3
FULL_CONFIDENCE_ACCOUNTS = 30
# Ниже этой уверенности признаки, завязанные на норму, не поднимаются выше
# слабого сигнала.
LOW_CONFIDENCE = 0.5

# Якорь: норма аккаунта не уходит от нормы площадки дальше трёх разбросов
# площадки в лог-шкале, показатель затухания — дальше 0.35, сдвиг — дальше
# множителя 4, доля итога — дальше 0.25.
ANCHOR_MADS = 3.0
ANCHOR_EXPONENT = 0.35
ANCHOR_SHIFT_FACTOR = 4.0
ANCHOR_SHARE = 0.25

# Дрейф: сдвиг медианы на разброс и больше или показателя затухания на 0.25 —
# резкое изменение нормы площадки, которое нельзя принять без разбора.
DRIFT_MADS = 1.0
DRIFT_EXPONENT = 0.25

ERV = "erv"
COUNTERS = (Metric.VIEWS, Metric.REACTIONS, Metric.COMMENTS, Metric.SHARES)
SHARE_QUANTILES = (0.1, 0.5, 0.9)
# Нижняя граница MAD: у идеально ровной выборки нулевой разброс дал бы
# бесконечный z и бесконечный дрейф.
MAD_FLOOR = 1e-3


class NormStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DRIFT_REVIEW = "drift_review"


@dataclass(frozen=True, slots=True)
class DecayFit:
    """Скорость `a·(t + c)^(−b)`, t в часах, скорость — доля значения в сутки в час."""

    a: float
    b: float
    c: float

    def rate(self, hours: np.ndarray) -> np.ndarray:
        return self.a * (np.asarray(hours, dtype=np.float64) + self.c) ** -self.b


@dataclass(frozen=True, slots=True)
class Robust:
    median: float
    mad: float


@dataclass(frozen=True, slots=True)
class NormCell:
    """Норма одной метрики в одном возрастном интервале таблицы расписания.

    Для счётчиков — лог нормированной скорости и доля итога на конце
    интервала; для `erv` — лог ERV на конце интервала.
    """

    metric: str
    band: int
    sample_size: int
    log_rate: Robust | None = None
    share: tuple[float, float, float] | None = None
    log_erv: Robust | None = None


@dataclass(frozen=True, slots=True)
class Norm:
    platform: str
    account_id: UUID | None
    basis: str
    posts: int
    confidence: float
    decay: Mapping[str, DecayFit] = field(default_factory=dict)
    cells: Mapping[tuple[str, int], NormCell] = field(default_factory=dict)

    @property
    def young(self) -> bool:
        return self.confidence < LOW_CONFIDENCE


@dataclass(frozen=True, slots=True)
class NormSet:
    platform: Norm
    accounts: Mapping[UUID, Norm]

    def for_account(self, account_id: UUID) -> Norm:
        return self.accounts.get(account_id, self.platform)


def fit_decay(hours: np.ndarray, rates: np.ndarray,
              exponent_bounds: tuple[float, float] = DECAY_EXPONENT_BOUNDS) -> DecayFit | None:
    """Подогнать затухание в лог-шкале с робастной потерей и границами."""
    hours, rates = np.asarray(hours, dtype=np.float64), np.asarray(rates, dtype=np.float64)
    keep = (rates > 0) & np.isfinite(rates) & (hours >= 0)
    if keep.sum() < 4:
        return None
    hours, target = hours[keep], np.log(rates[keep])
    low_b, high_b = exponent_bounds
    low_c, high_c = DECAY_SHIFT_BOUNDS

    def residuals(parameters: np.ndarray) -> np.ndarray:
        log_a, b, c = parameters
        return log_a - b * np.log(hours + c) - target

    start_b, start_c = float(np.clip(0.8, low_b, high_b)), 1.0
    start = np.array((float(np.median(target + start_b * np.log(hours + start_c))), start_b, start_c))
    result = least_squares(residuals, start, loss="soft_l1", f_scale=0.5,
                           bounds=((-np.inf, low_b, low_c), (np.inf, high_b, high_c)))
    log_a, b, c = result.x
    return DecayFit(float(np.exp(log_a)), float(np.clip(b, low_b, high_b)),
                    float(np.clip(c, low_c, high_c)))


def robust(values: np.ndarray) -> Robust | None:
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    if not values.size:
        return None
    center = float(np.median(values))
    return Robust(center, max(MAD_FLOOR, float(np.median(np.abs(values - center)))))


@dataclass
class _Samples:
    """Наблюдения одного аккаунта, собранные с его чистых постов."""

    posts: int = 0
    rate_hours: dict[str, list[np.ndarray]] = field(default_factory=dict)
    rate_logs: dict[str, list[np.ndarray]] = field(default_factory=dict)
    shares: dict[tuple[str, int], list[float]] = field(default_factory=dict)
    ervs: dict[int, list[float]] = field(default_factory=dict)
    contributors: dict[tuple[str, int], set[int]] = field(default_factory=dict)


def _collect(posts: Sequence[PreparedSeries], excluded: frozenset[UUID], final_age: float) -> _Samples:
    samples = _Samples()
    ends = AGE_BAND_EDGES[1:]
    for index, prepared in enumerate(posts):
        series = prepared.series
        # Просмотры репоста — счётчик источника, а не аудитория аккаунта.
        if series.publication_id in excluded or series.is_repost:
            continue
        samples.posts += 1
        for metric in COUNTERS:
            data = prepared.metrics.get(metric)
            if data is None or data.ages[-1] < NORMALIZATION_AGE:
                continue
            base = float(np.interp(NORMALIZATION_AGE, data.ages, data.values))
            if base <= 0:
                continue
            grid = data.grids.get(timedelta(seconds=RATE_GRID))
            if grid is not None and grid.rates.size:
                # Ячейки до момента публикации — артефакт выравнивания сетки
                # по границам часа; скорости «до поста» в норме нет.
                keep = grid.usable & (grid.rates > 0) & (grid.edges[:-1] >= 0)
                if not keep.any():
                    continue
                hours = (grid.edges[:-1][keep] + RATE_GRID / 2) / HOUR
                # Доля значения в сутки, приходящая за час: сравнима между постами разного охвата.
                logs = np.log(grid.rates[keep] * HOUR / base)
                samples.rate_hours.setdefault(metric.value, []).append(hours)
                samples.rate_logs.setdefault(metric.value, []).append(logs)
                for band in np.unique(age_band(hours * HOUR)):
                    samples.contributors.setdefault((metric.value, int(band)), set()).add(index)
            if data.ages[-1] >= final_age:
                final = float(np.interp(final_age, data.ages, data.values))
                if final > 0:
                    for band, end in enumerate(ends):
                        if end <= final_age:
                            share = float(np.interp(end, data.ages, data.values)) / final
                            samples.shares.setdefault((metric.value, band), []).append(share)
        views = prepared.metrics.get(Metric.VIEWS)
        if views is None or views.source_counter:
            continue
        for band, end in enumerate(ends):
            if views.ages[-1] < end:
                break
            seen = float(np.interp(end, views.ages, views.values))
            engaged = sum(float(np.interp(end, item.ages, item.values))
                          for metric, item in prepared.metrics.items()
                          if metric is not Metric.VIEWS and item.ages[-1] >= end)
            if seen > 0 and engaged > 0:
                samples.ervs.setdefault(band, []).append(float(np.log(engaged / seen)))
                samples.contributors.setdefault((ERV, band), set()).add(index)
    return samples


def _account_norm(platform: str, account_id: UUID | None, samples: _Samples) -> Norm:
    decay: dict[str, DecayFit] = {}
    cells: dict[tuple[str, int], NormCell] = {}
    for metric, hour_chunks in samples.rate_hours.items():
        hours = np.concatenate(hour_chunks)
        logs = np.concatenate(samples.rate_logs[metric])
        if not hours.size:
            continue
        # Медиана по постам в каждом часе возраста: один выброс не тянет кривую.
        bins = np.floor(hours).astype(np.int64)
        order = np.argsort(bins, kind="stable")
        unique, starts = np.unique(bins[order], return_index=True)
        medians = np.array([np.median(chunk) for chunk in np.split(logs[order], starts[1:])])
        fit = fit_decay(unique + 0.5, np.exp(medians))
        if fit is not None:
            decay[metric] = fit
        bands = age_band(hours * HOUR)
        for band in np.unique(bands):
            key = (metric, int(band))
            cells[key] = NormCell(metric, int(band), len(samples.contributors.get(key, ())),
                                  log_rate=robust(logs[bands == band]))
    for key, shares in samples.shares.items():
        low, middle, high = (float(item) for item in np.quantile(shares, SHARE_QUANTILES))
        cells[key] = replace(cells.get(key, NormCell(key[0], key[1], len(shares))),
                             share=(low, middle, high))
    for band, values in samples.ervs.items():
        cells[(ERV, band)] = NormCell(ERV, band, len(values), log_erv=robust(np.array(values)))
    confidence = min(1.0, samples.posts / FULL_CONFIDENCE_POSTS)
    return Norm(platform, account_id, "account", samples.posts, confidence, decay, cells)


def _median_norm(platform: str, norms: Sequence[Norm]) -> Norm:
    decay: dict[str, DecayFit] = {}
    for metric in {metric for norm in norms for metric in norm.decay}:
        fits = [norm.decay[metric] for norm in norms if metric in norm.decay]
        decay[metric] = DecayFit(*(float(np.median([getattr(fit, name) for fit in fits]))
                                   for name in ("a", "b", "c")))
    cells: dict[tuple[str, int], NormCell] = {}
    for key in sorted({key for norm in norms for key in norm.cells}):
        group = [norm.cells[key] for norm in norms if key in norm.cells]
        cells[key] = NormCell(
            key[0], key[1], sum(cell.sample_size for cell in group),
            log_rate=_median_robust([cell.log_rate for cell in group]),
            share=_median_share([cell.share for cell in group]),
            log_erv=_median_robust([cell.log_erv for cell in group]),
        )
    confidence = min(1.0, len(norms) / FULL_CONFIDENCE_ACCOUNTS)
    return Norm(platform, None, "platform", sum(norm.posts for norm in norms), confidence, decay, cells)


def _median_robust(values: Sequence[Robust | None]) -> Robust | None:
    present = [item for item in values if item is not None]
    if not present:
        return None
    medians = np.array([item.median for item in present])
    center = float(np.median(medians))
    # Норму площадки применяют к постам аккаунтов без своей нормы, поэтому её
    # разброс — это и разброс внутри аккаунта, и разброс между аккаунтами.
    within = float(np.median([item.mad for item in present]))
    between = float(np.median(np.abs(medians - center)))
    return Robust(center, float(np.hypot(within, between)))


def _median_share(values: Sequence[tuple[float, float, float] | None]):
    present = [item for item in values if item is not None]
    return tuple(float(item) for item in np.median(present, axis=0)) if present else None


def _anchor(norm: Norm, platform: Norm) -> Norm:
    decay = dict(norm.decay)
    for metric, fit in norm.decay.items():
        base = platform.decay.get(metric)
        if base is None:
            continue
        b = float(np.clip(fit.b, base.b - ANCHOR_EXPONENT, base.b + ANCHOR_EXPONENT))
        c = float(np.clip(fit.c, base.c / ANCHOR_SHIFT_FACTOR, base.c * ANCHOR_SHIFT_FACTOR))
        decay[metric] = DecayFit(fit.a, float(np.clip(b, *DECAY_EXPONENT_BOUNDS)),
                                 float(np.clip(c, *DECAY_SHIFT_BOUNDS)))
    cells = {}
    for key, cell in norm.cells.items():
        base = platform.cells.get(key)
        if base is None:
            cells[key] = cell
            continue
        share = cell.share
        if share is not None and base.share is not None:
            low, middle, high = (float(np.clip(value, anchor - ANCHOR_SHARE, anchor + ANCHOR_SHARE))
                                 for value, anchor in zip(share, base.share))
            share = (low, middle, high)
        cells[key] = replace(cell, log_rate=_anchor_robust(cell.log_rate, base.log_rate),
                             share=share, log_erv=_anchor_robust(cell.log_erv, base.log_erv))
    return Norm(norm.platform, norm.account_id, "account", norm.posts, norm.confidence, decay, cells)


def _anchor_robust(value: Robust | None, base: Robust | None) -> Robust | None:
    if value is None or base is None:
        return value
    reach = ANCHOR_MADS * base.mad
    return Robust(float(np.clip(value.median, base.median - reach, base.median + reach)), value.mad)


def raw_account_norm(platform: str, account_id: UUID, posts: Sequence[PreparedSeries], *,
                     excluded: frozenset[UUID] = frozenset(), final_age: float = 30 * DAY) -> Norm:
    """Норма одного аккаунта до якоря. Маленькая: ряды аккаунта можно сразу отпустить."""
    return _account_norm(platform, account_id, _collect(posts, excluded, final_age))


def combine(platform: str, raw: Mapping[UUID, Norm]) -> NormSet:
    """Норма площадки — медиана норм аккаунтов; нормы аккаунтов — с якорем к ней."""
    ordered = sorted(raw.items(), key=lambda item: str(item[0]))
    voters = [norm for _, norm in ordered if norm.posts >= MIN_POSTS_FOR_PLATFORM]
    platform_norm = _median_norm(platform, voters)
    accounts = {account: _anchor(norm, platform_norm) for account, norm in ordered
                if norm.posts >= MIN_ACCOUNT_POSTS}
    return NormSet(platform_norm, accounts)


def build_norms(platform: str, posts_by_account: Mapping[UUID, Sequence[PreparedSeries]], *,
                excluded: frozenset[UUID] = frozenset(), final_age: float = 30 * DAY) -> NormSet:
    """Нормы площадки и аккаунтов по подготовленным рядам.

    `excluded` — посты, помеченные абсолютными детекторами, получившие средний
    и высокий уровень, и посты эталона. `final_age` — возраст итога для доли.
    """
    return combine(platform, {account: raw_account_norm(platform, account, posts, excluded=excluded,
                                                        final_age=final_age)
                              for account, posts in posts_by_account.items()})


def build_account_norm(platform_norm: Norm, account_id: UUID, posts: Sequence[PreparedSeries], *,
                       excluded: frozenset[UUID] = frozenset(), final_age: float = 30 * DAY) -> Norm | None:
    """Норма одного аккаунта, заякоренная к уже построенной норме площадки."""
    raw = _account_norm(platform_norm.platform, account_id, _collect(posts, excluded, final_age))
    return _anchor(raw, platform_norm) if raw.posts >= MIN_ACCOUNT_POSTS else None


@dataclass(frozen=True, slots=True)
class Drift:
    max_shift_mads: float
    max_exponent_shift: float

    @property
    def sharp(self) -> bool:
        return self.max_shift_mads > DRIFT_MADS or self.max_exponent_shift > DRIFT_EXPONENT


def drift(new: Norm, previous: Norm | None) -> Drift:
    """Сдвиг новой нормы площадки относительно предыдущей принятой."""
    if previous is None:
        return Drift(0.0, 0.0)
    shifts = [0.0]
    for key, cell in new.cells.items():
        old = previous.cells.get(key)
        if old is None:
            continue
        for current, before in ((cell.log_rate, old.log_rate), (cell.log_erv, old.log_erv)):
            if current is not None and before is not None:
                shifts.append(abs(current.median - before.median) / max(before.mad, MAD_FLOOR))
    exponents = [0.0] + [abs(fit.b - previous.decay[metric].b)
                         for metric, fit in new.decay.items() if metric in previous.decay]
    return Drift(max(shifts), max(exponents))


@dataclass(frozen=True, slots=True)
class ReferencePost:
    case_id: str
    subject: PostSeries
    siblings: tuple[PostSeries, ...]
    required_level: Level
    # Честный эталон проверяется и сверху: норма, поднимающая органику до
    # выраженной аномалии, так же непригодна, как норма, прячущая подачу.
    allowed_level: Level | None = None


class ReferenceAssessor(Protocol):
    """Сборка уровня поста при заданных нормах; реализуется вместе с уровнями."""

    def __call__(self, subject: PostSeries, siblings: tuple[PostSeries, ...],
                 norms: NormSet) -> Level: ...


@dataclass(frozen=True, slots=True)
class ReferenceCheck:
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.failures


def check_reference(norms: NormSet, cases: Iterable[ReferencePost],
                    assess: ReferenceAssessor) -> ReferenceCheck:
    """Эталон обязан получить при новой норме уровень в своих границах."""
    failures = []
    for case in cases:
        level = assess(case.subject, case.siblings, norms)
        if level < case.required_level or (case.allowed_level is not None and level > case.allowed_level):
            failures.append(case.case_id)
    return ReferenceCheck(tuple(failures))


def review(reference: ReferenceCheck, shift: Drift) -> NormStatus:
    if not reference.passed:
        return NormStatus.REJECTED
    return NormStatus.DRIFT_REVIEW if shift.sharp else NormStatus.ACCEPTED


def norm_to_payload(norm: Norm) -> dict:
    """Компактный словарь для jsonb; числа округлены до шести значащих цифр."""
    return {
        "platform": norm.platform,
        "account_id": None if norm.account_id is None else str(norm.account_id),
        "basis": norm.basis, "posts": norm.posts, "confidence": _round(norm.confidence),
        "decay": {metric: [_round(fit.a), _round(fit.b), _round(fit.c)]
                  for metric, fit in sorted(norm.decay.items())},
        "cells": [_cell_payload(cell) for _, cell in sorted(norm.cells.items())],
    }


def norm_from_payload(payload: Mapping) -> Norm:
    cells = {}
    for item in payload["cells"]:
        cell = NormCell(
            item["m"], int(item["band"]), int(item["n"]),
            log_rate=Robust(*item["rate"]) if "rate" in item else None,
            share=(*map(float, item["share"]),) if "share" in item else None,  # type: ignore[arg-type]
            log_erv=Robust(*item["erv"]) if "erv" in item else None,
        )
        cells[(cell.metric, cell.band)] = cell
    account = payload["account_id"]
    return Norm(payload["platform"], None if account is None else UUID(account), payload["basis"],
                int(payload["posts"]), float(payload["confidence"]),
                {metric: DecayFit(*values) for metric, values in payload["decay"].items()}, cells)


def _cell_payload(cell: NormCell) -> dict:
    payload: dict = {"m": cell.metric, "band": cell.band, "n": cell.sample_size}
    if cell.log_rate is not None:
        payload["rate"] = [_round(cell.log_rate.median), _round(cell.log_rate.mad)]
    if cell.share is not None:
        payload["share"] = [_round(value) for value in cell.share]
    if cell.log_erv is not None:
        payload["erv"] = [_round(cell.log_erv.median), _round(cell.log_erv.mad)]
    return payload


def _round(value: float) -> float:
    return float(f"{value:.6g}")
