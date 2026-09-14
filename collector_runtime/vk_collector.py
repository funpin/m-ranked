from __future__ import annotations

from typing import Any


def validated_vk_metrics(
    post: Any,
    ever_positive: dict[str, bool],
) -> tuple[dict[str, int | None], list[str]]:
    """Turn VK's transient resets to zero into missing measurements.

    Прежде сюда приходил прежний максимум показателя, и проверка звучала как
    «максимум известен и больше нуля». Это ровно то же самое, что «показатель
    хоть раз был больше нуля», а вопрос дешевле ответа: считать максимум по
    всей истории снимков публикации было незачем.
    """
    metrics = {
        "views": post.views,
        "reactions": post.likes,
        "comments": post.comments,
        "shares": post.reposts,
    }
    ignored: list[str] = []
    for metric, value in metrics.items():
        if value == 0 and ever_positive.get(metric, False):
            metrics[metric] = None
            ignored.append(metric)
    return metrics, ignored
