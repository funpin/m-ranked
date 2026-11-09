"""Приёмка эталона постов ВК: объём, классы и причина у каждой строки."""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTS = ROOT / "research/vk-engagement-2026-11/reference/posts.csv"
CLASSES = {
    "organized_audience", "external_promotion", "view_bursts", "reaction_waves",
    "organic", "timezone_shift", "federal",
}
OWNER_TEST_PREFIXES = {"26aabf8e", "5d9369ab", "f3e2f2e7", "bb6f379e", "85b17359"}


def _rows() -> list[dict[str, str]]:
    with POSTS.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_reference_has_enough_confirmed_posts_in_every_class() -> None:
    rows = _rows()
    confirmed = Counter(row["class"] for row in rows if row["status"] == "confirmed")
    assert len(rows) >= 250
    assert set(confirmed) == CLASSES
    assert min(confirmed.values()) >= 30


def test_every_post_appears_once_with_a_reason_and_known_labels() -> None:
    rows = _rows()
    assert len({row["publication_id"] for row in rows}) == len(rows)
    assert all(row["reason"].strip() for row in rows)
    assert {row["status"] for row in rows} == {"confirmed", "disputed"}
    assert {row["source"] for row in rows} == {"form", "owner_test"}


def test_owner_paid_promotion_posts_are_the_only_owner_labels() -> None:
    owner = [row for row in _rows() if row["source"] == "owner_test"]
    assert {row["publication_id"][:8] for row in owner} == OWNER_TEST_PREFIXES
    assert {(row["class"], row["status"]) for row in owner} == {("external_promotion", "confirmed")}


def test_reasons_describe_counters_not_intent() -> None:
    text = POSTS.read_text(encoding="utf-8").casefold()
    assert "бот" not in text
    assert "накрут" not in text
