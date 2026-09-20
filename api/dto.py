"""Сборка тел ответов по контракту."""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from urllib.parse import urlparse


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


def _trend(current: Any, previous: Any) -> Any:
    """Насколько показатель изменился против предыдущего такого же окна.

    Разница, а не отношение: на экране это плашка «+100» или «−100» рядом с
    самим числом, и читателю нужна величина в тех же единицах. Пусто, когда
    сравнивать не с чем — за месяц истории наблюдений пока не хватает.
    """
    left, right = number(current), number(previous)
    if left is None or right is None:
        return None
    return left - right


def metric(total: Any, median: Any, as_of: Any, revision: int,
           samples: int, denominator: int | None,
           previous_total: Any = None, previous_median: Any = None,
           previous_samples: int = 0,
           previous_denominator: int | None = None) -> dict[str, Any]:
    """Показатель с оглядкой на предыдущее окно той же длины.

    Предыдущее окно считает та же витрина, что и текущее: живым запросом это
    удваивало стоимость обзора, а числа одинаковы для всех читателей.
    """
    return {
        "total": number(total),
        "median": number(median),
        "previousTotal": number(previous_total),
        "previousMedian": number(previous_median),
        "totalTrend": _trend(total, previous_total),
        "medianTrend": _trend(median, previous_median),
        "totalMetadata": aggregate(total, as_of, revision, samples, denominator),
        "medianMetadata": aggregate(median, as_of, revision, samples, denominator),
        "previousTotalMetadata": aggregate(previous_total, as_of, revision,
                                           previous_samples, previous_denominator),
        "previousMedianMetadata": aggregate(previous_median, as_of, revision,
                                            previous_samples, previous_denominator),
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
    # Знаменатель предыдущего окна отдельный: по нему видно, сравнимы ли
    # периоды вообще, или прошлое окно просто пустое.
    previous_denominator = card.get("previous_publication_count") or None
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
                        card["views_samples"], denominator,
                        card["previous_total_views"], card["previous_median_views"],
                        card["views_samples"], previous_denominator),
        "reactions": metric(card["total_reactions"], card["median_reactions"], as_of, revision,
                            card["reactions_samples"], denominator,
                            card["previous_total_reactions"], card["previous_median_reactions"],
                            card["reactions_samples"], previous_denominator),
        "comments": metric(card["total_comments"], card["median_comments"], as_of, revision,
                           card["comments_samples"], denominator,
                           card["previous_total_comments"], card["previous_median_comments"],
                           card["comments_samples"], previous_denominator),
        "shares": metric(card["total_shares"], card["median_shares"], as_of, revision,
                         card["shares_samples"], denominator,
                         card["previous_total_shares"], card["previous_median_shares"],
                         card["shares_samples"], previous_denominator),
        "asOf": iso(as_of),
    }


def counter(row: dict[str, Any], name: str, *, common_time: bool = False) -> dict[str, Any]:
    quality = row.get(f"{name}_quality")
    value = row.get(f"{name}_count")
    if quality in ("invalid", "suspected_reset"):
        value = None
    observed = row.get("observed_at") if common_time else row.get(f"{name}_observed_at")
    return {"value": value, "observedAt": iso(observed), "quality": quality}


def _presentation(row: dict[str, Any]) -> dict[str, Any]:
    flags = row.get("presentation_flags", row.get("quality_flags")) or {}
    if not isinstance(flags, dict):
        flags = {}
    authors = max(
        int(row.get("joint_authors") or 0),
        int(flags.get("additional_author_count") or 0),
        int(flags.get("legacy_additional_author_count") or 0),
    )
    external_id = row.get("external_id")
    display = external_id
    if row.get("platform") == "telegram":
        display = None
        public_url = row.get("public_url")
        if public_url:
            tail = urlparse(public_url).path.rsplit("/", 1)[-1]
            if tail.isdigit():
                display = tail
        if display is None and external_id and external_id.startswith("m:"):
            display = external_id[2:]
    return {
        "displayExternalId": display,
        "repost": bool(row.get("is_repost")),
        "joint": bool(authors or flags.get("joint_post") or flags.get("legacy_is_joint")),
        "additionalAuthorCount": authors,
        "ambiguousAlbumReactions": bool(
            flags.get("ambiguous_album_reactions") or flags.get("ambiguous_reactions")),
    }


