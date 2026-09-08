"""Сборка тел ответов по контракту."""
from __future__ import annotations

from decimal import Decimal
from typing import Any


def iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def number(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        # Контракт объявляет number: целые отдаём целыми, чтобы не плодить .0
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def aggregate(value: Any, as_of: Any, revision: int, samples: int,
              denominator: int | None, quality: str = "unknown") -> dict[str, Any]:
    """Метаданные агрегата считаются от его собственного набора кандидатов."""
    coverage = None
    if denominator:
        coverage = min(1.0, max(0.0, samples / denominator))
    return {
        "value": number(value),
        "asOf": iso(as_of),
        "datasetRevision": revision,
        "sampleSize": samples,
        "coverage": coverage,
        "quality": quality,
    }


def metric(total: Any, median: Any, as_of: Any, revision: int,
           samples: int, denominator: int | None) -> dict[str, Any]:
    """Предыдущее окно в этом режиме чтения не восстанавливается.

    Прежняя пересборка хранила исторические дельты в проекции. Проекций нет,
    и считать предыдущее окно живым запросом означало бы удвоить стоимость
    обзора ради значения, которого фронт не показывает без тренда.
    """
    empty = aggregate(None, as_of, revision, 0, None)
    return {
        "total": number(total),
        "median": number(median),
        "previousTotal": None,
        "previousMedian": None,
        "totalTrend": None,
        "medianTrend": None,
        "totalMetadata": aggregate(total, as_of, revision, samples, denominator),
        "medianMetadata": aggregate(median, as_of, revision, samples, denominator),
        "previousTotalMetadata": empty,
        "previousMedianMetadata": empty,
    }


def overview_account(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "accountId": str(row["account_id"]),
        "legacyId": row["account_legacy_id"],
        "legacyRoute": row["account_legacy_route"],
        "platform": row["account_platform"],
        "canonicalExternalId": row["account_external_id"],
        "username": row["account_username"],
        "title": row["account_title"],
        "url": row["account_url"],
        "accessMode": row["account_access_mode"],
        "enabled": row["account_enabled"],
        "subscriberCount": row["account_subscriber_count"],
        "subscriberDisplay": row["account_subscriber_display"],
        "subscriberObservedAt": iso(row["account_subscriber_observed_at"]),
        "latestPollStartedAt": iso(row["account_latest_poll_started_at"]),
        "latestPollCompletedAt": iso(row["account_latest_poll_completed_at"]),
        "latestPollStatus": row["account_latest_poll_status"],
        "latestErrorCode": row["account_latest_error_code"],
    }


def overview_row(card: dict[str, Any], accounts: list[dict[str, Any]], revision: int) -> dict[str, Any]:
    as_of = card["as_of"]
    denominator = card["sample_denominator"]
    return {
        "entityId": str(card["entity_id"]),
        "entityType": card["entity_type"],
        "legacyId": card["legacy_id"],
        "legacyRoute": card["legacy_route"],
        "institutionId": str(card["institution_id"]),
        "institutionLegacyId": card["institution_legacy_id"],
        "canonicalName": card["canonical_name"],
        "shortName": card["short_name"],
        "platform": card["platform"],
        "period": card["period_key"],
        "accounts": accounts,
        "accountCount": card["account_count"],
        "enabledAccountCount": card["enabled_account_count"],
        "connectedPlatformCount": card["connected_platform_count"],
        "subscriberCount": card["subscriber_count"],
        "lastCheckedAt": iso(card["last_checked_at"]),
        "lastErrorCode": card["last_error_code"],
        "statusCode": card["status_code"],
        "ratingRank": card["rating_rank"],
        "ratingScore": number(card["rating_score"]),
        "ratingPeriod": card["rating_period"],
        "ratingFetchedAt": iso(card["rating_fetched_at"]),
        "totalPublicationCount": card["total_publication_count"] or 0,
        "activityPublicationCount": card["activity_publication_count"] or 0,
        "newPublicationCount": card["new_publication_count"] or 0,
        "views": metric(card["total_views"], card["median_views"], as_of, revision,
                        card["views_samples"], denominator),
        "reactions": metric(card["total_reactions"], card["median_reactions"], as_of, revision,
                            card["reactions_samples"], denominator),
        "comments": metric(card["total_comments"], card["median_comments"], as_of, revision,
                           card["comments_samples"], denominator),
        "shares": metric(card["total_shares"], card["median_shares"], as_of, revision,
                         card["shares_samples"], denominator),
        "asOf": iso(as_of),
    }
