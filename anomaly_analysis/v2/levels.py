"""Сборка уровня поста из признаков по согласию независимых семейств.

Уровень — не сумма баллов, а согласие методов (исследование, раздел 7):

* слабый сигнал — один признак средней силы или несколько слабых;
* выраженная аномалия — один сильный признак;
* признаки искусственной активности — сильные признаки минимум из двух
  разных семейств.

Тексты здесь — единственное место, где вывод получает слова. Они проходят
глоссарий ADR-006: система сообщает о признаках и сигналах, а не о намерении.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .detectors import (
    ABSOLUTE_DETECTORS, NORM_RELATIVE_DETECTORS, REPOST_DETECTORS, DetectorContext, SiblingActivity,
)
from .domain import DataQuality, Family, Interval, Level, Metric, PostSeries, PostVerdict, Sign
from .norms import LOW_CONFIDENCE, NormSet
from .series import DAY, CollectionCadence, PreparedSeries, prepare

# Пороги силы. Сильный признак — тот, что один даёт выраженную аномалию: у
# детекторов это пуассоновский z в районе десяти и выше или физически
# невозможная картина. Средний — заметное, но объяснимое отклонение. Слабее
# пятой части признак в вывод не попадает вовсе.
STRONG = 0.7
MEDIUM = 0.45
WEAK = 0.2
# Молодая норма не выносит сильных вердиктов: признаки, опирающиеся на неё,
# обрезаются до средней силы (исследование, раздел 8, мера 5).
YOUNG_NORM_CAP = 0.55
MAX_SIGNS = 6
# Признак, больше половины интервала которого лежит в участке «вывод
# невозможен», отбрасывается. Прирост за пробел живёт именно там — он исключение.
UNANALYZABLE_OVERLAP = 0.5
GAP_PATTERN = 4

SYMBOLS = {1: "⟋", 2: "⚡", 4: "⋯", 5: "≈", 6: "⇅", 7: "≫", 8: "⫴", 9: "▭", 10: "◇"}
TITLES = {
    1: "Линейная подача",
    2: "Поздний скачок",
    4: "Прирост за пробел в замерах",
    5: "Реакции догоняют просмотры",
    6: "Реакции раньше просмотров",
    7: "Реакций больше, чем просмотров",
    8: "Синхронный подъём на постах аккаунта",
    9: "Рывок, обрывающийся в плато",
    10: "ERV вне нормы аккаунта",
}
LEVEL_SYMBOLS = {0: "○", 1: "◔", 2: "◑", 3: "●"}
LEVEL_LABELS = {
    0: "нет признаков",
    1: "слабый сигнал",
    2: "выраженная аномалия",
    3: "признаки искусственной активности",
}
ALTERNATIVES = {
    "recommendation_feed": "пост долго показывался в рекомендациях с ровным притоком",
    "smoothed_large_audience": "крупная аудитория со сглаженным трафиком",
    "counter_update_delay": "площадка обновила счётчик просмотров позже счётчика реакций",
    "views_counter_delay": "счётчик просмотров отстал от счётчика реакций",
    "account_mentioned_externally": "аккаунт упомянули во внешнем источнике, и старые посты посмотрели заново",
    "counter_frozen": "площадка перестала обновлять счётчик",
    "news_event": "новостной повод вернул внимание к посту",
    "pinned_post": "пост закрепили или подняли в ленте",
    "forward_by_large_channel": "похоже на пересылку крупным каналом",
    "recommendation_wave": "новая волна показов из рекомендаций площадки",
    "collection_outage_during_organic_wave": "во время пробела сбора у поста была живая волна",
    "evergreen_post": "пост-«вечнозелёнка» с живым поздним трафиком",
    "viral_post": "пост честно «выстрелил» и собрал больше реакций, чем обычно",
    "wide_reach_low_engagement": "пост разошёлся шире обычной аудитории, которая реагирует реже",
}
QUALITY_TEXTS = {
    "truncated_start": "ряд начат позже публикации: ранняя волна не оценивается",
    "repost_source_counter": "пост — репост: просмотры принадлежат источнику, проверяются только реакции",
    "no_norm": "нормы ещё нет: признаки относительно нормы не сильнее слабого сигнала",
    "young_norm": "норма молодая: признаки относительно нормы не сильнее слабого сигнала",
    "gaps": "в замерах есть пробелы: на этих участках вывод невозможен",
}
DISCLAIMER = ("Сигнал сам по себе не доказывает искусственное происхождение активности "
              "или действия университета.")


def assess(subject: PostSeries, siblings: Sequence[PostSeries] = (), *, norms: NormSet | None = None,
           subscribers: Iterable[tuple[datetime, int]] = (), analyzed_at: datetime | None = None,
           cadence: CollectionCadence | None = None, norm_version: int | None = None,
           activity: SiblingActivity | None = None, carried: Sequence[Sign] = ()) -> PostVerdict:
    """Вывод по посту.

    `siblings` — другие посты того же аккаунта рядами; работник вместо них
    передаёт готовые почасовые агрегаты `activity`. `carried` — признаки
    прежнего вывода, чей участок уже вне окна агрегатов: синхронный подъём,
    найденный неделю назад, не исчезает оттого, что окно ушло вперёд.
    """
    moment = analyzed_at or (subject.observed_at[-1] if subject.observed_at else subject.published_at)
    prepared = prepare(subject, moment, cadence or CollectionCadence())
    context = _context(prepared, siblings, norms, subscribers, activity)
    signs, versions = run_detectors(prepared, context)
    return verdict(prepared, context, [*signs, *carried], versions, norm_version)


def run_detectors(prepared: PreparedSeries, context: DetectorContext) -> tuple[list[Sign], dict[str, str]]:
    repost = prepared.series.is_repost
    detectors = REPOST_DETECTORS if repost else ABSOLUTE_DETECTORS + NORM_RELATIVE_DETECTORS
    signs: list[Sign] = []
    for detector in detectors:
        signs.extend(detector.detect(prepared, context))
    return signs, {detector.ID: detector.VERSION for detector in detectors}


def verdict(prepared: PreparedSeries, context: DetectorContext, signs: Sequence[Sign],
            versions: dict[str, str], norm_version: int | None = None) -> PostVerdict:
    unanalyzable = _unanalyzable(prepared)
    kept = []
    for sign in signs:
        if sign.pattern != GAP_PATTERN and _overlap(sign.interval, unanalyzable) > UNANALYZABLE_OVERLAP:
            continue
        if sign.norm_confidence is not None and sign.norm_confidence < LOW_CONFIDENCE:
            sign = replace(sign, strength=min(sign.strength, YOUNG_NORM_CAP))
        if sign.strength >= WEAK:
            kept.append(sign)
    level = level_for(kept)
    ordered = sorted(kept, key=lambda item: (-item.strength, item.pattern))[:MAX_SIGNS]
    return PostVerdict(prepared.series.publication_id, level, tuple(ordered) if level else (),
                       _quality(prepared, context, unanalyzable), versions, norm_version)


def level_for(signs: Iterable[Sign]) -> Level:
    signs = list(signs)
    strong_families = {sign.family for sign in signs if sign.strength >= STRONG}
    if len(strong_families) >= 2:
        return Level.ARTIFICIAL_ACTIVITY_SIGNS
    if strong_families:
        return Level.PRONOUNCED_ANOMALY
    if any(sign.strength >= MEDIUM for sign in signs) or sum(sign.strength >= WEAK for sign in signs) >= 2:
        return Level.WEAK_SIGNAL
    return Level.NONE


def compact(verdict: PostVerdict) -> dict[str, Any]:
    """Вывод для хранения и API: всё, что нужно показать, уже со словами."""
    return {
        "level": int(verdict.level),
        "levelLabel": LEVEL_LABELS[int(verdict.level)],
        "levelSymbol": LEVEL_SYMBOLS[int(verdict.level)],
        "signals": [sign_payload(sign) for sign in verdict.signs],
        "quality": quality_payload(verdict.quality),
        "disclaimer": DISCLAIMER,
    }


def sign_payload(sign: Sign) -> dict[str, Any]:
    return {
        "pattern": sign.pattern, "symbol": SYMBOLS[sign.pattern], "title": TITLES[sign.pattern],
        "family": sign.family.value, "metric": sign.metric.value, "strength": round(sign.strength, 3),
        "startAt": sign.interval.start.isoformat(), "endAt": sign.interval.end.isoformat(),
        "scaleSeconds": int(sign.scale.total_seconds()), "formula": sign.formula,
        "render": dict(sign.render),
        "alternatives": [{"code": code, "text": ALTERNATIVES[code]} for code in sign.alternatives],
        "normConfidence": None if sign.norm_confidence is None else round(sign.norm_confidence, 3),
    }


def sign_from_payload(payload: Mapping[str, Any]) -> Sign:
    """Обратно к признаку из сохранённого вида — для переноса в новый вывод."""
    return Sign(int(payload["pattern"]), Family(payload["family"]), Metric(payload["metric"]),
                float(payload["strength"]),
                Interval(datetime.fromisoformat(payload["startAt"]), datetime.fromisoformat(payload["endAt"])),
                timedelta(seconds=int(payload["scaleSeconds"])), payload["formula"], payload.get("render", {}),
                tuple(item["code"] for item in payload.get("alternatives", ())),
                payload.get("normConfidence"))


def quality_payload(quality: DataQuality) -> dict[str, Any]:
    texts = [QUALITY_TEXTS[code] for code in quality.codes if code in QUALITY_TEXTS]
    return {
        "coverage": round(quality.coverage, 4),
        "summary": "; ".join(texts) if texts else f"замеры полные, покрытие {quality.coverage:.0%}",
        "codes": list(quality.codes),
        "unanalyzable": [{"startAt": item.start.isoformat(), "endAt": item.end.isoformat()}
                         for item in quality.unanalyzable],
    }


def reference_assessor(cadence: CollectionCadence | None = None):
    """Проверка версии нормы эталоном: уровень эталонного поста при этой норме."""
    def assess_with(subject: PostSeries, siblings: tuple[PostSeries, ...], norms: NormSet) -> Level:
        return assess(subject, siblings, norms=norms, cadence=cadence).level
    return assess_with


def _context(prepared: PreparedSeries, siblings: Sequence[PostSeries], norms: NormSet | None,
             subscribers: Iterable[tuple[datetime, int]],
             activity: SiblingActivity | None = None) -> DetectorContext:
    series = prepared.series
    norm = None
    if norms is not None and norms.platform.platform == series.platform:
        norm = norms.for_account(series.account_id)
    if activity is not None:
        activity = activity.without(series.publication_id)
    elif siblings and series.observed_at:
        activity = SiblingActivity.from_series(
            tuple(item for item in siblings if item.publication_id != series.publication_id),
            series.observed_at[0].timestamp() - DAY, prepared.analyzed_at.timestamp())
    rows = sorted(subscribers)
    published = series.published_at
    return DetectorContext(
        series.platform, norm, activity,
        np.array([(at - published).total_seconds() for at, _ in rows], dtype=np.float64),
        np.array([count for _, count in rows], dtype=np.float64),
    )


def _unanalyzable(prepared: PreparedSeries) -> tuple[Interval, ...]:
    published = prepared.series.published_at
    spans = sorted((gap.start_age, gap.end_age) for metric in (Metric.VIEWS, Metric.REACTIONS)
                   if metric in prepared.metrics for gap in prepared.metrics[metric].gaps)
    merged: list[list[float]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return tuple(Interval(published + timedelta(seconds=start), published + timedelta(seconds=end))
                 for start, end in merged)


def _overlap(interval: Interval, spans: Sequence[Interval]) -> float:
    total = (interval.end - interval.start).total_seconds()
    covered = sum(max(0.0, (min(interval.end, span.end) - max(interval.start, span.start)).total_seconds())
                  for span in spans)
    return covered / total if total > 0 else 0.0


def _quality(prepared: PreparedSeries, context: DetectorContext,
             unanalyzable: tuple[Interval, ...]) -> DataQuality:
    codes = []
    if prepared.truncated_start:
        codes.append("truncated_start")
    if prepared.series.is_repost:
        codes.append("repost_source_counter")
    if context.norm is None:
        codes.append("no_norm")
    elif context.norm.young:
        codes.append("young_norm")
    if unanalyzable:
        codes.append("gaps")
    coverages = [prepared.metrics[metric].coverage for metric in (Metric.VIEWS, Metric.REACTIONS)
                 if metric in prepared.metrics]
    return DataQuality(min(coverages) if coverages else 0.0, unanalyzable, tuple(codes))
