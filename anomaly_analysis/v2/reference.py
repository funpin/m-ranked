"""Синтетический эталон анализа аномальной динамики.

Каждый случай — ряд поста (и, где нужно, посты того же аккаунта) с разметкой
ожидаемого вывода. Органика — сумма волн степенного затухания
`r(t) ∝ (1 + t/c)^-(1+θ)` (Crane–Sornette) с суточным ритмом и пуассоновским
шумом; реакции, комментарии и репосты приходят от живых просмотров с долей,
медленно падающей с возрастом. Подозрительная активность накладывается
поверх органики с малым шумом: механическая подача ровнее живой аудитории.

Генератор детерминирован: у каждого случая свой сид от общего и имени
случая, так что правка одного случая не сдвигает остальные.

Модуль живёт в пакете, а не в тестах, и файлов не пишет: ночное задание норм
строит эталон в памяти и проверяет им каждую новую версию нормы, тесты берут
его отсюда же. Источник правды один — этот код; сгенерированные ряды нигде не
хранятся. Реальные выгруженные ряды эталона — отдельно, в каталоге вне
репозитория (`ANOMALY_REFERENCE_DIRS`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import math
import random
from typing import Iterator, Mapping, Protocol
from uuid import UUID, uuid5
import zlib

import json

from anomaly_analysis.tools.reference_format import ReferenceCase, case_payload, dumps, parse_case
from anomaly_analysis.v2.domain import Level, Metric, PostSeries

SEED = 20260923
NAMESPACE = UUID("6a1f4b0e-2c8d-4e57-9b3a-0d5e7c9f1a24")

MINUTE, HOUR, DAY = 60, 3600, 86400
MSK = timezone(timedelta(hours=3))
V, R, C, S = Metric.VIEWS, Metric.REACTIONS, Metric.COMMENTS, Metric.SHARES

# Публичные счётчики площадок: пересылок Telegram и MAX с веб-страницы не видно,
# у RuTube их тоже нет, ВК отдаёт репосты у каждого поста.
PLATFORM_METRICS = {
    "telegram": (V, R, C),
    "vk": (V, R, C, S),
    "max": (V, R, C),
    "rutube": (V, R, C),
}
RATIOS = {
    "telegram": {R: 0.02, C: 0.002},
    "vk": {R: 0.03, C: 0.003, S: 0.004},
    "max": {R: 0.015, C: 0.001},
    "rutube": {R: 0.02, C: 0.003},
}


def cadence(platform: str, age: float) -> int:
    """Шаг сбора по возрасту поста — тот же, что у сборщиков."""
    if platform == "rutube":
        return HOUR if age < 3 * DAY else 3 * HOUR if age < 7 * DAY else 6 * HOUR
    if age < DAY:
        return 5 * MINUTE
    return 15 * MINUTE if age < 3 * DAY else 30 * MINUTE if age < 7 * DAY else HOUR


class Component(Protocol):
    def cumulative(self, age: float) -> float: ...


@dataclass(frozen=True)
class Wave:
    """Волна внимания с интегралом `total` до бесконечности."""

    start: float
    total: float
    c: float
    theta: float

    def cumulative(self, age: float) -> float:
        if age <= self.start:
            return 0.0
        return self.total * (1 - (1 + (age - self.start) / self.c) ** -self.theta)


@dataclass(frozen=True)
class Ramp:
    """Постоянная скорость на интервале; короткий интервал — ступенька в один замер."""

    start: float
    end: float
    total: float

    def cumulative(self, age: float) -> float:
        return self.total * min(1.0, max(0.0, (age - self.start) / (self.end - self.start)))


@dataclass(frozen=True)
class Hump:
    """Растянутый плавный подъём: скорость ∝ sin², без излома на краях."""

    start: float
    end: float
    total: float

    def cumulative(self, age: float) -> float:
        x = min(1.0, max(0.0, (age - self.start) / (self.end - self.start)))
        return self.total * (x - math.sin(2 * math.pi * x) / (2 * math.pi))


@dataclass(frozen=True)
class Follow:
    """Добавка к метрике, равная доле прироста просмотров, — подгонка под них."""

    start: float
    end: float
    ratio: float


@dataclass(frozen=True)
class Post:
    platform: str
    published_at: datetime
    waves: tuple[Wave, ...]
    horizon: float
    injections: Mapping[Metric, tuple[Component | Follow, ...]] = field(default_factory=dict)
    ratios: Mapping[Metric, float] | None = None
    start: float | None = None
    gaps: tuple[tuple[float, float], ...] = ()
    nulls: tuple[tuple[Metric, float, float], ...] = ()
    rhythm: float = 0.25
    is_repost: bool = False


def _poisson(rng: random.Random, mean: float) -> int:
    if mean <= 0:
        return 0
    if mean > 40:
        return max(0, round(rng.gauss(mean, math.sqrt(mean))))
    threshold, count, product = math.exp(-mean), 0, rng.random()
    while product > threshold:
        count += 1
        product *= rng.random()
    return count


def _ages(post: Post, rng: random.Random) -> list[float]:
    age = post.start if post.start is not None else rng.randint(90, 300)
    ages: list[float] = []
    while age <= post.horizon:
        if not any(low < age < high for low, high in post.gaps):
            ages.append(age)
        # Сборщик приходит не секунда в секунду: небольшой разброс вокруг шага.
        age += cadence(post.platform, age) + rng.randint(-15, 15)
    return ages


def _rhythm(post: Post, age: float) -> float:
    # Минимум активности около 03:00 по Москве, максимум около 15:00.
    clock = (post.published_at + timedelta(seconds=age)).astimezone(MSK)
    hours = clock.hour + clock.minute / 60
    return 1 + post.rhythm * math.cos(2 * math.pi * (hours - 15) / 24)


def _engagement(ratio: float, age: float) -> float:
    # Живая доля реакций на просмотр медленно падает с возрастом поста.
    return ratio * (1 + age / (2 * DAY)) ** -0.25


def build(post: Post, rng: random.Random, publication_id: UUID, account_id: UUID) -> PostSeries:
    metrics = PLATFORM_METRICS[post.platform]
    ratios = post.ratios if post.ratios is not None else RATIOS[post.platform]
    ages = _ages(post, rng)

    def organic(age: float) -> float:
        return sum(wave.cumulative(age) for wave in post.waves)

    def injected(metric: Metric, age: float) -> float:
        return sum(item.cumulative(age) for item in post.injections.get(metric, ())
                   if not isinstance(item, Follow))

    first = ages[0]
    totals = {V: _poisson(rng, organic(first)) + round(injected(V, first))}
    for metric in metrics[1:]:
        totals[metric] = (_poisson(rng, organic(first) * _engagement(ratios.get(metric, 0), 0))
                          + round(injected(metric, first)))
    columns: dict[Metric, list[int]] = {metric: [totals[metric]] for metric in metrics}
    carry = {metric: 0.0 for metric in metrics}
    for left, right in zip(ages, ages[1:]):
        middle = (left + right) / 2
        rhythm = _rhythm(post, middle)
        organic_views = (organic(right) - organic(left)) * rhythm
        views_delta = 0
        for metric in metrics:
            if metric is V:
                delta = _poisson(rng, organic_views)
            else:
                delta = _poisson(rng, organic_views * _engagement(ratios.get(metric, 0), middle))
            extra = (injected(metric, right) - injected(metric, left)) * rng.uniform(0.98, 1.02)
            extra += sum(item.ratio * views_delta for item in post.injections.get(metric, ())
                         if isinstance(item, Follow) and item.start <= middle < item.end)
            carry[metric] += extra
            whole = math.floor(carry[metric])
            carry[metric] -= whole
            totals[metric] += delta + whole
            columns[metric].append(totals[metric])
            if metric is V:
                views_delta = delta + whole
    values: dict[Metric, tuple[int | None, ...]] = {}
    for metric, column in columns.items():
        values[metric] = tuple(
            None if any(item is metric and low <= age <= high for item, low, high in post.nulls)
            else value for age, value in zip(ages, column))
    return PostSeries(publication_id, account_id, post.platform, post.published_at, post.is_repost,
                      tuple(post.published_at + timedelta(seconds=age) for age in ages), values)


def subscribers(published_at: datetime, horizon: float, base: int, rng: random.Random,
                steps: tuple[tuple[float, int], ...] = ()) -> tuple[tuple[datetime, int], ...]:
    """Подписчики аккаунта раз в три часа; `steps` — приток при внешнем толчке."""
    rows = []
    for age in range(0, int(horizon) + 1, 3 * HOUR):
        count = base * (1 + 0.002 * age / DAY)
        count += sum(amount * min(1.0, max(0.0, (age - start) / (2 * HOUR)))
                     for start, amount in steps)
        rows.append((published_at + timedelta(seconds=age), round(count) + rng.randint(-3, 3)))
    return tuple(rows)


@dataclass(frozen=True)
class Case:
    case_id: str
    source: str
    description: str
    subject: Post
    min_level: Level
    max_level: Level
    patterns: tuple[int, ...] = ()
    siblings: tuple[Post, ...] = ()
    subscriber_base: int = 12000
    subscriber_steps: tuple[tuple[float, int], ...] = ()


HONEST = dict(min_level=Level.NONE, max_level=Level.WEAK_SIGNAL)


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 3, day, hour, minute, tzinfo=MSK)


def _tg(total: float) -> Wave:
    return Wave(0, total, 1.5 * HOUR, 0.8)


def _vk(total: float) -> Wave:
    return Wave(0, total, 3 * HOUR, 0.6)


def _synchronous_siblings(event: datetime) -> tuple[Post, ...]:
    # Первые четыре подрастают вместе с разбираемым постом, последние два — нет.
    posts = []
    for index, days in enumerate((4, 7, 9, 12, 15, 19)):
        published = event - timedelta(days=days, hours=index)
        age = (event - published).total_seconds()
        lift = {R: (Ramp(age, age + 45 * MINUTE, 250 + 40 * index),)} if index < 4 else {}
        posts.append(Post("telegram", published, (_tg(3000 + 700 * index),), age + DAY,
                          lift, start=age - 2 * DAY))
    return tuple(posts)


def _account_background(latest: datetime, count: int = 20) -> tuple[Post, ...]:
    # Фон аккаунта для нормы ERV: двадцать постов — порог собственной нормы.
    return tuple(Post("vk", latest - timedelta(days=index + 1, hours=index % 5),
                      (_vk(6000 + 450 * index),), 2 * DAY) for index in range(count))


def cases() -> tuple[Case, ...]:
    synchronous_event = _at(8, 18)
    return (
        Case("p01_linear_feed_vk", "synthetic",
             "ВК: после органического затухания просмотры сутки идут с постоянной "
             "скоростью (~500/ч), затем подача обрывается.",
             Post("vk", _at(2, 12), (_vk(9000),), 4 * DAY, {V: (Ramp(30 * HOUR, 54 * HOUR, 12000),)}),
             Level.PRONOUNCED_ANOMALY, Level.ARTIFICIAL_ACTIVITY_SIGNS, (1,)),
        Case("p01_linear_feed_rutube", "synthetic",
             "RuTube: на пятые сутки трое суток ровной подачи просмотров при часовом и "
             "трёхчасовом шаге замеров.",
             Post("rutube", _at(3, 10), (Wave(0, 20000, 12 * HOUR, 0.5),), 10 * DAY,
                  {V: (Ramp(4 * DAY, 7 * DAY, 30000),)}),
             Level.PRONOUNCED_ANOMALY, Level.ARTIFICIAL_ACTIVITY_SIGNS, (1,)),
        Case("p02_late_spike_telegram", "synthetic",
             "Telegram: на четвёртые сутки новая волна просмотров без реакций поверх "
             "затухшего поста.",
             Post("telegram", _at(4, 9), (_tg(5000),), 5 * DAY,
                  {V: (Wave(72 * HOUR, 7000, 20 * MINUTE, 1.1),)}),
             Level.PRONOUNCED_ANOMALY, Level.ARTIFICIAL_ACTIVITY_SIGNS, (2,)),
        Case("p03_multiscale_rise_vk", "synthetic",
             "ВК: растянутый на сутки плавный подъём просмотров на четвёртые сутки — на "
             "получасовых барах тонет в шуме, выпуклый на шестичасовых (паттерн 3 как "
             "поздний скачок на крупном масштабе).",
             Post("vk", _at(5, 13), (_vk(60000),), 6 * DAY, {V: (Hump(3 * DAY, 4 * DAY, 2500),)}),
             Level.PRONOUNCED_ANOMALY, Level.ARTIFICIAL_ACTIVITY_SIGNS, (2,)),
        Case("p04_gap_growth_telegram", "synthetic",
             "Telegram: за четырнадцатичасовой пробел в замерах затухший пост прибавил "
             "7 000 просмотров, реакции не изменились.",
             Post("telegram", _at(6, 11), (_tg(6000),), 5 * DAY,
                  {V: (Ramp(64 * HOUR, 66 * HOUR, 7000),)}, gaps=((60 * HOUR, 74 * HOUR),)),
             Level.PRONOUNCED_ANOMALY, Level.ARTIFICIAL_ACTIVITY_SIGNS, (4,)),
        Case("p05_reactions_catch_up_vk", "synthetic",
             "ВК: с пятых суток реакции прибавляют ровно 5% от прироста просмотров, "
             "хотя живая доля на старом посте падает.",
             Post("vk", _at(7, 15), (_vk(80000),), 10 * DAY, {R: (Follow(4 * DAY, 10 * DAY, 0.05),)}),
             Level.PRONOUNCED_ANOMALY, Level.ARTIFICIAL_ACTIVITY_SIGNS, (5,)),
        Case("p06_reactions_before_views_telegram", "synthetic",
             "Telegram: реакции подскакивают на 500 за два часа до второй волны "
             "просмотров.",
             Post("telegram", _at(8, 10), (_tg(5000), Wave(42 * HOUR, 4000, 30 * MINUTE, 0.9)),
                  4 * DAY, {R: (Ramp(40 * HOUR, 43 * HOUR, 500),)}),
             Level.PRONOUNCED_ANOMALY, Level.ARTIFICIAL_ACTIVITY_SIGNS, (6,)),
        Case("p07_reactions_exceed_views_max", "synthetic",
             "MAX: у небольшого поста (~500 просмотров) за двадцать минут +700 реакций; "
             "реакций больше просмотров во всех последующих замерах.",
             Post("max", _at(9, 12), (Wave(0, 500, 1.2 * HOUR, 0.85),), 3 * DAY,
                  {R: (Ramp(30 * HOUR, 30 * HOUR + 20 * MINUTE, 700),)}),
             Level.PRONOUNCED_ANOMALY, Level.ARTIFICIAL_ACTIVITY_SIGNS, (7,)),
        Case("p08_synchronous_rise_telegram", "synthetic",
             "Telegram: в одно окно в 45 минут реакции подрастают на разбираемом посте и "
             "четырёх старых постах аккаунта; просмотры и подписчики не меняются.",
             Post("telegram", synchronous_event - timedelta(days=6), (_tg(4500),), 8 * DAY,
                  {R: (Ramp(6 * DAY, 6 * DAY + 45 * MINUTE, 320),)}),
             Level.PRONOUNCED_ANOMALY, Level.ARTIFICIAL_ACTIVITY_SIGNS, (8,),
             siblings=_synchronous_siblings(synchronous_event)),
        Case("p09_burst_plateau_telegram", "synthetic",
             "Telegram: на третьи сутки +6 000 просмотров за три часа, после чего "
             "скорость сразу возвращается к затухшему фону — без хвоста.",
             Post("telegram", _at(10, 9), (_tg(9000),), 4 * DAY, {V: (Ramp(50 * HOUR, 53 * HOUR, 6000),)}),
             Level.PRONOUNCED_ANOMALY, Level.ARTIFICIAL_ACTIVITY_SIGNS, (9,)),
        Case("p10_high_erv_vk", "synthetic",
             "ВК: ERV поста около 13% при норме аккаунта около 3,7%; форма ряда "
             "органическая. Сам по себе признак даёт только слабый сигнал.",
             Post("vk", _at(11, 12), (_vk(9000),), 2 * DAY, {R: (Follow(0, 2 * DAY, 0.10),)}),
             Level.WEAK_SIGNAL, Level.WEAK_SIGNAL, (10,), siblings=_account_background(_at(11, 12))),
        Case("p10_low_erv_vk", "synthetic",
             "ВК: просмотры органической формы, но реакций, комментариев и репостов в "
             "десять раз меньше нормы аккаунта. Только слабый сигнал.",
             Post("vk", _at(12, 12), (_vk(60000),), 2 * DAY,
                  ratios={R: 0.003, C: 0.0003, S: 0.0004}),
             Level.WEAK_SIGNAL, Level.WEAK_SIGNAL, (10,), siblings=_account_background(_at(12, 12))),
        Case("strong_linear_views_reaction_burst_telegram", "synthetic",
             "Telegram: сутки линейной подачи просмотров, затем +900 реакций за два часа "
             "и тишина. Сильные признаки двух семейств — скорость и форма.",
             Post("telegram", _at(13, 10), (_tg(4000),), 4 * DAY,
                  {V: (Ramp(36 * HOUR, 60 * HOUR, 15000),), R: (Ramp(62 * HOUR, 64 * HOUR, 900),)}),
             Level.ARTIFICIAL_ACTIVITY_SIGNS, Level.ARTIFICIAL_ACTIVITY_SIGNS, (1, 9)),
        Case("owner_vk_497246_linear_with_leading_likes", "owner_screenshot",
             "Форма со скриншота владельца, ВК №497246: после 1 д 21 ч просмотры за сутки "
             "линейно растут примерно с 300 до 26 000, лайки начинают расти на два часа "
             "раньше просмотров.",
             Post("vk", _at(14, 12), (_vk(370),), 4 * DAY,
                  {V: (Ramp(45 * HOUR, 69 * HOUR, 25700),), R: (Ramp(43 * HOUR, 67 * HOUR, 900),)}),
             Level.ARTIFICIAL_ACTIVITY_SIGNS, Level.ARTIFICIAL_ACTIVITY_SIGNS, (1, 6)),
        Case("owner_vk_reaction_jumps_on_decayed_post", "owner_screenshot",
             "Форма со скриншота владельца: на затухшем посте реакции дважды прыгают за "
             "один замер — на +3 300 и на +1 450, просмотры почти не растут. Сильные "
             "признаки двух семейств: реакции без просмотров (6) и обрыв в плато (9) — "
             "поэтому высший уровень, а не только выраженная аномалия.",
             Post("vk", _at(15, 11), (_vk(16000),), 8 * DAY,
                  {R: (Ramp(5 * DAY + 2 * HOUR, 5 * DAY + 2 * HOUR + MINUTE, 3300),
                       Ramp(6 * DAY + 7 * HOUR, 6 * DAY + 7 * HOUR + MINUTE, 1450))},
                  ratios={R: 0.02, C: 0.003, S: 0.004}),
             Level.ARTIFICIAL_ACTIVITY_SIGNS, Level.ARTIFICIAL_ACTIVITY_SIGNS, (6, 9)),
        Case("owner_vk_views_jump_second_day", "owner_screenshot",
             "Форма со скриншота владельца: на вторые сутки просмотры за час прыгают "
             "с ~6 000 до ~20 000, реакции остаются органическими.",
             Post("vk", _at(16, 14), (_vk(7500),), 4 * DAY, {V: (Ramp(30 * HOUR, 31 * HOUR, 14000),)}),
             Level.PRONOUNCED_ANOMALY, Level.ARTIFICIAL_ACTIVITY_SIGNS, (2,)),
        Case("honest_organic_telegram", "synthetic",
             "Telegram: органическое степенное затухание, 30 суток, шаг сбора по возрасту.",
             Post("telegram", _at(17, 9), (_tg(5200),), 30 * DAY), **HONEST),
        Case("honest_organic_vk", "synthetic",
             "ВК: органическое затухание с длинным хвостом ленты, 14 суток.",
             Post("vk", _at(18, 13), (_vk(11000),), 14 * DAY), **HONEST),
        Case("honest_organic_max", "synthetic",
             "MAX: органическое затухание, близкое к Telegram, 7 суток.",
             Post("max", _at(19, 10), (Wave(0, 2400, 1.2 * HOUR, 0.85),), 7 * DAY), **HONEST),
        Case("honest_organic_rutube", "synthetic",
             "RuTube: медленное затухание видео с самым длинным хвостом, 30 суток, "
             "шаг от часа до шести.",
             Post("rutube", _at(20, 16), (Wave(0, 18000, 12 * HOUR, 0.5),), 30 * DAY), **HONEST),
        Case("honest_second_wave_vk", "synthetic",
             "ВК: вторая органическая волна из рекомендаций на вторые сутки — со своим "
             "затуханием и реакциями в норме.",
             Post("vk", _at(21, 12), (_vk(9000), Wave(40 * HOUR, 5000, 2 * HOUR, 0.7)), 5 * DAY),
             **HONEST),
        Case("honest_forward_large_channel_telegram", "synthetic",
             "Telegram: пересылка крупным каналом на третьи сутки — резкий подъём со "
             "степенным затуханием, реакции согласованы, подписчики прирастают.",
             Post("telegram", _at(22, 10), (_tg(3000), Wave(50 * HOUR, 12000, 15 * MINUTE, 1.0)), 5 * DAY),
             **HONEST, subscriber_base=8000, subscriber_steps=((50 * HOUR, 300),)),
        Case("honest_forward_vk_reposts", "synthetic",
             "ВК: пост разошёлся репостами — новая волна со своим затуханием, "
             "одновременный рост репостов и подписчиков.",
             Post("vk", _at(23, 12), (_vk(8000), Wave(36 * HOUR, 15000, 20 * MINUTE, 0.9)), 5 * DAY,
                  {S: (Follow(36 * HOUR, 60 * HOUR, 0.01),)}),
             **HONEST, subscriber_steps=((36 * HOUR, 500),)),
        Case("honest_repost_of_foreign_telegram", "synthetic",
             "Telegram: вуз переслал чужой пост (is_repost) — просмотры отражают аудиторию "
             "источника, включая его позднюю волну; реакций мало.",
             Post("telegram", _at(24, 11), (Wave(0, 40000, HOUR, 0.9), Wave(30 * HOUR, 30000, 30 * MINUTE, 1.0)),
                  4 * DAY, ratios={R: 0.004, C: 0.0005}, is_repost=True),
             **HONEST),
        Case("honest_gaps_telegram", "synthetic",
             "Telegram: пробелы в замерах на раннем быстром участке (2–5 ч) и позже "
             "(30–38 ч), реакции не получены в двух часах замеров; рост органический.",
             Post("telegram", _at(25, 9), (_tg(6000),), 4 * DAY,
                  gaps=((2 * HOUR, 5 * HOUR), (30 * HOUR, 38 * HOUR)), nulls=((R, 45 * HOUR, 47 * HOUR),)),
             **HONEST),
        Case("honest_truncated_start_vk", "synthetic",
             "ВК: пост найден через девять часов после выхода — ряд начинается с уже "
             "набранных просмотров.",
             Post("vk", _at(26, 8), (_vk(10000),), 5 * DAY, start=9 * HOUR), **HONEST),
        Case("honest_daily_rhythm_telegram", "synthetic",
             "Telegram: вечерний пост (21:30 МСК) с выраженным суточным ритмом — ночью "
             "почти стоит, утром добирает.",
             Post("telegram", _at(27, 21, 30), (_tg(5000),), 4 * DAY, rhythm=0.7), **HONEST),
    )


# Органика площадок для фона нормы: форма волны (c, θ) и типичный охват.
BACKGROUND_SHAPE = {
    "telegram": (1.5 * HOUR, 0.8, 5000),
    "vk": (3 * HOUR, 0.6, 9000),
    "max": (1.2 * HOUR, 0.85, 2500),
    "rutube": (12 * HOUR, 0.5, 15000),
}


def background(platform: str, accounts: int = 20, posts: int = 3,
               horizon: float = 10 * DAY) -> dict[UUID, list[PostSeries]]:
    """Честные посты многих аккаунтов площадки — из них строится зрелая норма.

    Эталон проверяется при зрелой норме: так её и проверяет ночное задание.
    Аккаунты различаются формой затухания и вовлечённостью, посты — охватом.
    """
    rng = random.Random(SEED ^ zlib.crc32(f"background/{platform}".encode("utf-8")))
    c, theta, reach = BACKGROUND_SHAPE[platform]
    result: dict[UUID, list[PostSeries]] = {}
    for account_index in range(accounts):
        account = uuid5(NAMESPACE, f"background/{platform}/{account_index}")
        engagement = math.exp(rng.gauss(0, 0.25))
        ratios = {metric: value * engagement for metric, value in RATIOS[platform].items()}
        shape_c, shape_theta = c * math.exp(rng.gauss(0, 0.2)), theta + rng.uniform(-0.05, 0.05)
        series = []
        for index in range(posts):
            published = datetime(2026, 2, 1, 9, tzinfo=MSK) + timedelta(days=account_index + 7 * index,
                                                                        hours=rng.randint(0, 10))
            post = Post(platform, published, (Wave(0, reach * math.exp(rng.gauss(0, 0.4)), shape_c, shape_theta),),
                        horizon, ratios=ratios)
            series.append(build(post, rng, uuid5(NAMESPACE, f"background/{platform}/{account_index}/{index}"),
                                account))
        result[account] = series
    return result


def render(case: Case) -> dict:
    rng = random.Random(SEED ^ zlib.crc32(case.case_id.encode("utf-8")))
    account = uuid5(NAMESPACE, f"{case.case_id}/account")

    def series(index: int, post: Post) -> PostSeries:
        return build(post, rng, uuid5(NAMESPACE, f"{case.case_id}/post/{index}"), account)

    subject = series(0, case.subject)
    siblings = tuple(series(index, post) for index, post in enumerate(case.siblings, 1))
    return case_payload(
        case.case_id, case.source, case.description, subject, siblings,
        subscribers(case.subject.published_at, case.subject.horizon, case.subscriber_base, rng,
                    case.subscriber_steps),
        expected_min_level=int(case.min_level), expected_max_level=int(case.max_level),
        expected_patterns=case.patterns,
    )


def rendered() -> Iterator[tuple[str, str]]:
    """Каждый случай в том же JSON, что пишет выгрузка реальных рядов."""
    for case in cases():
        yield case.case_id, dumps(render(case))


def synthetic_reference() -> list[ReferenceCase]:
    """Синтетический эталон тем же путём разбора, что и выгруженные ряды."""
    return [parse_case(json.loads(text)) for _, text in rendered()]
