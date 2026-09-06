import hashlib,json,os,subprocess,sys,tempfile,time,uuid
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
ROOT=Path('/Users/funpin/Documents/ChatGPT/TG-monitoring');sys.path.insert(0,str(ROOT))
from migration.bridge.model import BridgeOptions
from migration.bridge.source import LegacySource
from migration.bridge.service import BridgeService
from migration.bridge.target import PostgresTarget
from migration.release_manifest import flyway_manifest, release_identity
from operations.collector_parity_evidence import EXPECTED_MIGRATIONS
from operations.disaster_recovery.rehearse import STATE_SQL

OUTPUT=ROOT/'migration/reports/representative-reimport-v29-r1';OUTPUT.mkdir(exist_ok=False);OUTPUT.chmod(0o700)
SOURCE=Path('/private/tmp/mranked-frontend-review-20260905-v3.sqlite')
SOURCE_SHA='22ec8c52a2e0484bc752221010798d20a66856ff19f4762b09c96749e887b41c'
NAMESPACE='root-admin-visual-v7';CONTAINER='mranked-review-it-postgres-1';SOURCE_DATABASE='admin_review_visual_v7_it'
DATABASE='representative_reimport_'+uuid.uuid4().hex[:12]+'_it'
secret_values={}
for line in Path('/private/tmp/mranked-review-it.env').read_text().splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        key,value=line.split('=',1);secret_values[key]=value.strip().strip('"').strip("'")
BASE=dict(host='127.0.0.1',port=55439,user='mranked_bootstrap',password=secret_values['POSTGRES_SUPERUSER_PASSWORD'])
report={'scope':'disposable-representative-completed-batch-reimport','productionAcceptance':False,'status':'running',
        'sourceDatabase':SOURCE_DATABASE,'cloneDatabase':DATABASE,'sourceNamespace':NAMESPACE,'snapshotKind':'fixture',
        'sourcePath':str(SOURCE),'sourceSha256':SOURCE_SHA,'commands':[],'checks':{},'timingsSeconds':{}}
