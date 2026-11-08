"""Суточный ритм аудитории: тихое окно аккаунта вместо «ночи по Москве»."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from anomaly_analysis.v2.account_findings import LedgerPost, findings
from anomaly_analysis.v2.account_tail import PostLedger, profiles, window_end
from anomaly_analysis.v2.audience_rhythm import account_rhythm, rhythm_from_hours
from anomaly_analysis.v2.detectors import DetectorContext, night_reaction_stream
from anomaly_analysis.v2.domain import Metric, PostSeries
from anomaly_analysis.v2.reach_findings import flat_day_findings, promotion_findings
from anomaly_analysis.v2.series import CollectionCadence, prepare
from anomaly_analysis.v2.tail_ledger import DAY, Point, TailLedger

TODAY = date(2026, 11, 1)
MSK_UTC = 3


def profile(quiet_msk: int, *, peak_msk: int | None = None, quiet: int = 10, day: int = 200, peak: int = 400):
    """Просмотры по часу UTC: четыре тихих часа с `quiet_msk` МСК и четыре пиковых."""
    peak_msk = (quiet_msk + 16) % 24 if peak_msk is None else peak_msk
    hours = [day] * 24
    for offset in range(4):
        hours[(peak_msk - MSK_UTC + offset) % 24] = peak
    for offset in range(4):
        hours[(quiet_msk - MSK_UTC + offset) % 24] = quiet
    return hours


def scaled(hours: list[int], times: int = 10) -> list[int]:
    return [value * times for value in hours]


def test_moscow_audience_has_zero_offset_and_a_known_clock():
    rhythm = rhythm_from_hours(scaled(profile(3)))
    assert (rhythm.quiet_start_msk, rhythm.offset_hours, rhythm.clock_known) == (3, 0, True)
    assert rhythm.quiet_over_peak == 10 / 400


def test_eastern_audience_is_shifted_east_and_stays_within_the_clock_range():
    for quiet_msk, offset in ((23, 4), (21, 6)):
        rhythm = rhythm_from_hours(scaled(profile(quiet_msk)))
        assert (rhythm.offset_hours, rhythm.clock_known) == (offset, True)


def test_quiet_window_outside_the_range_leaves_the_clock_unknown():
    assert not rhythm_from_hours(scaled(profile(20))).clock_known  # +7, Дальний Восток
    assert not rhythm_from_hours(scaled(profile(6))).clock_known  # −3, западнее России


def test_too_few_views_give_no_rhythm():
    assert rhythm_from_hours(profile(3)) is None


def test_a_peak_right_before_the_quiet_window_is_outside_audience_daytime():
    assert rhythm_from_hours(scaled(profile(3, peak_msk=19))).peak_in_daytime
    assert not rhythm_from_hours(scaled(profile(6, peak_msk=1))).peak_in_daytime


def test_account_rhythm_sums_posts_and_skips_hourless_ledgers():
    hours = (tuple(profile(23)), tuple([0] * 24))
    ledgers = [TailLedger(None, None, None, hours=hours) for _ in range(10)] + [TailLedger(None, None, None)]
    assert account_rhythm(ledgers).offset_hours == 4
    assert account_rhythm([TailLedger(None, None, None)]) is None


def _tail_post(account: int, index: int, hours: tuple[tuple[int, ...], tuple[int, ...]]) -> PostLedger:
    published = window_end(TODAY) - timedelta(days=5 + index)
    ledger = TailLedger(Point(DAY, 1000, 30), Point(4 * DAY, 1100, 32), Point(13 * DAY, 1300, 33), hours=hours)
    return PostLedger(UUID(int=account * 1000 + index), UUID(int=account), "vk", published, ledger)


def test_profile_reports_the_rhythm_cohort_and_warns_only_about_an_unknown_clock():
    usual = (tuple(profile(3)), tuple([0] * 24))
    far = (tuple(profile(20)), tuple([0] * 24))
    posts = [_tail_post(account, index, usual) for account in range(2, 22) for index in range(16)]
    posts += [_tail_post(1, index, far) for index in range(16)]
    by_account = {item.account_id: item for item in profiles(posts, {UUID(int=a): "vk" for a in range(1, 22)}, TODAY)}
    shifted, moscow = by_account[UUID(int=1)].metrics["rhythm"], by_account[UUID(int=2)].metrics["rhythm"]
    assert moscow["offsetHours"] == 0 and moscow["clockKnown"] and moscow["warning"] is None
    assert moscow["cohortP90"] is not None
    assert not shifted["clockKnown"]
    assert "20:00–00:00 МСК" in shifted["warning"]
    assert "накрут" not in shifted["warning"] and "бот" not in shifted["warning"]


def _night_post(account: int, index: int, views: list[int], reactions: list[int]) -> LedgerPost:
    published = datetime(2026, 10, 20, 9, tzinfo=timezone.utc) + timedelta(hours=6 * index)
    point = Point(DAY, 1000, 30)
    ledger = TailLedger(point, Point(4 * DAY, 2000, 60), Point(10 * DAY, 3000, 90),
                        hours=(tuple(views), tuple(reactions)))
    return LedgerPost(UUID(int=account * 1000 + index), UUID(int=account), "vk", published, False, ledger)


def test_far_eastern_quiet_window_gives_no_night_finding():
    # Тихие шесть часов с 19:00 МСК — сдвиг −6 входит в пояса, с 18:00 (−7) уже нет.
    inside, outside = [10] * 24, [10] * 24
    for hour in range(6):
        inside[(19 - MSK_UTC + hour) % 24] = 0
        outside[(18 - MSK_UTC + hour) % 24] = 0
    def reactions(views: list[int]) -> list[int]:
        return [40 if value == 0 else 1 for value in views]
    found = findings([_night_post(1, index, inside, reactions(inside)) for index in range(40)], TODAY)
    assert [item.kind for item in found if item.kind == "night_reactions"] == ["night_reactions"]
    found = findings([_night_post(1, index, outside, reactions(outside)) for index in range(40)], TODAY)
    assert not [item for item in found if item.kind == "night_reactions"]


PUBLISHED = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)


def _clip(reactions_per_hour, hours=40):
    observed, views, reactions = [], [], []
    v = r = 0.0
    for minute in range(5, hours * 60 + 1, 5):
        moment = PUBLISHED + timedelta(minutes=minute)
        v += 200 * 5 / 60
        r += reactions_per_hour((moment + timedelta(hours=MSK_UTC)).hour) * 5 / 60
        observed.append(moment)
        views.append(int(v))
        reactions.append(int(r))
    return PostSeries(UUID(int=18), UUID(int=8), "vk", PUBLISHED, False, tuple(observed),
                      {Metric.VIEWS: tuple(views), Metric.REACTIONS: tuple(reactions)},
                      publication_type="video")


def _clip_signs(offset):
    night_msk = _clip(lambda hour: 30 if hour < 6 else 0)
    prepared = prepare(night_msk, night_msk.observed_at[-1], CollectionCadence())
    return night_reaction_stream.detect(prepared, DetectorContext("vk", audience_offset=offset))


def test_clip_night_follows_the_audience_clock():
    assert _clip_signs(0)
    # 00–06 МСК у аудитории с +6 — это утро 06–12.
    assert not _clip_signs(6)


def test_clip_without_a_known_audience_clock_is_not_judged():
    assert not _clip_signs(None)


def _flat_post(account: int, index: int, views: list[int]) -> LedgerPost:
    published = datetime(2026, 10, 10, tzinfo=timezone.utc) + timedelta(hours=8 * index)
    ledger = TailLedger(None, None, None, hours=(tuple(views), tuple([0] * 24)))
    return LedgerPost(UUID(int=account * 1000 + index), UUID(int=account), "vk", published, False, ledger)


def test_flat_rhythm_needs_a_peak_outside_audience_daytime():
    cohort = [_flat_post(account, index, scaled(profile(3))) for account in range(2, 12) for index in range(20)]
    federal = [_flat_post(1, index, scaled(profile(3, peak_msk=19, quiet=150))) for index in range(20)]
    assert not flat_day_findings(cohort + federal, TODAY)
    packed = [_flat_post(1, index, scaled(profile(6, peak_msk=1, quiet=150))) for index in range(20)]
    (finding,) = flat_day_findings(cohort + packed, TODAY)
    assert finding.kind == "flat_daily_views"


def _promoted(account: int, night: int, hours: list[int] | None) -> list[LedgerPost]:
    start = datetime(2026, 10, 12, 9, tzinfo=timezone.utc)
    result = []
    for index in range(8):
        promoted = index < 2
        days = tuple(((start + timedelta(days=1 + k)).date().isoformat(), 5000 if promoted else 100, 1,
                      night if promoted else 5) for k in range(3))
        ledger = TailLedger(None, None, None, hours=(tuple(hours), tuple([0] * 24)) if hours else None, days=days)
        result.append(LedgerPost(UUID(int=account * 1000 + index), UUID(int=account), "vk", start, False, ledger))
    return result


def test_promotion_night_share_allows_for_an_eastern_audience():
    # 25 % суток в 00–06 МСК: у московского аккаунта не ночной провал, у сибирского — его утро.
    assert not promotion_findings(_promoted(1, 1250, scaled(profile(3))), TODAY)
    assert promotion_findings(_promoted(1, 1250, scaled(profile(23), 2)), TODAY)


def _ledger(hours: list[int]) -> TailLedger:
    return TailLedger(None, None, None, hours=(tuple(hours), tuple([0] * 24)))


def _packed_account(pack_utc: range, posts: int = 40, packed: int = 6) -> list[TailLedger]:
    """Московская аудитория; у части постов — крупные регулярные пакеты в часы `pack_utc`."""
    usual = profile(3)
    pack = [10_000 if hour in pack_utc else 0 for hour in range(24)]
    return [_ledger(usual) for _ in range(posts - packed)] + [_ledger(pack) for _ in range(packed)]


def test_regular_daytime_packs_do_not_move_the_audience_clock():
    # Просмотры идут только с 03 до 13 UTC: по сумме самые тихие часы оказались бы вечером.
    rhythm = account_rhythm(_packed_account(range(3, 14)))
    assert (rhythm.quiet_start_msk, rhythm.offset_hours, rhythm.clock_known) == (3, 0, True)


def test_regular_night_packs_stay_visible_against_the_audience_clock():
    clean = account_rhythm([_ledger(profile(3)) for _ in range(40)])
    packed = account_rhythm(_packed_account(range(0, 4)))
    assert packed.offset_hours == 0
    assert packed.quiet_over_peak > 10 * clean.quiet_over_peak
    assert not packed.peak_in_daytime


def test_too_few_posts_give_no_account_rhythm():
    assert account_rhythm([_ledger(scaled(profile(3), 100)) for _ in range(7)]) is None
