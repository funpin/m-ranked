from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import numpy as np
import pytest

from anomaly_analysis.v2.domain import Level, Metric, PostSeries
from anomaly_analysis.v2.norms import (
    ANCHOR_MADS, DECAY_EXPONENT_BOUNDS, ERV, NormStatus, ReferencePost, build_norms,
    check_reference, drift, fit_decay, norm_from_payload, norm_to_payload, review,
)
from anomaly_analysis.v2.series import DAY, HOUR, CollectionCadence, prepare

BASE = datetime(2026, 1, 1, 9, tzinfo=timezone.utc)
CADENCE = CollectionCadence()
HORIZON = 3 * DAY
# Итог для доли — двое суток: ряд теста кончается чуть раньше трёх.
FINAL = 2 * DAY


def make_post(rng, account: int, index: int, *, linear=False, rate_scale=1.0, erv=0.02,
              total=5000.0, b=1.3, c=1.5) -> PostSeries:
    published = BASE + timedelta(days=index, hours=account % 7)
    ages, age = [], 120.0
    while age <= HORIZON:
        ages.append(age)
        age += float(CADENCE.expected_step_seconds("telegram", np.array([age]))[0])
    hours = np.asarray(ages) / HOUR
    if linear:
        # Механическая подача: ровная скорость все трое суток.
        views = total * rate_scale * hours / (HORIZON / HOUR)
    else:
        views = total * rate_scale * (1 - (1 + hours / c) ** -(b - 1))
    views = np.maximum.accumulate(np.round(views + rng.normal(0, 0.2, views.size) * np.sqrt(views)))
    reactions = np.maximum.accumulate(np.round(views * erv * rng.lognormal(0, 0.05)))
    return PostSeries(UUID(int=account * 10_000 + index), UUID(int=account + 1), "telegram",
                      published, False,
                      tuple(published + timedelta(seconds=item) for item in ages),
                      {Metric.VIEWS: tuple(int(item) for item in views),
                       Metric.REACTIONS: tuple(int(item) for item in reactions)})


def prepared(series: PostSeries):
    return prepare(series, series.published_at + timedelta(seconds=HORIZON), CADENCE)


def platform_posts(accounts: int, posts: int, *, pumped=frozenset(), seed=1, **kwargs):
    rng = np.random.default_rng(seed)
    return {UUID(int=account + 1): [prepared(make_post(rng, account, index, linear=account in pumped,
                                                        **kwargs))
                                    for index in range(posts)]
            for account in range(accounts)}


def test_fit_recovers_synthetic_decay():
    rng = np.random.default_rng(3)
    hours = np.linspace(0.5, 72, 150)
    rates = 2.0 * (hours + 1.2) ** -0.9 * rng.lognormal(0, 0.05, hours.size)
    fit = fit_decay(hours, rates)
    assert fit.b == pytest.approx(0.9, abs=0.05)
    assert fit.c == pytest.approx(1.2, rel=0.2)
    assert fit.a == pytest.approx(2.0, rel=0.15)


def test_fit_cannot_learn_a_straight_line():
    hours = np.linspace(0.5, 72, 150)
    fit = fit_decay(hours, np.full(hours.size, 3.0))
    low, high = DECAY_EXPONENT_BOUNDS
    assert low <= fit.b <= high
    # Ровную скорость модель передаёт только ближайшей допустимой формой.
    assert fit.b == pytest.approx(low, abs=1e-6)
    posts = platform_posts(1, 20, pumped={0})
    norm = build_norms("telegram", posts, final_age=FINAL).platform
    assert low <= norm.decay["views"].b <= high


def test_ten_pumping_accounts_of_eighty_do_not_move_the_platform_median():
    clean = build_norms("telegram", platform_posts(70, 5), final_age=FINAL).platform
    poisoned = build_norms("telegram", platform_posts(80, 5, pumped=frozenset(range(70, 80))),
                           final_age=FINAL).platform
    assert poisoned.decay["views"].b == pytest.approx(clean.decay["views"].b, abs=0.05)
    for key, cell in clean.cells.items():
        if cell.log_rate is not None:
            shift = abs(poisoned.cells[key].log_rate.median - cell.log_rate.median)
            assert shift < 0.25 * cell.log_rate.mad + 0.05, key
    views_share = clean.cells[("views", 0)].share
    assert poisoned.cells[("views", 0)].share[1] == pytest.approx(views_share[1], abs=0.03)


def test_excluded_posts_do_not_touch_the_norm():
    rng = np.random.default_rng(5)
    clean = [prepared(make_post(rng, 0, index)) for index in range(22)]
    pumped = [prepared(make_post(rng, 0, 100 + index, linear=True, rate_scale=4)) for index in range(6)]
    account = UUID(int=1)
    alone = build_norms("telegram", {account: clean}, final_age=FINAL)
    excluded = frozenset(item.series.publication_id for item in pumped)
    with_exclusions = build_norms("telegram", {account: clean + pumped}, excluded=excluded,
                                  final_age=FINAL)
    assert norm_to_payload(with_exclusions.for_account(account)) == norm_to_payload(alone.for_account(account))
    included = build_norms("telegram", {account: clean + pumped}, final_age=FINAL)
    assert norm_to_payload(included.for_account(account)) != norm_to_payload(alone.for_account(account))


