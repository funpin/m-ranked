from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import median
from typing import Any

from .config import Settings
from .database import Database


PLATFORM_PRESENTATION: dict[str, dict[str, Any]] = {
    "vk": {
        "label": "ВКонтакте",
        "short": "ВК",
        "primary": "лайков",
        "primary_one": "лайк",
        "views": "просмотров",
        "comments": "комментариев",
        "shares": "репостов",
        "capabilities": {"views", "reactions", "comments", "shares"},
    },
    "max": {
        "label": "MAX",
        "short": "MAX",
        "primary": "реакций",
        "primary_one": "реакция",
        "views": "просмотров",
        "comments": "комментариев",
        "shares": "репостов",
        "capabilities": {"views", "comments", "shares"},
    },
    "rutube": {
        "label": "Rutube",
        "short": "RUTUBE",
        "primary": "лайков",
        "primary_one": "лайк",
        "views": "просмотров",
        "comments": "комментариев",
        "shares": "репостов",
        "capabilities": {"views"},
    },
}

RATING_FIELDS = {
    "vk": ("m_rating_vk_rank", "m_rating_vk_score"),
    "max": ("m_rating_max_rank", "m_rating_max_score"),
    "rutube": ("m_rating_rutube_rank", "m_rating_rutube_score"),
}


def _as_datetime(value: str | datetime) -> datetime:
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result


def _rounded_median(values: list[int]) -> int | None:
    return math.floor(median(values) + 0.5) if values else None


def collector_configured(settings: Settings, platform: str) -> bool:
    if platform == "vk":
        return bool(settings.vk_access_token)
    if platform == "max":
        return bool(settings.max_access_token)
    if platform == "rutube":
        return settings.rutube_public_api_enabled
    return False


