"""Bounded, credential-free legacy account presentation evidence.

Canonical access_mode describes the collector protocol. The original public
label is a separate fact: e.g. public and public_api normalize to the same
protocol but legacy displays different labels. Arbitrary errors are never kept.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from .model import row_hash


def representation(row: Mapping) -> dict:
    error = str(row.get("last_error") or "")
    mode = row.get("access_mode")
    # Do not retain arbitrary text in this dedicated safe representation.
    allowed = {"public", "public_api", "official_api", "public_web", "telegram_web", "user_session", "owner", "mtproto", "api", "official", "user", "user_api", "disabled"}
    return {
        "access_mode": mode if mode in allowed else None,
        "last_error": {"present": bool(error), "length": len(error),
                       "sha256": hashlib.sha256(error.encode()).hexdigest() if error else None},
    }


def ensure_admin_presentation(service) -> bool:
    """Also backfill unchanged, already accepted pre-V25 source artifacts.

Only an exact current source-row hash may fill its missing representation;
an existing evidence row is never overwritten during replay.
"""
    if "platform_accounts" not in service.source.table_names():
        return False
    missing = service.target.fetchone("""SELECT EXISTS (
        SELECT 1 FROM migration.legacy_identity_map mapping
        WHERE mapping.source_namespace=%s AND mapping.last_seen_batch_id=%s
          AND mapping.source_table='platform_accounts' AND mapping.target_type='platform_account'
          AND NOT EXISTS (SELECT 1 FROM migration.legacy_evidence evidence
              WHERE evidence.batch_id=mapping.last_seen_batch_id AND evidence.source_table=mapping.source_table
                AND evidence.source_pk=mapping.source_pk AND evidence.source_row_hash=mapping.source_row_hash
                AND evidence.evidence_kind='legacy_account_presentation'))""",
        (service.source_namespace_uuid, service.batch_id))
    if not missing or not missing[0]:
        return False
    for rows in service.source.iter_rows("platform_accounts", batch_size=service.options.batch_size):
        with service.target.transaction():
            for row in rows:
                digest = row_hash({key: value for key, value in row.items() if not key.startswith("__")})
                service.target.execute("""INSERT INTO migration.legacy_evidence
                    (batch_id,source_table,source_pk,source_row_hash,evidence_kind,evidence,sanitized)
                    SELECT %s,'platform_accounts',%s,%s,'legacy_account_presentation',%s::jsonb,true
                    WHERE EXISTS(SELECT 1 FROM migration.legacy_identity_map mapping
                        WHERE mapping.source_namespace=%s AND mapping.last_seen_batch_id=%s
                          AND mapping.source_table='platform_accounts' AND mapping.source_pk=%s
                          AND mapping.target_type='platform_account' AND mapping.source_row_hash=%s)
                    ON CONFLICT DO NOTHING""",
                    (service.batch_id, str(row["id"]), digest, json.dumps(representation(row),ensure_ascii=False),
                     service.source_namespace_uuid, service.batch_id, str(row["id"]), digest))
    return True