def test_short_history_falls_back_to_the_platform_norm():
    posts = platform_posts(12, 5)
    rng = np.random.default_rng(9)
    posts[UUID(int=500)] = [prepared(make_post(rng, 499, index)) for index in range(25)]
    norms = build_norms("telegram", posts, final_age=FINAL)
    short = norms.for_account(UUID(int=1))
    assert short is norms.platform and short.basis == "platform"
    own = norms.for_account(UUID(int=500))
    assert own.basis == "account" and own.posts == 25 and own.account_id == UUID(int=500)
    assert norms.platform.young  # двенадцать аккаунтов — ещё молодая норма площадки


def test_account_norm_is_anchored_to_the_platform():
    posts = platform_posts(20, 5)
    rng = np.random.default_rng(11)
    outlier = UUID(int=900)
    posts[outlier] = [prepared(make_post(rng, 899, index, erv=0.6)) for index in range(25)]
    norms = build_norms("telegram", posts, final_age=FINAL)
    base = norms.platform.cells[(ERV, 0)].log_erv
    anchored = norms.for_account(outlier).cells[(ERV, 0)].log_erv
    assert anchored.median == pytest.approx(base.median + ANCHOR_MADS * base.mad)


def test_sharp_platform_shift_goes_to_drift_review():
    previous = build_norms("telegram", platform_posts(30, 5), final_age=FINAL).platform
    same = build_norms("telegram", platform_posts(30, 5, seed=2), final_age=FINAL).platform
    shifted = build_norms("telegram", platform_posts(30, 5, erv=0.2), final_age=FINAL).platform
    passed = check_reference(None, (), lambda *_: Level.NONE)
    assert review(passed, drift(same, previous)) is NormStatus.ACCEPTED
    assert drift(shifted, previous).sharp
    assert review(passed, drift(shifted, previous)) is NormStatus.DRIFT_REVIEW
    assert not drift(previous, None).sharp


def test_reference_check_rejects_a_norm_that_hides_the_reference():
    norms = build_norms("telegram", platform_posts(5, 5), final_age=FINAL)
    rng = np.random.default_rng(13)
    case = ReferencePost("linear", make_post(rng, 77, 0, linear=True), (), Level.PRONOUNCED_ANOMALY)
    blind = check_reference(norms, (case,), lambda subject, siblings, used: Level.WEAK_SIGNAL)
    assert blind.failures == ("linear",)
    assert review(blind, drift(norms.platform, None)) is NormStatus.REJECTED
    seeing = check_reference(norms, (case,), lambda subject, siblings, used: Level.ARTIFICIAL_ACTIVITY_SIGNS)
    assert seeing.passed and review(seeing, drift(norms.platform, None)) is NormStatus.ACCEPTED


def test_payload_round_trip_and_determinism():
    posts = platform_posts(4, 22)
    first = build_norms("telegram", posts, final_age=FINAL)
    second = build_norms("telegram", platform_posts(4, 22), final_age=FINAL)
    payload = norm_to_payload(first.for_account(UUID(int=1)))
    assert payload == norm_to_payload(second.for_account(UUID(int=1)))
    assert norm_to_payload(norm_from_payload(payload)) == payload
    assert norm_to_payload(norm_from_payload(norm_to_payload(first.platform))) == norm_to_payload(first.platform)


def test_age_band_stays_inside_the_schedule_table():
    """Ячейка сетки чуть раньше публикации — первый интервал, а не «−1»:
    строку с таким интервалом отвергает ограничение таблицы норм."""
    from anomaly_analysis.v2.series import age_band

    assert age_band(np.array([-600.0, 0.0, DAY - 1, 31 * DAY])).tolist() == [0, 0, 0, 4]


@pytest.mark.parametrize("platform", ["telegram", "vk", "max", "rutube"])
def test_platform_norm_cells_fit_the_table_without_numpy_warnings(platform):
    import warnings

    from anomaly_analysis.v2.reference import background

    posts = {account: [prepare(item, item.observed_at[-1], CADENCE) for item in items]
             for account, items in background(platform).items()}
    with warnings.catch_warnings():
        # Пустые выборки давали «Mean of empty slice» и медиану nan.
        warnings.simplefilter("error", RuntimeWarning)
        norms = build_norms(platform, posts, final_age=7 * DAY)
    for norm in (norms.platform, *norms.accounts.values()):
        assert all(0 <= band <= 4 for _, band in norm.cells), norm.cells.keys()
