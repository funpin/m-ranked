from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .source import LegacySource


ColumnStatus = Literal[
    "mapped",
    "derived-and-verified",
    "preserved-as-evidence",
    "intentionally-deprecated-after-acceptance",
]


@dataclass(frozen=True)
class ColumnDecision:
    status: ColumnStatus
    target: str
    rule: str


def _mapped(target: str, rule: str = "lossless mapping") -> ColumnDecision:
    return ColumnDecision("mapped", target, rule)


def _evidence(rule: str) -> ColumnDecision:
    return ColumnDecision("preserved-as-evidence", "migration.legacy_evidence", rule)


COLUMN_MAPPING: dict[str, dict[str, ColumnDecision]] = {
    "schema_migrations": {
        "version": _evidence("record source schema provenance; never add to Flyway history"),
        "applied_at": _evidence("record source migration provenance"),
    },
    "app_state": {
        "key": _mapped(
            "operations.operational_checkpoint.key",
            "allowlisted freshness keys are mapped; every key is also retained as evidence",
        ),
        "value": _mapped(
            "operations.operational_checkpoint.value",
            "allowlisted values are mapped without interpretation; unknown values remain evidence",
        ),
    },
    "institutions": {
        "id": _mapped("catalog.legacy_entity_alias + migration.legacy_identity_map"),
        "name": _mapped("catalog.institution.canonical_name"),
        "short_name": _mapped("catalog.institution.short_name"),
        "created_at": _mapped("catalog.institution.created_at", "parse as UTC"),
        "m_rating_social_rank": _mapped("rating.official_rating_observation.rank"),
        "m_rating_social_score": _mapped("rating.official_rating_observation.score"),
        "m_rating_tg_rank": _mapped("rating.official_rating_observation.rank"),
        "m_rating_tg_score": _mapped("rating.official_rating_observation.score"),
        "m_rating_vk_rank": _mapped("rating.official_rating_observation.rank"),
        "m_rating_vk_score": _mapped("rating.official_rating_observation.score"),
        "m_rating_max_rank": _mapped("rating.official_rating_observation.rank"),
        "m_rating_max_score": _mapped("rating.official_rating_observation.score"),
        "m_rating_rutube_rank": _mapped("rating.official_rating_observation.rank"),
        "m_rating_rutube_score": _mapped("rating.official_rating_observation.score"),
        "m_rating_period": _mapped("rating.official_rating_observation.period"),
        "m_rating_measured_at": _mapped("rating.official_rating_observation.fetched_at"),
    },
    "platform_accounts": {
        "id": _mapped("catalog.legacy_entity_alias + migration.legacy_identity_map"),
        "institution_id": _mapped("catalog.platform_account.institution_id"),
        "platform": _mapped("catalog.platform_account.platform"),
        "external_key": _mapped("catalog.platform_account.canonical_external_id"),
        "native_id": _mapped("catalog.account_external_identity.external_id"),
        "username": _mapped("catalog.platform_account.current_username + account_identity_history"),
        "title": _mapped("catalog.platform_account.current_title + account_identity_history"),
        "url": _mapped("catalog.platform_account.current_url + account_identity_history"),
        "enabled": _mapped("catalog.platform_account.enabled"),
        "access_mode": _mapped("catalog.platform_account.access_mode"),
        "data_quality": _mapped("ingest.account_metric_snapshot.quality"),
        "subscriber_count": _mapped("ingest.account_metric_snapshot.subscriber_count"),
        "subscriber_count_display": _mapped("ingest.account_metric_snapshot.subscriber_display"),
        "subscriber_measured_at": _mapped("ingest.account_metric_snapshot.observed_at"),
        "last_checked_at": _mapped("operations.operational_checkpoint.observed_at"),
        "last_error": _evidence("sanitized legacy collector state; never expose from public health"),
        "added_at": _mapped("catalog.platform_account.created_at", "parse as UTC"),
    },
    "channels": {
        "id": _mapped("catalog.legacy_entity_alias", "channel alias resolves to platform_account UUID"),
        "telegram_id": _mapped("catalog.account_external_identity.external_id"),
        "username": _mapped("catalog.platform_account.current_username"),
        "title": _mapped("catalog.platform_account.current_title"),
        "enabled": _mapped("catalog.platform_account.enabled"),
        "added_at": _mapped("catalog.platform_account.created_at"),
        "last_seen_message_id": _mapped("operations.operational_checkpoint.value"),
        "last_checked_at": _mapped("operations.operational_checkpoint.observed_at"),
        "last_error": _evidence("sanitized legacy collector state"),
        "subscriber_count": _mapped("ingest.account_metric_snapshot.subscriber_count"),
        "subscriber_count_display": _mapped("ingest.account_metric_snapshot.subscriber_display"),
        "subscriber_measured_at": _mapped("ingest.account_metric_snapshot.observed_at"),
        "m_rating_tg_rank": _mapped("rating.official_rating_observation.rank"),
        "m_rating_tg_score": _mapped("rating.official_rating_observation.score"),
        "m_rating_period": _mapped("rating.official_rating_observation.period"),
        "m_rating_measured_at": _mapped("rating.official_rating_observation.fetched_at"),
        "institution_id": _mapped("catalog.platform_account.institution_id"),
        "platform_account_id": _mapped("migration identity linkage", "takes priority over inferred account"),
    },
    "platform_posts": {
        "id": _mapped("catalog.legacy_entity_alias + migration.legacy_identity_map"),
        "platform_account_id": _mapped("ingest.publication.primary_account_id"),
        "external_id": _mapped("ingest.publication_identity.external_id"),
        "published_at": _mapped("ingest.publication.published_at"),
        "discovered_at": _mapped("ingest.publication.discovered_at"),
        "post_type": _mapped("ingest.publication.publication_type"),
        "url": _mapped("ingest.publication_identity.public_url"),
        "deleted_at": _mapped("ingest.publication.deleted_at"),
        "missing_check_count": _mapped("ingest.deletion_observation.consecutive_missing"),
        "missing_last_checked_at": _mapped("ingest.deletion_observation.observed_at"),
        "missing_reason": _mapped("ingest.deletion_observation.reason_code"),
        "raw_json": _evidence("raw migration evidence retained through acceptance"),
        "history_complete": _mapped("ingest.publication.history_completeness"),
        "history_forced_incomplete": _mapped("ingest.publication.history_completeness"),
        "source_external_id": _mapped("ingest.publication_identity.source_external_id"),
        "is_joint": _evidence(
            "retain the joint flag with lineage; absent author identities are never invented"
        ),
        "additional_author_count": _evidence("joint-post evidence; canonical relationship rebuilt explicitly"),
        "is_repost": _mapped("ingest.publication.is_repost"),
        "created_at": _mapped("ingest.publication.created_at"),
    },
    "posts": {
        "id": _mapped("catalog.legacy_entity_alias + migration.legacy_identity_map"),
        "channel_id": _mapped("ingest.publication.primary_account_id", "resolve channel alias"),
        "logical_key": _mapped(
            "migration.legacy_identity_map.natural_key + ingest.content_group",
            "preserve the logical key in immutable mapping; canonicalize album grouping",
        ),
        "telegram_message_id": _mapped(
            "ingest.publication_identity.external_id",
            "strip the canonical m:/g: namespace; groups use g:<grouped_id>",
        ),
        "telegram_grouped_id": _mapped("ingest.content_group + migration evidence"),
        "published_at": _mapped("ingest.publication.published_at"),
        "discovered_at": _mapped("ingest.publication.discovered_at"),
        "first_observation_age_seconds": _mapped("ingest.publication.first_observation_age_seconds"),
        "history_complete": _mapped("ingest.publication.history_completeness"),
        "history_forced_incomplete": _mapped("ingest.publication.history_completeness"),
        "baseline_from_publication": _mapped("ingest.publication.synthetic_baseline_allowed"),
        "post_type": _mapped("ingest.publication.publication_type"),
        "ambiguous_album_reactions": _mapped("ingest.publication.quality_flags"),
        "is_repost": _mapped("ingest.publication.is_repost"),
        "deleted_at": _mapped("ingest.publication.deleted_at"),
        "missing_check_count": _mapped("ingest.deletion_observation.consecutive_missing"),
        "missing_last_checked_at": _mapped("ingest.deletion_observation.observed_at"),
        "missing_reason": _mapped("ingest.deletion_observation.reason_code"),
        "created_at": _mapped("ingest.publication.created_at"),
    },
    "post_messages": {
        "post_id": _mapped("ingest.publication_identity.publication_id"),
        "telegram_message_id": _mapped(
            "ingest.publication_identity.external_id",
            "all message IDs retained as m:<message_id>",
        ),
    },
    "platform_snapshots": {
        "id": _mapped("migration.legacy_identity_map.target_bigint"),
        "platform_post_id": _mapped("ingest.publication_metric_snapshot.publication_id"),
        "measured_at": _mapped("ingest.publication_metric_snapshot.observed_at"),
        "measurement_bucket": _mapped("ingest.publication_metric_snapshot.sampling_bucket"),
        "age_seconds": _mapped("ingest.publication_metric_snapshot.age_seconds"),
        "views_count": _mapped("ingest.publication_metric_snapshot.views_count"),
        "reactions_count": _mapped("ingest.publication_metric_snapshot.reactions_count"),
        "comments_count": _mapped("ingest.publication_metric_snapshot.comments_count"),
        "shares_count": _mapped("ingest.publication_metric_snapshot.shares_count"),
        "raw_json": _evidence("raw migration evidence retained through acceptance"),
        "created_at": _mapped("ingest.publication_metric_snapshot.created_at"),
    },
    "reaction_snapshots": {
        "id": _mapped("migration.legacy_identity_map.target_bigint"),
        "post_id": _mapped("ingest.publication_metric_snapshot.publication_id"),
        "measured_at": _mapped("ingest.publication_metric_snapshot.observed_at"),
        "measurement_bucket": _mapped("ingest.publication_metric_snapshot.sampling_bucket"),
        "age_seconds": _mapped("ingest.publication_metric_snapshot.age_seconds"),
        "total_reactions": _mapped("ingest.publication_metric_snapshot.reactions_count"),
        "reactions_json": _mapped("ingest.reaction_breakdown"),
        "raw_state_json": _evidence("raw migration evidence retained through acceptance"),
        "delta_total": _evidence("recalculate as versioned projection and compare to retained value"),
        "delta_by_reaction_json": _evidence("recalculate as versioned projection and compare to retained value"),
        "delta_seconds": _evidence("recalculate from observed_at and compare to retained value"),
        "rate_per_hour": _evidence("recalculate as versioned projection and compare with explicit epsilon"),
        "interval_uncertain": _mapped("ingest.publication_metric_snapshot.interval_uncertain"),
        "spike": _evidence("legacy derived flag is not a raw fact"),
        "comments_count": _mapped("ingest.publication_metric_snapshot.comments_count"),
        "delta_comments": _evidence("recalculate as versioned projection and compare to retained value"),
        "views_count": _mapped("ingest.publication_metric_snapshot.views_count"),
        "delta_views": _evidence("recalculate as versioned projection and compare to retained value"),
        "synthetic": _mapped("ingest.publication_metric_snapshot.synthetic"),
        "created_at": _mapped("ingest.publication_metric_snapshot.created_at"),
    },
}


def validate_mapping(source: LegacySource) -> list[str]:
    """Return every unmapped or stale matrix entry; an empty result is the gate."""

    errors: list[str] = []
    existing = source.table_names()
    for table in sorted(existing.intersection(COLUMN_MAPPING)):
        actual = set(source.columns(table))
        declared = set(COLUMN_MAPPING[table])
        for column in sorted(actual - declared):
            errors.append(f"unmapped source column: {table}.{column}")
        for column in sorted(declared - actual):
            errors.append(f"mapping references absent source column: {table}.{column}")
    for table in sorted(existing - set(COLUMN_MAPPING) - {"sqlite_sequence"}):
        errors.append(f"unmapped source table: {table}")
    return errors


def mapping_as_rows() -> list[dict[str, str]]:
    return [
        {
            "source": f"{table}.{column}",
            "status": decision.status,
            "target": decision.target,
            "rule": decision.rule,
        }
        for table, columns in COLUMN_MAPPING.items()
        for column, decision in columns.items()
    ]