def platform_activity_cards(
    db: Database,
    settings: Settings,
    platform: str,
    start: datetime,
    previous_start: datetime,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    """Aggregate one platform without ever substituting another network's data."""
    if platform not in PLATFORM_PRESENTATION:
        raise ValueError(f"Unsupported platform analytics: {platform}")
    end = end or datetime.now(timezone.utc)
    institutions = [dict(row) for row in db.list_institutions()]
    accounts = [dict(row) for row in db.list_platform_accounts(platform=platform)]
    accounts_by_institution: dict[int, list[dict[str, Any]]] = {}
    for account in accounts:
        accounts_by_institution.setdefault(int(account["institution_id"]), []).append(account)

    def window_samples(window_start: datetime, window_end: datetime) -> dict[int, list[dict[str, Any]]]:
        rows = [dict(row) for row in db.query(
            """SELECT pp.id, pp.platform_account_id, pa.institution_id,
                      pp.published_at, latest.id latest_snapshot_id,
                      latest.views_count, latest.reactions_count,
                      latest.comments_count, latest.shares_count,
                      (SELECT f.id FROM platform_snapshots f
                       WHERE f.platform_post_id=pp.id AND f.measured_at>? AND f.measured_at<=?
                       ORDER BY f.measured_at LIMIT 1) first_snapshot_id,
                      (SELECT f.age_seconds FROM platform_snapshots f
                       WHERE f.platform_post_id=pp.id AND f.measured_at>? AND f.measured_at<=?
                       ORDER BY f.measured_at LIMIT 1) first_age_seconds,
                      (SELECT f.views_count FROM platform_snapshots f
                       WHERE f.platform_post_id=pp.id AND f.measured_at>? AND f.measured_at<=?
                       ORDER BY f.measured_at LIMIT 1) first_views,
                      (SELECT f.reactions_count FROM platform_snapshots f
                       WHERE f.platform_post_id=pp.id AND f.measured_at>? AND f.measured_at<=?
                       ORDER BY f.measured_at LIMIT 1) first_reactions,
                      (SELECT f.comments_count FROM platform_snapshots f
                       WHERE f.platform_post_id=pp.id AND f.measured_at>? AND f.measured_at<=?
                       ORDER BY f.measured_at LIMIT 1) first_comments,
                      (SELECT f.shares_count FROM platform_snapshots f
                       WHERE f.platform_post_id=pp.id AND f.measured_at>? AND f.measured_at<=?
                       ORDER BY f.measured_at LIMIT 1) first_shares
               FROM platform_posts pp
               JOIN platform_accounts pa ON pa.id=pp.platform_account_id
               JOIN platform_snapshots latest ON latest.id=(
                    SELECT s.id FROM platform_snapshots s
                    WHERE s.platform_post_id=pp.id
                      AND s.measured_at>? AND s.measured_at<=?
                    ORDER BY s.measured_at DESC LIMIT 1)
               WHERE pa.platform=? AND pp.published_at<=?""",
            (
                window_start.isoformat(), window_end.isoformat(),
                window_start.isoformat(), window_end.isoformat(),
                window_start.isoformat(), window_end.isoformat(),
                window_start.isoformat(), window_end.isoformat(),
                window_start.isoformat(), window_end.isoformat(),
                window_start.isoformat(), window_end.isoformat(),
                window_start.isoformat(), window_end.isoformat(),
                platform, window_end.isoformat(),
            ),
        )]
        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            published = _as_datetime(row["published_at"])
            from_publication = (
                published >= window_start
                and row["first_age_seconds"] is not None
                and int(row["first_age_seconds"])
                <= settings.complete_history_max_first_age_minutes * 60
            )
            has_interval = (
                row["first_snapshot_id"] is not None
                and int(row["first_snapshot_id"]) != int(row["latest_snapshot_id"])
            )
            for metric in ("views", "reactions", "comments", "shares"):
                latest_value = row[f"{metric}_count"]
                first_value = row[f"first_{metric}"]
                base = 0 if from_publication else first_value if has_interval else None
                row[f"{metric}_delta"] = (
                    int(latest_value) - int(base)
                    if latest_value is not None and base is not None else None
                )
            if any(row[f"{metric}_delta"] is not None for metric in (
                "views", "reactions", "comments", "shares",
            )):
                grouped.setdefault(int(row["institution_id"]), []).append(row)
        return grouped

    current = window_samples(start, end)
    previous = window_samples(previous_start, start)
    new_counts = {
        int(row["institution_id"]): int(row["post_count"])
        for row in db.query(
            """SELECT pa.institution_id, COUNT(*) post_count
               FROM platform_posts pp JOIN platform_accounts pa
                 ON pa.id=pp.platform_account_id
               WHERE pa.platform=? AND pp.published_at>=? AND pp.published_at<=?
               GROUP BY pa.institution_id""",
            (platform, start.isoformat(), end.isoformat()),
        )
    }
    total_counts = {
        int(row["institution_id"]): int(row["post_count"])
        for row in db.query(
            """SELECT pa.institution_id, COUNT(*) post_count
               FROM platform_posts pp JOIN platform_accounts pa
                 ON pa.id=pp.platform_account_id
               WHERE pa.platform=? GROUP BY pa.institution_id""",
            (platform,),
        )
    }
    rank_field, score_field = RATING_FIELDS[platform]
    configured = collector_configured(settings, platform)
    cards: list[dict[str, Any]] = []
    for institution in institutions:
        institution_id = int(institution["id"])
        selected_accounts = accounts_by_institution.get(institution_id, [])
        samples = current.get(institution_id, [])
        previous_samples = previous.get(institution_id, [])
        metrics: dict[str, Any] = {}
        for metric in ("views", "reactions", "comments", "shares"):
            values = [
                int(row[f"{metric}_delta"])
                for row in samples if row[f"{metric}_delta"] is not None
            ]
            previous_values = [
                int(row[f"{metric}_delta"])
                for row in previous_samples if row[f"{metric}_delta"] is not None
            ]
            total = sum(values) if values else None
            previous_total = sum(previous_values) if previous_values else None
            current_median = _rounded_median(values)
            previous_median = _rounded_median(previous_values)
            metrics[f"total_{metric}"] = total
            metrics[f"median_{metric}"] = current_median
            metrics[f"delta_total_{metric}"] = (
                total - previous_total
                if total is not None and previous_total is not None else None
            )
            metrics[f"delta_median_{metric}"] = (
                current_median - previous_median
                if current_median is not None and previous_median is not None else None
            )
        subscriber_values = [
            int(account["subscriber_count"])
            for account in selected_accounts if account["subscriber_count"] is not None
        ]
        if not selected_accounts:
            status_text, status_kind = "Аккаунт не добавлен", "muted"
        elif not any(bool(account["enabled"]) for account in selected_accounts):
            status_text, status_kind = "Все аккаунты отключены", "warn"
        elif not configured:
            token_name = "VK_ACCESS_TOKEN" if platform == "vk" else "MAX_ACCESS_TOKEN"
            status_text, status_kind = f"Нужен {token_name}", "warn"
        elif any(account["last_error"] for account in selected_accounts):
            status_text, status_kind = "Последний опрос завершился ошибкой", "bad"
        elif any(account["last_checked_at"] for account in selected_accounts):
            status_text, status_kind = "Источник опрашивается", "ok"
        else:
            status_text, status_kind = "Ожидает первого опроса", "muted"
        cards.append({
            "institution": institution,
            "accounts": selected_accounts,
            "account_count": len(selected_accounts),
            "subscriber_count": sum(subscriber_values) if subscriber_values else None,
            "rating_rank": institution.get(rank_field),
            "rating_score": institution.get(score_field),
            "total_post_count": total_counts.get(institution_id, 0),
            "activity_post_count": len(samples),
            "post_count": new_counts.get(institution_id, 0),
            "status_text": status_text,
            "status_kind": status_kind,
            **metrics,
        })
    return cards
