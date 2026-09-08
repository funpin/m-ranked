#!/usr/bin/env python3
"""Required integration gate with real, self-provisioned PostgreSQL and Redis.

Only creates a randomly named Compose project with fresh volumes/passwords.
No existing database or deployment configuration is accepted as a test target.
Logs and commands are retained; passwords stay in a mode-0600 temporary file.
"""
from __future__ import annotations
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import urllib.request
import xml.etree.ElementTree as ET
from migration.integration.evidence import retain_spring_junit

ROOT = Path(__file__).resolve().parents[2]
PASSWORDS = ('POSTGRES_SUPERUSER_PASSWORD','MIGRATION_DB_PASSWORD','API_READ_DB_PASSWORD',
             'API_WRITE_ADMIN_DB_PASSWORD','COLLECTOR_INGEST_DB_PASSWORD','BACKUP_DB_PASSWORD',
             'MIGRATION_BRIDGE_DB_PASSWORD','MAINTENANCE_DB_PASSWORD','REDIS_PASSWORD')


def free_port():
    with closing(socket.socket()) as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


class Gate:
    def __init__(self, output: Path):
        self.output = output.resolve()
        if (self.output/'integration.json').exists():
            raise FileExistsError('integration evidence already exists; choose a new output directory')
        self.output.mkdir(parents=True, exist_ok=True)
        self.output.chmod(0o700)
        self.results = []
        self.environment = dict(os.environ)

    def command(self, name, args, *, env=None, cwd=ROOT, timeout=900):
        print(f'[{name}] started', flush=True)
        start = time.monotonic()
        command_env=self.environment | (env or {})
        if args[1:3] == ['-m','pytest'] and hasattr(self, 'pytest_tmpdir'):
            # Only provenance fixtures need the private ancestry. Browser/Node
            # IPC sockets must retain the host's short system temporary path.
            command_env['TMPDIR']=self.pytest_tmpdir
        with (self.output / f'{name}.log').open('w') as log:
            try:
                result = subprocess.run(args, cwd=cwd, env=command_env,
                                        stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
                code = result.returncode
            except subprocess.TimeoutExpired:
                code = 124
        contents = (self.output / f'{name}.log').read_text(errors='replace')
        for secret in getattr(self, 'secrets', {}).values():
            contents = contents.replace(secret, '[redacted]')
        (self.output / f'{name}.log').write_text(contents)
        self.results.append({'name':name,'command':args,'exitCode':code,
                             'durationSeconds':round(time.monotonic()-start,3)})
        self.save()
        print(f'[{name}] exit={code}', flush=True)
        if name in ('spring', 'query-plans') and any((self.output/'backend-build/surefire-reports').glob('TEST-*.xml')):
            retain_spring_junit(self.output, getattr(self, 'secrets', {}).values())
        if code:
            # PostgreSQL appends long SQL context after the actual exception.
            # Retain both ends within the same bounded, already-redacted log.
            excerpt = contents if len(contents) <= 6000 else (
                contents[:4000] + '\n[... full diagnostic in retained log ...]\n' + contents[-2000:]
            )
            print(excerpt, flush=True)
            raise RuntimeError(f'{name} failed; see retained log')

    def save(self):
        payload = {'reportVersion':1,'environment':'disposable-local-compose',
                   'generatedAt':datetime.now(timezone.utc).isoformat(),
                   'productionAcceptance':False,'checks':self.results}
        (self.output/'integration.json').write_text(json.dumps(payload,indent=2)+'\n')

    def junit_no_skip(self, path):
        root = ET.parse(path).getroot()
        cases = list(root.iter('testcase'))
        if not cases or any(list(c.iter('skipped')) for c in cases):
            raise RuntimeError(f'{path.name}: required integration tests were skipped')

    def run(self, *, python, maven, visual=False, semantic_only=False):
        resolved_python=shutil.which(python)
        if resolved_python is None:
            raise FileNotFoundError('integration Python executable is unavailable')
        self.environment['MRANKED_INTEGRATION_PYTHON']=resolved_python
        project = 'mranked-ci-'+uuid.uuid4().hex[:12]
        pg_port, redis_port = free_port(), free_port()
        self.secrets = {key:secrets.token_hex(24) for key in PASSWORDS}
        # Provenance fixtures deliberately reject any world-writable ancestor
        # (including /tmp). Keep disposable runtime files below the private run
        # directory and give pytest children the same trusted temporary root.
        with tempfile.TemporaryDirectory(prefix='mranked-integration-', dir=self.output) as directory:
            # macOS exposes its temp directory through /var -> /private/var.
            # Resolve this already-owned directory before handing its path to
            # producers that intentionally reject symlinked storage ancestors.
            directory=str(Path(directory).resolve())
            self.pytest_tmpdir=directory
            self.environment['MRANKED_IDENTITY_RECEIPT_DIR']=str(Path(directory)/'identity-receipts')
            envfile = Path(directory)/'services.env'
            envfile.write_text('\n'.join(k+'='+v for k,v in self.secrets.items())+
                               f'\nPOSTGRES_PORT={pg_port}\nREDIS_PORT={redis_port}\n')
            envfile.chmod(0o600)
            compose=['docker','compose','--project-name',project,'--env-file',str(envfile),'-f',str(ROOT/'infra/compose.yaml')]
            container=project+'-postgres-1'
            dbnames=(('clean_it','second_clean_it','bridge_it') if visual or semantic_only else
                     ('clean_it','second_clean_it','bridge_it','collector_it','reverse_it','ledger_it','catalog_it','native_it','history_it','partition_it'))
            def url(db): return f'jdbc:postgresql://127.0.0.1:{pg_port}/{db}'
            def dsn(db,role,key):
                return f'host=127.0.0.1 port={pg_port} dbname={db} user={role} password={self.secrets[key]}'
            migration_env={'MRANKED_MIGRATION_TEST_URL':url('clean_it'),
                'MRANKED_SECOND_SCHEMA_TEST_URL':url('second_clean_it'),
                'MRANKED_MIGRATION_TEST_USER':'migration_owner',
                'MRANKED_MIGRATION_TEST_PASSWORD':self.secrets['MIGRATION_DB_PASSWORD']}
            mvn=[maven,'-Dmranked.build.directory='+str(self.output/'backend-build'),*(['-Dmaven.repo.local='+os.environ['MRANKED_MAVEN_REPOSITORY']] if os.getenv('MRANKED_MAVEN_REPOSITORY') else [])]
            try:
                self.command('services',compose+['up','-d','--wait','postgres','redis'])
                for db in dbnames:
                    self.command('create-'+db,['docker','exec',container,'psql','-U','mranked_bootstrap','-d','postgres','-v','ON_ERROR_STOP=1','-c',f'CREATE DATABASE {db} OWNER migration_owner'])
                if not (visual or semantic_only):
                    self.command('create-golden_it',['docker','exec',container,'psql','-U','mranked_bootstrap','-d','postgres','-v','ON_ERROR_STOP=1','-c','CREATE DATABASE golden_it OWNER migration_owner'])
                self.command('final-schema-clean-install',mvn+['-Pschema-integration','-Dtest=MigrationInstallationTest#cleanInstallationCreatesFinalContract','test'],env=migration_env,cwd=ROOT/'backend')
                for db in dbnames[2:]:
                    self.command('final-schema-'+db,mvn+['-Pschema-integration','-Dtest=MigrationInstallationTest#installAdditionalDisposableRehearsalDatabase','test'],env=migration_env|{'MRANKED_REHEARSAL_INSTALL_URL':url(db)},cwd=ROOT/'backend')
                self.command('redis-ping',['docker','exec',project+'-redis-1','sh','-c','REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning ping'])
                if visual or semantic_only:
                    self.visual(python=python,mvn=mvn,directory=Path(directory),database_url=url('bridge_it'),
                                bridge_dsn=dsn('bridge_it','migration_bridge','MIGRATION_BRIDGE_DB_PASSWORD'),
                                inspect_dsn=dsn('bridge_it','migration_owner','MIGRATION_DB_PASSWORD'),
                                capture_visual=not semantic_only)
                    return
                pg=dsn('bridge_it','migration_bridge','MIGRATION_BRIDGE_DB_PASSWORD')
                admin=dsn('bridge_it','mranked_bootstrap','POSTGRES_SUPERUSER_PASSWORD')
                # Performance fixtures import their own source namespaces. Keep
                # them out of the exact identity-history and query-plan corpus.
                self.command('partition-batches',[python,'-m','pytest','-q','tests/test_migration_partition_postgres.py','--junitxml='+str(self.output/'partition-batches.xml')],env={'MRANKED_TEST_POSTGRES_DSN':dsn('partition_it','migration_bridge','MIGRATION_BRIDGE_DB_PASSWORD')})
                self.junit_no_skip(self.output/'partition-batches.xml')
                self.command('bridge',[python,'-m','pytest','-q','tests/test_migration_bridge_postgres.py','tests/test_bridge_actual_target_postgres.py','-k','not missing_source_row and not cleared_native_identity','--junitxml='+str(self.output/'bridge.xml')],env={'MRANKED_TEST_POSTGRES_DSN':pg,'MRANKED_TEST_POSTGRES_ADMIN_DSN':admin})
                self.junit_no_skip(self.output/'bridge.xml')
                # Native clear/re-enrollment starts from its own accepted source.
                # The correction test intentionally leaves a different immutable
                # tip in bridge_it; restoring an old completed batch cannot erase it.
                self.command('native-identity',[python,'-m','pytest','-q','tests/test_bridge_actual_target_postgres.py::test_cleared_native_identity_closes_history_and_reenrollment_appends','--junitxml='+str(self.output/'native-identity.xml')],env={'MRANKED_TEST_POSTGRES_ADMIN_DSN':dsn('native_it','mranked_bootstrap','POSTGRES_SUPERUSER_PASSWORD')})
                self.junit_no_skip(self.output/'native-identity.xml')
                self.command('identity-history',[python,'-m','pytest','-q','tests/test_identity_history_postgres.py','--junitxml='+str(self.output/'identity-history.xml')],env={'MRANKED_TEST_POSTGRES_ADMIN_DSN':dsn('history_it','mranked_bootstrap','POSTGRES_SUPERUSER_PASSWORD')})
                self.junit_no_skip(self.output/'identity-history.xml')
                self.command('preserved-source',[python,'-m','pytest','-q','tests/test_bridge_actual_target_postgres.py::test_missing_source_row_requires_verified_owner_ledger_and_remains_checked','--junitxml='+str(self.output/'preserved-source.xml')],env={'MRANKED_TEST_POSTGRES_ADMIN_DSN':dsn('ledger_it','mranked_bootstrap','POSTGRES_SUPERUSER_PASSWORD')})
                self.junit_no_skip(self.output/'preserved-source.xml')
                self.command('archive',[python,'-m','pytest','-q','tests/test_cold_archive_postgres.py','--junitxml='+str(self.output/'archive.xml')],env={'MRANKED_TEST_MAINTENANCE_DSN':dsn('bridge_it','maintenance','MAINTENANCE_DB_PASSWORD')})
                self.junit_no_skip(self.output/'archive.xml')
                self.command('collectors',[python,'-m','pytest','-q','tests/test_target_collectors_postgres.py','--junitxml='+str(self.output/'collectors.xml')],env={'MRANKED_TEST_POSTGRES_DSN':dsn('collector_it','collector_ingest','COLLECTOR_INGEST_DB_PASSWORD'),'MRANKED_TEST_POSTGRES_ADMIN_DSN':dsn('collector_it','mranked_bootstrap','POSTGRES_SUPERUSER_PASSWORD')})
                self.junit_no_skip(self.output/'collectors.xml')
                self.command('observation-integrity',[python,'-m','pytest','-q','tests/test_observation_integrity_postgres.py','tests/test_operational_projection_guards.py','--junitxml='+str(self.output/'observations.xml')],env={'MRANKED_TEST_POSTGRES_ADMIN_DSN':dsn('collector_it','mranked_bootstrap','POSTGRES_SUPERUSER_PASSWORD')})
                self.junit_no_skip(self.output/'observations.xml')
                self.command('operations-metrics',[python,'-m','pytest','-q','tests/test_operations_metrics_postgres.py','--junitxml='+str(self.output/'metrics.xml')],env={
                    'MRANKED_TEST_METRICS_MONITOR_DSN':dsn('bridge_it','backup','BACKUP_DB_PASSWORD'),
                    'MRANKED_TEST_METRICS_APPLICATION_DSN':dsn('bridge_it','maintenance','MAINTENANCE_DB_PASSWORD'),
                    'MRANKED_TEST_METRICS_REDIS_URL':f'redis://:{self.secrets["REDIS_PASSWORD"]}@127.0.0.1:{redis_port}/0'})
                self.junit_no_skip(self.output/'metrics.xml')
                backend_env={'MRANKED_ADMIN_TEST_POSTGRES_URL':url('clean_it'),
                    'MRANKED_IDENTITY_COMMAND_PROOF':str(self.output/'identity-command-postgres.json'),
                    'MRANKED_HEALTH_TEST_ADMIN_URL':url('clean_it'),
                    'MRANKED_HEALTH_TEST_ADMIN_USERNAME':'mranked_bootstrap',
                    'MRANKED_HEALTH_TEST_ADMIN_PASSWORD':self.secrets['POSTGRES_SUPERUSER_PASSWORD'],
                    'MRANKED_HEALTH_TEST_REPORT_PATH':str(self.output/'health-postgres.json'),
                    'MRANKED_CATALOG_TEST_POSTGRES_URL':url('catalog_it'),
                    'MRANKED_LEGACY_CSV_COLLECTOR_PASSWORD':self.secrets['COLLECTOR_INGEST_DB_PASSWORD'],
                    'MRANKED_LEGACY_CSV_BRIDGE_PASSWORD':self.secrets['MIGRATION_BRIDGE_DB_PASSWORD'],
                    'MRANKED_LEGACY_CSV_MAINTENANCE_PASSWORD':self.secrets['MAINTENANCE_DB_PASSWORD'],
                    'MRANKED_EXPORT_TEST_ADMIN_URL':url('clean_it'),
                    'MRANKED_EXPORT_TEST_ADMIN_USERNAME':'mranked_bootstrap',
                    'MRANKED_EXPORT_TEST_ADMIN_PASSWORD':self.secrets['POSTGRES_SUPERUSER_PASSWORD'],
                    'MRANKED_GOLDEN_TEST_POSTGRES_URL':url('golden_it'),
                    'MRANKED_ADMIN_TEST_OWNER_USERNAME':'mranked_bootstrap','MRANKED_ADMIN_TEST_OWNER_PASSWORD':self.secrets['POSTGRES_SUPERUSER_PASSWORD'],
                    'MRANKED_ADMIN_TEST_USERNAME':'api_write_admin','MRANKED_ADMIN_TEST_PASSWORD':self.secrets['API_WRITE_ADMIN_DB_PASSWORD'],
                    'MRANKED_QUERY_TEST_PASSWORD':self.secrets['API_READ_DB_PASSWORD'],
                    'MRANKED_API_READ_TEST_USERNAME':'api_read','MRANKED_API_READ_TEST_PASSWORD':self.secrets['API_READ_DB_PASSWORD'],
                    'MRANKED_TEST_REDIS_HOST':'127.0.0.1','MRANKED_TEST_REDIS_PORT':str(redis_port),'MRANKED_TEST_REDIS_PASSWORD':self.secrets['REDIS_PASSWORD']}
                self.command('spring',mvn+['-Dtest=!QueryPlanEvidenceTest','test'],env=backend_env,cwd=ROOT/'backend')
                # CI excludes the generated build tree from uploaded artifacts.
                # Retain the actual structured oracle/heap reports beside JUnit
                # and command logs before that disposable tree is discarded.
                for report in (self.output/'backend-build').glob('*.json'):
                    json.loads(report.read_text())
                    shutil.copyfile(report, self.output/report.name)
                for xml in (self.output/'backend-build/surefire-reports').glob('TEST-*.xml'):
                    if not xml.name.endswith('.MigrationInstallationTest.xml'):
                        self.junit_no_skip(xml)
                self.command('query-plans',mvn+['-Dtest=QueryPlanEvidenceTest','test'],env=backend_env|{
                    'MRANKED_PLAN_TEST_URL':url('bridge_it'),'MRANKED_PLAN_OUTPUT':str(self.output/'query-plans')},cwd=ROOT/'backend')
                self.junit_no_skip(self.output/'backend-build/surefire-reports/TEST-org.mranked.query.infrastructure.QueryPlanEvidenceTest.xml')
                self.command('python',[python,'-m','pytest','-q'])
                reverse_env={f'MRANKED_TEST_REVERSE_SYNC_{suffix}':dsn('reverse_it',role,key) for suffix,role,key in (
                    ('POSTGRES_DSN','migration_bridge','MIGRATION_BRIDGE_DB_PASSWORD'),('BRIDGE_DSN','migration_bridge','MIGRATION_BRIDGE_DB_PASSWORD'),
                    ('COLLECTOR_DSN','collector_ingest','COLLECTOR_INGEST_DB_PASSWORD'),('ADMIN_DSN','mranked_bootstrap','POSTGRES_SUPERUSER_PASSWORD'))}
                reverse_env['MRANKED_TEST_REVERSE_SYNC_REPORT_PATH']=str(self.output/'reverse.json')
                self.command('reverse-rehearsal',[python,'-m','pytest','-q','tests/test_reverse_sync_postgres.py','--junitxml='+str(self.output/'reverse.xml')],env=reverse_env)
                self.junit_no_skip(self.output/'reverse.xml')
            finally:
                # Names are random and created by this invocation; no external volumes accepted.
                self.command('cleanup',compose+['down','--volumes','--remove-orphans'])

    def visual(self, *, python, mvn, directory, database_url, bridge_dsn, inspect_dsn, capture_visual=True):
        """One browser runtime, two real servers, one immutable fixture and clock."""
        fixture=directory/'visual.sqlite'
        producer=ROOT/'frontend/scripts/legacy-fixture.py'
        self.command('visual-fixture',[python,str(producer),'--database',str(fixture),
                                      *(['--overview-status-only'] if not capture_visual else [])])
        manifest=fixture.with_suffix('.manifest.json')
        clock=json.loads(manifest.read_text())['clock']
        epoch=datetime.fromisoformat(clock).timestamp()
        os.utime(fixture,(epoch,epoch))
        self.command('visual-import',[python,'-m','migration.bridge','import',str(fixture),
            '--source-namespace','ci-frozen-visual','--snapshot-kind','fixture','--batch-size','500',
            '--report-dir',str(self.output/'reconciliation'),'--stem','frozen'],
            env={'BRIDGE_DATABASE_URL':bridge_dsn},timeout=1200)
        self.command('visual-api-package',mvn+['-DskipTests','package'],cwd=ROOT/'backend')
        api_port,management_port,legacy_port,next_port=(free_port() for _ in range(4))
        api=f'http://127.0.0.1:{api_port}'
        legacy=f'http://127.0.0.1:{legacy_port}'
        target=f'http://127.0.0.1:{next_port}'
        from migration.integration.fixture_auth import bcrypt_hash
        java=str(Path(os.environ['JAVA_HOME'])/'bin/java') if os.getenv('JAVA_HOME') else 'java'
        password=secrets.token_hex(24)
        csrf_secret=secrets.token_hex(32)
        self.secrets['VISUAL_ADMIN_PASSWORD']=password
        self.secrets['VISUAL_CSRF_SECRET']=csrf_secret
        password_hash=bcrypt_hash(password,java=java,repository=Path(os.getenv('MRANKED_MAVEN_REPOSITORY',str(Path.home()/'.m2/repository'))))
        auth={'LEGACY_ADMIN_USERNAME':'visual-admin','LEGACY_ADMIN_PASSWORD':password,'LEGACY_CSRF_SECRET':csrf_secret,
              'TARGET_ADMIN_USERNAME':'visual-admin','TARGET_ADMIN_PASSWORD':password}
        api_env={'SPRING_DATASOURCE_URL':database_url,'SPRING_DATASOURCE_USERNAME':'api_read',
                 'SPRING_DATASOURCE_PASSWORD':self.secrets['API_READ_DB_PASSWORD'],
                 'MRANKED_ADMIN_DATABASE_ENABLED':'true',
                 'MRANKED_ADMIN_DATABASE_URL':database_url,'MRANKED_ADMIN_DATABASE_USERNAME':'api_write_admin',
                 'MRANKED_ADMIN_DATABASE_PASSWORD':self.secrets['API_WRITE_ADMIN_DB_PASSWORD'],
                 'MRANKED_ADMIN_OFFICIAL_RATING_ENABLED':'false',
                 'MRANKED_INTEGRATIONS_TELEGRAM':'configured','MRANKED_INTEGRATIONS_VK':'missing',
                 'MRANKED_INTEGRATIONS_MAX':'missing','MRANKED_INTEGRATIONS_RUTUBE':'configured',
                 'SPRING_APPLICATION_JSON':json.dumps({'mranked.admin.auth.users':[{'username':'visual-admin','password-hash':password_hash,'roles':['ADMIN']}]}),
                 'MRANKED_CACHE_REDIS_ENABLED':'false','SERVER_ADDRESS':'127.0.0.1','SERVER_PORT':str(api_port),
                 'MRANKED_EXPORTS_SPOOL_DIRECTORY':str(directory/'visual-export-spool'),
                 'MANAGEMENT_SERVER_ADDRESS':'127.0.0.1','MANAGEMENT_SERVER_PORT':str(management_port),
                 'MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_INCLUDE':'health,prometheus'}
        dist='.next-integration-'+uuid.uuid4().hex[:12]
        next_env={'API_BASE_URL':api,'NEXT_PUBLIC_DATA_CACHE':'disabled','NEXT_DIST_DIR':dist}
        servers=[]
        logs=[]
        def start(name,args,env=None,cwd=ROOT):
            log=(self.output/(name+'.log')).open('w')
            logs.append(log)
            process=subprocess.Popen(args,cwd=cwd,env=self.environment|(env or {}),stdout=log,stderr=subprocess.STDOUT)
            servers.append(process)
        def ready(url):
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                if any(p.poll() is not None for p in servers):
                    raise RuntimeError('a visual server exited before readiness')
                try:
                    with urllib.request.urlopen(url,timeout=2) as response:
                        if response.status==200:return
                except (OSError,TimeoutError):pass
                time.sleep(.25)
            raise RuntimeError('visual server readiness deadline exceeded')
        try:
            start('visual-api',[java,'-jar',str(self.output/'backend-build/m-ranked-backend-0.1.0-SNAPSHOT.jar')],api_env)
            start('visual-legacy',[python,str(producer),'--database',str(fixture),'--serve','--port',str(legacy_port)],auth)
            ready(api+'/api/v1/health/ready');ready(legacy)
            from operations.performance.rehearse import inspect_database
            with urllib.request.urlopen(api+'/api/v1/revision',timeout=10) as response:
                revision=json.load(response)
            runtime_path=self.output/'visual-runtime.json'
            runtime={'apiBaseUrl':api,'sourceSha256':hashlib.sha256(fixture.read_bytes()).hexdigest(),
                     # The bridge role cannot read every analytics projection.
                     # The inspector enforces a read-only transaction while
                     # reading counts and the final schema contract through the owner.
                     'database':inspect_database(inspect_dsn),'revision':revision,
                     'jarSha256':hashlib.sha256((self.output/'backend-build/m-ranked-backend-0.1.0-SNAPSHOT.jar').read_bytes()).hexdigest(),
                     'productionAcceptance':False,'writerGate':'CLOSED'}
            runtime_path.write_text(json.dumps(runtime,indent=2)+'\n')
            self.command('visual-next-build',['pnpm','build'],cwd=ROOT/'frontend',env=next_env)
            start('visual-next',['pnpm','exec','next','start','--hostname','127.0.0.1','--port',str(next_port)],next_env,ROOT/'frontend')
            ready(target)
            visual_env={
                'LEGACY_BASE_URL':legacy,'TARGET_BASE_URL':target,'VISUAL_FIXTURE_MANIFEST':str(manifest),
                'VISUAL_RUNTIME_EVIDENCE':str(runtime_path),'NEXT_DIST_DIR':dist,
                'VISUAL_OUTPUT':str(self.output/'visual'),'SEMANTIC_OUTPUT':str(self.output/'overview-semantics')}|auth
            self.command('overview-semantics',['node','--import','tsx','scripts/overview-semantic-parity.mts'],cwd=ROOT/'frontend',env=visual_env,timeout=1200)
            if capture_visual:
                self.command('visual-parity',['pnpm','test:visual'],cwd=ROOT/'frontend',env=visual_env,timeout=2400)
        finally:
            for server in reversed(servers):
                server.terminate()
                try:server.wait(timeout=10)
                except subprocess.TimeoutExpired:server.kill();server.wait()
            for log in logs:log.close()
            shutil.rmtree(ROOT/'frontend'/dist,ignore_errors=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'migration/reports'/('integration-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')))
    parser.add_argument('--python',default=sys.executable)
    parser.add_argument('--maven',default=str(ROOT/'backend/mvnw'))
    browser_mode=parser.add_mutually_exclusive_group()
    browser_mode.add_argument('--visual-only',action='store_true',help='Audit historical legacy pixels in disposable services; intentional UI changes can differ')
    browser_mode.add_argument('--semantic-only',action='store_true',help='Verify public data semantics against the frozen legacy corpus without requiring historical pixels')
    args=parser.parse_args()
    from migration.legacy_reference import reference_root
    reference_root()  # Fail before provisioning services if the oracle is absent.
    Gate(args.output).run(python=args.python,maven=args.maven,visual=args.visual_only,semantic_only=args.semantic_only)

if __name__=='__main__': main()
