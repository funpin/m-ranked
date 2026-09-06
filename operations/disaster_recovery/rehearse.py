"""Physical backup, archived-WAL PITR and standby-promotion rehearsal.

Only a named local integration container may be read. All writes and stops are
restricted to UUID-named resources created by this run. No production endpoint,
upstream, writer switch, or production attestation is supported.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time
from uuid import uuid4

from operations.cold_archive.parquet import ParquetArchiveWriter, verify_archive
from operations.cold_archive.service import EXPORT_SQL

IMAGE = 'postgres:18.6'
LABEL = 'org.mranked.disposable-dr'
MANIFEST_SQL = """SELECT coalesce(jsonb_agg(jsonb_build_object('version',version,'script',script,'checksum',checksum,'success',success) ORDER BY installed_rank),'[]'::jsonb) FROM flyway.flyway_schema_history"""
STATE_SQL = """SELECT jsonb_build_object(
 'flyway',(SELECT jsonb_agg(jsonb_build_object('version',version,'script',script,'checksum',checksum,'success',success) ORDER BY installed_rank) FROM flyway.flyway_schema_history),
 'revision',(SELECT max(id) FROM analytics.dataset_revision),
 'projections',(SELECT coalesce(jsonb_agg(jsonb_build_object('name',projection_name,'status',status,'revision',dataset_revision_id,'rowCount',row_count) ORDER BY projection_name),'[]'::jsonb) FROM analytics.projection_state),
 'institutions',(SELECT count(*) FROM catalog.institution),
 'accounts',(SELECT count(*) FROM catalog.platform_account),
 'publications',(SELECT count(*) FROM ingest.publication),
 'snapshots',(SELECT count(*) FROM ingest.publication_metric_snapshot),
 'partitions',(SELECT coalesce(jsonb_agg(to_jsonb(d)||jsonb_build_object('month',m.published_month) ORDER BY m.published_month),'[]'::jsonb) FROM (SELECT DISTINCT published_month FROM ingest.publication_metric_snapshot) m CROSS JOIN LATERAL ops_and_admin.publication_partition_digest(m.published_month) d),
 'unvalidatedConstraints',(SELECT count(*) FROM pg_constraint WHERE connamespace IN ('ingest'::regnamespace,'catalog'::regnamespace,'analytics'::regnamespace) AND NOT convalidated),
 'sizeBytes',pg_database_size(current_database()))"""


class Rehearsal:
    def __init__(self, source_container: str, source_database: str, report_dir: Path):
        if not re.fullmatch(r'mranked-[a-z0-9-]*it[a-z0-9-]*-postgres-1', source_container):
            raise ValueError('source must be an explicitly named local mranked integration container')
        if not re.fullmatch(r'[a-z][a-z0-9_]*_it', source_database):
            raise ValueError('source database must be a disposable *_it fixture')
        self.source = source_container
        self.database = source_database
        self.report_dir = report_dir.resolve()
        self.run_id = uuid4().hex[:12]
        self.prefix = 'mranked-dr-' + self.run_id
        self.containers: list[str] = []
        self.volumes: list[str] = []
        self.network: str | None = None
        self.passwords = {key: secrets.token_hex(24) for key in (
            'POSTGRES_PASSWORD','MIGRATION_DB_PASSWORD','API_READ_DB_PASSWORD',
            'API_WRITE_ADMIN_DB_PASSWORD','COLLECTOR_INGEST_DB_PASSWORD',
            'BACKUP_DB_PASSWORD','MIGRATION_BRIDGE_DB_PASSWORD','MAINTENANCE_DB_PASSWORD')}
        self.report = {'formatVersion':1,'scope':'disposable-local-physical-rehearsal',
                       'productionAcceptance':False,'runId':self.run_id,'image':IMAGE,
                       'sourceContainer':source_container,'sourceDatabase':source_database,
                       'startedAt':datetime.now(timezone.utc).isoformat(),
                       'commands':[],'checks':{},'measurements':{},'status':'running'}

    def run(self, args: list[str], *, body: str | bytes | None = None, timeout=90,
            description: str | None = None, check=True) -> str:
        began=time.monotonic()
        self.report['commands'].append({'action':description or ' '.join(args), 'startedAt':datetime.now(timezone.utc).isoformat()})
        result=subprocess.run(['docker',*args],input=body.encode() if isinstance(body,str) else body,
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
        output=(result.stdout+result.stderr).decode(errors='replace')
        for value in self.passwords.values(): output=output.replace(value,'[REDACTED]')
        self.report['commands'][-1].update(exitCode=result.returncode,durationSeconds=round(time.monotonic()-began,4))
        if check and result.returncode:
            raise RuntimeError((description or 'docker command')+' failed: '+output[-3000:])
        stdout=(result.stdout+result.stderr if args[0]=='logs' else result.stdout).decode(errors='replace').strip()
        for value in self.passwords.values(): stdout=stdout.replace(value,'[REDACTED]')
        return stdout

    def query(self, container: str, statement: str, *, database: str | None = None) -> str:
        return self.run(['exec','-i',container,'psql','-U','mranked_bootstrap','-d',database or self.database,
                         '-X','-q','-A','-t','-v','ON_ERROR_STOP=1'],body=statement,
                        description='SQL verification in '+container)

    def wait(self, predicate, label: str, timeout=60):
        deadline=time.monotonic()+timeout
        last_error=None
        while time.monotonic()<deadline:
            try:
                if predicate(): return
            except RuntimeError as error:
                last_error=str(error)
            time.sleep(.25)
        raise TimeoutError(label+(': '+last_error if last_error else ''))

    def volume(self, suffix: str) -> str:
        name=self.prefix+'-'+suffix
        self.run(['volume','create','--label',LABEL+'='+self.run_id,name])
        self.volumes.append(name)
        return name

    def state(self, container: str) -> dict:
        state=json.loads(self.query(container,STATE_SQL))
        state['canonicalSha256']=hashlib.sha256(json.dumps({k:v for k,v in state.items() if k!='sizeBytes'},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        return state

    def copy_backup(self, backup: str, destination: str):
        self.run(['run','--rm','-v',backup+':/backup:ro','-v',destination+':/data',IMAGE,
                  'sh','-ec','cp -a /backup/base/. /data/; chmod 0700 /data; chown -R postgres:postgres /data'],
                 description='Restore physical base backup into own empty volume')

    def configure(self, volume: str, content: str, signal: str):
        self.run(['run','--rm','-i','-v',volume+':/data',IMAGE,'sh','-ec',
                  'cat > /data/postgresql.auto.conf; touch /data/'+signal+'; chown postgres:postgres /data/postgresql.auto.conf /data/'+signal+'; chmod 0600 /data/postgresql.auto.conf'],
                 body=content,description='Write isolated recovery configuration (credentials omitted)')

    def start_restore(self, suffix: str, volume: str, archive: str, *, standby: bool = False) -> str:
        name=self.prefix+'-'+suffix
        self.run(['run','-d','--name',name,'--label',LABEL+'='+self.run_id,'--network',self.network,
                  '-e','PGDATA=/data','-v',volume+':/data','-v',archive+':/archive:ro',IMAGE,
                  'postgres','-c','listen_addresses=*','-c','archive_mode=off','-c','max_wal_senders=12'])
        self.containers.append(name)
        try:
            # Hot standby accepts SELECT before WAL reaches a named recovery
            # target. That is not a completed writable full/PITR restore.
            readiness=("SELECT pg_is_in_recovery() AND current_setting('transaction_read_only')='on'"
                       if standby else "SELECT NOT pg_is_in_recovery() AND current_setting('transaction_read_only')='off'")
            self.wait(lambda:self.query(name,readiness)=='t',suffix+' recovery-state readiness')
        except Exception:
            self.report.setdefault('recoveryDiagnostics',[]).append({'server':suffix,'logs':self.run(['logs','--tail','100',name],check=False,description='Read sanitized logs of own failed recovery server')})
            raise
        return name

    def stop_and_checksums(self, container: str, volume: str):
        self.run(['stop','--time','30',container])
        self.run(['run','--rm','--user','postgres','-v',volume+':/data',IMAGE,'pg_checksums','--check','-D','/data'],
                 description='Offline PostgreSQL page-checksum verification')

    def archive_fixture(self, primary: str) -> tuple[Path, dict]:
        """Stream the production archive schema through the maintenance role.

        The artifact is outside the primary's Docker volume. This is a local
        archive-read rehearsal, never a provider attestation or DROP authority.
        """
        month=date.fromisoformat(self.query(primary,'SELECT min(published_month) FROM ingest.publication_metric_snapshot'))
        literal="DATE '"+month.isoformat()+"'"
        self.query(primary,'SET ROLE maintenance; SELECT ops_and_admin.begin_publication_archive('+literal+')')
        expected=json.loads(self.query(primary,'SET ROLE maintenance; SELECT to_jsonb(d) FROM ops_and_admin.publication_partition_digest('+literal+') d'))
        path=self.report_dir/('cold-'+self.run_id+'.parquet')
        sql='SET ROLE maintenance; BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY; SELECT row_to_json(archive_row) FROM ('+EXPORT_SQL.replace('%s',literal)+') archive_row; COMMIT;'
        began=time.monotonic()
        with tempfile.TemporaryFile() as errors:
            process=subprocess.Popen(['docker','exec','-i',primary,'psql','-U','mranked_bootstrap','-d',self.database,'-X','-q','-A','-t','-v','ON_ERROR_STOP=1'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors)
            try:
                process.stdin.write(sql.encode()); process.stdin.close()
                with ParquetArchiveWriter(path) as writer:
                    batch=[]
                    for line in process.stdout:
                        if not line.strip(): continue
                        row=json.loads(line)
                        row['published_month']=date.fromisoformat(row['published_month'])
                        for key in ('published_at','observed_at','collected_at','created_at'):
                            row[key]=datetime.fromisoformat(row[key])
                        batch.append(row)
                        if len(batch)==500: writer.append(batch); batch=[]
                    writer.append(batch)
                if process.wait(timeout=90): raise RuntimeError('bounded archive export failed')
            finally:
                if process.poll() is None: process.kill(); process.wait()
        path.chmod(0o600)
        verified=verify_archive(path,expected_row_count=expected['row_count'])
        if verified.canonical_sha256!=expected['canonical_sha256']: raise RuntimeError('archive canonical digest differs')
        self.query(primary,'SET ROLE maintenance; SELECT ops_and_admin.abort_publication_archive('+literal+')')
        record={'path':path.name,'schemaVersion':3,'sha256':verified.sha256,
                'canonicalSha256':verified.canonical_sha256,'rowCount':verified.row_count,
                'exportSeconds':round(time.monotonic()-began,4),'providerAttestation':False}
        self.report['commands'].append({'action':'Bounded maintenance-role Parquet export and full canonical verification','exitCode':0,'durationSeconds':record['exportSeconds']})
        return path,record

    def execute(self):
        started=time.monotonic()
        self.report_dir.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='mranked-dr-secret-') as secret_dir:
            env=Path(secret_dir)/'fixture.env'
            env.write_text('\n'.join(k+'='+v for k,v in self.passwords.items())+'\n')
            env.chmod(0o600)
            try:
                before=self.state(self.source)
                if before['snapshots']<1 or not before['flyway'] or before['unvalidatedConstraints']:
                    raise ValueError('source must contain representative validated Flyway/canonical data')
                if not before['projections'] or any(item['status']!='ready' or item['revision']!=before['revision'] for item in before['projections']):
                    raise ValueError('source projections must all be ready at the canonical revision')
                self.report['sourceState']=before
                self.network=self.prefix+'-net'
                self.run(['network','create','--internal','--label',LABEL+'='+self.run_id,self.network])
                primary_data=self.volume('primary'); archive=self.volume('wal'); backup=self.volume('backup')
                self.run(['run','--rm','-v',archive+':/archive','-v',backup+':/backup',IMAGE,
                          'sh','-ec','chown postgres:postgres /archive /backup; chmod 0700 /archive /backup'])
                primary=self.prefix+'-primary'
                init=Path('infra/postgres/init').resolve()
                self.run(['run','-d','--name',primary,'--label',LABEL+'='+self.run_id,'--network',self.network,
                          '--env-file',str(env),'-e','POSTGRES_DB='+self.database,'-e','POSTGRES_USER=mranked_bootstrap',
                          '-e','POSTGRES_INITDB_ARGS=--data-checksums','-e','PGDATA=/var/lib/postgresql/18/docker',
                          '-v',primary_data+':/var/lib/postgresql','-v',archive+':/archive','-v',backup+':/backup',
                          '-v',str(init)+':/docker-entrypoint-initdb.d:ro',IMAGE,'postgres',
                          '-c','wal_level=replica','-c','archive_mode=on','-c',
                          'archive_command=test ! -f /archive/%f && cp %p /archive/%f','-c','max_wal_senders=12',
                          '-c','wal_keep_size=128MB'],description='Start own checksum-enabled primary with independent WAL/basebackup volumes')
                self.containers.append(primary)
                # The official image briefly starts a socket-only init server.
                # It must not satisfy readiness before role initialization and
                # the final postmaster have completed.
                self.wait(lambda:self.query(primary,"SELECT current_setting('listen_addresses')='*' AND EXISTS(SELECT 1 FROM pg_roles WHERE rolname='backup')")=='t','primary readiness')
                self.run(['exec',primary,'sh','-ec',
                          'printf "%s\\n" "host replication backup all scram-sha-256" >> "$PGDATA/pg_hba.conf"'],
                         description='Allow password-authenticated replication only inside the isolated Docker network')
                self.query(primary,'SELECT pg_reload_conf()')
                # Dump output is streamed via an on-disk file, never retained in
                # model-visible logs or interpreted as shell code.
                dump=Path(secret_dir)/'fixture.sql'
                with dump.open('wb') as output:
                    result=subprocess.run(['docker','exec',self.source,'pg_dump','-U','mranked_bootstrap','-d',self.database,
                                           '--clean','--if-exists'],stdout=output,stderr=subprocess.PIPE,timeout=120)
                if result.returncode: raise RuntimeError('read-only fixture pg_dump failed')
                digest=hashlib.sha256()
                with dump.open('rb') as stream:
                    for chunk in iter(lambda:stream.read(1024*1024),b''): digest.update(chunk)
                self.report['fixtureDumpSha256']=digest.hexdigest()
                with dump.open('rb') as stream:
                    restored=subprocess.run(['docker','exec','-i',primary,'psql','-U','mranked_bootstrap','-d',self.database,
                                              '-X','-q','-v','ON_ERROR_STOP=1','-c','SET session_replication_role=replica','-f','-'],stdin=stream,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
                if restored.returncode: raise RuntimeError('disposable dump restore failed: '+restored.stderr.decode()[-1500:])
                after=self.state(self.source)
                if after['canonicalSha256']!=before['canonicalSha256']: raise RuntimeError('source fixture changed while dumping')
                cloned=self.state(primary)
                if cloned['canonicalSha256']!=before['canonicalSha256']: raise RuntimeError('logical bootstrap differs from frozen fixture')
                self.report['checks']['independentSourceClone']=True
                archive_path,archive_record=self.archive_fixture(primary)
                self.report['coldArchive']=archive_record
                self.query(primary,"CREATE TABLE public.dr_marker(id text PRIMARY KEY,committed_at timestamptz NOT NULL DEFAULT clock_timestamp()); INSERT INTO public.dr_marker(id) VALUES('baseline');")
                roles=json.loads(self.query(primary,"SELECT jsonb_build_object('backupReplication',rolreplication,'backupSuperuser',rolsuper,'backupCreateDb',rolcreatedb,'backupCreateRole',rolcreaterole) FROM pg_roles WHERE rolname='backup'"))
                if roles!={'backupReplication':True,'backupSuperuser':False,'backupCreateDb':False,'backupCreateRole':False}: raise RuntimeError('backup role privilege drift')
                self.report['roles']=roles
                began=time.monotonic()
                self.run(['exec','--user','postgres',primary,'sh','-ec','PGPASSWORD="$BACKUP_DB_PASSWORD" pg_basebackup -h 127.0.0.1 -U backup -D /backup/base -Fp -X stream --checkpoint=fast --label=disposable-dr'],timeout=180,description='pg_basebackup using restricted replication role')
                self.run(['exec','--user','postgres',primary,'pg_verifybackup','/backup/base'],description='pg_verifybackup validates manifest and WAL')
                self.report['measurements']['baseBackupSeconds']=round(time.monotonic()-began,4)
                self.report['backupManifestSha256']=self.run(['exec',primary,'sha256sum','/backup/base/backup_manifest']).split()[0]
                self.report['checks']['physicalBackupVerified']=True
                standby_data=self.volume('standby'); self.copy_backup(backup,standby_data)
                config="primary_conninfo = 'host="+primary+" port=5432 user=backup password="+self.passwords['BACKUP_DB_PASSWORD']+" application_name=dr_standby'\nhot_standby = on\n"
                self.configure(standby_data,config,'standby.signal')
                standby=self.start_restore('standby',standby_data,archive,standby=True)
                self.wait(lambda:self.query(standby,"SELECT pg_is_in_recovery() AND current_setting('transaction_read_only')='on'")=='t','standby recovery')
                included=self.query(primary,"INSERT INTO public.dr_marker(id) VALUES('pitr-included') RETURNING committed_at::text")
                target='dr_target_'+self.run_id
                self.query(primary,"SELECT pg_create_restore_point('"+target+"')")
                excluded=self.query(primary,"INSERT INTO public.dr_marker(id) VALUES('pitr-excluded') RETURNING committed_at::text")
                wal=self.query(primary,'SELECT pg_walfile_name(pg_current_wal_insert_lsn())')
                self.query(primary,'SELECT pg_switch_wal()')
                self.wait(lambda:self.query(primary,"SELECT coalesce(last_archived_wal >= '"+wal+"',false) FROM pg_stat_archiver")=='t','archive durable segment')
                self.wait(lambda:self.query(standby,"SELECT count(*) FROM public.dr_marker WHERE id='pitr-excluded'")=='1','standby exact catch-up')
                self.report['checks']['streamingStandbyCaughtUp']=True
                self.report['walFiles']=self.run(['exec',primary,'sh','-ec','cd /archive; sha256sum *']).splitlines()
                outage=time.monotonic()
                self.run(['stop','--time','30',primary],description='Simulate loss of only the UUID-owned primary')
                archive_began=time.monotonic()
                fallback=verify_archive(archive_path,expected_row_count=archive_record['rowCount'],expected_sha256=archive_record['sha256'])
                if fallback.canonical_sha256!=archive_record['canonicalSha256']: raise RuntimeError('archive fallback digest mismatch')
                self.report['measurements']['coldArchiveFallbackSeconds']=round(time.monotonic()-archive_began,4)
                self.report['checks']['coldArchiveFallbackWithPrimaryStopped']=True
                self.query(standby,'SELECT pg_promote(true,30)')
                if self.query(standby,"SELECT NOT pg_is_in_recovery() AND (SELECT count(*)=3 FROM public.dr_marker)")!='t': raise RuntimeError('standby promotion lost a committed marker')
                self.report['measurements']['standbyControlledRpoSeconds']=0
                if self.state(standby)['canonicalSha256']!=before['canonicalSha256']: raise RuntimeError('promoted canonical state differs')
                self.report['measurements']['standbyPromotionRtoSeconds']=round(time.monotonic()-outage,4)
                self.report['checks']['standbyPromotion']=True
                full_data=self.volume('full-restore'); began=time.monotonic(); self.copy_backup(backup,full_data)
                full=self.start_restore('full-restore',full_data,archive)
                if self.query(full,'SELECT count(*) FROM public.dr_marker')!='1': raise RuntimeError('basebackup restore crossed its captured boundary')
                if self.state(full)['canonicalSha256']!=before['canonicalSha256']: raise RuntimeError('restored manifest/canonical data differs')
                self.run(['exec',full,'pg_amcheck','--all','--install-missing','-U','mranked_bootstrap'],description='pg_amcheck full restored cluster (diagnostic extension installed only in disposable restore)')
                self.report['measurements']['fullRestoreRtoSeconds']=round(time.monotonic()-began,4)
                self.stop_and_checksums(full,full_data)
                self.report['checks']['fullRestorePageChecksumsAndAmcheck']=True
                pitr_data=self.volume('pitr'); began=time.monotonic(); self.copy_backup(backup,pitr_data)
                self.configure(pitr_data,"restore_command = 'cp /archive/%f %p'\nrecovery_target_name = '"+target+"'\nrecovery_target_action = 'promote'\n",'recovery.signal')
                pitr=self.start_restore('pitr',pitr_data,archive)
                markers=json.loads(self.query(pitr,"SELECT jsonb_agg(id ORDER BY id) FROM public.dr_marker"))
                in_recovery=self.query(pitr,'SELECT pg_is_in_recovery()')!='f'
                self.report['pitr']={'method':'named WAL restore point','restorePoint':target,'includedCommittedAt':included,
                                    'excludedCommittedAt':excluded,'restoredMarkers':markers,'inRecovery':in_recovery}
                if markers!=['baseline','pitr-included'] or in_recovery:
                    self.report.setdefault('recoveryDiagnostics',[]).append({'server':'pitr','logs':self.run(['logs','--tail','100',pitr],check=False,description='Read sanitized logs of own PITR boundary failure')})
                    raise RuntimeError('PITR boundary assertion failed')
                if self.state(pitr)['canonicalSha256']!=before['canonicalSha256']: raise RuntimeError('PITR manifest/canonical data differs')
                self.run(['exec',pitr,'pg_amcheck','--all','--install-missing','-U','mranked_bootstrap'],description='pg_amcheck PITR restored cluster (diagnostic extension installed only in disposable restore)')
                self.report['measurements']['pitrRestoreRtoSeconds']=round(time.monotonic()-began,4)
                gap=(datetime.fromisoformat(excluded)-datetime.fromisoformat(included)).total_seconds()
                self.report['measurements']['pitrControlledRpoSeconds']=gap
                self.stop_and_checksums(pitr,pitr_data)
                self.stop_and_checksums(standby,standby_data)
                self.report['checks']['pitrBoundaryPageChecksumsAndAmcheck']=True
                self.report['checks']['promotedStandbyPageChecksums']=True
                self.report['checks']['sameExactFlywayManifest']=True
                measures=self.report['measurements']
                self.report['checks']['localRpoBudget']=max(measures['pitrControlledRpoSeconds'],measures['standbyControlledRpoSeconds'])<=900
                self.report['checks']['localRtoBudget']=max(measures[k] for k in ('standbyPromotionRtoSeconds','fullRestoreRtoSeconds','pitrRestoreRtoSeconds'))<=7200
                if not all(self.report['checks'].values()): raise RuntimeError('rehearsal budget failure')
                self.report['status']='pass'
            except Exception as error:
                message=str(error)
                for value in self.passwords.values(): message=message.replace(value,'[REDACTED]')
                self.report['status']='fail'; self.report['error']=message
                raise
            finally:
                cleanup_ok=True
                cleanup=[(['rm','-f',name],'container') for name in reversed(self.containers)]
                cleanup += [(['volume','rm',name],'volume') for name in reversed(self.volumes)]
                if self.network: cleanup.append((['network','rm',self.network],'network'))
                for command,kind in cleanup:
                    try:
                        self.run(command,description='Cleanup UUID-owned fixture '+kind,check=False)
                        cleanup_ok &= self.report['commands'][-1]['exitCode']==0
                    except Exception:
                        cleanup_ok=False
                self.report['checks']['ownedResourcesCleaned']=cleanup_ok
                if not cleanup_ok: self.report['status']='fail'
                self.report['durationSeconds']=round(time.monotonic()-started,4)
                self.report['finishedAt']=datetime.now(timezone.utc).isoformat()
                self.report['externalGates']=['Separate physical DR host and encrypted channel','Production-like capacity and concurrent workload','pgBackRest encrypted multi-repository retention acceptance','Provider immutable cold archive attestation','Production RPO/RTO acceptance and named operator approval']
                path=self.report_dir/('dr-'+self.run_id+'.json')
                text=json.dumps(self.report,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
                for value in self.passwords.values(): text=text.replace(value,'[REDACTED]')
                path.write_text(text); path.with_suffix('.json.sha256').write_text(hashlib.sha256(text.encode()).hexdigest()+'  '+path.name+'\n')
                markdown=['# Disposable PostgreSQL recovery rehearsal','',
                          '**Status:** '+self.report['status']+'. **Production acceptance:** false.','',
                          'Source: `'+self.source+' / '+self.database+'`. No source writes or stops.','',
                          '| Measurement | Seconds |','|---|---:|']
                markdown.extend('| '+key+' | '+str(value)+' |' for key,value in self.report['measurements'].items())
                markdown.extend(['','| Check | Result |','|---|---|'])
                markdown.extend('| '+key+' | '+str(value)+' |' for key,value in self.report['checks'].items())
                markdown.extend(['','Exact command descriptions, durations, canonical digests, WAL/basebackup checksums, Flyway manifest and controlled PITR boundary: ['+path.name+']('+path.name+').','',
                                 'RTO includes Docker start/restore and integrity/readiness checks. Standby RPO is zero only for the acknowledged catch-up marker. PITR RPO is the measured gap between included and intentionally excluded commits; this is a controlled failure drill, not observed production archive lag.','',
                                 'Remaining external acceptance gates:',''])
                markdown.extend('- '+gate for gate in self.report['externalGates'])
                if self.report.get('error'): markdown.extend(['','Failure: '+self.report['error']])
                path.with_suffix('.md').write_text('\n'.join(markdown)+'\n')
                print(json.dumps({'status':self.report['status'],'report':str(path),'measurements':self.report['measurements']}))
                if not cleanup_ok: raise RuntimeError('UUID-owned resource cleanup incomplete; inspect report')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-container',required=True)
    parser.add_argument('--source-database',required=True)
    parser.add_argument('--report-dir',type=Path,required=True)
    args=parser.parse_args()
    try:
        Rehearsal(args.source_container,args.source_database,args.report_dir).execute()
    except Exception:
        # The sanitized failure and cleanup evidence are in the report; never
        # echo raw driver/authentication exception details to terminal logs.
        raise SystemExit(1) from None

if __name__=='__main__': main()
