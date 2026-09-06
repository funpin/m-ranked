"""Read-only source-artifact oracle for the complete account identity timeline.

Revisions supply event order and capture time, never identity values.
Expected values are read from frozen SQLite and original input files; actual values are read from
the two canonical history tables. No migration digest is a target value.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
import json
import sqlite3
import tempfile

from .model import stable_uuid
from .normalize import as_utc
from .reconciliation import compare_rows, encode
from .source import LegacySource, sha256_file


class IdentityHistorySourceError(ValueError):
    """A safe, classified failure suitable for a reconciliation report."""


def _url(value):
    from urllib.parse import urlsplit
    text = str(value or "").strip()
    try:
        parts = urlsplit(text)
        return text if parts.scheme in {"http", "https"} and parts.hostname and parts.username is None and parts.password is None else None
    except ValueError:
        return None


def _artifact(path: Path):
    path = path.resolve(strict=True)
    if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise IdentityHistorySourceError("HISTORY_SOURCE_NOT_FROZEN")
    return path, sha256_file(path)


def _source_rows(path, table, max_accounts):
    source = LegacySource(path)
    if table not in source.table_names():
        return []
    rows = []
    for batch in source.iter_rows(table, batch_size=500):
        rows.extend(batch)
        if len(rows) > max_accounts:
            raise IdentityHistorySourceError("HISTORY_SOURCE_ACCOUNT_LIMIT")
    return rows


def _apply(db, account, kind, values, captured_at, created_at, run, *, policy="migration"):
    current = db.execute("SELECT seq,body FROM history WHERE account=? AND kind=? AND active=1", (account,kind)).fetchone()
    body = json.loads(current[1]) if current else None
    if kind == "native" and values is None:
        if current:
            body["validTo"] = captured_at if policy == "collector" else max(captured_at,as_utc(body["validFrom"])+timedelta(microseconds=1))
            db.execute("UPDATE history SET active=0,body=? WHERE account=? AND kind=? AND seq=?", (encode(body),account,kind,current[0]))
        return
    if body and all(body.get(key) == value for key,value in values.items()):
        return
    last = db.execute("SELECT seq,body FROM history WHERE account=? AND kind=? ORDER BY seq DESC LIMIT 1", (account,kind)).fetchone()
    if current:
        transition = max(captured_at,as_utc(body["validFrom"])+timedelta(microseconds=1))
        body["validTo"] = transition
        db.execute("UPDATE history SET active=0,body=? WHERE account=? AND kind=? AND seq=?", (encode(body),account,kind,current[0]))
    elif last:
        transition = max(captured_at,as_utc(json.loads(last[1])["validTo"])+timedelta(microseconds=1))
    else:
        transition = created_at
    if policy == "collector":
        transition = captured_at
    elif policy == "admin" and not current and (kind != "native" or not last):
        transition = captured_at
    if current and policy == "collector" and transition <= as_utc(body["validFrom"]):
        raise IdentityHistorySourceError("HISTORY_COLLECTOR_TIME_COLLISION")
    if kind == "native" and not current and last and policy == "collector" and transition <= as_utc(json.loads(last[1])["validTo"]):
        raise IdentityHistorySourceError("HISTORY_COLLECTOR_TIME_COLLISION")
    new = {**values,"validFrom":transition,"validTo":None,"sourceRun":str(run)}
    if kind == "native":
        new["verifiedAt"] = max(transition,captured_at)
    db.execute("INSERT INTO history VALUES(?,?,?,?,?,1)", (account,kind,(last[0]+1 if last else 0),encode(new),str(run)))


def _current_values(db, account):
    row = db.execute("SELECT body FROM history WHERE account=? AND kind='presentation' AND active=1", (account,)).fetchone()
    return json.loads(row[0]) if row else {"username":None,"title":None,"url":None}


def _collector_input(connection, event, receipts):
    from collector_target.identity_evidence import IdentityEvidenceStore, IdentityEvidenceUnavailable, configured_root
    from collector_target.evidence import ImmutableEvidenceStore, EvidenceUnavailable
    import os
    event_id,_,_,run,metadata,_ = event
    account = str(metadata.get("account_id", ""))
    platform = metadata.get("platform")
    if platform not in {"telegram","vk","max","rutube"} or not account or run is None:
        raise IdentityHistorySourceError("HISTORY_COLLECTOR_BINDING_INVALID")
    digest = metadata.get("identity_source_receipt")
    try:
        if digest:
            store = IdentityEvidenceStore(configured_root()/"collector"/platform)
            original = store.read(digest)
            receipts[("collector",platform,digest)] = store
            if set(original) != {"version","kind","accountId","platform","sourceRunId","sourceFingerprint","observedAt","username","title","url","nativeId"} \
                    or original["version"] != 1 or original["kind"] != "collector-account-identity" \
                    or original["accountId"] != account or original["platform"] != platform or original["sourceRunId"] != str(run):
                raise IdentityHistorySourceError("HISTORY_COLLECTOR_BINDING_INVALID")
            if not connection.execute("""SELECT EXISTS(SELECT 1 FROM ingest.account_metric_snapshot
                WHERE platform_account_id=%s AND source_fingerprint=%s AND observed_at=%s)""",
                (account,original["sourceFingerprint"],as_utc(original["observedAt"]))).fetchone()[0]:
                raise IdentityHistorySourceError("HISTORY_COLLECTOR_OBSERVATION_UNBOUND")
            return original
        # Older accepted collectors can be verified while their original raw
        # object remains retrievable. No target history value supplies a field.
        sources = connection.execute("""SELECT raw.external_ref,raw.sha256,raw.purge_after
            FROM ingest.raw_payload raw JOIN ingest.account_metric_snapshot snapshot
              ON snapshot.collection_run_id=raw.collection_run_id AND snapshot.platform_account_id=raw.owner_id
             AND snapshot.source_fingerprint=raw.sha256
            WHERE raw.collection_run_id=%s AND raw.owner_type='account' AND raw.owner_id=%s LIMIT 2""", (run,account)).fetchall()
        if len(sources) != 1:
            raise IdentityHistorySourceError("HISTORY_COLLECTOR_SOURCE_REQUIRED")
        uri,source_sha,purge_after = sources[0]
        store = ImmutableEvidenceStore(Path(os.environ.get("COLLECTOR_RAW_EVIDENCE_DIR","data/target-raw-evidence")).absolute())
        from datetime import timezone
        original = store.read(uri,source_sha,purge_after=purge_after,now=datetime.now(timezone.utc))
        if original.get("account") != account or original.get("platform") != platform:
            raise IdentityHistorySourceError("HISTORY_COLLECTOR_BINDING_INVALID")
        return {"accountId":account,"platform":platform,"sourceRunId":str(run),"observedAt":original["observed_at"],
            "username":original.get("username"),"title":original.get("title"),"url":original.get("url"),"nativeId":original.get("native_external_id")}
    except (IdentityEvidenceUnavailable,EvidenceUnavailable) as error:
        raise IdentityHistorySourceError("HISTORY_"+str(error)) from error


def _replay_collector(db, connection, event, receipts):
    original = _collector_input(connection,event,receipts)
    account = original["accountId"]
    current = _current_values(db,account)
    # Independently implement the input semantics: absent/blank observations
    # retain the prior value; a non-HTTPS URL is not a presentation observation.
    def text(value):
        if value is not None and not isinstance(value,(str,int)):
            raise IdentityHistorySourceError("HISTORY_COLLECTOR_VALUE_INVALID")
        return str(value).strip() or None if value is not None else None
    username,title,native = (text(original[key]) for key in ("username","title","nativeId"))
    url = _url(original["url"])
    from urllib.parse import urlsplit
    url = url if url and urlsplit(url).scheme.casefold() == "https" else None
    observed = as_utc(original["observedAt"])
    run = original["sourceRunId"]
    if any(value is not None for value in (username,title,url)):
        _apply(db,account,"presentation",{"username":username or current["username"],"title":title or current["title"],"url":url or current["url"]},observed,observed,run,policy="collector")
    if native is not None:
        _apply(db,account,"native",{"namespace":original["platform"]+":native_id","externalId":native},observed,observed,run,policy="collector")


def _replay_admin(db, connection, event, owned, receipts, admin_accounts):
    from collector_target.identity_evidence import IdentityEvidenceStore, IdentityEvidenceUnavailable, configured_root, accepted_admin_input
    try:
        accepted=accepted_admin_input(connection,event[0],event[2])
    except IdentityEvidenceUnavailable as error:
        raise IdentityHistorySourceError("HISTORY_"+str(error)) from error
    if accepted is None:
        return
    digest,captured,account=accepted["sha256"],accepted["accepted_at"],accepted["target_id"]
    original=accepted["input"]
    receipts[("admin","",digest)] = IdentityEvidenceStore(configured_root()/"admin")
    action,body = original["action"],original["body"]
    if action not in {"account.upsert","channel.upsert","account.native_id"} or account not in owned:
        return
    admin_accounts.add(account)
    current = _current_values(db,account)
    if action == "account.native_id":
        if original["target"] != account:
            raise IdentityHistorySourceError("HISTORY_ADMIN_TARGET_INVALID")
        platform = db.execute("SELECT platform FROM accounts WHERE account=?", (account,)).fetchone()
        if platform is None:
            raise IdentityHistorySourceError("HISTORY_ADMIN_ACCOUNT_SOURCE_REQUIRED")
        native = str(body.get("nativeId") or "").strip() or None
        _apply(db,account,"native",{"namespace":platform[0]+":native_id","externalId":native} if native else None,captured,captured,None,policy="admin")
    else:
        platform = body.get("platform")
        if platform not in {"telegram","vk","max","rutube"}:
            raise IdentityHistorySourceError("HISTORY_ADMIN_SOURCE_INVALID")
        db.execute("INSERT OR IGNORE INTO accounts VALUES(?,?)", (account,platform))
        _apply(db,account,"presentation",{"username":body.get("username"),"title":body.get("title") if body.get("title") is not None else current["title"],
            "url":body.get("url") if body.get("url") is not None else current["url"]},captured,captured,None,policy="admin")


def verify_identity_history(service, **options):
    connection = service.target.connection
    idle = connection.info.transaction_status.name == "IDLE"
    with connection.transaction():
        if idle:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        elif connection.execute("SHOW transaction_isolation").fetchone()[0] not in {"repeatable read","serializable"}:
            raise IdentityHistorySourceError("HISTORY_REPEATABLE_READ_REQUIRED")
        return _verify_identity_history(service,**options)


def _verify_identity_history(service, *, historical_source_paths=(), max_artifacts=64, max_accounts=5000, max_events=100000,
                             max_account_operations=1000000, max_transitions=250000):
    connection = service.target.connection
    namespace = service.source_namespace_uuid
    source_name = service.options.source_namespace
    current, current_sha = _artifact(service.source.path)
    if current_sha != service.inventory.source_sha256:
        raise IdentityHistorySourceError("HISTORY_SOURCE_SHA_MISMATCH")
    paths = (current,*historical_source_paths,*service.options.preserved_source_paths)
    if len(paths) > max_artifacts:
        raise IdentityHistorySourceError("HISTORY_SOURCE_ARTIFACT_LIMIT")
    artifacts = {}
    for path in paths:
        resolved,digest = _artifact(Path(path))
        artifacts[digest] = resolved
    batches = connection.execute("""SELECT id,source_sha256,source_snapshot_at FROM migration.import_batch
        WHERE source_name=%s AND NOT dry_run LIMIT %s""", (source_name,max_events+1)).fetchall()
    if len(batches) > max_events:
        raise IdentityHistorySourceError("HISTORY_EVENT_LIMIT")
    metadata = {str(row[0]):(row[1],row[2]) for row in batches}
    known = {row[1] for row in batches}
    if set(artifacts)-known:
        raise IdentityHistorySourceError("HISTORY_SOURCE_ARTIFACT_NOT_IMPORTED")
    owned = connection.execute("""SELECT DISTINCT target_uuid FROM migration.legacy_identity_map
        WHERE source_namespace=%s AND target_type='platform_account' LIMIT %s""", (namespace,max_accounts+1)).fetchall()
    owned = {str(row[0]) for row in owned}
    if len(owned) > max_accounts:
        raise IdentityHistorySourceError("HISTORY_SOURCE_ACCOUNT_LIMIT")
    aliases = connection.execute("""SELECT entity_type::text,legacy_id,target_uuid FROM catalog.legacy_entity_alias
        WHERE entity_type IN ('platform_accounts','channels') AND target_uuid=ANY(%s::uuid[]) LIMIT %s""", (list(owned),max_accounts*2+1)).fetchall()
    if len(aliases) > max_accounts*2:
        raise IdentityHistorySourceError("HISTORY_SOURCE_ACCOUNT_LIMIT")
    aliases = {(row[0],int(row[1])):str(row[2]) for row in aliases}
    # Every committed import stream remains visible, including a deliberate
    # replay of an older accepted file. Adjacent revisions are chunks of a
    # single ordered stream, not separate account transitions.
    events = connection.execute("""SELECT r.id,r.cause::text,r.correlation_id,r.source_run_id,r.metadata,r.committed_at
        FROM analytics.dataset_revision r LEFT JOIN migration.import_batch b ON b.id=r.correlation_id
        WHERE (r.cause='migration' AND b.source_name=%s) OR r.cause IN ('ingestion','configuration')
        ORDER BY r.id LIMIT %s""", (source_name,max_events+1)).fetchall()
    if len(events) > max_events:
        raise IdentityHistorySourceError("HISTORY_EVENT_LIMIT")
    used = set()
    operations = 0
    receipts = {}
    admin_accounts = set()
    with tempfile.TemporaryDirectory(prefix="mranked-history-oracle-") as temporary:
        with closing(sqlite3.connect(str(Path(temporary)/"expected.sqlite"))) as db:
            db.execute("PRAGMA cache_size=-2048")
            db.execute("""CREATE TABLE history(account TEXT,kind TEXT,seq INTEGER,body TEXT,run TEXT,active INTEGER,
                PRIMARY KEY(account,kind,seq))""")
            db.execute("CREATE UNIQUE INDEX current_history ON history(account,kind) WHERE active=1")
            db.execute("CREATE TABLE accounts(account TEXT PRIMARY KEY,platform TEXT)")
            previous_stream = None
            for event in events:
                revision,cause,correlation,source_run,event_metadata,committed_at = event
                if cause != "migration":
                    previous_stream = None
                    if cause == "configuration":
                        _replay_admin(db,connection,event,owned,receipts,admin_accounts)
                    elif str(event_metadata.get("account_id", "")) in owned:
                        if event_metadata.get("identity_observation") is not False:
                            _replay_collector(db,connection,event,receipts)
                    if db.execute("SELECT count(*) FROM history").fetchone()[0] > max_transitions:
                        raise IdentityHistorySourceError("HISTORY_TRANSITION_LIMIT")
                    continue
                batch,stream = str(correlation),event_metadata.get("stream")
                if previous_stream == (batch,stream):
                    continue
                previous_stream = (batch,stream)
                if stream not in {"platform_accounts","channels"}:
                    continue
                digest,captured_at = metadata[batch]
                path = artifacts.get(digest)
                if path is None:
                    # Actual absence of closed rows cannot prove that no prior
                    # transition occurred: damaged target rows are not authority.
                    raise IdentityHistorySourceError("HISTORY_PRIOR_SOURCE_REQUIRED")
                used.add(digest)
                channels = _source_rows(path,"channels",max_accounts)
                linked = {int(row["platform_account_id"]):row for row in channels if row.get("platform_account_id") is not None}
                rows = channels if stream == "channels" else _source_rows(path,stream,max_accounts)
                for row in rows:
                    operations += 1
                    if operations > max_account_operations:
                        raise IdentityHistorySourceError("HISTORY_OPERATION_LIMIT")
                    account = aliases.get((stream,int(row["id"])))
                    if account is None:
                        raise IdentityHistorySourceError("HISTORY_SOURCE_IDENTITY_UNMAPPED")
                    platform = "telegram" if stream == "channels" else row["platform"]
                    db.execute("INSERT OR IGNORE INTO accounts VALUES(?,?)", (account,platform))
                    run = stable_uuid(source_name,"migration_collection_run",{"batch_id":batch,"platform":platform})
                    username = str(row["username"]) if stream == "channels" else row.get("username")
                    url = "https://t.me/"+username if stream == "channels" else _url(row.get("url"))
                    channel = linked.get(int(row["id"])) if stream == "platform_accounts" and platform == "telegram" else None
                    native = row.get("telegram_id") if stream == "channels" else channel.get("telegram_id") if channel is not None else row.get("native_id")
                    native = str(native) if native is not None and str(native).strip() else None
                    created_at = as_utc(row.get("added_at"),fallback=captured_at)
                    _apply(db,account,"presentation",{"username":username,"title":row.get("title"),"url":url},captured_at,created_at,run)
                    _apply(db,account,"native",{"namespace":platform+":native_id","externalId":native} if native else None,captured_at,created_at,run)
                if db.execute("SELECT count(*) FROM history").fetchone()[0] > max_transitions:
                    raise IdentityHistorySourceError("HISTORY_TRANSITION_LIMIT")
            db.commit()
            unsupported = owned-admin_accounts
            if unsupported and connection.execute("""SELECT EXISTS(SELECT 1 FROM catalog.account_identity_history
                WHERE platform_account_id=ANY(%s::uuid[]) AND source_run_id IS NULL UNION ALL
                SELECT 1 FROM catalog.account_external_identity WHERE platform_account_id=ANY(%s::uuid[]) AND source_run_id IS NULL)""",
                (list(unsupported),list(unsupported))).fetchone()[0]:
                raise IdentityHistorySourceError("HISTORY_NON_MIGRATION_AUTHORITY_REQUIRED")
            checks = []
            for kind,table in (("presentation","account_identity_history"),("native","account_external_identity")):
                expected = (((account,seq),json.loads(body)) for account,seq,body in db.execute("SELECT account,seq,body FROM history WHERE kind=?", (kind,)))
                def actual():
                    from psycopg.rows import dict_row
                    with connection.cursor(name="identity_history_actual",row_factory=dict_row) as cursor:
                        cursor.execute(f"""SELECT *,row_number() OVER(PARTITION BY platform_account_id ORDER BY valid_from,id)-1 AS ordinal
                            FROM catalog.{table} WHERE platform_account_id=ANY(%s::uuid[])""", (list(owned),))
                        for row in cursor:
                            body = {"validFrom":row["valid_from"],"validTo":row["valid_to"],"sourceRun":str(row["source_run_id"])}
                            body.update({"username":row["username"],"title":row["title"],"url":row["url"]} if kind == "presentation" else
                                {"namespace":row["identity_namespace"],"externalId":row["external_id"],"verifiedAt":row["verified_at"]})
                            yield (str(row["platform_account_id"]),row["ordinal"]),body
                result = compare_rows(expected,actual())
                checks.append({"name":kind,"status":"pass" if result["expected"] == result["actual"] and not result["actual"]["duplicateKeys"] else "fail",**result})
    unchanged = all(sha256_file(path) == digest for digest,path in artifacts.items())
    if not unchanged:
        raise IdentityHistorySourceError("HISTORY_SOURCE_CHANGED_DURING_SCAN")
    for (_,_,digest),store in receipts.items():
        try:
            store.read(digest)
        except ValueError as error:
            raise IdentityHistorySourceError("HISTORY_RECEIPT_CHANGED_DURING_SCAN") from error
    return {"status":"pass" if all(check["status"] == "pass" for check in checks) else "fail",
        "sourceSha256":current_sha,"sourceUnchanged":True,"sourceArtifacts":sorted(used),
        "datasetRevision":connection.execute("SELECT max(id) FROM analytics.dataset_revision").fetchone()[0],
        "asOf":service.source_snapshot_at.isoformat(),
        "identitySourceReceipts":[{"kind":kind,"platform":platform or None,"sha256":digest} for kind,platform,digest in sorted(receipts)],
        "checks":checks}