began=time.monotonic();created=False
def sha(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()
def state(database):
    with psycopg.connect(**BASE,dbname=database) as connection:
        connection.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        value=connection.execute(STATE_SQL).fetchone()[0]
    value['canonicalSha256']=hashlib.sha256(json.dumps({k:v for k,v in value.items() if k!='sizeBytes'},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return value
def hashes(database,label):
    started=time.monotonic();values={}
    with psycopg.connect(**BASE,dbname=database) as connection:
        connection.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        connection.execute("SET LOCAL statement_timeout='5min'")
        tables=connection.execute("""SELECT n.nspname,c.relname,coalesce((
            SELECT array_agg(a.attname ORDER BY k.position) FROM pg_index i
            CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum,position)
            JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum
            WHERE i.indrelid=c.oid AND i.indisprimary AND k.position<=i.indnkeyatts),ARRAY[]::name[])
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE c.relkind IN ('r','p','m')
            AND (n.nspname IN ('catalog','ingest','rating','analytics','migration')
                 OR (n.nspname='ops_and_admin' AND c.relname='outbox_event'))
            AND NOT(n.nspname='migration' AND c.relname='reconciliation_result')
            AND NOT EXISTS(SELECT 1 FROM pg_inherits parent WHERE parent.inhrelid=c.oid)
            ORDER BY n.nspname,c.relname""").fetchall()
        for schema,table,keys in tables:
            qualified=sql.Identifier(schema,table)
            ordered=sql.SQL(',').join(map(sql.Identifier,keys)) if keys else sql.SQL('to_jsonb(t)::text COLLATE "C"')
            query=sql.SQL('COPY (SELECT * FROM {} t ORDER BY {}) TO STDOUT (FORMAT BINARY)').format(qualified,ordered)
            digest=hashlib.sha256();length=0
            with connection.cursor().copy(query) as stream:
                for block in stream:digest.update(block);length+=len(block)
            count=connection.execute(sql.SQL('SELECT count(*) FROM {}').format(qualified)).fetchone()[0]
            values[schema+'.'+table]={'rows':count,'sha256':digest.hexdigest(),'bytesHashed':length,'orderBy':list(keys) or ['canonical JSON text C collation']}
    report['timingsSeconds'][label]=round(time.monotonic()-started,4)
    print(label,'tables',len(values),'rows',sum(v['rows'] for v in values.values()),flush=True)
    return values
def check(name,value):
    report['checks'][name]=bool(value)
    if not value:raise AssertionError(name)
def command(label,args,**kwargs):
    started=time.monotonic();entry={'name':label,'argv':args};report['commands'].append(entry)
    result=subprocess.run(args,stderr=subprocess.PIPE,**kwargs)
    entry.update(exitCode=result.returncode,durationSeconds=round(time.monotonic()-started,4))
    if result.returncode:raise RuntimeError(label+' failed')
    print(label,'PASS',flush=True)
try:
    check('sourceShaMatchesFrozenFixture',sha(SOURCE)==SOURCE_SHA)
    manifest=flyway_manifest();check('exactFrozen29FilePins',len(manifest)==29 and tuple((m['version'],m['script'],m['sha256'],m['checksum']) for m in manifest)==EXPECTED_MIGRATIONS)
    report['flyway']=manifest;report['releaseIdentity']=release_identity()
    before_source=state(SOURCE_DATABASE);report['sourceBefore']=before_source
    check('sourceIsReadyR30',before_source['revision']==30 and len(before_source['projections'])==9 and all(s['status']=='ready' and s['revision']==30 for s in before_source['projections']))
    with psycopg.connect(**BASE,dbname='postgres',autocommit=True) as owner:
        owner.execute(sql.SQL('CREATE DATABASE {} OWNER migration_owner').format(sql.Identifier(DATABASE)));created=True
    with tempfile.TemporaryDirectory(prefix='mranked-reimport-dump-') as directory:
        dump=Path(directory)/'source.sql'
        with dump.open('wb') as stream:
            command('read-only-pg-dump',['docker','exec',CONTAINER,'pg_dump','-U','mranked_bootstrap','-d',SOURCE_DATABASE,'--clean','--if-exists'],stdout=stream,timeout=180)
        report['dumpSha256']=sha(dump);report['dumpBytes']=dump.stat().st_size
        with dump.open('rb') as stream:
            command('restore-owned-clone',['docker','exec','-i',CONTAINER,'psql','-U','mranked_bootstrap','-d',DATABASE,'-X','-q','-v','ON_ERROR_STOP=1','-c','SET session_replication_role=replica','-f','-'],stdin=stream,stdout=subprocess.DEVNULL,timeout=300)
    clone_before=state(DATABASE);report['cloneBefore']=clone_before
    check('cloneExactlyMatchesCanonicalSource',clone_before['canonicalSha256']==before_source['canonicalSha256'])
    check('cloneExactFlyway29', [m for m in clone_before['flyway'] if m['version'] is not None]==[{k:m[k] for k in ('version','script','checksum','success')} for m in manifest])
    before_hashes=hashes(DATABASE,'beforeHashes');report['tableHashesBefore']=before_hashes
    bridge_dsn=make_conninfo(host='127.0.0.1',port=55439,dbname=DATABASE,user='migration_bridge',password=secret_values['MIGRATION_BRIDGE_DB_PASSWORD'])
    started=time.monotonic()
    report['commands'].append({'name':'BridgeService.run','source':str(SOURCE),'sourceNamespace':NAMESPACE,'snapshotKind':'fixture','verify_projections':True,'verify_identity_history':True,'database':DATABASE,'databaseRole':'migration_bridge'})
    with PostgresTarget(bridge_dsn) as target:
        service=BridgeService(BridgeOptions(SOURCE,NAMESPACE,report_dir=OUTPUT/'bridge',verify_projections=True,verify_identity_history=True),LegacySource(SOURCE),target,snapshot_kind='fixture')
        prior=target.fetchone('SELECT status::text,source_sha256,snapshot_kind,source_name FROM migration.import_batch WHERE id=%s',(service.batch_id,))
        check('sameCompletedBatchBeforeImport',prior==('succeeded',SOURCE_SHA,'fixture',NAMESPACE))
        stats,reconciliation=service.run()
    report['timingsSeconds']['BridgeService.run']=round(time.monotonic()-started,4)
    report['commands'][-1].update(exitCode=0,durationSeconds=report['timingsSeconds']['BridgeService.run'])
    report['stats']=stats.as_dict()
    (OUTPUT/'reconciliation.json').write_text(json.dumps(reconciliation,ensure_ascii=False,indent=2,default=str)+'\n')
    print('BridgeService.run',stats.rows_written,reconciliation['gate'],flush=True)
    clone_after=state(DATABASE);report['cloneAfter']=clone_after
    after_hashes=hashes(DATABASE,'afterHashes');report['tableHashesAfter']=after_hashes
    after_source=state(SOURCE_DATABASE);report['sourceAfter']=after_source
    report['changedTables']=[name for name in before_hashes.keys()|after_hashes.keys() if before_hashes.get(name)!=after_hashes.get(name)]
    check('completedBatchRowsWrittenZero',stats.rows_written==0)
    check('noProjectionRebuild',stats.projection_rebuild is None)
    check('independentProjectionOraclePassed',reconciliation['projection_verification']['status']=='pass')
    check('independentIdentityHistoryOraclePassed',reconciliation['identity_history_verification']['status']=='pass')
    check('reconciliationZeroCriticalMismatches',reconciliation['gate']=={'status':'pass','critical_mismatches':0})
    check('allCanonicalProjectionHistoryHashesUnchanged',before_hashes==after_hashes)
    check('revisionAndNineProjectionReadinessUnchanged',clone_before['canonicalSha256']==clone_after['canonicalSha256'] and clone_after['revision']==30)
    check('sourceCanonicalStateUnchanged',before_source['canonicalSha256']==after_source['canonicalSha256'])
    check('sourceSqliteShaUnchanged',sha(SOURCE)==SOURCE_SHA)
    report['status']='pass'
except Exception as error:
    message=str(error)
    for key,value in secret_values.items():
        if 'PASSWORD' in key:message=message.replace(value,'[redacted]')
    report['status']='fail';report['errorType']=type(error).__name__;report['error']=message
    print('FAILED',type(error).__name__,message,flush=True)
finally:
    if created:
        with psycopg.connect(**BASE,dbname='postgres',autocommit=True) as owner:
            owner.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(DATABASE)))
    report['checks']['ownedCloneRemoved']=created
    report['durationSeconds']=round(time.monotonic()-began,4)
    report['digestMethod']='SHA-256 of complete PostgreSQL binary COPY streams ordered by primary key; all canonical/projection tables, migration facts/history, and outbox; technical reconciliation receipts excluded'
    report['harnessSha256']=sha(Path(__file__))
    (OUTPUT/'producer.py').write_bytes(Path(__file__).read_bytes())
    path=OUTPUT/'representative-reimport.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str,sort_keys=True)+'\n')
    path.with_suffix('.json.sha256').write_text(sha(path)+'  '+path.name+'\n')
    if (OUTPUT/'reconciliation.json').exists():
        p=OUTPUT/'reconciliation.json';p.with_suffix('.json.sha256').write_text(sha(p)+'  '+p.name+'\n')
print(json.dumps({'status':report['status'],'report':str(OUTPUT/'representative-reimport.json'),'timingsSeconds':report['timingsSeconds'],'durationSeconds':report['durationSeconds']}))
raise SystemExit(0 if report['status']=='pass' else 1)
