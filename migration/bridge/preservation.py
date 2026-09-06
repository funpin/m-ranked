"""Owner-authorized, source-derived classification of disappeared legacy rows."""
from __future__ import annotations

import hashlib
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
from uuid import uuid4

from psycopg.types.json import Jsonb

from .model import BridgeOptions, row_hash
from .reconciliation import PRESERVED_MAPPING, encode, fact_pairs
from .service import BridgeService, _source_pk, _without_internal
from .source import LegacySource, sha256_file


def preserve_disappeared(service: BridgeService, prior_path: Path, *, operator: str,
                        ticket: str, reason: str) -> dict:
    """Approve preservation only when both independent source and target agree.

    Call with the migration owner's connection. No canonical fact is edited.
    The current import must already have recorded its missing rows. Every missing
    mapping must match the exact row bytes of an earlier imported source artifact.
    Facts are derived exclusively from that artifact; target values are only
    compared after staging the ledger in the same transaction.
    """
    if not all(str(value).strip() for value in (operator, ticket, reason)):
        raise ValueError("operator, ticket and reason are required")
    prior = BridgeService(BridgeOptions(source=prior_path, source_namespace=service.options.source_namespace),
                          LegacySource(prior_path), service.target, snapshot_kind="s0")
    target = service.target
    with target.transaction(), tempfile.TemporaryDirectory(prefix="mranked-preservation-") as directory:
        target.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        target.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                       (str(service.source_namespace_uuid),))
        known = target.fetchone("""SELECT count(*) FROM migration.import_batch
            WHERE source_name=%s AND source_sha256=%s AND NOT dry_run""",
            (service.options.source_namespace, prior.inventory.source_sha256))
        if not known or not known[0]:
            raise ValueError("prior source artifact has no recorded import in this namespace")
        # Approval alone is not a projection oracle. Keep the exact prior artifact
        # available for the same invocation's required source-only overlay.
        service.options = replace(service.options,preserved_source_paths=tuple(dict.fromkeys(
            (*service.options.preserved_source_paths,prior_path.resolve()))))
        db = sqlite3.connect(f"{directory}/facts.sqlite")
        try:
            db.execute("PRAGMA cache_size=-2048")
            db.execute("CREATE TABLE missing(table_name TEXT,pk TEXT,target_type TEXT,hash TEXT,verified INTEGER DEFAULT 0)")
            with target.connection.cursor(name="preservation_missing") as cursor:
                cursor.execute("""SELECT m.source_table,m.source_pk,m.target_type,m.source_row_hash
                    FROM migration.legacy_identity_map m WHERE m.source_namespace=%s
                    AND m.last_seen_batch_id<>%s AND NOT ("""+PRESERVED_MAPPING+")",
                    (service.source_namespace_uuid, service.batch_id))
                db.executemany("INSERT INTO missing(table_name,pk,target_type,hash) VALUES(?,?,?,?)", cursor)
            db.execute("CREATE INDEX missing_row ON missing(table_name,pk,hash)")
            for table in prior.inventory.tables:
                for row in prior._all_rows(table.name):
                    db.execute("UPDATE missing SET verified=1 WHERE table_name=? AND pk=? AND hash=?",
                               (table.name, _source_pk(table.name, row), row_hash(_without_internal(row))))
            if db.execute("SELECT count(*) FROM missing WHERE verified=0").fetchone()[0]:
                raise ValueError("prior artifact does not verify every disappeared source row")
            count = db.execute("SELECT count(*) FROM missing").fetchone()[0]
            if not count:
                report = service.reconcile()
                if report["gate"]["status"] != "pass":
                    raise ValueError("no unclassified disappeared rows; independent reconciliation still fails")
                return report
            db.execute("CREATE TABLE current_key(key TEXT PRIMARY KEY)")
            db.execute("CREATE TABLE fact(kind TEXT,key TEXT,body TEXT,PRIMARY KEY(kind,key))")
            for kind, source_rows, _ in fact_pairs():
                db.execute("DELETE FROM current_key")
                db.executemany("INSERT INTO current_key VALUES(?)", ((encode(key),) for key, _ in source_rows(service)))
                for key, body in source_rows(prior):
                    encoded_key = encode(key)
                    if not db.execute("SELECT 1 FROM current_key WHERE key=?", (encoded_key,)).fetchone():
                        db.execute("INSERT INTO fact VALUES(?,?,?)", (kind, encoded_key, encode(body)))
            digest = hashlib.sha256()
            for row in db.execute("SELECT * FROM fact ORDER BY kind,key,body"):
                digest.update(("\t".join(row)+"\n").encode())
            preservation_id = uuid4()
            target.execute("""INSERT INTO migration.source_preservation(
                id,source_namespace,current_batch_id,prior_source_sha256,facts_sha256,operator,ticket,reason)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""", (preservation_id, service.source_namespace_uuid,
                service.batch_id, prior.inventory.source_sha256, digest.hexdigest(), operator.strip(), ticket.strip(), reason.strip()))
            for table, pk, target_type, source_hash in db.execute("SELECT table_name,pk,target_type,hash FROM missing"):
                decision = target.fetchone("""INSERT INTO migration.source_disappearance_decision(
                    source_namespace,source_table,source_pk,target_type,source_row_hash,decision,operator,ticket,reason)
                    VALUES(%s,%s,%s,%s,%s,'preserved_history',%s,%s,%s) RETURNING id""",
                    (service.source_namespace_uuid,table,pk,target_type,source_hash,operator.strip(),ticket.strip(),reason.strip()))
                target.execute("INSERT INTO migration.preserved_source_decision VALUES(%s,%s)", (preservation_id, decision[0]))
            with target.connection.cursor() as cursor:
                cursor.executemany("INSERT INTO migration.preserved_canonical_fact VALUES(%s,%s,%s,%s)",
                    ((preservation_id,kind,Jsonb(json.loads(key)),Jsonb(json.loads(body)))
                     for kind,key,body in db.execute("SELECT * FROM fact ORDER BY kind,key")))
            if sha256_file(prior.source.path) != prior.inventory.source_sha256:
                raise ValueError("prior source artifact changed during preservation")
            report = service.reconcile()
            if report["gate"]["status"] != "pass":
                failures = [f"{row['check']}:{row['scope']}" for row in report["mismatches"]]
                # Verifier reports contain safe codes, hashes and timeline keys,
                # never raw source payloads, credentials or identity values.
                verifiers = {name:report[name] for name in
                    ("identity_history_verification","projection_verification") if report.get(name)}
                raise ValueError("preserved source does not match actual target: "+", ".join(failures)
                    + ("; verifiers="+json.dumps(verifiers,ensure_ascii=False) if verifiers else ""))
            report["preservation"] = {"id":str(preservation_id), "decisions":count,
                "priorSourceSha256":prior.inventory.source_sha256,"factsSha256":digest.hexdigest(),
                "facts":db.execute("SELECT count(*) FROM fact").fetchone()[0],
                "operator":operator.strip(),"ticket":ticket.strip(),"decision":"preserved_history"}
            return report
        finally:
            db.close()
