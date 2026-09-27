"""Policy boundaries: an alternative explanation caps confidence, not history."""
from math import log1p
from anomaly_analysis.v2.context_cap import WindowEvidence, assess_context_cap


LATE = {"pattern": 2, "metric": "views", "strength": 0.9,
        "startAt": "2026-09-14T12:00:00Z", "endAt": "2026-09-14T14:15:00Z"}
CONTEXT = WindowEvidence(LATE["startAt"], LATE["endAt"], True, True,
                         ("11343",), 1, 2, 2, log1p(.077))


def test_measured_shared_growth_caps_only_the_saved_strong_late_view():
    decision = assess_context_cap("telegram", 2, [LATE], [CONTEXT])
    assert (decision.original_level, decision.effective_level, decision.reason) == (
        2, 1, "new_post_and_shared_old_growth")


def test_missing_reads_or_new_post_abstains_instead_of_inventing_context():
    for window in (
        WindowEvidence(CONTEXT.start_at, CONTEXT.end_at, False, True, ("11343",), 1, 2, 2, log1p(.077)),
        WindowEvidence(CONTEXT.start_at, CONTEXT.end_at, True, False, ("11343",), 1, 2, 2, log1p(.077)),
        WindowEvidence(CONTEXT.start_at, CONTEXT.end_at, True, True, (), 0, 2, 2, log1p(.077)),
        WindowEvidence(CONTEXT.start_at, CONTEXT.end_at, True, True, ("11343",), 0, 2, 2, log1p(.077)),
        WindowEvidence(CONTEXT.start_at, CONTEXT.end_at, True, True, ("11343",), 1, 1, 2, log1p(.077)),
        WindowEvidence(CONTEXT.start_at, CONTEXT.end_at, True, True, ("11343",), 1, 2, 2, log1p(.001)),
    ):
        assert assess_context_cap("telegram", 2, [LATE], [window]).effective_level == 2


def test_every_strong_window_must_have_context_and_independent_signals_win():
    second = dict(LATE, startAt="2026-09-15T09:30:00Z", endAt="2026-09-15T16:30:00Z")
    assert assess_context_cap("telegram", 2, [LATE, second], [CONTEXT]).effective_level == 2
    independent = {"pattern": 7, "metric": "reactions", "strength": 0.85}
    assert assess_context_cap("telegram", 2, [LATE, independent], [CONTEXT]).effective_level == 2
    assert assess_context_cap("telegram", 3, [LATE], [CONTEXT]).effective_level == 3
    assert assess_context_cap("vk", 2, [LATE], [CONTEXT]).effective_level == 2
    assert assess_context_cap("max", 2, [LATE], [CONTEXT]).effective_level == 1
