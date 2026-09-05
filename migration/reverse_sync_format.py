from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
from typing import Any, Mapping
from uuid import UUID


ENVELOPE_KEY = "_mranked_reverse_sync"
ENVELOPE_VERSION = 1
PUBLICATION_ENVELOPE_KEY = "_mranked_reverse_publication"
PUBLICATION_ENVELOPE_VERSION = 1
SNAPSHOT_TABLES = frozenset({"reaction_snapshots", "platform_snapshots"})
PUBLICATION_TABLES = frozenset({"platform_posts"})
PUBLICATION_IDENTITY_ROLES = frozenset({
    "primary",
    "album_member",
    "joint_author",
    "source",
    "repost_source",
})
OBSERVATION_QUALITIES = frozenset({
    "unknown",
    "rounded",
    "estimated",
    "exact",
    "degraded",
    "suspected_reset",
    "invalid",
})


@dataclass(frozen=True, slots=True)
class ReverseSnapshotEnvelope:
    legacy_table: str
    publication_id: UUID
    published_month: date
    snapshot_id: int
    collected_at: datetime
    quality: str
    interval_uncertain: bool
    synthetic: bool
    metric_semantics_version: int
    capability_version: int
    source_fingerprint: str
    created_at: datetime

    def as_payload(self) -> dict[str, Any]:
        return {
            ENVELOPE_KEY: {
                "version": ENVELOPE_VERSION,
                "legacy_table": self.legacy_table,
                "publication_id": str(self.publication_id),
                "published_month": self.published_month.isoformat(),
                "snapshot_id": self.snapshot_id,
                "collected_at": self.collected_at.isoformat(),
                "quality": self.quality,
                "interval_uncertain": self.interval_uncertain,
                "synthetic": self.synthetic,
                "metric_semantics_version": self.metric_semantics_version,
                "capability_version": self.capability_version,
                "source_fingerprint": self.source_fingerprint,
                "created_at": self.created_at.isoformat(),
            }
        }

    def as_json(self) -> str:
        return json.dumps(self.as_payload(), ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True, slots=True)
class ReversePublicationEnvelope:
    legacy_table: str
    publication_id: UUID
    quality_flags: Mapping[str, Any]
    identities: tuple[Mapping[str, Any], ...]

    def as_payload(self) -> dict[str, Any]:
        return {
            PUBLICATION_ENVELOPE_KEY: {
                "version": PUBLICATION_ENVELOPE_VERSION,
                "legacy_table": self.legacy_table,
                "publication_id": str(self.publication_id),
                "quality_flags": dict(self.quality_flags),
                "identities": [dict(identity) for identity in self.identities],
            }
        }


def add_reverse_publication_envelope(
    value: Any,
    envelope: ReversePublicationEnvelope,
) -> str:
    """Add protocol metadata without destroying object-shaped legacy payloads."""

    if value is None or value == "":
        payload: dict[str, Any] = {}
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = {"legacy_unparsed_text": value}
        payload = (
            dict(parsed)
            if isinstance(parsed, Mapping)
            else {"legacy_payload": parsed}
        )
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        payload = {"legacy_payload": value}
    payload.update(envelope.as_payload())
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def parse_reverse_publication_envelope(
    value: Any,
) -> ReversePublicationEnvelope | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return None
    else:
        payload = value
    if not isinstance(payload, Mapping) or PUBLICATION_ENVELOPE_KEY not in payload:
        return None
    raw = payload[PUBLICATION_ENVELOPE_KEY]
    if not isinstance(raw, Mapping):
        raise ValueError("reverse-sync publication envelope must be an object")
    if raw.get("version") != PUBLICATION_ENVELOPE_VERSION:
        raise ValueError("unsupported reverse-sync publication envelope version")
    legacy_table = str(raw.get("legacy_table") or "")
    if legacy_table not in PUBLICATION_TABLES:
        raise ValueError("invalid reverse-sync legacy publication table")
    flags = raw.get("quality_flags")
    if not isinstance(flags, Mapping):
        raise ValueError("reverse-sync publication quality_flags must be an object")
    raw_identities = raw.get("identities")
    if not isinstance(raw_identities, list) or not raw_identities:
        raise ValueError("reverse-sync publication identities must be a non-empty list")
    identities: list[Mapping[str, Any]] = []
    primary_count = 0
    for raw_identity in raw_identities:
        if not isinstance(raw_identity, Mapping):
            raise ValueError("reverse-sync publication identity must be an object")
        external_id = str(raw_identity.get("external_id") or "").strip()
        role = str(raw_identity.get("role") or "")
        if not external_id or role not in PUBLICATION_IDENTITY_ROLES:
            raise ValueError("invalid reverse-sync publication identity")
        primary_count += int(role == "primary")
        identities.append({
            "external_id": external_id,
            "source_external_id": _optional_string(
                raw_identity.get("source_external_id")
            ),
            "role": role,
            "public_url": _optional_https(raw_identity.get("public_url")),
        })
    if primary_count != 1:
        raise ValueError("reverse-sync publication must have exactly one primary identity")
    return ReversePublicationEnvelope(
        legacy_table=legacy_table,
        publication_id=UUID(str(raw["publication_id"])),
        quality_flags=dict(flags),
        identities=tuple(identities),
    )


