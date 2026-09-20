from __future__ import annotations

from decimal import Decimal

import pytest

from api import dto
from api.errors import BadRequest
from api.params import encode_scoped_cursor, scoped_cursor, statistics_query
from api.routes.statistics import _like_pattern
from api.sql import statistics as sql
from api.statistics_capabilities import (
    PLATFORM_METRIC_CAPABILITIES,
    aggregate_statistics,
    interactions,
    publication_erv,
)


def test_capability_matrix_is_exhaustive_and_matches_collector_contracts() -> None:
    assert set(PLATFORM_METRIC_CAPABILITIES) == {"telegram", "vk", "max", "rutube"}
    assert PLATFORM_METRIC_CAPABILITIES["telegram"] == {"views", "reactions", "comments"}
    assert PLATFORM_METRIC_CAPABILITIES["vk"] == {"views", "reactions", "comments", "shares"}
    assert PLATFORM_METRIC_CAPABILITIES["max"] == {"views", "reactions"}
    assert PLATFORM_METRIC_CAPABILITIES["rutube"] == {"views", "reactions", "comments"}


def test_interactions_distinguish_unsupported_missing_and_zero() -> None:
    assert interactions("telegram", 3, 2, None) == 5
    assert interactions("max", 3, None, None) == 3
    assert interactions("vk", 3, 2, None) is None
    assert interactions("rutube", None, 2, None) is None
    assert interactions("vk", 0, 0, 0) == 0


def test_publication_erv_requires_known_interactions_and_positive_views() -> None:
    assert publication_erv(6, 40) == Decimal("15")
    assert publication_erv(None, 40) is None
    assert publication_erv(0, 0) is None
    assert publication_erv(0, None) is None


def test_entity_aggregate_uses_median_and_one_weighted_erv_cohort() -> None:
    odd = aggregate_statistics([(1, 10), (100, 1000), (2, 10)])
    assert odd["medianInteractions"] == Decimal("2")
    assert odd["erv"] == Decimal(103) * 100 / Decimal(1020)

    even = aggregate_statistics([(1, 10), (3, 0), (None, 100), (5, None)])
    assert even["medianInteractions"] == Decimal("3")
    assert even["interactionSampleSize"] == 3
    assert even["viewSampleSize"] == 3
    assert even["ervSampleSize"] == 1
    assert even["erv"] == Decimal("10")


def test_statistics_query_and_cursor_include_every_result_dimension() -> None:
    query = statistics_query("entities", "vk", "7d", "alpha", "views", "asc",
                             "interactions", "desc")
    cursor = encode_scoped_cursor("00000000-0000-4000-8000-000000000001", 17,
                                  "statistics:" + query.dimensions)
    assert scoped_cursor(cursor, 17, "statistics:" + query.dimensions)
    changed = statistics_query("entities", "vk", "7d", "beta", "views", "asc",
                               "interactions", "desc")
    with pytest.raises(BadRequest) as error:
        scoped_cursor(cursor, 17, "statistics:" + changed.dimensions)
    assert "курсор" in (error.value.detail or "")


def test_search_pattern_escapes_sql_wildcards_literally() -> None:
    assert _like_pattern(r"50%_\\") == r"%50\%\_\\\\%"


def test_sql_applies_search_before_caps_and_nulls_last_in_both_directions() -> None:
    normalized_publications = " ".join(sql.PUBLICATIONS.split())
    normalized_entities = " ".join(sql.ENTITIES.split())
    assert normalized_publications.index("filtered AS") < normalized_publications.index("newest AS")
    assert "newest_position<=200" in normalized_publications
    assert "rank<=50" in normalized_publications
    assert "AS legacy_type" in normalized_publications
    assert "AS account_username" in normalized_publications
    assert "AS account_title" in normalized_publications
    assert "ASC NULLS LAST" in normalized_publications
    assert "DESC NULLS LAST" in normalized_publications
    assert "PARTITION BY institution_id" in normalized_entities
    assert "institution_position<=20" in normalized_entities
    assert "subscriber" not in normalized_entities.lower()
    assert "percentile_cont(0.5)" in normalized_entities
    assert "FILTER (WHERE interactions IS NOT NULL AND views>0)" in normalized_entities


def test_statistics_dto_preserves_zero_and_unknown() -> None:
    base = {
        "rank": 1, "publication_id": "00000000-0000-4000-8000-000000000001",
        "platform": "vk", "legacy_id": 1, "legacy_type": "platform_posts",
        "legacy_route": "/platform-posts/1", "institution_id": "00000000-0000-4000-8000-000000000002",
        "institution_legacy_id": 1, "institution_canonical_name": "University",
        "institution_short_name": None, "account_id": "00000000-0000-4000-8000-000000000003",
        "account_legacy_id": 2, "account_username": "uni", "account_title": "Uni",
        "canonical_external_id": "-1", "external_id": "-1_1", "public_url": "https://vk.com/wall-1_1",
        "published_at": None, "deleted_at": None, "additional_author_count": 0,
        "is_repost": False, "views": 10, "reactions": 0, "comments": 0, "shares": 0,
        "interactions": 0, "erv": Decimal("0"),
    }
    result = dto.statistics_publication(base)
    assert result["interactions"] == 0
    assert result["erv"] == 0.0
    assert result["interactionsAvailable"] is True
    base["interactions"], base["erv"] = None, None
    unknown = dto.statistics_publication(base)
    assert unknown["interactions"] is None and unknown["erv"] is None
    assert unknown["interactionsAvailable"] is False
