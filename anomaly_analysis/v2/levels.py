"""Сборка уровня поста из признаков по согласию независимых семейств.

Уровень — не сумма баллов, а согласие методов (исследование, раздел 7):

* слабый сигнал — один признак средней силы или несколько слабых;
* выраженная аномалия — один сильный признак;
* признаки искусственной активности — сильные признаки минимум из двух
  разных семейств либо подтверждённый короткий рывок с плато и продолжающимся
  притоком зрителей без сопоставимого отклика.

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
from .detectors.reactions_before_views import ENDPOINT_MODE
from .domain import DataQuality, Family, Interval, Level, Metric, PostSeries, PostVerdict, Sign
from .detectors.bounded_reaction_burst import (
    CONFIRMED_PLATEAU_MODE, MEASUREMENT_MODE as BOUNDED_REACTION_MODE, REPORTED_SHAPE_MODE,
)
from .detectors.burst_plateau import RAPID_VIEW_MODE, VIEW_MEASUREMENT_MODE
from .detectors import engagement_regime
from .detectors.engagement_regime import CONFIRMED_MODE as CONFIRMED_EPISODE_MODE
from .detectors.late_engagement import MEASUREMENT_MODE as LATE_ENGAGEMENT_MODE
from .detectors.reactions_exceed_views import TELEGRAM_ORDER_MODE
from .norms import LOW_CONFIDENCE, NormSet
from .mature_reference import MatureReference, ReferenceSet, PATTERNS as REFERENCE_PATTERNS, VERSION as REFERENCE_VERSION
from .series import DAY, PREPARATION_VERSION, CollectionCadence, PreparedSeries, prepare, views_belong_to_source

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
AGGREGATION_VERSION = "2.5.0"
# Признак, больше половины интервала которого лежит в участке «вывод
# невозможен», отбрасывается. Прирост за пробел живёт именно там — он исключение.
UNANALYZABLE_OVERLAP = 0.5
GAP_PATTERN = 4
# Признаки одного события, разделённые не больше чем этим, — одно событие:
# детектор рывка доказывает соседние пятиминутки по отдельности.
SAME_EVENT_GAP = timedelta(minutes=10)
# RuTube: форма прихода просмотров — не признак. Видео внутри площадки почти
# не находят, смотрят по ссылке из соцсети или с сайта: волна за час-два и
# тишина. По журналу циклов (квитанции подтвердили 49 из 52 мест роста) так
# выглядят 13 % постов RuTube из 30 аккаунтов — это норма площадки, а не
# пакет. Рывок с плато и поздний скачок просмотров, а с ними рывок
# реакций в ту же волну, ослабляются ниже порога вывода: при пороге 0,3 две
# волны одного поста давали слабый сигнал у 3 % постов RuTube. Реакции,
# оторванные от просмотров (6, 7, 14), и линейная подача (1: волна по ссылке
# не бывает ровной по часам) проверяются как прежде.
RUTUBE_WAVE_CAP = 0.15
RUTUBE_VIEW_SHAPES = frozenset({2, 9})
# Волна по ссылке растягивается на десятки минут; скачок, доказанный на
# более коротком окне (при частых замерах), — уже не она.
RUTUBE_WAVE_SCALE = timedelta(minutes=30)

SYMBOLS = {1: "⟋", 2: "⚡", 4: "⋯", 5: "≈", 6: "⇅", 7: "≫", 8: "⫴", 9: "▭", 10: "◇", 11: "↥", 12: "↗", 13: "↻",
           14: "⊓", 15: "↧", 16: "⌐"}
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
    11: "Отклик выше исторического диапазона",
    12: "Продолжение отклика выше ожидаемого",
    13: "Поздняя вовлечённость выше ранней",
    14: "Пакет реакций, оторванный от просмотров",
    15: "Площадка списала реакции",
    16: "Одновременный обрыв просмотров и реакций",
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
    "reaction_counter_batch_update": "площадка обновила счётчик реакций пакетно",
    "returning_readers": "ранее увидевшие пост читатели вернулись и поставили реакции",
    "views_counter_delay": "счётчик просмотров отстал от счётчика реакций",
    "account_mentioned_externally": "аккаунт упомянули во внешнем источнике, и старые посты посмотрели заново",
    "counter_frozen": "площадка перестала обновлять счётчик",
    "audience_change": "изменилась аудитория или обычное продвижение аккаунта",
    "news_event": "новостной повод вернул внимание к посту",
    "pinned_post": "пост закрепили или подняли в ленте",
    "forward_by_large_channel": "похоже на пересылку крупным каналом",
    "recommendation_wave": "новая волна показов из рекомендаций площадки",
    "collection_outage_during_organic_wave": "во время пробела сбора у поста была живая волна",
    "conditional_count_variation": "обычные реакции могут иметь разброс ниже пуассоновского",
    "evergreen_post": "пост-«вечнозелёнка» с живым поздним трафиком",
    "viral_post": "пост честно «выстрелил» и собрал больше реакций, чем обычно",
    "wide_reach_low_engagement": "пост разошёлся шире обычной аудитории, которая реагирует реже",
    "interested_audience_found_post": "пост нашла заинтересованная аудитория: подборка, профильный чат или новый увлечённый читатель архива",
    "multiple_reactions_per_viewer": "один читатель мог поставить несколько реакций; правило сравнения использует порог 1:1",
    "external_link_wave": "видео посмотрели по ссылке из соцсети или с сайта: на RuTube такие волны обычны",
    "platform_write_off": "площадка удалила реакции аккаунтов, которые сочла недостоверными",
    "post_edited_reactions_reset": "пост пересоздали или изменили так, что площадка сбросила часть реакций",
}
QUALITY_TEXTS = {
    "reported_reaction_shape": "форма сохранённых реакций отмечена слабым сигналом без подтверждения точности или сопоставимой аудитории",
    "no_precise_metrics": "недостаточно данных для точных проверок; отсутствие сигнала не подтверждает обычность статистики",
    "bounded_reaction_counts": "крупные изменения реакций проверены с учётом точности каждого счётчика; форма роста между замерами неизвестна",
    "bounded_view_counts": "крупные изменения просмотров проверены с учётом точности счётчиков; форма роста между замерами неизвестна",
    "telegram_counter_order": "реакции и просмотры сопоставлены по правилу 1:1; при пересечении диапазонов округления превышение показано слабым сигналом",
    "non_exact_counters": "округлённые счётчики и значения без подтверждённой точности исключены из точных проверок",
    "uncertain_observations": "замеры с неопределённым интервалом исключены из точных проверок",
    "truncated_start": "начало истории отсутствует: рост до первого замера не оценивается",
    "repost_source_counter": "пост — репост: просмотры принадлежат источнику, проверяются только реакции",
    "no_norm": "нормы ещё нет: признаки относительно нормы не сильнее слабого сигнала",
    "young_norm": "норма молодая: признаки относительно нормы не сильнее слабого сигнала",
    "gaps": "в замерах есть пробелы: форма роста недоступной метрики внутри них неизвестна; прирост между пригодными замерами проверяется отдельно",
}
DISCLAIMER = ("Сигнал сам по себе не доказывает искусственное происхождение активности "
              "или действия университета.")


def assess(subject: PostSeries, siblings: Sequence[PostSeries] = (), *, norms: NormSet | None = None,
           subscribers: Iterable[tuple[datetime, int]] = (), analyzed_at: datetime | None = None,
           cadence: CollectionCadence | None = None, norm_version: int | None = None,
           activity: SiblingActivity | None = None, carried: Sequence[Sign] = (),
           reference: MatureReference | ReferenceSet | None = None) -> PostVerdict:
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
    if reference is not None:
        signs.extend(reference.detect(subject, moment))
        versions["mature_reference"] = REFERENCE_VERSION
        versions["mature_reference_model"] = reference.version_for(subject)
    return verdict(prepared, context, [*signs, *carried], versions, norm_version)


def run_detectors(prepared: PreparedSeries, context: DetectorContext) -> tuple[list[Sign], dict[str, str]]:
    repost = prepared.series.is_repost
    detectors = REPOST_DETECTORS if repost else ABSOLUTE_DETECTORS + NORM_RELATIVE_DETECTORS
    signs: list[Sign] = []
    for detector in detectors:
        signs.extend(detector.detect(prepared, context))
    signs = _widen_to_episodes(prepared, context, signs)
    signs = [replace(sign, render={"measurementMode": "exact_quality_v1", **sign.render}) for sign in signs]
    return signs, {"preparation": PREPARATION_VERSION, "aggregation": AGGREGATION_VERSION,
                   **{detector.ID: detector.VERSION for detector in detectors}}


def _widen_to_episodes(prepared: PreparedSeries, context: DetectorContext, signs: list[Sign]) -> list[Sign]:
    """Рывок реакций на коротком окне подсвечивает весь эпизод, в котором лежит.

    Детектор рывка доказывает изменение на самом коротком убедительном окне;
    отрезок с той же высокой долей реакций вокруг него — тот же пакет, и
    читатель должен видеть его целиком. Формула и числа признака не меняются.
    """
    reactions_bursts = [sign for sign in signs if sign.pattern == 9 and sign.metric is Metric.REACTIONS]
    if not reactions_bursts:
        return signs
    spans = engagement_regime.episode_spans(prepared, context)
    published = prepared.series.published_at
    widened = []
    for sign in signs:
        if sign in reactions_bursts:
            start = (sign.interval.start - published).total_seconds()
            end = (sign.interval.end - published).total_seconds()
            for low, high in spans:
                if low <= start + 60 and end - 60 <= high and (high - low) > (end - start):
                    sign = replace(sign, interval=Interval(published + timedelta(seconds=low),
                                                           published + timedelta(seconds=high)),
                                   render={**sign.render, "startAge": round(low), "endAge": round(high),
                                           "burstStartAge": round(start), "burstEndAge": round(end)})
                    break
        widened.append(sign)
    return widened


def verdict(prepared: PreparedSeries, context: DetectorContext, signs: Sequence[Sign],
            versions: dict[str, str], norm_version: int | None = None) -> PostVerdict:
    unanalyzable = _unanalyzable(prepared)
    kept = []
    signs = _rutube_waves(prepared, signs)
    for sign in signs:
        bounded_counts = (sign.pattern == 9 and (
            sign.metric is Metric.REACTIONS and sign.render.get("measurementMode") in {BOUNDED_REACTION_MODE, REPORTED_SHAPE_MODE}
            or sign.metric is Metric.VIEWS and sign.render.get("measurementMode") == VIEW_MEASUREMENT_MODE)
            or sign.pattern == 7 and sign.family is Family.CROSS_METRIC
            and sign.render.get("measurementMode") == TELEGRAM_ORDER_MODE)
        required = (Metric.VIEWS, Metric.REACTIONS) if sign.family is Family.CROSS_METRIC else (sign.metric,)
        if not bounded_counts and any(metric not in prepared.metrics for metric in required):
            continue
        # A validated endpoint model makes no claim about timing inside gaps.
        endpoint_reference = (sign.pattern in REFERENCE_PATTERNS
                              and sign.render.get("measurementMode") == "exact_quality_v1")
        relevant_gaps = _unanalyzable(prepared, required)
        endpoint_comparison = (sign.pattern == 6 and sign.family is Family.CROSS_METRIC
                               and sign.render.get("measurementMode") == "exact_quality_v1"
                               and sign.render.get("comparisonMode") == ENDPOINT_MODE)
        # Late engagement compares exact endpoints of a days-long window.
        late_endpoints = sign.pattern == 13 and sign.render.get("measurementMode") == LATE_ENGAGEMENT_MODE
        if (sign.pattern != GAP_PATTERN and not endpoint_reference and not bounded_counts
                and not endpoint_comparison and not late_endpoints
                and _overlap(sign.interval, relevant_gaps) > UNANALYZABLE_OVERLAP):
            continue
        if sign.norm_confidence is not None and sign.norm_confidence < LOW_CONFIDENCE:
            sign = replace(sign, strength=min(sign.strength, YOUNG_NORM_CAP))
        if sign.strength >= WEAK:
            kept.append(sign)
    unique = _same_events(kept)
    level = level_for(unique)
    # Keep the independent evidence that produced the level visible even when
    # one family has more than six stronger events.
    families = set()
    required = []
    for index, sign in enumerate(unique):
        if sign.strength >= STRONG and sign.family not in families:
            required.append(index)
            families.add(sign.family)
    chosen = (required + [i for i in range(len(unique)) if i not in required])[:MAX_SIGNS]
    ordered = [unique[i] for i in sorted(chosen)]
    quality = _quality(prepared, context, unanalyzable)
    if any(sign.render.get("measurementMode") == BOUNDED_REACTION_MODE for sign in ordered):
        quality = replace(quality, codes=(*quality.codes, "bounded_reaction_counts"))
    if any(sign.render.get("measurementMode") == VIEW_MEASUREMENT_MODE for sign in ordered):
        quality = replace(quality, codes=(*quality.codes, "bounded_view_counts"))
    if any(sign.render.get("measurementMode") == TELEGRAM_ORDER_MODE for sign in ordered):
        quality = replace(quality, codes=(*quality.codes, "telegram_counter_order"))
    if any(sign.render.get("measurementMode") == REPORTED_SHAPE_MODE for sign in ordered):
        quality = replace(quality, codes=(*quality.codes, "reported_reaction_shape"))
    return PostVerdict(prepared.series.publication_id, level, tuple(ordered) if level else (),
                       quality, versions, norm_version)


def _rutube_waves(prepared: PreparedSeries, signs: Sequence[Sign]) -> list[Sign]:
    if prepared.series.platform != "rutube":
        return list(signs)
    def wave(sign: Sign) -> bool:
        return (sign.pattern in RUTUBE_VIEW_SHAPES and sign.metric is Metric.VIEWS
                and sign.scale >= RUTUBE_WAVE_SCALE)
    waves = [sign.interval for sign in signs if wave(sign)]
    capped = []
    for sign in signs:
        view_shape = wave(sign)
        same_wave = (sign.pattern == 9 and sign.metric is Metric.REACTIONS
                     and any(sign.interval.start <= wave.end + SAME_EVENT_GAP
                             and wave.start <= sign.interval.end + SAME_EVENT_GAP for wave in waves))
        if (view_shape or same_wave) and sign.strength > RUTUBE_WAVE_CAP:
            sign = replace(sign, strength=RUTUBE_WAVE_CAP,
                           alternatives=tuple(dict.fromkeys(("external_link_wave", *sign.alternatives))))
        capped.append(sign)
    return capped


def _event(sign: Sign) -> tuple[Any, ...]:
    """Что именно утверждает признак — у разных детекторов одного события ключ общий.

    Рывок реакций (9) и пакет реакций (14) — два способа увидеть одну и ту же
    пачку реакций на фоне просмотров: рывок доказывает её на коротком окне,
    эпизод — по доле реакций на просмотр. Как два независимых семейства они
    давали уровень 3 одним событием.
    """
    if sign.pattern == 14 or sign.pattern == 9 and sign.metric is Metric.REACTIONS:
        return ("reaction_episode",)
    return (sign.pattern, sign.metric, sign.family)


def _same_events(signs: Sequence[Sign]) -> list[Sign]:
    """Признаки одного события — один признак: сильнейший, на весь участок события.

    Остальные названия уходят в `render.sameEpisode`: читатель видит, что
    событие подтвердили несколько проверок, но в уровень оно входит один раз.
    """
    unique: list[Sign] = []
    others: dict[int, list[str]] = {}
    patterns: dict[int, set[int]] = {}
    for sign in sorted(signs, key=lambda item: (not _confirmed_plateau(item), -item.strength, item.pattern)):
        for index, item in enumerate(unique):
            if (_event(sign) == _event(item) and sign.interval.start <= item.interval.end + SAME_EVENT_GAP
                    and item.interval.start <= sign.interval.end + SAME_EVENT_GAP):
                unique[index] = replace(item, interval=Interval(min(item.interval.start, sign.interval.start),
                                                                max(item.interval.end, sign.interval.end)))
                if sign.pattern != item.pattern:
                    patterns.setdefault(index, set()).add(sign.pattern)
                title = sign_title(sign)
                if title != sign_title(item):
                    others.setdefault(index, [])
                    if title not in others[index]:
                        others[index].append(title)
                break
        else:
            unique.append(sign)
    return [replace(item, render={**item.render, "sameEpisode": others[index],
                                  "sameEpisodePatterns": sorted(patterns.get(index, ()))})
            if index in others else item for index, item in enumerate(unique)]


def _confirmed_plateau(sign: Sign) -> bool:
    if sign.pattern == 14:
        return sign.strength >= .9 and sign.render.get("plateauEvidence") == CONFIRMED_EPISODE_MODE
    return (sign.pattern == 9 and sign.family is Family.SHAPE and sign.strength >= .9
            and (sign.metric, sign.render.get("measurementMode"), sign.render.get("plateauEvidence")) in {
                (Metric.REACTIONS, BOUNDED_REACTION_MODE, CONFIRMED_PLATEAU_MODE),
                (Metric.VIEWS, VIEW_MEASUREMENT_MODE, RAPID_VIEW_MODE),
            })


def level_for(signs: Iterable[Sign]) -> Level:
    signs = list(signs)
    strong_families = {sign.family for sign in signs if sign.strength >= STRONG}
    if len(strong_families) >= 2 or any(_confirmed_plateau(sign) for sign in signs):
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


def sign_title(sign: Sign) -> str:
    title = TITLES[sign.pattern]
    if sign.render.get("measurementMode") == REPORTED_SHAPE_MODE:
        title = "Рывок реакций с плато по сохранённым значениям"
    elif sign.render.get("measurementMode") == BOUNDED_REACTION_MODE:
        title = ("Рывок, переходящий в плато" if sign.render.get("plateauEvidence") == CONFIRMED_PLATEAU_MODE
                 else "Резкий прирост реакций с последующим замедлением")
        if sign.render.get("mode") == "initial_plateau":
            title = "Ранние реакции с последующим плато"
        if sign.render.get("roundingLimited"):
            title = "Рывок с плато в округлённых счётчиках"
    elif sign.render.get("measurementMode") == VIEW_MEASUREMENT_MODE:
        title = "Резкий скачок просмотров с последующим плато"
    elif sign.pattern == 6 and sign.render.get("comparisonMode") == ENDPOINT_MODE:
        title = "Прирост реакций при малом приросте просмотров"
    elif sign.pattern == 14:
        if sign.render.get("viewsSurge"):
            title = "Приток просмотров без отклика"
        elif sign.render.get("mode") == "start":
            title = "Реакции включились без новой аудитории"
        else:
            title = "Пакет реакций с остановкой"
    return title


def sign_payload(sign: Sign) -> dict[str, Any]:
    title = sign_title(sign)
    return {
        "pattern": sign.pattern, "symbol": SYMBOLS[sign.pattern], "title": title,
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


def _unanalyzable(prepared: PreparedSeries,
                  metrics: Iterable[Metric] = (Metric.VIEWS, Metric.REACTIONS)) -> tuple[Interval, ...]:
    published = prepared.series.published_at
    spans = sorted((gap.start_age, gap.end_age) for metric in metrics
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
    codes = list(prepared.quality_codes)
    if prepared.truncated_start:
        codes.append("truncated_start")
    if views_belong_to_source(prepared.series):
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
