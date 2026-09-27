"""Conservative cap for a strong late-view signal after bounded context review.

The cap limits the *strength of the conclusion*, not the observed jump. Shared
old-post growth and a new publication are plausible context, never a proven
source of traffic. M2's signed contrast is intentionally absent from this API.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import log1p
from typing import Iterable, Mapping


VERSION = "late-view-context-cap-v3"
STRONG = 0.7
MIN_SHARED_LOG_GROWTH = log1p(0.02)
FAR_SHARED_LOG_GROWTH = log1p(0.03)


@dataclass(frozen=True, slots=True)
class WindowEvidence:
    start_at: str
    end_at: str
    target_measured: bool
    same_revision: bool
    new_publication_ids: tuple[str, ...]
    measured_new_posts: int
    positive_old_posts: int
    measured_old_posts: int
    median_old_log_growth: float | None
    nearest_event_feed_distance: int | None
    feed_matched_old_posts: int

    def supports_cap(self) -> bool:
        distance = self.nearest_event_feed_distance
        if distance is None or distance < 1:
            return False
        # A remote new post needs a broader and stronger channel-wide pattern
        # before it can weaken the signal. These are conservative policy gates,
        # not estimated referral probabilities.
        required_peers = 2 if distance <= 2 else 3 if distance <= 4 else 4
        growth_floor = FAR_SHARED_LOG_GROWTH if distance > 4 else MIN_SHARED_LOG_GROWTH
        return (self.target_measured and self.same_revision
                and bool(self.new_publication_ids)
                and self.measured_new_posts >= 1
                and self.measured_old_posts >= required_peers
                and self.feed_matched_old_posts >= required_peers
                and required_peers <= self.positive_old_posts <= self.measured_old_posts
                and self.median_old_log_growth is not None
                and self.median_old_log_growth >= growth_floor)


@dataclass(frozen=True, slots=True)
class ContextCapDecision:
    original_level: int
    effective_level: int
    reason: str | None
    method_version: str = VERSION


def assess_context_cap(
    platform: str,
    original_level: int,
    signals: Iterable[Mapping[str, object]],
    windows: Iterable[WindowEvidence],
) -> ContextCapDecision:
    """Cap level 2 at 1 only when every strong sign is a contextual late view.

    Missing evidence abstains. Independent strong signs or an existing level 3
    are never weakened. The source detector's signals and level stay intact.
    """
    unchanged = ContextCapDecision(original_level, original_level, None)
    if platform not in {"telegram", "max"} or original_level != 2:
        return unchanged
    strong = [signal for signal in signals if float(signal.get("strength", 0)) >= STRONG]
    if not strong or any(signal.get("pattern") != 2 or signal.get("metric") != "views"
                         for signal in strong):
        return unchanged
    by_interval = {(window.start_at, window.end_at): window for window in windows}
    for signal in strong:
        window = by_interval.get((str(signal.get("startAt")), str(signal.get("endAt"))))
        if window is None or not window.supports_cap():
            return unchanged
    return ContextCapDecision(original_level, 1, "new_post_and_shared_old_growth")
