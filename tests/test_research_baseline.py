from anomaly_analysis.research_baseline import (
    FixedAgePost, RobustPlatformBaseline, empirical_upper_tail,
)


def test_account_baseline_and_empirical_tail_stay_separate():
    rows = [
        FixedAgePost("telegram", "small", "text", 100 + i, 4 + i % 3)
        for i in range(20)
    ] + [
        FixedAgePost("telegram", "large", "text", 1000 + 10*i, 40 + i % 5)
        for i in range(20)
    ]
    model = RobustPlatformBaseline.fit("telegram", rows)
    normal_small = model.predict(FixedAgePost("telegram", "small", "text", 110, 5))
    normal_large = model.predict(FixedAgePost("telegram", "large", "text", 1100, 42))
    abnormal = model.predict(FixedAgePost("telegram", "small", "text", 10000, 5))

    assert normal_large.predicted_log_views > normal_small.predicted_log_views
    assert abnormal.combined_score > max(normal_small.combined_score,
                                         normal_large.combined_score)
    calibration = [model.predict(row).combined_score for row in rows]
    assert empirical_upper_tail(abnormal.combined_score, calibration) == 1 / 41


def test_tied_empirical_scores_are_conservative():
    assert empirical_upper_tail(2.0, [1.0, 2.0, 2.0, 3.0]) == 4 / 5
