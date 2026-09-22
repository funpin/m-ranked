"""Two producers, one bucket: what survives and what is merely counted."""
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


def _dsn(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        pytest.skip(f"{name} is not configured")
    return value


def _seed(admin, institution_id, account_id, canonical_external_id) -> None:
    admin.execute(
        "INSERT INTO catalog.institution(id,canonical_name) VALUES (%s,%s)",
        (institution_id, f"merge {institution_id}"),
    )
    admin.execute(
        """INSERT INTO catalog.platform_account(
               id,institution_id,platform,canonical_external_id,access_mode
           ) VALUES (%s,%s,'vk',%s,'official_api')""",
        (account_id, institution_id, canonical_external_id),
    )


def _batch(context, account, external_id, published_at, observed_at, metrics, source):
    raw = RawCollectionBatch(
        account, None,
        (RawPublication(
            external_id, published_at, observed_at, observed_at, observed_at,
            "post", metrics, source,
            history_completeness=HistoryCompleteness.COMPLETE,
        ),),
        "merge-integration", "1",
    )
    return CanonicalNormalizer().normalize(raw, context)


def test_a_second_producer_in_the_same_bucket_becomes_a_recorded_correction() -> None:
    """What two hosts observing one account a moment apart actually produce.

    ADR-013 proposed discarding the loser. The store already does better:
    the later observation lands as a correction that supersedes the earlier
    one, both rows survive with their lineage, and nothing is thrown away.
    Discarding would have lost an observation the schema is happy to keep.
    """
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    collector_dsn = _dsn("MRANKED_TEST_POSTGRES_DSN")
    admin = psycopg.connect(_dsn("MRANKED_TEST_POSTGRES_ADMIN_DSN"),
                            autocommit=True, row_factory=dict_row)
    institution_id, account_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    published = now - timedelta(minutes=3)
    partition = f"merge-{uuid4()}"
    account = AccountRef(
        account_id, institution_id, Platform.VK,
        f"merge_{account_id.hex}", "official_api",
    )
    context = CollectionContext.create(
        Platform.VK, partition, "merge-v1", now, now,
    )
    # Same observation instant, so both land in the same sampling bucket, but
    # different values: this is exactly what two hosts observing one account a
    # moment apart produce.
    first = _batch(context, account, "wall:-9_1", published, now,
                   {"views": 10, "reactions": 2, "comments": 1, "shares": 0},
                   {"producer": "server-1"})
    second = _batch(context, account, "wall:-9_1", published, now,
                    {"views": 11, "reactions": 2, "comments": 1, "shares": 0},
                    {"producer": "server-2"})
    assert first.publications[0].snapshot.sampling_bucket == \
        second.publications[0].snapshot.sampling_bucket
    assert first.publications[0].snapshot.source_fingerprint != \
        second.publications[0].snapshot.source_fingerprint

    repository = PostgresCollectorRepository(collector_dsn)
    try:
        _seed(admin, institution_id, account_id, account.canonical_external_id)
        repository.start_run(context)
        assert repository.begin_account(context, account, now)

        one = repository.persist_account_batch(first)
        assert one.snapshot_count == 1
        assert one.diverged_count == 0

        # The second producer is recorded, not rejected, and it is counted so
        # that systematic disagreement between hosts is visible.
        two = repository.persist_account_batch(second)
        assert two.snapshot_count == 1
        assert two.diverged_count == 1

        rows = admin.execute(
            """SELECT snapshot.views_count, snapshot.correction_sequence,
                      snapshot.correction_reason,
                      snapshot.supersedes_snapshot_id IS NOT NULL AS supersedes
                 FROM ingest.publication_metric_snapshot snapshot
                 JOIN ingest.publication_identity identity
                   ON identity.publication_id=snapshot.publication_id
                WHERE identity.external_id=%s AND NOT snapshot.synthetic
                  AND identity.platform_account_id=%s
                ORDER BY snapshot.correction_sequence""",
            ("wall:-9_1", account_id),
        ).fetchall()
        # Both observations survive, the later one carrying its lineage.
        assert [row["views_count"] for row in rows] == [10, 11]
        assert [row["correction_sequence"] for row in rows] == [0, 1]
        assert rows[1]["correction_reason"] == "provider_payload_changed"
        assert rows[1]["supersedes"] is True
    finally:
        repository.close()
        admin.close()


def test_a_gap_left_by_one_producer_is_filled_by_the_other() -> None:
    """The requirement replication exists for.

    A bucket the first host missed is empty, so the second host's observation
    lands normally. Gap closing needs no special case at all.
    """
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    collector_dsn = _dsn("MRANKED_TEST_POSTGRES_DSN")
    admin = psycopg.connect(_dsn("MRANKED_TEST_POSTGRES_ADMIN_DSN"),
                            autocommit=True, row_factory=dict_row)
    institution_id, account_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    published = now - timedelta(hours=2)
    partition = f"gap-{uuid4()}"
    account = AccountRef(
        account_id, institution_id, Platform.VK,
        f"gap_{account_id.hex}", "official_api",
    )
    repository = PostgresCollectorRepository(collector_dsn)
    try:
        _seed(admin, institution_id, account_id, account.canonical_external_id)
        observed = []
        for index, offset in enumerate((90, 60, 30)):
            moment = now - timedelta(minutes=offset)
            context = CollectionContext.create(
                Platform.VK, partition, "merge-v1", moment, moment,
            )
            repository.start_run(context)
            assert repository.begin_account(context, account, moment)
            # The middle observation stands for the one host-A missed and
            # host-B supplied; nothing marks it as coming from elsewhere.
            result = repository.persist_account_batch(_batch(
                context, account, "wall:-9_2", published, moment,
                {"views": 10 + index, "reactions": 1, "comments": 0, "shares": 0},
                {"producer": "server-2" if offset == 60 else "server-1"},
            ))
            observed.append((result.snapshot_count, result.diverged_count))

        assert observed == [(1, 0), (1, 0), (1, 0)]
        rows = admin.execute(
            """SELECT views_count FROM ingest.publication_metric_snapshot snapshot
                 JOIN ingest.publication_identity identity
                   ON identity.publication_id=snapshot.publication_id
                WHERE identity.external_id=%s AND NOT snapshot.synthetic
                  AND identity.platform_account_id=%s
                ORDER BY snapshot.observed_at""",
            ("wall:-9_2", account_id),
        ).fetchall()
        assert [row["views_count"] for row in rows] == [10, 11, 12]
    finally:
        repository.close()
        admin.close()


def test_an_exact_replay_is_still_a_replay_not_a_divergence() -> None:
    """Redelivering the same batch must not look like producer disagreement."""
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    collector_dsn = _dsn("MRANKED_TEST_POSTGRES_DSN")
    admin = psycopg.connect(_dsn("MRANKED_TEST_POSTGRES_ADMIN_DSN"),
                            autocommit=True, row_factory=dict_row)
    institution_id, account_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    partition = f"replay-{uuid4()}"
    account = AccountRef(
        account_id, institution_id, Platform.VK,
        f"replay_{account_id.hex}", "official_api",
    )
    context = CollectionContext.create(Platform.VK, partition, "merge-v1", now, now)
    batch = _batch(context, account, "wall:-9_3", now - timedelta(minutes=4), now,
                   {"views": 5, "reactions": 1, "comments": 0, "shares": 0},
                   {"producer": "server-1"})
    repository = PostgresCollectorRepository(collector_dsn)
    try:
        _seed(admin, institution_id, account_id, account.canonical_external_id)
        repository.start_run(context)
        assert repository.begin_account(context, account, now)
        assert repository.persist_account_batch(batch).snapshot_count == 1
        again = repository.persist_account_batch(batch)
        assert again.snapshot_count == 0
        assert again.diverged_count == 0
    finally:
        repository.close()
        admin.close()