def institution(row: dict[str, Any], platform: str, period: str, revision: int) -> dict[str, Any]:
    return {
        "institutionId": str(row["institution_id"]),
        "legacyId": row["legacy_id"],
        "canonicalName": row["canonical_name"],
        "shortName": row["short_name"],
        "platform": platform,
        "period": period,
        "metrics": {
            "totalReactions": number(row["total_reactions"]),
            "totalViews": number(row["total_views"]),
            "medianReactions": number(row["median_reactions"]),
            "medianViews": number(row["median_views"]),
            "sampleSize": row["sample_size"],
            "coverage": number(row["coverage"]),
            "quality": row["quality"],
            "aggregates": row["aggregate_metadata"],
        },
        "datasetRevision": revision,
        "asOf": iso(row["as_of"]),
    }


def account_daily(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Недельная динамика: день, сколько постов вышло и какими они вышли."""
    return [{
        "day": row["metric_day"].isoformat(),
        "publishedCount": int(row["published_count"]),
        "medianReactions": number(row["median_reactions"]),
        "medianViews": number(row["median_views"]),
        # Прирост всех отслеживаемых постов за эти сутки — то же число, что
        # на карточке обзора. Медиана отвечает «каким вышел типичный пост»,
        # сумма — «сколько площадка набрала».
        "totalReactions": number(row.get("total_reactions")),
        "totalViews": number(row.get("total_views")),
    } for row in rows]


def account_stats(row: dict[str, Any], revision: int, as_of: Any,
                  daily: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    medians = row["medians"] or {}

    def median(name: str) -> dict[str, Any]:
        data = medians.get(name, {})
        return {
            "value": number(data.get("value")),
            "asOf": iso(as_of),
            "datasetRevision": revision,
            "sampleSize": int(data.get("sampleSize", 0)),
            "coverage": number(data.get("coverage", 0)),
            "quality": data.get("quality", "unknown"),
        }

    previous = row.get("previous_medians") or {}

    return {
        "retentionDays": row["retention_days"],
        "postCount": row["post_count"],
        "monitored": row["monitored"],
        "medianReactions": median("reactions"),
        "medianViews": median("views"),
        "medianComments": median("comments"),
        "ratingRank": row["rating_rank"],
        "ratingPeriod": row["rating_period"],
        "subscriberCount": row["subscriber_count"],
        "lastError": row["last_error"],
        "lastCheckedAt": iso(row["last_checked_at"]),
        "dailySeries": daily or [],
        # Вчерашние значения тех же плиток: по ним рисуется плашка «за сутки».
        # Место в рейтинге сравнивается с прошлым месяцем, а не с прошлыми
        # сутками: рейтинг выходит раз в месяц.
        "previous": {
            "postCount": row.get("previous_post_count"),
            "monitored": row.get("previous_monitored"),
            "medianReactions": number(previous.get("reactions")),
            "medianViews": number(previous.get("views")),
            "medianComments": number(previous.get("comments")),
            "ratingRank": row.get("previous_rating_rank"),
            "ratingPeriod": row.get("previous_rating_period"),
        },
    }


def account(row: dict[str, Any], revision: int, stats: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "accountId": str(row["account_id"] if "account_id" in row else row["id"]),
        "legacyId": row["legacy_id"],
        "legacyType": row["entity_type"],
        "channelLegacyId": row["channel_legacy_id"],
        "platformAccountLegacyId": row["platform_account_legacy_id"],
        "institutionId": str(row["institution_id"]),
        "institutionLegacyId": row["institution_legacy_id"],
        "institutionName": row["canonical_name"],
        "institutionShortName": row["short_name"],
        "platform": row["platform"],
        "canonicalExternalId": row["canonical_external_id"],
        "username": row["current_username"],
        "title": row["current_title"],
        "url": row["current_url"],
        "accessMode": row["access_mode"],
        "enabled": row["enabled"],
        "publicationCount": row["publication_count"],
        "latestObservedAt": iso(row.get("latest_observed_at", row.get("observed_at"))),
        "datasetRevision": revision,
        "asOf": iso(row["as_of"]),
        "stats": stats,
    }


def publication(row: dict[str, Any], revision: int) -> dict[str, Any]:
    return {
        "publicationId": str(row["publication_id"]),
        "legacyId": row["legacy_id"],
        "legacyType": row["entity_type"],
        "institutionId": str(row["institution_id"]),
        "platform": row["platform"],
        "publishedAt": iso(row["published_at"]),
        "publicationType": row["publication_type"],
        "deletedAt": iso(row["deleted_at"]),
        "views": counter(row, "views"),
        "reactions": counter(row, "reactions"),
        "comments": counter(row, "comments"),
        "shares": counter(row, "shares"),
        "quality": row["quality"],
        "intervalUncertain": row["interval_uncertain"],
        "synthetic": row["synthetic"],
        "historyCompleteness": row["history_completeness"],
        "datasetRevision": revision,
        "asOf": iso(row["observed_at"]),
        "accountLegacyId": row["account_legacy_id"],
        "accountLegacyType": row["account_legacy_type"],
        "accountName": row["account_name"],
        "accountUsername": row["account_username"],
        "externalId": row["external_id"],
        "publicUrl": row["public_url"],
        **_presentation(row),
    }


def publication_list_item(row: dict[str, Any]) -> dict[str, Any]:
    growth_day = row.get("growth_day")
    return {
        "publicationId": str(row["publication_id"]),
        "legacyId": row["legacy_id"],
        "legacyType": row["entity_type"],
        "legacyRoute": row["legacy_route"],
        "externalId": row["external_id"],
        "publishedAt": iso(row["published_at"]),
        "publicUrl": row["public_url"],
        "publicationType": row["publication_type"],
        "deletedAt": iso(row["deleted_at"]),
        "historyCompleteness": row["history_completeness"],
        "views": counter(row, "views"),
        "reactions": counter(row, "reactions"),
        "comments": counter(row, "comments"),
        "shares": counter(row, "shares"),
        "title": None,
        "archivedText": None,
        "dailyGrowth": None if growth_day is None else {
            "day": growth_day.isoformat(),
            "reactions": row.get("day_reactions_gain"),
            "views": row.get("day_views_gain"),
        },
        **_presentation(row),
    }


def history_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "snapshotId": str(row["snapshot_id"]),
        "observedAt": iso(row["observed_at"]),
        "ageHours": number((Decimal(row["age_seconds"]) / Decimal(3600)).quantize(Decimal("0.00000001"))),
        "views": counter(row, "views", common_time=True),
        "reactions": counter(row, "reactions", common_time=True),
        "comments": counter(row, "comments", common_time=True),
        "shares": counter(row, "shares", common_time=True),
        "deltaViews": row["delta_views"],
        "deltaReactions": row["delta_reactions"],
        "deltaComments": row["delta_comments"],
        "deltaShares": row["delta_shares"],
        "reactionsBreakdown": row["reaction_breakdown"],
        "deltaReactionsBreakdown": row["delta_reaction_breakdown"],
        "reactionsBreakdownEntries": row["reaction_entries"],
        "deltaReactionsBreakdownEntries": row["delta_reaction_entries"],
        "synthetic": row["synthetic"],
        "intervalUncertain": row["interval_uncertain"],
        "quality": row["quality"],
        "rawEvidence": row["lineage"],
        "collectorInterval": row["collector_interval"],
    }


def collector_coverage(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "availableFrom": iso(row["available_from"]),
        "through": iso(row["through_at"]),
        "expectedIntervalSeconds": row["expected_interval_seconds"],
        "successfulPolls": row["successful_polls"],
        "failedPolls": row["failed_polls"],
        "gaps": row["gaps"],
    }


def statistics_entity(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": row["rank"],
        "legacyRoute": row["legacy_route"],
        "institutionId": str(row["institution_id"]),
        "institutionLegacyId": row["institution_legacy_id"],
        "canonicalName": row["canonical_name"],
        "shortName": row["short_name"],
        "platform": row["platform"],
        "publicationCount": row["publication_count"],
        "interactionSampleSize": row["interaction_sample_size"],
        "viewSampleSize": row["view_sample_size"],
        "ervSampleSize": row["erv_sample_size"],
        "medianInteractions": number(row["median_interactions"]),
        "interactions": row["interactions"],
        "views": row["views"],
        "erv": number(row["erv"]),
    }


def statistics_publication(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": row["rank"],
        "publicationId": str(row["publication_id"]),
        "platform": row["platform"],
        "legacyId": row["legacy_id"],
        "legacyType": row["legacy_type"],
        "legacyRoute": row["legacy_route"],
        "institutionId": str(row["institution_id"]),
        "institutionLegacyId": row["institution_legacy_id"],
        "institutionCanonicalName": row["institution_canonical_name"],
        "institutionShortName": row["institution_short_name"],
        "accountId": str(row["account_id"]),
        "accountLegacyId": row["account_legacy_id"],
        "accountUsername": row["account_username"],
        "accountTitle": row["account_title"],
        "accountExternalId": row["canonical_external_id"],
        "externalId": row["external_id"],
        "publicUrl": row["public_url"],
        "publishedAt": iso(row["published_at"]),
        "deletedAt": iso(row["deleted_at"]),
        "joint": row["additional_author_count"] > 0,
        "additionalAuthorCount": row["additional_author_count"],
        "repost": row["is_repost"],
        "views": row["views"],
        "reactions": row["reactions"],
        "comments": row["comments"],
        "shares": row["shares"],
        "interactions": row["interactions"],
        "erv": number(row["erv"]),
        "interactionsAvailable": row["interactions"] is not None,
        "ervEligible": row["erv"] is not None,
    }


def comparison_candidate(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "selectionId": str(row["entity_id"]),
        "selectionType": row["entity_type"],
        "selectionLegacyId": row["legacy_id"],
        "selectionLabel": row["label"],
        "institutionId": str(row["institution_id"]),
        "canonicalName": row["canonical_name"],
        "selectionDescription": row["description"],
    }


def comparison_point(row: dict[str, Any], engagement: bool = False) -> dict[str, Any]:
    prefix = "engagement_" if engagement else ""
    return {
        "hourOffset": row["hour_offset"],
        "value": number(row[f"{prefix}value"]),
        "sampleSize": row[f"{prefix}sample_size"],
        "coverage": number(row[f"{prefix}coverage"]),
        "quality": row[f"{prefix}quality"],
    }


def comparison_series(row: dict[str, Any], points: list[dict[str, Any]],
                      engagement_points: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "selectionId": str(row["selection_id"]),
        "selectionType": row["selection_type"],
        "selectionLegacyId": row["selection_legacy_id"],
        "selectionLabel": row["selection_label"],
        "institutionId": str(row["institution_id"]),
        "legacyId": row["legacy_id"],
        "canonicalName": row["canonical_name"],
        "shortName": row["short_name"],
        "primaryCohortSize": row["primary_cohort_size"],
        "engagementCohortSize": row["engagement_cohort_size"],
        "points": points,
        "engagementPoints": engagement_points,
    }
