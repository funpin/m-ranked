"""Only legacy CSV representation fields; never a second observation store.

Numeric counters are read from canonical PostgreSQL observations when rebuilding
the export. JSON text and timestamp spelling cannot be recovered from JSONB or
timestamptz, so these explicit fields are retained separately and immutably.
Unsafe raw JSON is classified without retaining the original plaintext.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from .model import row_hash
from .normalize import sanitize_evidence

FIELDS = {
    "institutions": ("short_name",),
    "platform_accounts": ("external_key",),
    "channels": ("username",),
    "posts": ("published_at", "telegram_message_id", "history_complete"),
    "platform_posts": ("published_at", "external_id", "url", "post_type"),
    "reaction_snapshots": ("measured_at", "reactions_json", "delta_total", "delta_views", "delta_comments"),
    "platform_snapshots": ("measured_at", "raw_json"),
}


def representation(table: str, row: Mapping) -> tuple[dict, str | None]:
    result = {key: row.get(key) for key in FIELDS[table]}
    reason = None
    if "age_seconds" in row:
        result["age_seconds"] = row["age_seconds"]
        result["age_hours"] = str(row["age_seconds"] / 3600.0)
    for field in ("raw_json", "reactions_json"):
        value = result.get(field)
        if value is None or value == "":
            continue
        code = None
        if len(str(value).encode("utf-8")) > 1_048_576:
            code = "FIELD_TOO_LARGE"
        else:
            try:
                parsed = json.loads(value)
                if sanitize_evidence(parsed) != parsed:
                    code = "UNSAFE_RAW_JSON"
            except (TypeError, ValueError):
                code = "UNPARSEABLE_RAW_JSON"
        if code:
            result[field] = None
            result[field + "_sha256"] = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
            reason = code
    return result, reason


def preserve_export_lexemes(target, namespace, table: str, row: Mapping) -> int:
    if table not in FIELDS:
        return 0
    body, reason = representation(table, row)
    digest = row_hash({key: value for key, value in row.items() if not key.startswith("__")})
    target.execute("""INSERT INTO migration.legacy_export_lexeme
        (source_namespace,source_table,source_pk,source_row_hash,fields,blocked_reason)
        VALUES(%s,%s,%s,%s,%s::jsonb,%s) ON CONFLICT DO NOTHING""",
        (namespace, table, str(row["id"]), digest,
         json.dumps(body, ensure_ascii=False, sort_keys=True), reason))
    return 1


def ensure_export_lexemes(service) -> bool:
    """Backfill an already accepted pre-V17 import from its unchanged source.

    Source row hashes must match the current mapping. A changed/older source is
    never used to fill another import's representation. Memory stays one batch.
    """
    missing = service.target.fetchone("""SELECT EXISTS(SELECT 1 FROM migration.legacy_identity_map mapping
        LEFT JOIN migration.legacy_export_lexeme lexeme ON lexeme.source_namespace=mapping.source_namespace
            AND lexeme.source_table=mapping.source_table AND lexeme.source_pk=mapping.source_pk
            AND lexeme.source_row_hash=mapping.source_row_hash
        WHERE mapping.source_namespace=%s AND mapping.last_seen_batch_id=%s
            AND mapping.source_table=ANY(%s) AND lexeme.source_pk IS NULL)""",
        (service.source_namespace_uuid, service.batch_id, list(FIELDS)))
    if not missing or not missing[0]:
        return False
    for table in FIELDS:
        if table not in service.source.table_names():
            continue
        for rows in service.source.iter_rows(table, batch_size=service.options.batch_size):
            with service.target.transaction():
                for row in rows:
                    preserve_export_lexemes(service.target, service.source_namespace_uuid, table, row)
    return True
