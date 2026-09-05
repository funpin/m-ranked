from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
import fcntl
import os
from pathlib import Path
import stat
import time
from typing import Any, Iterator, Mapping
from uuid import UUID

from migration.bridge.model import stable_uuid

from .journal import ReverseSyncJournal
from .model import (
    JournalState,
    STATE_VERSION,
    SyncPlan,
    payload_sha256,
    require_nonempty,
    utc_now,
)
from .postgres import PostgresReverseSource
from .sqlite_target import LegacySqliteTarget


class ReverseSyncService:
    """Fail-closed state machine for the bounded rollback compatibility window."""

    def __init__(
        self,
        source: PostgresReverseSource,
        target: LegacySqliteTarget,
        journal: ReverseSyncJournal,
    ) -> None:
        self.source = source
        self.target = target
        self.journal = journal
        target_path = getattr(target, "path", None)
        if target_path is not None:
            normalized_target = Path(os.path.abspath(Path(target_path).expanduser()))
            self._lock_path = normalized_target.with_name(
                f".{normalized_target.name}.reverse-sync.lock"
            )
        else:
            self._lock_path = journal.path.parent / (
                f".reverse-sync-{target.identity()}.lock"
            )

    def preflight(self) -> dict[str, Any]:
        if self.journal.path.is_symlink():
            raise ValueError("reverse-sync journal must not be a symlink")
        postgres = self.source.preflight()
        sqlite = self.target.preflight()
        journal = self.journal.integrity()
        if journal["exists"] and (
            journal["quickCheck"] != "ok"
            or journal["schemaVersion"] != STATE_VERSION
        ):
            raise RuntimeError("reverse-sync journal integrity check failed")
        with self.source.connect() as connection:
            s_final = self.source.s_final(connection)
        state = self.journal.load_state()
        if state is not None:
            self._assert_binding(state, s_final)
        elif self.journal.legacy_target_identity() is not None:
            self._assert_target_binding()
        return {
            "status": "pass",
            "sourceNamespace": self.source.source_namespace,
            "postgres": {
                "database": postgres.get("database", "test-double"),
                "role": postgres.get("role", "test-double"),
                "requiredSelectPrivileges": postgres.get(
                    "requiredSelectPrivileges", True
                ),
                "aliasMappingsUnambiguous": postgres["aliasMappingsUnambiguous"],
                "singlePrimaryIdentity": postgres["singlePrimaryIdentity"],
                "sFinalBatchId": str(s_final["id"]),
                "sFinalSourceSha256": str(s_final["source_sha256"]),
            },
            "legacySqlite": sqlite,
            "journal": journal,
            "state": state.status if state is not None else "uninitialized",
        }

    def start(
        self,
        *,
        rollback_window_hours: int,
        operator: str,
        ticket: str,
    ) -> dict[str, Any]:
        hours = int(rollback_window_hours)
        if hours < 1 or hours > 24 * 31:
            raise ValueError("rollback window must be between 1 and 744 hours")
        operator = require_nonempty(operator, "operator")
        ticket = require_nonempty(ticket, "ticket")
        self.preflight()
        self.journal.initialize()
        with self._operation_lock():
            existing = self.journal.load_state()
            if existing is not None:
                self._assert_start_idempotency(existing, operator, ticket, hours)
                self._assert_target_binding()
                return self._state_result(existing, idempotent=True)
            self.journal.bind_legacy_target(self.target.identity())
            with self.source.drain_lock() as connection:
                s_final = self.source.s_final(connection)
                baseline = tuple(item.id for item in self.source.revisions(connection))
            now = utc_now()
            state = JournalState(
                status="active",
                source_namespace=self.source.source_namespace,
                operator=operator,
                ticket=ticket,
                started_at=now,
                rollback_deadline=now + timedelta(hours=hours),
                s_final_batch_id=UUID(str(s_final["id"])),
                s_final_source_sha256=str(s_final["source_sha256"]),
            )
            self.journal.replace_revisions("baseline_revision", baseline)
            self.journal.replace_revisions("drain_revision", ())
            self.journal.replace_revisions("applied_revision", ())
            self.journal.save_state(state, "started")
        return {
            **self._state_result(state, idempotent=False),
            "baselineRevisionCount": len(baseline),
            "baselineRevisionSetSha256": payload_sha256(baseline),
        }

    def once(self) -> dict[str, Any]:
        with self._operation_lock():
            state = self._required_state("active")
            if utc_now() > state.rollback_deadline:
                raise RuntimeError("rollback compatibility window has expired")
            plan, aliases = self._build_and_reserve(state)
            counts = self.target.apply(plan, aliases)
            self.journal.record_applied(plan.revision_ids, plan.digest)
            current_ids = self._current_revision_ids(state)
            expected_ids = tuple(sorted((*plan.baseline_revision_ids, *plan.revision_ids)))
            return {
                "status": "active",
                "planSha256": plan.digest,
                "revisionCount": len(plan.revision_ids),
                "revisionSetSha256": payload_sha256(plan.revision_ids),
                "counts": counts,
                "caughtUp": current_ids == expected_ids,
            }

    def drain(self, *, operator: str, ticket: str) -> dict[str, Any]:
        operator = require_nonempty(operator, "operator")
        ticket = require_nonempty(ticket, "ticket")
        with self._operation_lock():
            state = self._required_state("active", "drained", "verified")
            self._assert_idempotency(state, operator, ticket)
            with self.source.drain_lock() as connection:
                self._assert_binding(state, self.source.s_final(connection))
                if state.status in {"drained", "verified"}:
                    plan, aliases = self._fixed_plan(connection, state)
                    verification = self.target.verify(plan, aliases)
                    counts = plan.counts()
                else:
                    plan = self._repeatable_plan(connection, state)
                    maximums = self.target.maximum_legacy_ids()
                    aliases = self.source.reserve_publication_aliases(
                        connection,
                        plan.publications,
                        sqlite_maximums={
                            entity_type: int(maximums.get(entity_type, 0))
                            for entity_type in ("posts", "platform_posts")
                        },
                    )
                    plan = self._with_aliases(plan, aliases)
                    plan = self._reserve_snapshot_aliases(plan, maximums)
                    self._record_aliases(aliases)
                    counts = self.target.apply(plan, aliases)
                    verification = None
                durability = self.target.durability_barrier()
                visible_ids = tuple(
                    item.id for item in self.source.revisions(connection)
                )
                expected_ids = tuple(
                    sorted((*plan.baseline_revision_ids, *plan.revision_ids))
                )
                if visible_ids != expected_ids:
                    raise RuntimeError("dataset revision set changed during fixed drain")
                if state.status == "active":
                    self.journal.record_applied(plan.revision_ids, plan.digest)
            self.journal.replace_revisions("drain_revision", plan.revision_ids)
            next_status = "verified" if state.status == "verified" else "drained"
            drained = replace(
                state,
                status=next_status,
                plan_digest=plan.digest,
                drained_at=state.drained_at or utc_now(),
                verified_at=(state.verified_at if next_status == "verified" else None),
                stopped_at=None,
            )
            self.journal.save_state(drained, "drained")
        return {
            "status": drained.status,
            "idempotent": state.status in {"drained", "verified"},
            "fixedRevisionCount": len(plan.revision_ids),
            "fixedRevisionSetSha256": payload_sha256(plan.revision_ids),
            "planSha256": plan.digest,
            "counts": counts,
            "durability": durability,
            "verification": verification,
        }

    def verify(self) -> dict[str, Any]:
        with self._operation_lock():
            state = self._required_state("drained", "verified")
            with self.source.drain_lock() as connection:
                plan, aliases = self._fixed_plan(connection, state)
                verification = self.target.verify(plan, aliases)
                verified = replace(
                    state,
                    status="verified",
                    verified_at=state.verified_at or utc_now(),
                    stopped_at=None,
                )
                self.journal.save_state(verified, "verified")
        return {
            "status": "verified",
            "idempotent": state.status == "verified",
            "fixedRevisionCount": len(plan.revision_ids),
            "fixedRevisionSetSha256": payload_sha256(plan.revision_ids),
            "planSha256": plan.digest,
            "verification": verification,
        }

    def stop(self) -> dict[str, Any]:
        with self._operation_lock():
            state = self._required_state("verified", "stopped")
            if state.status == "stopped":
                return self._state_result(state, idempotent=True)
            with self.source.drain_lock() as connection:
                plan, aliases = self._fixed_plan(connection, state)
                self.target.verify(plan, aliases)
                durability = self.target.durability_barrier()
                stopped = replace(state, status="stopped", stopped_at=utc_now())
                self.journal.save_state(stopped, "stopped")
        return {
            **self._state_result(stopped, idempotent=False),
            "planSha256": plan.digest,
            "durability": durability,
        }

    def status(self) -> dict[str, Any]:
        state = self.journal.load_state()
        if state is None:
            return {"status": "uninitialized"}
        baseline = self.journal.revision_ids("baseline_revision")
        current = self._current_revision_ids(state)
        baseline_set = set(baseline)
        current_set = set(current)
        if not baseline_set.issubset(current_set):
            raise RuntimeError("baseline dataset revision set is no longer visible")
        delta = tuple(item for item in current if item not in baseline_set)
        applied = self.journal.applied_checkpoint()
        applied_ids = tuple(int(item) for item in applied["revisionIds"])
        applied_set = set(applied_ids)
        if not applied_set.issubset(set(delta)):
            raise RuntimeError("applied dataset revision set is no longer visible")
        lag = tuple(item for item in delta if item not in applied_set)
        result = self._state_result(state, idempotent=True)
        result.update({
            "baselineRevisionCount": len(baseline),
            "visibleDeltaRevisionCount": len(delta),
            "visibleDeltaRevisionSetSha256": payload_sha256(delta),
            "appliedRevisionCount": len(applied_ids),
            "lagRevisionCount": len(lag),
            "lastAppliedAt": applied["appliedAt"],
            "lastAppliedPlanSha256": applied["planDigest"],
            "windowExpired": utc_now() > state.rollback_deadline,
        })
        if state.status in {"drained", "verified", "stopped"}:
            fixed = self.journal.revision_ids("drain_revision")
            result["fixedRevisionCount"] = len(fixed)
            result["fixedRevisionSetSha256"] = payload_sha256(fixed)
            result["unchangedSinceDrain"] = fixed == delta
        return result

    def run(self, *, poll_seconds: float = 5.0) -> dict[str, Any]:
        interval = float(poll_seconds)
        if interval < 0.25 or interval > 300:
            raise ValueError("poll interval must be between 0.25 and 300 seconds")
        cycles = 0
        while True:
            state = self.journal.load_state()
            if state is None:
                raise RuntimeError("reverse-sync has not been started")
            if state.status != "active":
                return {"status": state.status, "cycles": cycles}
            self.once()
            cycles += 1
            time.sleep(interval)

    def _build_and_reserve(
        self, state: JournalState
    ) -> tuple[SyncPlan, Mapping[UUID, tuple[str, int]]]:
        with self.source.connect() as connection:
            self._assert_binding(state, self.source.s_final(connection))
            plan = self._repeatable_plan(connection, state)
            maximums = self.target.maximum_legacy_ids()
            aliases = self.source.reserve_publication_aliases(
                connection,
                plan.publications,
                sqlite_maximums={
                    entity_type: int(maximums.get(entity_type, 0))
                    for entity_type in ("posts", "platform_posts")
                },
            )
            plan = self._with_aliases(plan, aliases)
            plan = self._reserve_snapshot_aliases(plan, maximums)
        self._record_aliases(aliases)
        return plan, aliases

    def _fixed_plan(
        self, connection: Any, state: JournalState
    ) -> tuple[SyncPlan, Mapping[UUID, tuple[str, int]]]:
        self._assert_binding(state, self.source.s_final(connection))
        plan = self._repeatable_plan(connection, state)
        plan = self._attach_snapshot_aliases(plan)
        fixed = self.journal.revision_ids("drain_revision")
        if plan.revision_ids != fixed or plan.digest != state.plan_digest:
            raise RuntimeError("target changed after the fixed drain")
        aliases = self._aliases_from_plan(plan)
        return plan, aliases

    def _reserve_snapshot_aliases(
        self,
        plan: SyncPlan,
        sqlite_maximums: Mapping[str, int],
    ) -> SyncPlan:
        reserved: dict[UUID, int] = {}
        for entity_type in ("reaction_snapshots", "platform_snapshots"):
            next_id = max(
                int(sqlite_maximums.get(entity_type, 0)),
                self.journal.maximum_alias_id(entity_type),
            )
            relevant = sorted(
                (
                    snapshot
                    for snapshot in plan.snapshots
                    if self._snapshot_entity_type(snapshot) == entity_type
                ),
                key=lambda snapshot: (
                    str(snapshot["published_month"]),
                    int(snapshot["id"]),
                    str(snapshot["publication_id"]),
                ),
            )
            for snapshot in relevant:
                target_key = self._snapshot_alias_key(snapshot, entity_type)
                legacy_id = self.journal.resolve_alias(entity_type, target_key)
                if legacy_id is None:
                    next_id += 1
                    legacy_id = next_id
                    self.journal.record_alias(entity_type, target_key, legacy_id)
                else:
                    next_id = max(next_id, legacy_id)
                reserved[target_key] = legacy_id
        return self._with_snapshot_aliases(plan, reserved)

    def _attach_snapshot_aliases(self, plan: SyncPlan) -> SyncPlan:
        reserved: dict[UUID, int] = {}
        for snapshot in plan.snapshots:
            entity_type = self._snapshot_entity_type(snapshot)
            target_key = self._snapshot_alias_key(snapshot, entity_type)
            legacy_id = self.journal.resolve_alias(entity_type, target_key)
            if legacy_id is None:
                raise RuntimeError("fixed plan snapshot lost its legacy alias")
            reserved[target_key] = legacy_id
        return self._with_snapshot_aliases(plan, reserved)

    def _with_snapshot_aliases(
        self,
        plan: SyncPlan,
        reserved: Mapping[UUID, int],
    ) -> SyncPlan:
        return replace(
            plan,
            snapshots=tuple(
                {
                    **snapshot,
                    "legacy_id": reserved[
                        self._snapshot_alias_key(
                            snapshot, self._snapshot_entity_type(snapshot)
                        )
                    ],
                }
                for snapshot in plan.snapshots
            ),
        )

    @staticmethod
    def _snapshot_entity_type(snapshot: Mapping[str, Any]) -> str:
        return (
            "reaction_snapshots"
            if snapshot["platform"] == "telegram"
            else "platform_snapshots"
        )

    def _snapshot_alias_key(
        self,
        snapshot: Mapping[str, Any],
        entity_type: str,
    ) -> UUID:
        return stable_uuid(
            self.source.source_namespace,
            "reverse_snapshot_alias",
            {
                "legacy_table": entity_type,
                "published_month": snapshot["published_month"],
                "target_id": int(snapshot["id"]),
            },
        )

    @staticmethod
    def _with_aliases(
        plan: SyncPlan,
        aliases: Mapping[UUID, tuple[str, int]],
    ) -> SyncPlan:
        publications = tuple(
            {
                **publication,
                "legacy_id": aliases[UUID(str(publication["id"]))][1],
            }
            for publication in plan.publications
        )
        snapshots = tuple(
            {
                **snapshot,
                "publication_legacy_id": aliases[
                    UUID(str(snapshot["publication_id"]))
                ][1],
            }
            for snapshot in plan.snapshots
        )
        return replace(plan, publications=publications, snapshots=snapshots)

    def _repeatable_plan(
        self,
        connection: Any,
        state: JournalState,
    ) -> SyncPlan:
        baseline = self.journal.revision_ids("baseline_revision")
        with connection.transaction():
            connection.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
            return self.source.build_plan(
                connection,
                baseline_revision_ids=baseline,
                started_at=state.started_at,
            )

    @staticmethod
    def _aliases_from_plan(
        plan: SyncPlan,
    ) -> dict[UUID, tuple[str, int]]:
        aliases: dict[UUID, tuple[str, int]] = {}
        for publication in plan.publications:
            legacy_id = publication.get("legacy_id")
            if legacy_id is None:
                raise RuntimeError("fixed plan publication lost its legacy alias")
            publication_id = UUID(str(publication["id"]))
            aliases[publication_id] = (
                "posts" if publication["platform"] == "telegram" else "platform_posts",
                int(legacy_id),
            )
        return aliases

    def _record_aliases(
        self, aliases: Mapping[UUID, tuple[str, int]]
    ) -> None:
        for target_id, (entity_type, legacy_id) in sorted(
            aliases.items(), key=lambda item: (item[1][0], item[1][1], str(item[0]))
        ):
            self.journal.record_alias(entity_type, target_id, legacy_id)

    def _current_revision_ids(self, state: JournalState) -> tuple[int, ...]:
        with self.source.connect() as connection:
            self._assert_binding(state, self.source.s_final(connection))
            return tuple(item.id for item in self.source.revisions(connection))

    def _required_state(self, *allowed: str) -> JournalState:
        state = self.journal.load_state()
        if state is None or state.status not in set(allowed):
            raise RuntimeError("reverse-sync state transition is not allowed")
        return state

    def _assert_binding(
        self, state: JournalState, s_final: Mapping[str, Any]
    ) -> None:
        if (
            state.source_namespace != self.source.source_namespace
            or state.s_final_batch_id != UUID(str(s_final["id"]))
            or state.s_final_source_sha256 != str(s_final["source_sha256"])
        ):
            raise RuntimeError("reverse-sync S-final binding changed")
        self._assert_target_binding()

    def _assert_target_binding(self) -> None:
        bound = self.journal.legacy_target_identity()
        if bound is None or bound != self.target.identity():
            raise RuntimeError("reverse-sync legacy target binding changed")

    def _assert_idempotency(
        self, state: JournalState, operator: str, ticket: str
    ) -> None:
        if state.operator != operator or state.ticket != ticket:
            raise RuntimeError("reverse-sync idempotency key does not match")

    def _assert_start_idempotency(
        self,
        state: JournalState,
        operator: str,
        ticket: str,
        rollback_window_hours: int,
    ) -> None:
        self._assert_idempotency(state, operator, ticket)
        if state.rollback_deadline - state.started_at != timedelta(
            hours=rollback_window_hours
        ):
            raise RuntimeError("reverse-sync rollback window does not match")

    @staticmethod
    def _state_result(
        state: JournalState, *, idempotent: bool
    ) -> dict[str, Any]:
        return {
            "status": state.status,
            "idempotent": idempotent,
            "sourceNamespace": state.source_namespace,
            "operator": state.operator,
            "ticket": state.ticket,
            "startedAt": state.started_at.isoformat(),
            "rollbackDeadline": state.rollback_deadline.isoformat(),
            "sFinalBatchId": str(state.s_final_batch_id),
            "sFinalSourceSha256": state.s_final_source_sha256,
            "drainedAt": (
                state.drained_at.isoformat() if state.drained_at is not None else None
            ),
            "verifiedAt": (
                state.verified_at.isoformat() if state.verified_at is not None else None
            ),
            "stoppedAt": (
                state.stopped_at.isoformat() if state.stopped_at is not None else None
            ),
        }

    @contextmanager
    def _operation_lock(self) -> Iterator[None]:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        if self._lock_path.is_symlink():
            raise ValueError("reverse-sync operation lock must not be a symlink")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(
            self._lock_path,
            flags,
            0o600,
        )
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode):
                raise ValueError("reverse-sync operation lock must be a regular file")
            if stat.S_IMODE(details.st_mode) & 0o077:
                raise PermissionError("reverse-sync operation lock permissions are too broad")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError("another reverse-sync operation is running") from error
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
