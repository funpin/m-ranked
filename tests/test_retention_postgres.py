"""Retention against real PostgreSQL: append-only, watermark and semantics."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

import pytest

from collector_target.model import (
    AccountRef, CollectionContext, HistoryCompleteness, Platform,
    RawCollectionBatch, RawPublication,
)
from collector_target.normalize import CanonicalNormalizer
from collector_target.repository import PostgresCollectorRepository
from collector_target.retention import (
    RetentionPolicy, RetentionRefused, WorkingSetRetention,
)
from collector_target.transfer import (
    InProcessTransport, PostgresDataAdapter, PostgresTransferProducer,
)


TRACK_HOURS = 960


def _dsn(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        pytest.skip(f"{name} is not configured")
    return value


def _account(institution_id, account_id, suffix: str) -> AccountRef:
    return AccountRef(
        account_id, institution_id, Platform.VK,
        f"retention_{suffix}_{account_id.hex}", "official_api",
    )


def _seed(admin, institution_id, account_id, canonical_external_id) -> None:
    admin.execute(
        "INSERT INTO catalog.institution(id,canonical_name) VALUES (%s,%s)",
        (institution_id, f"retention {institution_id}"),
    )
    admin.execute(
        """INSERT INTO catalog.platform_account(
               id,institution_id,platform,canonical_external_id,access_mode
           ) VALUES (%s,%s,'vk',%s,'official_api')""",
        (account_id, institution_id, canonical_external_id),
    )


def _batch(context, account, external_id, published_at, observed_at, metrics):
    raw = RawCollectionBatch(
        account, None,
        (RawPublication(
            external_id, published_at, observed_at, observed_at, observed_at,
            "post", metrics, {"kind": "retention-test"},
            history_completeness=HistoryCompleteness.COMPLETE,
        ),),
        "retention-integration", "1",
    )
    return CanonicalNormalizer().normalize(raw, context)


def _reset(admin) -> None:
    admin.execute("DELETE FROM ops_and_admin.transfer_inbox_event")
    admin.execute("DELETE FROM ops_and_admin.transfer_inbox")
    admin.execute("DELETE FROM ops_and_admin.transfer_outbox")


def test_retention_releases_only_acknowledged_months_and_keeps_the_window() -> None:
    """The headline guarantee, and the semantics that must survive it.

    Observations are append-only, so retention drops a whole month or nothing.
    A publication still inside the tracking window therefore keeps all of its
    history, which is exactly what `metric_ever_positive` needs: its three
    branches depend on the last 24 observations, and a boolean flag could not
    reproduce them.
    """
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    collector_dsn = _dsn("MRANKED_TEST_POSTGRES_DSN")
    admin = psycopg.connect(_dsn("MRANKED_TEST_POSTGRES_ADMIN_DSN"),
                            autocommit=True, row_factory=dict_row)
    institution_id, account_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    # Comfortably past month_end + 960 h, so the month is fully out of window.
    stale = (now - timedelta(days=200)).replace(day=1, hour=12, minute=0, second=0)
    stale_month = stale.date().replace(day=1)
    fresh = now - timedelta(hours=2)

    account = _account(institution_id, account_id, "mix")
    partition = f"retention-{uuid4()}"
    producer_id = f"server-1/{partition}"
    repository = PostgresCollectorRepository(
        collector_dsn, transfer_producer_id=producer_id, deployment_profile="b",
    )
    adapter = PostgresDataAdapter(repository)
    repository.configure_transfer_sender(
        PostgresTransferProducer(repository, InProcessTransport(adapter)),
    )
    try:
        _reset(admin)
        _seed(admin, institution_id, account_id, account.canonical_external_id)

        stale_context = CollectionContext.create(
            Platform.VK, partition, "retention-v1", stale, stale,
        )
        repository.start_run(stale_context)
        assert repository.begin_account(stale_context, account, stale)
        repository.persist_account_batch(_batch(
            stale_context, account, "wall:-1_100", stale, stale,
            {"views": 10, "reactions": 2, "comments": 0, "shares": None},
        ))

        # Three publications in the current window, one per ever-positive branch.
        fresh_context = CollectionContext.create(
            Platform.VK, partition, "retention-v1", fresh, fresh,
        )
        repository.start_run(fresh_context)
        assert repository.begin_account(fresh_context, account, fresh)
        repository.persist_account_batch(_batch(
            fresh_context, account, "wall:-1_200", fresh, fresh,
            {"views": 7, "reactions": 3, "comments": 1, "shares": 2},
        ))
        repository.persist_account_batch(_batch(
            fresh_context, account, "wall:-1_201", fresh, fresh,
            {"views": 5, "reactions": None, "comments": None, "shares": None},
        ))

        tracked_ids = ["wall:-1_200", "wall:-1_201"]
        before = repository.metric_ever_positive(account, tracked_ids)
        # Branch two: observations exist but the metric is entirely NULL, so the
        # cautious answer is true — a reset may be in progress.
        assert before["wall:-1_201"]["reactions"] is True
        assert before["wall:-1_201"]["views"] is True
        # Branch three: ordinary positive values.
        assert before["wall:-1_200"] == {
            "views": True, "reactions": True, "comments": True, "shares": True,
        }
        # Branch one is the released month itself: the publication still exists,
        # its observations do not yet.
        assert repository.metric_ever_positive(account, ["wall:-1_100"])[
            "wall:-1_100"
        ]["views"] is True

        months = {
            row["published_month"] for row in admin.execute(
                "SELECT DISTINCT published_month FROM ingest.publication_metric_snapshot",
            ).fetchall()
        }
        assert stale_month in months

        policy = RetentionPolicy(
            mode="on", track_post_for_hours=TRACK_HOURS, months_per_run=12,
        )
        outcome = WorkingSetRetention(repository, policy).run()

        assert stale_month in outcome.released_months
        remaining = {
            row["published_month"] for row in admin.execute(
                "SELECT DISTINCT published_month FROM ingest.publication_metric_snapshot",
            ).fetchall()
        }
        assert stale_month not in remaining

        # The window survived byte for byte: both branches unchanged.
        after = repository.metric_ever_positive(account, tracked_ids)
        assert after == before

        # Branch one, now reached for real: the released publication keeps its
        # identity but has no observations, so its zero is treated as genuine.
        assert repository.metric_ever_positive(account, ["wall:-1_100"]) == {
            "wall:-1_100": {
                "views": False, "reactions": False,
                "comments": False, "shares": False,
            },
        }

        # Refresh planning still sees the tracked publications.
        tracked = {
            item.external_id for item in repository.tracked_publications(
                account,
                published_after=now - timedelta(hours=TRACK_HOURS),
                limit=50,
            )
        }
        assert {"wall:-1_200", "wall:-1_201"} <= tracked

        # A second run is a no-op rather than an error.
        again = WorkingSetRetention(repository, policy).run()
        assert stale_month not in again.released_months
    finally:
        repository.close()
        admin.close()


def test_unacknowledged_batches_pin_every_month_they_cover() -> None:
    """Nothing leaves Server 1 before Server 2 says it has it."""
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    collector_dsn = _dsn("MRANKED_TEST_POSTGRES_DSN")
    admin = psycopg.connect(_dsn("MRANKED_TEST_POSTGRES_ADMIN_DSN"),
                            autocommit=True, row_factory=dict_row)
    institution_id, account_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    stale = (now - timedelta(days=200)).replace(day=1, hour=12, minute=0, second=0)
    stale_month = stale.date().replace(day=1)
    account = _account(institution_id, account_id, "pinned")
    partition = f"pinned-{uuid4()}"
    producer_id = f"server-1/{partition}"
    repository = PostgresCollectorRepository(
        collector_dsn, transfer_producer_id=producer_id, deployment_profile="b",
    )

    class NeverAcknowledges:
        def send(self, envelope):
            raise ConnectionError("Server 2 is down")

    repository.configure_transfer_sender(
        PostgresTransferProducer(repository, NeverAcknowledges()),
    )
    try:
        _reset(admin)
        _seed(admin, institution_id, account_id, account.canonical_external_id)
        context = CollectionContext.create(
            Platform.VK, partition, "retention-v1", stale, stale,
        )
        repository.start_run(context)
        assert repository.begin_account(context, account, stale)
        repository.persist_account_batch(_batch(
            context, account, "wall:-2_100", stale, stale,
            {"views": 4, "reactions": 1, "comments": 0, "shares": None},
        ))

        unacknowledged = admin.execute(
            """SELECT count(*) AS count FROM ops_and_admin.transfer_outbox
                WHERE state <> 'acknowledged'""",
        ).fetchone()["count"]
        assert unacknowledged == 1

        policy = RetentionPolicy(
            mode="on", track_post_for_hours=TRACK_HOURS, months_per_run=12,
        )
        outcome = WorkingSetRetention(repository, policy).run()

        # The month is out of the tracking window, yet it stays: the only copy
        # of these rows is still here.
        assert stale_month not in outcome.released_months
        assert stale_month in outcome.deferred_months
        assert admin.execute(
            """SELECT count(*) AS count FROM ingest.publication_metric_snapshot
                WHERE published_month=%s""",
            (stale_month,),
        ).fetchone()["count"] > 0
    finally:
        repository.close()
        admin.close()


def test_dry_run_reports_what_it_would_release_and_changes_nothing() -> None:
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    collector_dsn = _dsn("MRANKED_TEST_POSTGRES_DSN")
    admin = psycopg.connect(_dsn("MRANKED_TEST_POSTGRES_ADMIN_DSN"),
                            autocommit=True, row_factory=dict_row)
    institution_id, account_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    stale = (now - timedelta(days=200)).replace(day=1, hour=12, minute=0, second=0)
    stale_month = stale.date().replace(day=1)
    account = _account(institution_id, account_id, "dry")
    partition = f"dry-{uuid4()}"
    repository = PostgresCollectorRepository(
        collector_dsn, transfer_producer_id=f"server-1/{partition}",
        deployment_profile="b",
    )
    adapter = PostgresDataAdapter(repository)
    repository.configure_transfer_sender(
        PostgresTransferProducer(repository, InProcessTransport(adapter)),
    )
    try:
        _reset(admin)
        _seed(admin, institution_id, account_id, account.canonical_external_id)
        context = CollectionContext.create(
            Platform.VK, partition, "retention-v1", stale, stale,
        )
        repository.start_run(context)
        assert repository.begin_account(context, account, stale)
        repository.persist_account_batch(_batch(
            context, account, "wall:-3_100", stale, stale,
            {"views": 9, "reactions": 4, "comments": 2, "shares": 1},
        ))

        def rows() -> int:
            return admin.execute(
                """SELECT count(*) AS count FROM ingest.publication_metric_snapshot
                    WHERE published_month=%s""",
                (stale_month,),
            ).fetchone()["count"]

        before = rows()
        assert before > 0
        dry = WorkingSetRetention(repository, RetentionPolicy(
            mode="dry-run", track_post_for_hours=TRACK_HOURS, months_per_run=12,
        )).run()
        assert dry.dry_run is True
        assert stale_month in dry.released_months
        assert rows() == before

        wet = WorkingSetRetention(repository, RetentionPolicy(
            mode="on", track_post_for_hours=TRACK_HOURS, months_per_run=12,
        )).run()
        # The rehearsal named exactly what the real run released.
        assert dry.released_months == wet.released_months
        assert rows() == 0
    finally:
        repository.close()
        admin.close()


def test_profile_b_leaves_the_read_projection_and_cache_queue_alone() -> None:
    """Server 1 in profile B serves nobody, so it maintains neither."""
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    collector_dsn = _dsn("MRANKED_TEST_POSTGRES_DSN")
    admin = psycopg.connect(_dsn("MRANKED_TEST_POSTGRES_ADMIN_DSN"),
                            autocommit=True, row_factory=dict_row)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    results = {}
    try:
        for profile in ("a", "b"):
            institution_id, account_id = uuid4(), uuid4()
            account = _account(institution_id, account_id, f"profile{profile}")
            partition = f"profile-{profile}-{uuid4()}"
            repository = PostgresCollectorRepository(
                collector_dsn, transfer_producer_id=f"server-1/{partition}",
                deployment_profile=profile,
            )
            try:
                _seed(admin, institution_id, account_id,
                      account.canonical_external_id)
                context = CollectionContext.create(
                    Platform.VK, partition, "retention-v1", now, now,
                )
                repository.start_run(context)
                assert repository.begin_account(context, account, now)
                result = repository.persist_account_batch(_batch(
                    context, account, f"wall:-4_{profile}", now, now,
                    {"views": 6, "reactions": 2, "comments": 1, "shares": 0},
                ))
                assert result.revision_id is not None
                assert result.snapshot_count == 1
                results[profile] = {
                    "latest": admin.execute(
                        """SELECT count(*) AS count FROM analytics.publication_latest
                            WHERE platform_account_id=%s""",
                        (account_id,),
                    ).fetchone()["count"],
                    "cache_events": admin.execute(
                        """SELECT count(*) AS count FROM ops_and_admin.outbox_event
                            WHERE dataset_revision_id=%s""",
                        (result.revision_id,),
                    ).fetchone()["count"],
                }
            finally:
                repository.close()
        # Profile A keeps behaving exactly as before.
        assert results["a"]["latest"] == 1
        assert results["a"]["cache_events"] == 2
        # Profile B writes the batch atomically but maintains neither the read
        # projection nor the invalidation queue.
        assert results["b"]["latest"] == 0
        assert results["b"]["cache_events"] == 0
    finally:
        admin.close()


def test_retention_refuses_to_run_in_profile_a_against_a_real_repository() -> None:
    collector_dsn = _dsn("MRANKED_TEST_POSTGRES_DSN")
    repository = PostgresCollectorRepository(collector_dsn, deployment_profile="a")
    try:
        with pytest.raises(RetentionRefused):
            WorkingSetRetention(repository, RetentionPolicy(mode="on"))
    finally:
        repository.close()


def test_an_empty_ledger_proves_nothing_and_releases_nothing() -> None:
    """Absence of objection is not proof of delivery.

    A freshly provisioned Server 1 has an empty outbox, exactly like one whose
    batches were all acknowledged. Releasing a month on that basis would delete
    observations Server 2 has never seen.
    """
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    collector_dsn = _dsn("MRANKED_TEST_POSTGRES_DSN")
    admin = psycopg.connect(_dsn("MRANKED_TEST_POSTGRES_ADMIN_DSN"),
                            autocommit=True, row_factory=dict_row)
    institution_id, account_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    stale = (now - timedelta(days=200)).replace(day=1, hour=12, minute=0, second=0)
    stale_month = stale.date().replace(day=1)
    account = _account(institution_id, account_id, "noledger")
    partition = f"noledger-{uuid4()}"
    # No transfer producer at all: nothing was ever shipped from this host.
    repository = PostgresCollectorRepository(
        collector_dsn, deployment_profile="b",
    )
    try:
        _reset(admin)
        _seed(admin, institution_id, account_id, account.canonical_external_id)
        context = CollectionContext.create(
            Platform.VK, partition, "retention-v1", stale, stale,
        )
        repository.start_run(context)
        assert repository.begin_account(context, account, stale)
        repository.persist_account_batch(_batch(
            context, account, "wall:-5_100", stale, stale,
            {"views": 3, "reactions": 1, "comments": 0, "shares": None},
        ))
        assert admin.execute(
            "SELECT count(*) AS count FROM ops_and_admin.transfer_outbox",
        ).fetchone()["count"] == 0

        outcome = WorkingSetRetention(repository, RetentionPolicy(
            mode="on", track_post_for_hours=TRACK_HOURS, months_per_run=12,
        )).run()
        assert stale_month not in outcome.released_months
        assert stale_month in outcome.deferred_months
        assert admin.execute(
            """SELECT count(*) AS count FROM ingest.publication_metric_snapshot
                WHERE published_month=%s""",
            (stale_month,),
        ).fetchone()["count"] > 0
    finally:
        repository.close()
        admin.close()