def parse_reverse_snapshot_envelope(value: Any) -> ReverseSnapshotEnvelope | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return None
    else:
        payload = value
    if not isinstance(payload, Mapping) or ENVELOPE_KEY not in payload:
        return None
    raw = payload[ENVELOPE_KEY]
    if not isinstance(raw, Mapping):
        raise ValueError("reverse-sync snapshot envelope must be an object")
    if raw.get("version") != ENVELOPE_VERSION:
        raise ValueError("unsupported reverse-sync snapshot envelope version")
    legacy_table = str(raw.get("legacy_table") or "")
    if legacy_table not in SNAPSHOT_TABLES:
        raise ValueError("invalid reverse-sync legacy snapshot table")
    published_month = date.fromisoformat(str(raw["published_month"]))
    if published_month.day != 1:
        raise ValueError("reverse-sync published_month must be the first day")
    snapshot_id = _positive_integer(raw.get("snapshot_id"), "snapshot_id")
    quality = str(raw.get("quality") or "")
    if quality not in OBSERVATION_QUALITIES:
        raise ValueError("invalid reverse-sync observation quality")
    source_fingerprint = str(raw.get("source_fingerprint") or "").strip()
    if not source_fingerprint:
        raise ValueError("reverse-sync source_fingerprint must not be blank")
    return ReverseSnapshotEnvelope(
        legacy_table=legacy_table,
        publication_id=UUID(str(raw["publication_id"])),
        published_month=published_month,
        snapshot_id=snapshot_id,
        collected_at=_aware_datetime(raw.get("collected_at"), "collected_at"),
        quality=quality,
        interval_uncertain=_boolean(raw.get("interval_uncertain"), "interval_uncertain"),
        synthetic=_boolean(raw.get("synthetic"), "synthetic"),
        metric_semantics_version=_positive_integer(
            raw.get("metric_semantics_version"), "metric_semantics_version"
        ),
        capability_version=_positive_integer(
            raw.get("capability_version"), "capability_version"
        ),
        source_fingerprint=source_fingerprint,
        created_at=_aware_datetime(raw.get("created_at"), "created_at"),
    )


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"reverse-sync {field} must be a positive integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"reverse-sync {field} must be a positive integer"
        ) from error
    if result <= 0 or str(value).strip() != str(result):
        raise ValueError(f"reverse-sync {field} must be a canonical positive integer")
    return result


def _aware_datetime(value: Any, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid reverse-sync {field}") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"reverse-sync {field} must include an offset")
    return result


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"reverse-sync {field} must be boolean")
    return value


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _optional_https(value: Any) -> str | None:
    normalized = _optional_string(value)
    if normalized is not None and not normalized.startswith("https://"):
        raise ValueError("reverse-sync publication public_url must use https")
    return normalized
