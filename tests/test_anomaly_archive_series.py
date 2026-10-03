from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from anomaly_analysis.v2.archive_series import ArchiveSeriesSource, archive_row, merge_rows
from anomaly_analysis.v2.domain import Metric
from anomaly_analysis.v2.store import series_from_rows
from operations.cold_archive import browse

POST = UUID("00000000-0000-4000-8000-000000000001")
ACCOUNT = UUID("00000000-0000-4000-8000-0000000000aa")
PUBLISHED = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
TARGET = {"id": POST, "primary_account_id": ACCOUNT, "platform": "telegram", "published_at": PUBLISHED,
          "is_repost": False}


def item(snapshot: int, minutes: int, views: int, reactions: int, *, quality: str = "exact",
         synthetic: bool = False) -> dict:
    observed = (PUBLISHED + timedelta(minutes=minutes)).isoformat()
    return {"snapshotId": str(snapshot), "observedAt": observed, "synthetic": synthetic, "intervalUncertain": False,
            "views": {"value": views, "observedAt": observed, "quality": "exact"},
            "reactions": {"value": reactions, "observedAt": observed, "quality": quality},
            "comments": {"value": None, "observedAt": observed, "quality": None},
            "shares": {"value": 1, "observedAt": observed, "quality": "exact"},
            "reactionsBreakdown": {"👍": reactions}}


def test_history_item_becomes_a_series_row_like_the_database_query() -> None:
    row = archive_row(TARGET, item(7, 5, 100, 9, quality="rounded"))
    assert row["observed_at"] == PUBLISHED + timedelta(minutes=5)
    assert (row["views_count"], row["views_quality"], row["reactions_quality"]) == (100, "exact", "rounded")
    assert row["reaction_breakdown"] == {"👍": 9}
    assert archive_row(TARGET, item(8, 10, 1, 1))["reaction_breakdown"] is None
    assert archive_row(TARGET, item(9, 15, 1, 1, synthetic=True)) is None


def test_late_database_rows_win_over_the_archive_at_the_same_moment() -> None:
    archived = [archive_row(TARGET, item(1, 0, 10, 1)), archive_row(TARGET, item(2, 5, 20, 2))]
    late = [{**archive_row(TARGET, item(3, 5, 25, 2)), "_snapshot_id": 3},
            {**archive_row(TARGET, item(4, 60 * 24 * 40, 90, 5))}]
    merged = merge_rows(archived, late)
    assert [row["views_count"] for row in merged] == [10, 25, 90]


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, files):
        self.files = files

    def execute(self, sql, params):
        if "cold_archive_generation" in sql:
            return Cursor([{"published_month": date(2026, 8, 1), "name": name} for name in self.files])
        return Cursor([TARGET])


def test_series_of_an_archived_month_is_read_from_its_browse_files(tmp_path) -> None:
    (tmp_path / "archive").mkdir()
    # Поколение 1 — основной ряд, поколение 2 — поздний контрольный замер.
    generations = [[item(2, 5, 20, 2), item(1, 0, 10, 1)], [item(5, 60 * 24 * 32, 80, 4)]]
    for number, items in enumerate(generations, start=1):
        record = browse.BrowseRecord(str(POST), str(ACCOUNT), PUBLISHED, items, None, len(items), 10)
        browse.write(tmp_path / "archive" / f"browse-2026-08-g{number}.sqlite", "2026-08", [record])
    source = ArchiveSeriesSource(tmp_path)
    connection = Connection(["browse-2026-08-g1.sqlite", "browse-2026-08-g2.sqlite"])
    files = source.cold_files(connection, [date(2026, 8, 1)])
    rows, unreadable = source.rows(connection, [POST, UUID(int=5)], files,
                                   {POST: date(2026, 8, 1), UUID(int=5): date(2026, 9, 1)})
    assert list(rows) == [POST] and unreadable == set()
    series = series_from_rows(merge_rows(rows[POST], []))
    assert series.values[Metric.VIEWS] == (10, 20, 80)
    assert Metric.COMMENTS not in series.values
    assert series.observed_at[0] == PUBLISHED


def test_missing_registry_disables_the_archive_for_a_while() -> None:
    class Broken:
        def execute(self, sql, params):
            raise RuntimeError("relation does not exist")

    moments = iter([0.0, 0.0, 10.0, 700.0])
    source = ArchiveSeriesSource(clock=lambda: next(moments))
    assert source.cold_files(Broken(), [date(2026, 8, 1)]) == {}
    assert source.cold_files(Broken(), [date(2026, 8, 1)]) == {}
    assert source.cold_files(Connection([]), [date(2026, 8, 1)]) == {}


def test_an_unreadable_archive_file_marks_the_post_instead_of_failing_the_batch(tmp_path) -> None:
    source = ArchiveSeriesSource(tmp_path)
    connection = Connection(["browse-2026-08-g1.sqlite"])
    files = source.cold_files(connection, [date(2026, 8, 1)])
    rows, unreadable = source.rows(connection, [POST], files, {POST: date(2026, 8, 1)})
    assert rows == {} and unreadable == {POST}
