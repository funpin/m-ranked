"""Суточный ритм аудитории аккаунта: тихое окно вместо «ночи по Москве».

Часового пояса вуза в каталоге нет, а у сибирских и дальневосточных аккаунтов
московская ночь — утро. Пояс оценивается по самой аудитории: четыре подряд часа
с наименьшей долей поздних просмотров (сводка поста, `hours`, возраст 1–14
суток — там, где первый всплеск публикации уже не определяет час).

Сдвиг считается от типичного для площадки начала тихого окна — 03:00 МСК
(ВК 01.09–07.11.2026: 67 аккаунтов из 120); плюс — на восток. Окно вне поясов
России (−1…+6 ч) пояса не задаёт: так выглядит и приток просмотров в обычно тихие
часы. Для такого аккаунта признаки ночи не считаются, карточка предупреждает.

Плоский ритм сам по себе не признак: у крупных федеральных вузов тихое окно
неглубокое и пик приходится на вечер, как у всех. Необычен пик вне дневных часов
аудитории — меньше 9 или больше 18 часов от начала тихого окна.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .tail_ledger import TailLedger

QUIET_HOURS = 4
# Ниже пяти тысяч поздних просмотров за четыре недели окно определяется случаем.
MIN_VIEWS = 5_000
REFERENCE_QUIET_START_MSK = 3
OFFSET_RANGE = (-1, 6)
PEAK_LAG_RANGE = (9, 18)
MOSCOW_UTC_OFFSET = 3


@dataclass(frozen=True, slots=True)
class AudienceRhythm:
    views: int
    quiet_start_msk: int
    peak_start_msk: int
    offset_hours: int
    quiet_over_peak: float

    @property
    def clock_known(self) -> bool:
        return OFFSET_RANGE[0] <= self.offset_hours <= OFFSET_RANGE[1]

    @property
    def peak_in_daytime(self) -> bool:
        return PEAK_LAG_RANGE[0] <= (self.peak_start_msk - self.quiet_start_msk) % 24 <= PEAK_LAG_RANGE[1]

    @property
    def warning(self) -> str | None:
        if self.clock_known:
            return None
        end = (self.quiet_start_msk + QUIET_HOURS) % 24
        return (f"Самые тихие часы аккаунта — {self.quiet_start_msk:02d}:00–{end:02d}:00 МСК, это не совпадает "
                "с часовыми поясами России. Признаки, связанные с ночью аудитории, для него не считаются. "
                "Возможные причины: аудитория за рубежом или неравномерный приток просмотров.")

    def payload(self) -> dict[str, Any]:
        return {"views": self.views, "quietStartMsk": self.quiet_start_msk, "peakStartMsk": self.peak_start_msk,
                "offsetHours": self.offset_hours, "quietOverPeak": round(self.quiet_over_peak, 4),
                "clockKnown": self.clock_known, "peakInDaytime": self.peak_in_daytime, "warning": self.warning}


def rhythm_from_hours(views_by_utc_hour: Sequence[int]) -> AudienceRhythm | None:
    """Ритм по просмотрам за сутки по часам UTC; None — просмотров слишком мало."""
    total = sum(views_by_utc_hour)
    if total < MIN_VIEWS:
        return None
    windows = [sum(views_by_utc_hour[(start + shift) % 24] for shift in range(QUIET_HOURS)) for start in range(24)]
    quiet = min(range(24), key=lambda start: (windows[start], start))
    peak = max(range(24), key=lambda start: (windows[start], -start))
    quiet_msk = (quiet + MOSCOW_UTC_OFFSET) % 24
    offset = (REFERENCE_QUIET_START_MSK - quiet_msk + 12) % 24 - 12
    return AudienceRhythm(total, quiet_msk, (peak + MOSCOW_UTC_OFFSET) % 24, offset,
                          windows[quiet] / max(windows[peak], 1))


def summed_views(ledgers: Iterable[TailLedger]) -> list[int]:
    views = [0] * 24
    for ledger in ledgers:
        if ledger.hours is not None:
            for hour, value in enumerate(ledger.hours[0]):
                views[hour] += value
    return views


def account_rhythm(ledgers: Iterable[TailLedger]) -> AudienceRhythm | None:
    return rhythm_from_hours(summed_views(ledgers))
