from __future__ import annotations

from typing import Any


def validated_vk_metrics(
    post: Any,
    high_watermarks: dict[str, int | None],
) -> tuple[dict[str, int | None], list[str]]:
    """Turn VK's transient resets to zero into missing measurements."""
    metrics = {
        "views": post.views,
        "reactions": post.likes,
        "comments": post.comments,
        "shares": post.reposts,
    }
    ignored: list[str] = []
    for metric, value in metrics.items():
        previous_high = high_watermarks.get(metric)
        if value == 0 and previous_high is not None and previous_high > 0:
            metrics[metric] = None
            ignored.append(metric)
    return metrics, ignored
