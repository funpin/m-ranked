"""Measure real HTTP latency and executed JDBC calls on an isolated local clone.

Credentials are environment-only: PERFORMANCE_DATABASE_URL (JDBC),
PERFORMANCE_API_READ_PASSWORD and PERFORMANCE_INSPECT_DSN (read-only inspection).
The process owns and stops only its own Java server. It never changes DB data.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time
from datetime import datetime, timezone

import httpx
import psycopg

from migration.release_manifest import release_identity, flyway_manifest


def percentile(values, quantile):
    return sorted(values)[max(0,math.ceil(len(values)*quantile)-1)]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def scrape(client, origin):
    response=client.get(origin+'/actuator/prometheus');response.raise_for_status()
    output={}
    for line in response.text.splitlines():
        if not line.startswith('mranked_'):continue
        name,value=line.rsplit(' ',1)
        output[name]=float(value)
    count=output.get('mranked_jdbc_executions_seconds_count')
    if count is None:raise RuntimeError('actual JDBC execution metric is missing')
    return {'queries':int(count),'cacheMisses':sum(value for key,value in output.items()
        if key.startswith('mranked_cache_requests_total{') and 'outcome="miss"' in key),
        'cacheHits':sum(value for key,value in output.items()
        if key.startswith('mranked_cache_requests_total{') and 'outcome="hit"' in key)}


def inspect_database(dsn):
    with psycopg.connect(dsn,options='-c default_transaction_read_only=on -c statement_timeout=10000') as connection:
        info=connection.execute("""SELECT current_database(),pg_database_size(current_database()),
            (SELECT count(*) FROM catalog.institution),(SELECT count(*) FROM catalog.platform_account),
            (SELECT count(*) FROM ingest.publication),(SELECT count(*) FROM ingest.publication_metric_snapshot),
            (SELECT count(*) FROM analytics.comparison_metric_point),(SELECT max(id) FROM analytics.dataset_revision)""").fetchone()
        manifest=connection.execute("SELECT version,script,checksum,success FROM flyway.flyway_schema_history WHERE version IS NOT NULL ORDER BY installed_rank").fetchall()
        keys=('name','bytes','institutions','accounts','publications','snapshots','comparisonPoints','datasetRevision')
        return dict(zip(keys,info,strict=True))|{'flyway':[dict(zip(('version','script','checksum','success'),row,strict=True)) for row in manifest]}


def run(args):
    jar=args.jar.resolve()
    if not jar.is_file() or jar.is_symlink():raise ValueError('regular packaged API jar required')
    database_url=os.environ['PERFORMANCE_DATABASE_URL']
    if not re.fullmatch(r'jdbc:postgresql://(?:127\.0\.0\.1|localhost):\d+/[a-z0-9_]+_it',database_url):
        raise ValueError('performance server requires an explicit local disposable *_it database')
    if not 30<=args.samples<=100:raise ValueError('use 30..100 independent request samples')
    args.output.mkdir(parents=True,exist_ok=False)
    args.output.chmod(0o700)
    report={'reportVersion':1,'generatedAt':datetime.now(timezone.utc).isoformat(),
        'scope':'Local synthetic representative corpus; API JSON and legacy HTML are reported separately.',
        'productionAcceptance':False,'release':release_identity(),'jarSha256':hashlib.sha256(jar.read_bytes()).hexdigest(),
        'database':inspect_database(os.environ['PERFORMANCE_INSPECT_DSN']), 'samplesPerGroup':args.samples,
        'measurements':{},'checks':[]}
    def check(name,passed,**details):report['checks'].append({'name':name,'passed':bool(passed),**details})
    expected=[{k:v for k,v in row.items() if k!='sha256'} for row in flyway_manifest()]
    check('exactFlywayManifest',report['database']['flyway']==expected)
    check('representativeData',report['database']['institutions']>200 and report['database']['snapshots']>=9000)
    api_port,management_port=free_port(),free_port()
    api,management=f'http://127.0.0.1:{api_port}',f'http://127.0.0.1:{management_port}'
    process=None
    log_path=args.output/'api.log'
    with tempfile.TemporaryDirectory(prefix='mranked-performance-') as directory, log_path.open('w') as log:
        environment=dict(os.environ,SPRING_DATASOURCE_URL=database_url,SPRING_DATASOURCE_USERNAME='api_read',
            SPRING_DATASOURCE_PASSWORD=os.environ['PERFORMANCE_API_READ_PASSWORD'],SPRING_FLYWAY_ENABLED='false',
            MRANKED_ADMIN_DATABASE_ENABLED='false',MRANKED_CACHE_REDIS_ENABLED='false',
            MRANKED_EXPORTS_SPOOL_DIRECTORY=str(Path(directory)/'export-spool'),
            SERVER_ADDRESS='127.0.0.1',SERVER_PORT=str(api_port),MANAGEMENT_SERVER_ADDRESS='127.0.0.1',
            MANAGEMENT_SERVER_PORT=str(management_port),MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_INCLUDE='health,prometheus')
        try:
            process=subprocess.Popen([args.java,'-Xms128m','-Xmx512m','-jar',str(jar)],env=environment,stdout=log,stderr=subprocess.STDOUT)
            with httpx.Client(timeout=15,trust_env=False) as client:
                deadline=time.monotonic()+90
                while True:
                    if process.poll() is not None:raise RuntimeError('isolated API exited before readiness')
                    try:
                        response=client.get(api+'/api/v1/health/ready')
                        if response.status_code==200:break
                    except httpx.HTTPError:pass
                    if time.monotonic()>deadline:raise RuntimeError('isolated API readiness deadline exceeded')
                    time.sleep(.25)
                public_metrics=client.get(api+'/actuator/prometheus')
                check('managementPortIsolated',public_metrics.status_code==403)
                base={'platform':'telegram','period':'1d','limit':200}
                baseline=client.get(api+'/api/v1/overview',params=base);baseline.raise_for_status()
                baseline_json=baseline.json()
                check('boundedPageHas200Rows',len(baseline_json['items'])==200)
                body_hash=hashlib.sha256(baseline.content).hexdigest()
                for _ in range(20):client.get(api+'/api/v1/overview',params=base).raise_for_status()
                for group in ('cacheHit','boundedMiss'):
                    rows=[]
                    for index in range(args.samples):
                        params=base|({'q':'%'*(index+1)} if group=='boundedMiss' else {})
                        before=scrape(client,management);start=time.perf_counter()
                        response=client.get(api+'/api/v1/overview',params=params)
                        elapsed=(time.perf_counter()-start)*1000;response.raise_for_status()
                        after=scrape(client,management)
                        if response.json()!=baseline_json:raise RuntimeError('cache/uncached response differs at fixed revision')
                        rows.append({'ms':elapsed,'queries':after['queries']-before['queries'],
                            'misses':after['cacheMisses']-before['cacheMisses'],'hits':after['cacheHits']-before['cacheHits']})
                    summary={'p50Ms':percentile([r['ms'] for r in rows],.5),'p95Ms':percentile([r['ms'] for r in rows],.95),
                        'queryCounts':dict(Counter(r['queries'] for r in rows)),'samples':rows,'bodySha256':body_hash}
                    report['measurements'][group]=summary
                    threshold=300 if group=='cacheHit' else 1000
                    check(group+'P95',summary['p95Ms']<=threshold,thresholdMs=threshold,actualMs=summary['p95Ms'])
                    check(group+'ConstantQueryCount',len(summary['queryCounts'])==1 and all(r['queries']>0 for r in rows))
                    check(group+'CachePathVerified',all(r['hits']==1 and r['misses']==0 if group=='cacheHit' else r['misses']==1 and r['hits']==0 for r in rows))
                    print(group,round(summary['p95Ms'],2),'ms p95; queries',summary['queryCounts'],flush=True)
                sizes=[]
                for index,size in enumerate((1,10,50,100,200)):
                    before=scrape(client,management)
                    response=client.get(api+'/api/v1/overview',params=base|{'limit':size,'q':'%'*(args.samples+index+1)})
                    response.raise_for_status();after=scrape(client,management)
                    sizes.append({'limit':size,'rows':len(response.json()['items']),'queries':after['queries']-before['queries']})
                report['measurements']['pageSizeQueries']=sizes
                check('noNPlusOneAcrossPageSizes',len({r['queries'] for r in sizes})==1 and all(r['rows']==r['limit'] for r in sizes))
                etag=baseline.headers['etag']; response=client.get(api+'/api/v1/overview',params=base,headers={'If-None-Match':etag})
                check('etag304',response.status_code==304 and not response.content)
                if args.legacy_url:
                    if not re.match(r'^http://(?:127\.0\.0\.1|localhost):\d+$',args.legacy_url):raise ValueError('legacy comparison must be local')
                    measurements=[]
                    for index in range(args.samples+5):
                        start=time.perf_counter();response=client.get(args.legacy_url+'/',params={'platform':'telegram','period':'1d'})
                        elapsed=(time.perf_counter()-start)*1000;response.raise_for_status()
                        if index>=5:measurements.append(elapsed)
                    report['measurements']['legacyHtmlBefore']={'p50Ms':percentile(measurements,.5),'p95Ms':percentile(measurements,.95),'samplesMs':measurements,
                        'comparisonLimit':'Legacy includes server HTML rendering; target measurements above are JSON API only.'}
                report['datasetRevisionAfter']=client.get(api+'/api/v1/revision').json()['datasetRevision']
                check('revisionDidNotChange',report['datasetRevisionAfter']==report['database']['datasetRevision'])
        except Exception as error:
            report['errorType']=type(error).__name__
            check('producerCompleted',False)
            raise
        finally:
            if process is not None:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            report['gate']='PASS' if report['checks'] and all(row['passed'] for row in report['checks']) else 'NO-GO'
            (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
            lines=['# Public read performance rehearsal','',f"Gate: **{report['gate']}**. Production acceptance: **false**.",'',report['scope'],'']
            for name,values in report['measurements'].items():
                if isinstance(values,dict) and 'p95Ms' in values:lines.append(f"- {name}: p95 {values['p95Ms']:.2f} ms.")
            lines.extend(['','Every check:']+['- '+row['name']+': '+('PASS' if row['passed'] else 'FAIL') for row in report['checks']])
            (args.output/'report.md').write_text('\n'.join(lines)+'\n')
    raw=log_path.read_text()
    raw=raw.replace(os.environ['PERFORMANCE_API_READ_PASSWORD'],'[redacted]')
    log_path.write_text(raw)
    return report['gate']=='PASS'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jar',type=Path,required=True)
    parser.add_argument('--java',default='java')
    parser.add_argument('--samples',type=int,default=50)
    parser.add_argument('--legacy-url')
    parser.add_argument('--output',type=Path,required=True)
    raise SystemExit(0 if run(parser.parse_args()) else 1)


if __name__=='__main__':main()
