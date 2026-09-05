from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.public_web import PublicChannel
from collector_target.adapters import telegram_public_batch
from collector_target.model import (
    AccountRef,
    CollectionContext,
    DeletionProbeOutcome,
    HistoryCompleteness,
    ObservationQuality,
    Platform,
    RawAccountObservation,
    RawCollectionBatch,
    RawDeletionProbe,
    RawPublication,
)
from collector_target.normalize import CanonicalNormalizer
from collector_target.repository import PostgresCollectorRepository


def _dsn(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        pytest.skip(f"{name} is not configured")
    return value


def test_real_postgres_telegram_public_baseline_is_idempotent_and_v5_eligible() -> None:
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    collector_dsn = _dsn("MRANKED_TEST_POSTGRES_DSN")
    admin_dsn = os.getenv(
        "MRANKED_TEST_POSTGRES_ADMIN_DSN", collector_dsn,
    ).strip()
    institution_id = uuid4()
    account_id = uuid4()
    partition = f"telegram-public-baseline-{uuid4()}"
    now = datetime.now(timezone.utc).replace(microsecond=0)
    public_observed = now - timedelta(minutes=20)
    public_published = public_observed - timedelta(minutes=4)
    forced_observed = now - timedelta(minutes=15)
    forced_published = forced_observed - timedelta(minutes=2)
    contradictory_observed = now - timedelta(minutes=5)
    contexts = (
        CollectionContext.create(
            Platform.TELEGRAM,
            partition,
            "public-baseline-integration-v1",
            public_observed,
            public_observed,
        ),
        CollectionContext.create(
            Platform.TELEGRAM,
            partition,
            "public-baseline-integration-v1",
            forced_observed,
            forced_observed,
        ),
        CollectionContext.create(
            Platform.TELEGRAM,
            partition,
            "public-baseline-integration-v1",
            contradictory_observed,
            contradictory_observed,
        ),
    )
    public_context, forced_context, contradictory_context = contexts
    account = AccountRef(
        account_id,
        institution_id,
        Platform.TELEGRAM,
        f"public_{account_id.hex}",
        "public_web",
        current_username=f"public_{account_id.hex[:16]}",
    )

    def connect(dsn: str):
        return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

    admin = connect(admin_dsn)
    try:
        v5_installed = admin.execute(
            """SELECT EXISTS (
                       SELECT 1 FROM flyway.flyway_schema_history
                        WHERE version='5' AND success
                   ) AS installed""",
        ).fetchone()["installed"]
        if not v5_installed:
            pytest.skip("Flyway V5 is required for target-public activity coverage")

        admin.execute(
            """INSERT INTO catalog.institution(id, canonical_name)
               VALUES (%s,%s)""",
            (institution_id, f"public baseline integration {institution_id}"),
        )
        admin.execute(
            """INSERT INTO catalog.platform_account(
                   id, institution_id, platform, canonical_external_id,
                   current_username, access_mode
               ) VALUES (%s,%s,'telegram',%s,%s,'public_web')""",
            (
                account_id,
                institution_id,
                account.canonical_external_id,
                account.current_username,
            ),
        )

        repository = PostgresCollectorRepository(collector_dsn)
        public_raw = telegram_public_batch(
            account=account,
            channel=PublicChannel(
                "Public integration channel",
                100,
                "100",
                [SimpleNamespace(
                    message_id=42,
                    published_at=public_published,
                    post_type="text",
                    views_count=370,
                    reactions=SimpleNamespace(
                        total=173,
                        raw="173",
                        reactions={"like": 173},
                    ),
                    is_repost=False,
                )],
            ),
            observed_at=public_observed,
            collected_at=public_observed,
            username=account.current_username or "public",
            comments={42: 12},
            complete_history_max_first_age_seconds=360,
        )
        public_batch = CanonicalNormalizer().normalize(public_raw, public_context)
        repository.start_run(public_context)
        assert repository.begin_account(
            public_context, account, public_context.started_at,
        )
        first = repository.persist_account_batch(public_batch)
        retry = repository.persist_account_batch(public_batch)
        assert first.discovered_count == 1
        assert first.snapshot_count == 2
        assert first.revision_id is not None
        assert retry.discovered_count == 0
        assert retry.snapshot_count == 0
        assert retry.revision_id is None
        assert repository.finish_run(
            public_context, public_context.started_at,
        ).status.value == "succeeded"

        public_id = public_batch.publications[0].id
        snapshots = admin.execute(
            """SELECT sampling_bucket, age_seconds, synthetic,
                      views_count, reactions_count, comments_count, shares_count
                 FROM ingest.publication_metric_snapshot
                WHERE publication_id=%s
                ORDER BY sampling_bucket""",
            (public_id,),
        ).fetchall()
        assert len(snapshots) == 2
        assert snapshots[0] == {
            "sampling_bucket": -1,
            "age_seconds": 0,
            "synthetic": True,
            "views_count": 0,
            "reactions_count": 0,
            "comments_count": 0,
            "shares_count": None,
        }
        assert snapshots[1]["sampling_bucket"] >= 0
        assert snapshots[1]["age_seconds"] == 240
        assert snapshots[1]["synthetic"] is False
        assert snapshots[1]["views_count"] == 370
        publication_state = admin.execute(
            """SELECT history_completeness::text AS history_completeness,
                      synthetic_baseline_allowed
                 FROM ingest.publication WHERE id=%s""",
            (public_id,),
        ).fetchone()
        assert publication_state == {
            "history_completeness": "complete",
            "synthetic_baseline_allowed": True,
        }
        assert admin.execute(
            """SELECT count(*) AS count
                 FROM ingest.deletion_observation
                WHERE collection_run_id=%s AND publication_id=%s""",
            (public_context.run_id, public_id),
        ).fetchone()["count"] == 1
        assert admin.execute(
            """SELECT count(*) AS count
                 FROM analytics.dataset_revision WHERE source_run_id=%s""",
            (public_context.run_id,),
        ).fetchone()["count"] == 1
        public_event = admin.execute(
            """SELECT event.event_type, event.published_at
                 FROM ops_and_admin.outbox_event AS event
                WHERE event.dataset_revision_id=%s""",
            (first.revision_id,),
        ).fetchone()
        assert public_event == {
            "event_type": "projection.rebuild.requested",
            "published_at": None,
        }

        # V5 deliberately excludes the synthetic row from endpoints, then uses
        # the persisted eligibility flag to count a timely public publication
        # from zero. Roll the global projection replacement back after proving it.
        with admin.transaction(force_rollback=True):
            published = admin.execute(
                "SELECT analytics.rebuild_core_projections(%s) AS result",
                (first.revision_id,),
            ).fetchone()["result"]
            assert published["institution_period_semantics_version"] == 2
            period = admin.execute(
                """SELECT value, sample_size
                     FROM analytics.institution_period_metrics
                    WHERE institution_id=%s
                      AND platform='telegram'
                      AND period_key='1d'
                      AND metric_key='views'
                      AND aggregation='sum'""",
                (institution_id,),
            ).fetchone()
            assert period["value"] == 370
            assert period["sample_size"] == 1

        forced_raw = RawCollectionBatch(
            account,
            None,
            (RawPublication(
                "m:99",
                forced_published,
                forced_observed,
                forced_observed,
                forced_observed,
                "text",
                {"views": 5, "reactions": 1, "comments": 0, "shares": None},
                {"gateway": "forced-incomplete-integration"},
                public_url=f"https://t.me/{account.current_username}/99",
                history_completeness=HistoryCompleteness.FORCED_INCOMPLETE,
            ),),
            "forced-incomplete-integration",
            "1",
        )
        repository.start_run(forced_context)
        assert repository.begin_account(
            forced_context, account, forced_context.started_at,
        )
        forced = repository.persist_account_batch(
            CanonicalNormalizer().normalize(forced_raw, forced_context),
        )
        assert forced.revision_id is not None
        assert repository.finish_run(
            forced_context, forced_context.started_at,
        ).status.value == "succeeded"

        contradictory_raw = telegram_public_batch(
            account=account,
            channel=PublicChannel(
                "Public integration channel",
                100,
                "100",
                [SimpleNamespace(
                    message_id=99,
                    published_at=forced_published,
                    post_type="text",
                    views_count=25,
                    reactions=SimpleNamespace(
                        total=3, raw="3", reactions={"like": 3},
                    ),
                    is_repost=False,
                )],
            ),
            observed_at=contradictory_observed,
            collected_at=contradictory_observed,
            username=account.current_username or "public",
            complete_history_max_first_age_seconds=3600,
        )
        contradictory_raw = replace(contradictory_raw, account_observation=None)
        contradictory_batch = CanonicalNormalizer().normalize(
            contradictory_raw, contradictory_context,
        )
        assert any(
            item.synthetic_baseline_allowed
            for item in contradictory_batch.publications
        )
        repository.start_run(contradictory_context)
        assert repository.begin_account(
            contradictory_context, account, contradictory_context.started_at,
        )
        contradictory = repository.persist_account_batch(contradictory_batch)
        contradictory_retry = repository.persist_account_batch(contradictory_batch)
        assert contradictory.revision_id is not None
        assert contradictory_retry.revision_id is None
        assert repository.finish_run(
            contradictory_context, contradictory_context.started_at,
        ).status.value == "succeeded"
        forced_id = contradictory_batch.publications[0].id
        merged_state = admin.execute(
            """SELECT history_completeness::text AS history_completeness,
                      synthetic_baseline_allowed
                 FROM ingest.publication WHERE id=%s""",
            (forced_id,),
        ).fetchone()
        assert merged_state == {
            "history_completeness": "forced_incomplete",
            "synthetic_baseline_allowed": False,
        }
        assert admin.execute(
            """SELECT count(*) AS count
                 FROM ingest.deletion_observation
                WHERE collection_run_id=%s AND publication_id=%s""",
            (contradictory_context.run_id, forced_id),
        ).fetchone()["count"] == 1
    finally:
        run_ids = [item.run_id for item in contexts]
        try:
            admin.execute(
                """DELETE FROM ops_and_admin.outbox_event
                    WHERE dataset_revision_id IN (
                        SELECT id FROM analytics.dataset_revision
                         WHERE source_run_id=ANY(%s)
                    )""",
                (run_ids,),
            )
            admin.execute(
                """DELETE FROM ingest.reaction_breakdown AS reaction
                     USING ingest.publication_metric_snapshot AS snapshot
                     WHERE reaction.snapshot_published_month=snapshot.published_month
                       AND reaction.snapshot_id=snapshot.id
                       AND snapshot.collection_run_id=ANY(%s)""",
                (run_ids,),
            )
            admin.execute(
                "DELETE FROM ingest.raw_payload WHERE collection_run_id=ANY(%s)",
                (run_ids,),
            )
            admin.execute(
                "DELETE FROM ingest.deletion_observation WHERE collection_run_id=ANY(%s)",
                (run_ids,),
            )
            admin.execute(
                """DELETE FROM ingest.publication_metric_snapshot
                    WHERE collection_run_id=ANY(%s)""",
                (run_ids,),
            )
            admin.execute(
                """DELETE FROM ingest.account_metric_snapshot
                    WHERE platform_account_id=%s""",
                (account_id,),
            )
            admin.execute(
                "DELETE FROM ingest.publication_identity WHERE platform_account_id=%s",
                (account_id,),
            )
            admin.execute(
                "DELETE FROM ingest.publication WHERE primary_account_id=%s",
                (account_id,),
            )
            admin.execute(
                """DELETE FROM catalog.account_identity_history
                    WHERE platform_account_id=%s""",
                (account_id,),
            )
            admin.execute(
                """DELETE FROM catalog.account_external_identity
                    WHERE platform_account_id=%s""",
                (account_id,),
            )
            admin.execute(
                """DELETE FROM analytics.dataset_revision
                    WHERE source_run_id=ANY(%s)""",
                (run_ids,),
            )
            admin.execute(
                """DELETE FROM ingest.collection_account_result
                    WHERE collection_run_id=ANY(%s)""",
                (run_ids,),
            )
            admin.execute(
                "DELETE FROM ingest.collection_run WHERE id=ANY(%s)",
                (run_ids,),
            )
            admin.execute(
                """DELETE FROM ops_and_admin.operational_checkpoint
                    WHERE scope_id IN (%s,%s)""",
                (account_id, public_context.partition_scope_id),
            )
            admin.execute(
                "DELETE FROM catalog.platform_account WHERE id=%s", (account_id,),
            )
            admin.execute(
                "DELETE FROM catalog.institution WHERE id=%s", (institution_id,),
            )
        finally:
            admin.close()


def test_real_postgres_account_transaction_is_idempotent_and_atomic() -> None:
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    collector_dsn = _dsn("MRANKED_TEST_POSTGRES_DSN")
    admin_dsn = os.getenv(
        "MRANKED_TEST_POSTGRES_ADMIN_DSN", collector_dsn,
    ).strip()
    institution_id = uuid4()
    account_id = uuid4()
    partition = f"integration-{uuid4()}"
    scheduled = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)
    context = CollectionContext.create(
        Platform.TELEGRAM, partition, "integration-v1", scheduled, scheduled,
    )
    changed_context = CollectionContext.create(
        Platform.TELEGRAM,
        partition,
        "integration-v1",
        scheduled + timedelta(minutes=10),
        scheduled + timedelta(minutes=10),
    )
    failed_context = CollectionContext.create(
        Platform.TELEGRAM,
        partition,
        "integration-v1",
        scheduled + timedelta(minutes=15),
        scheduled + timedelta(minutes=15),
    )
    missing_contexts = tuple(
        CollectionContext.create(
            Platform.TELEGRAM,
            partition,
            "integration-v1",
            scheduled + timedelta(minutes=minutes),
            scheduled + timedelta(minutes=minutes),
        )
        for minutes in (20, 25, 30)
    )
    recovery_context = CollectionContext.create(
        Platform.TELEGRAM,
        partition,
        "integration-v1",
        scheduled + timedelta(minutes=35),
        scheduled + timedelta(minutes=35),
    )
    account = AccountRef(
        account_id,
        institution_id,
        Platform.TELEGRAM,
        f"integration_{account_id.hex}",
        "mtproto",
        current_username=f"integration_{account_id.hex[:16]}",
    )

    def connect(dsn: str):
        return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

    admin = connect(admin_dsn)
    try:
        admin.execute(
            """INSERT INTO catalog.institution(id, canonical_name)
               VALUES (%s,%s)""",
            (institution_id, f"collector integration {institution_id}"),
        )
        admin.execute(
            """INSERT INTO catalog.platform_account(
                   id, institution_id, platform, canonical_external_id,
                   current_username, access_mode
               ) VALUES (%s,%s,'telegram',%s,%s,'mtproto')""",
            (
                account_id,
                institution_id,
                account.canonical_external_id,
                account.current_username,
            ),
        )

        repository = PostgresCollectorRepository(collector_dsn)
        repository.start_run(context)
        assert repository.begin_account(context, account, scheduled)
        raw = RawCollectionBatch(
            account,
            RawAccountObservation(
                scheduled,
                scheduled,
                0,
                "0",
                ObservationQuality.EXACT,
                username=account.current_username,
                title="Integration channel",
                url="https://t.me/integration",
                native_external_id="424242",
                source={"gateway": "integration", "api_key": "must-redact"},
            ),
            (
                RawPublication(
                    "m:1",
                    scheduled - timedelta(minutes=1),
                    scheduled,
                    scheduled,
                    scheduled,
                    "text",
                    {"views": 0, "reactions": 1, "comments": None, "shares": None},
                    {"gateway": "integration", "authorization": "Bearer must-redact"},
                    public_url="https://t.me/integration/1",
                    reaction_breakdown={"like": 1},
                    history_completeness=HistoryCompleteness.COMPLETE,
                ),
            ),
            "integration",
            "1",
            "1",
        )
        batch = CanonicalNormalizer().normalize(raw, context)
        first = repository.persist_account_batch(batch)
        second = repository.persist_account_batch(batch)
        assert first.snapshot_count == 1
        assert first.revision_id is not None
        assert second.snapshot_count == 0
        assert second.revision_id is None

        run_times = admin.execute(
            """SELECT scheduled_at, started_at
                 FROM ingest.collection_run WHERE id=%s""",
            (context.run_id,),
        ).fetchone()
        assert run_times["scheduled_at"] == scheduled
        assert run_times["started_at"] == scheduled

        assert admin.execute(
            """SELECT count(*) AS count
                 FROM ingest.publication_metric_snapshot
                WHERE collection_run_id=%s""",
            (context.run_id,),
        ).fetchone()["count"] == 1
        assert admin.execute(
            """SELECT count(*) AS count
                 FROM analytics.dataset_revision
                WHERE source_run_id=%s""",
            (context.run_id,),
        ).fetchone()["count"] == 1
        assert admin.execute(
            """SELECT array_agg(event.event_type ORDER BY event.id) AS event_types
                 FROM ops_and_admin.outbox_event AS event
                 JOIN analytics.dataset_revision AS revision
                   ON revision.id=event.dataset_revision_id
                WHERE revision.source_run_id=%s""",
            (context.run_id,),
        ).fetchone()["event_types"] == ["projection.rebuild.requested"]
        lineage = admin.execute(
            """SELECT external_ref, payload
                 FROM ingest.raw_payload
                WHERE collection_run_id=%s
                ORDER BY owner_type""",
            (context.run_id,),
        ).fetchall()
        assert len(lineage) == 2
        assert all(row["payload"] is None for row in lineage)
        assert all(row["external_ref"].startswith("sha256:") for row in lineage)
        assert admin.execute(
            """SELECT count(*) AS count
                 FROM catalog.account_identity_history
                WHERE platform_account_id=%s AND valid_to IS NULL""",
            (account_id,),
        ).fetchone()["count"] == 1
        assert admin.execute(
            """SELECT count(*) AS count
                 FROM catalog.account_external_identity
                WHERE platform_account_id=%s
                  AND identity_namespace='telegram:native_id'
                  AND external_id='424242'
                  AND valid_to IS NULL""",
            (account_id,),
        ).fetchone()["count"] == 1
        loaded = {
            item.id: item
            for item in repository.enabled_accounts(Platform.TELEGRAM, "all")
        }[account_id]
        assert loaded.native_external_id == "424242"
        assert loaded.current_title == "Integration channel"
        collected_times = admin.execute(
            """SELECT observed_at, collected_at
                 FROM ingest.publication_metric_snapshot
                WHERE collection_run_id=%s""",
            (context.run_id,),
        ).fetchone()
        assert collected_times["observed_at"] == scheduled
        assert collected_times["collected_at"] == scheduled
        assert repository.resumable_scheduled_at(
            Platform.TELEGRAM, partition, "integration-v1",
        ) == scheduled
        assert repository.finish_run(context, scheduled).status.value == "succeeded"
        assert repository.resumable_scheduled_at(
            Platform.TELEGRAM, partition, "integration-v1",
        ) is None

        repository.start_run(changed_context)
        assert repository.begin_account(
            changed_context, account, changed_context.started_at,
        )
        changed_raw = replace(
            raw,
            account_observation=replace(
                raw.account_observation,
                observed_at=changed_context.started_at,
                collected_at=changed_context.started_at,
                username="renamed_channel",
                title="Renamed integration channel",
                url="https://t.me/renamed_channel",
                native_external_id="525252",
            ),
            publications=(),
            cursor="identity-change",
        )
        changed = repository.persist_account_batch(
            CanonicalNormalizer().normalize(changed_raw, changed_context),
        )
        assert changed.revision_id is not None
        assert repository.finish_run(
            changed_context, changed_context.started_at,
        ).status.value == "succeeded"
        history = admin.execute(
            """SELECT username, valid_from, valid_to
                 FROM catalog.account_identity_history
                WHERE platform_account_id=%s ORDER BY valid_from""",
            (account_id,),
        ).fetchall()
        assert len(history) == 2
        assert history[0]["valid_to"] == changed_context.started_at
        assert history[1]["username"] == "renamed_channel"
        assert history[1]["valid_to"] is None
        native_history = admin.execute(
            """SELECT external_id, valid_from, valid_to
                 FROM catalog.account_external_identity
                WHERE platform_account_id=%s
                  AND identity_namespace='telegram:native_id'
                ORDER BY valid_from""",
            (account_id,),
        ).fetchall()
        assert len(native_history) == 2
        assert native_history[0]["valid_to"] == changed_context.started_at
        assert native_history[1]["external_id"] == "525252"
        assert native_history[1]["valid_to"] is None
        loaded_after_change = {
            item.id: item
            for item in repository.enabled_accounts(Platform.TELEGRAM, "all")
        }[account_id]
        assert loaded_after_change.current_username == "renamed_channel"
        assert loaded_after_change.native_external_id == "525252"

        publication_id = batch.publications[0].id

        def persist_probe(
            probe_context: CollectionContext,
            outcome: DeletionProbeOutcome,
            reason: str,
        ) -> None:
            repository.start_run(probe_context)
            assert repository.begin_account(
                probe_context, account, probe_context.started_at,
            )
            probe_raw = replace(
                raw,
                account_observation=None,
                publications=(),
                cursor=None,
                deletion_probes=(RawDeletionProbe(
                    publication_id,
                    probe_context.started_at,
                    outcome,
                    reason,
                    2,
                ),),
                refresh_cursor=str(publication_id),
            )
            persisted = repository.persist_account_batch(
                CanonicalNormalizer().normalize(probe_raw, probe_context),
            )
            assert persisted.revision_id is not None
            assert repository.finish_run(
                probe_context, probe_context.started_at,
            ).status.value == "succeeded"

        persist_probe(
            missing_contexts[0],
            DeletionProbeOutcome.MISSING,
            "telegram_mtproto_empty_get_messages",
        )
        first_missing = admin.execute(
            """SELECT outcome::text AS outcome, consecutive_missing
                 FROM ingest.deletion_observation
                WHERE publication_id=%s
                ORDER BY observed_at DESC, id DESC LIMIT 1""",
            (publication_id,),
        ).fetchone()
        assert first_missing == {"outcome": "missing", "consecutive_missing": 1}
        assert admin.execute(
            "SELECT deleted_at FROM ingest.publication WHERE id=%s",
            (publication_id,),
        ).fetchone()["deleted_at"] is None

        persist_probe(
            missing_contexts[1],
            DeletionProbeOutcome.TRANSIENT_ERROR,
            "telegram_mtproto_auth_error",
        )
        transient = admin.execute(
            """SELECT outcome::text AS outcome, consecutive_missing
                 FROM ingest.deletion_observation
                WHERE publication_id=%s
                ORDER BY observed_at DESC, id DESC LIMIT 1""",
            (publication_id,),
        ).fetchone()
        assert transient == {
            "outcome": "transient_error",
            "consecutive_missing": 1,
        }
        assert admin.execute(
            "SELECT deleted_at FROM ingest.publication WHERE id=%s",
            (publication_id,),
        ).fetchone()["deleted_at"] is None

        persist_probe(
            missing_contexts[2],
            DeletionProbeOutcome.MISSING,
            "telegram_mtproto_empty_get_messages",
        )
        confirmed = admin.execute(
            """SELECT outcome::text AS outcome, consecutive_missing
                 FROM ingest.deletion_observation
                WHERE publication_id=%s
                ORDER BY observed_at DESC, id DESC LIMIT 1""",
            (publication_id,),
        ).fetchone()
        assert confirmed == {
            "outcome": "confirmed_deleted",
            "consecutive_missing": 2,
        }
        assert admin.execute(
            "SELECT deleted_at FROM ingest.publication WHERE id=%s",
            (publication_id,),
        ).fetchone()["deleted_at"] == missing_contexts[2].started_at
        assert repository.tracked_publications(
            account,
            published_after=scheduled - timedelta(days=1),
            limit=10,
        ) == ()

        repository.start_run(recovery_context)
        assert repository.begin_account(
            recovery_context, account, recovery_context.started_at,
        )
        recovery_raw = replace(
            raw,
            account_observation=None,
            publications=(replace(
                raw.publications[0],
                observed_at=recovery_context.started_at,
                collected_at=recovery_context.started_at,
            ),),
            cursor=None,
            deletion_probes=(),
            refresh_cursor=str(publication_id),
        )
        recovery = repository.persist_account_batch(
            CanonicalNormalizer().normalize(recovery_raw, recovery_context),
        )
        assert recovery.snapshot_count == 1
        assert repository.finish_run(
            recovery_context, recovery_context.started_at,
        ).status.value == "succeeded"
        recovered = admin.execute(
            """SELECT observation.outcome::text AS outcome,
                      observation.consecutive_missing,
                      publication.deleted_at
                 FROM ingest.deletion_observation AS observation
                 JOIN ingest.publication AS publication
                   ON publication.id=observation.publication_id
                WHERE observation.publication_id=%s
                ORDER BY observation.observed_at DESC, observation.id DESC LIMIT 1""",
            (publication_id,),
        ).fetchone()
        assert recovered == {
            "outcome": "present",
            "consecutive_missing": 0,
            "deleted_at": None,
        }
        tracked = repository.tracked_publications(
            account,
            published_after=scheduled - timedelta(days=1),
            limit=10,
        )
        assert [item.id for item in tracked] == [publication_id]

        repository.start_run(failed_context)
        assert repository.begin_account(
            failed_context, account, failed_context.started_at,
        )
        failed_raw = replace(
            raw,
            account_observation=replace(
                raw.account_observation,
                observed_at=failed_context.started_at,
                collected_at=failed_context.started_at,
            ),
            publications=(replace(
                raw.publications[0],
                external_id="m:rollback",
                published_at=failed_context.started_at - timedelta(minutes=1),
                discovered_at=failed_context.started_at,
                observed_at=failed_context.started_at,
                collected_at=failed_context.started_at,
                public_url="https://t.me/integration/rollback",
            ),),
            cursor="rollback",
        )
        failed_batch = CanonicalNormalizer().normalize(failed_raw, failed_context)
        invalid_snapshot = replace(
            failed_batch.publications[0].snapshot,
            reaction_breakdown={"invalid": -1},
        )
        failed_batch = replace(
            failed_batch,
            publications=(replace(
                failed_batch.publications[0], snapshot=invalid_snapshot,
            ),),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            repository.persist_account_batch(failed_batch)
        assert admin.execute(
            """SELECT count(*) AS count
                 FROM ingest.publication_identity
                WHERE platform_account_id=%s AND external_id='m:rollback'""",
            (account_id,),
        ).fetchone()["count"] == 0
        assert admin.execute(
            """SELECT count(*) AS count
                 FROM ingest.publication_metric_snapshot
                WHERE collection_run_id=%s""",
            (failed_context.run_id,),
        ).fetchone()["count"] == 0
        assert admin.execute(
            """SELECT count(*) AS count
                 FROM analytics.dataset_revision
                WHERE source_run_id=%s""",
            (failed_context.run_id,),
        ).fetchone()["count"] == 0
        current_identity = admin.execute(
            """SELECT username
                 FROM catalog.account_identity_history
                WHERE platform_account_id=%s AND valid_to IS NULL""",
            (account_id,),
        ).fetchone()
        assert current_identity["username"] == "renamed_channel"
        current_native = admin.execute(
            """SELECT external_id
                 FROM catalog.account_external_identity
                WHERE platform_account_id=%s
                  AND identity_namespace='telegram:native_id'
                  AND valid_to IS NULL""",
            (account_id,),
        ).fetchone()
        assert current_native["external_id"] == "525252"
    finally:
        run_ids = (
            context.run_id,
            changed_context.run_id,
            failed_context.run_id,
            *(item.run_id for item in missing_contexts),
            recovery_context.run_id,
        )
        try:
            admin.execute(
                """DELETE FROM ops_and_admin.outbox_event
                    WHERE dataset_revision_id IN (
                        SELECT id FROM analytics.dataset_revision
                         WHERE source_run_id=ANY(%s)
                    )""",
                (list(run_ids),),
            )
            admin.execute(
                """DELETE FROM ingest.reaction_breakdown AS reaction
                     USING ingest.publication_metric_snapshot AS snapshot
                     WHERE reaction.snapshot_published_month=snapshot.published_month
                       AND reaction.snapshot_id=snapshot.id
                       AND snapshot.collection_run_id=ANY(%s)""",
                (list(run_ids),),
            )
            admin.execute(
                "DELETE FROM ingest.raw_payload WHERE collection_run_id=ANY(%s)",
                (list(run_ids),),
            )
            admin.execute(
                "DELETE FROM ingest.deletion_observation WHERE collection_run_id=ANY(%s)",
                (list(run_ids),),
            )
            admin.execute(
                """DELETE FROM ingest.publication_metric_snapshot
                    WHERE collection_run_id=ANY(%s)""",
                (list(run_ids),),
            )
            admin.execute(
                "DELETE FROM ingest.account_metric_snapshot WHERE platform_account_id=%s",
                (account_id,),
            )
            admin.execute(
                "DELETE FROM ingest.publication_identity WHERE platform_account_id=%s",
                (account_id,),
            )
            admin.execute(
                "DELETE FROM ingest.publication WHERE primary_account_id=%s",
                (account_id,),
            )
            admin.execute(
                "DELETE FROM catalog.account_identity_history WHERE platform_account_id=%s",
                (account_id,),
            )
            admin.execute(
                "DELETE FROM catalog.account_external_identity WHERE platform_account_id=%s",
                (account_id,),
            )
            admin.execute(
                "DELETE FROM analytics.dataset_revision WHERE source_run_id=ANY(%s)",
                (list(run_ids),),
            )
            admin.execute(
                "DELETE FROM ingest.collection_account_result WHERE collection_run_id=ANY(%s)",
                (list(run_ids),),
            )
            admin.execute(
                "DELETE FROM ingest.collection_run WHERE id=ANY(%s)",
                (list(run_ids),),
            )
            admin.execute(
                """DELETE FROM ops_and_admin.operational_checkpoint
                    WHERE scope_id IN (%s,%s)""",
                (account_id, context.partition_scope_id),
            )
            admin.execute("DELETE FROM catalog.platform_account WHERE id=%s", (account_id,))
            admin.execute("DELETE FROM catalog.institution WHERE id=%s", (institution_id,))
        finally:
            admin.close()
