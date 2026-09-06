import hashlib,json,os,pathlib,signal,subprocess,sys,time,urllib.request
import psycopg
from psycopg.conninfo import make_conninfo
root=pathlib.Path('/Users/funpin/Documents/ChatGPT/TG-monitoring')
sys.path.insert(0,str(root))
from migration.integration.fixture_auth import bcrypt_hash
from migration.release_manifest import flyway_manifest
from operations.performance.rehearse import inspect_database
secrets=dict(line.split('=',1) for line in pathlib.Path('/private/tmp/mranked-review-it.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
credentials_path=pathlib.Path('/private/tmp/mranked-manage-visual-credentials.json')
credentials=json.loads(credentials_path.read_text())
java='/Users/funpin/Library/Java/JavaVirtualMachines/openjdk-21/Contents/Home/bin/java'
env=os.environ|{'JAVA_HOME':str(pathlib.Path(java).parent.parent),'MAVEN_USER_HOME':'/private/tmp/mranked-maven-home'}
output=root/'migration/reports/runtime-final-v29-20260906-r2'
output.mkdir(parents=True,exist_ok=False)
(output/'producer.py').write_bytes(pathlib.Path(__file__).read_bytes())
mvn=[str(root/'backend/mvnw'),'-Dmranked.build.directory=/private/tmp/mranked-review-v29-final-r2-build','-Dmaven.repo.local=/private/tmp/mranked-maven-repository']
jar=pathlib.Path('/private/tmp/mranked-review-v29-final-r2-build/m-ranked-backend-0.1.0-SNAPSHOT.jar')
def run(name,args,environment,cwd):
    with (output/(name+'.log')).open('w') as log:
        done=subprocess.run(args,env=environment,cwd=cwd,stdout=log,stderr=subprocess.STDOUT)
    print(name,'exit',done.returncode,flush=True)
    if done.returncode: raise RuntimeError(name+' failed; inspect retained log')
assert len(flyway_manifest())==29
records=[]
for label,recordpath,expected_jar in (
    ('visual',pathlib.Path('/private/tmp/mranked-admin-visual-v7-runtime.json'),'/private/tmp/mranked-review-v29-final-build/'),
    ('forms',pathlib.Path('/private/tmp/mranked-admin-forms-v8-runtime.json'),'/private/tmp/mranked-review-v29-final-build/')):
    record=json.loads(recordpath.read_text())
    assert record['database'] in ('admin_review_visual_v7_it','admin_review_forms_v8_it')
    command=subprocess.check_output(['ps','-p',str(record['pid']),'-o','command='],text=True)
    assert expected_jar in command and '-jar' in command
    records.append((label,recordpath,record))
run('package',mvn+['-DskipTests','package'],env,root/'backend')
password_hash=bcrypt_hash(credentials['TARGET_ADMIN_PASSWORD'],java=java,repository=pathlib.Path('/private/tmp/mranked-maven-repository'))
users=[{'username':credentials['TARGET_ADMIN_USERNAME'],'password-hash':password_hash,'roles':['ADMIN']},
       {'username':'visual-editor','password-hash':password_hash,'roles':['EDITOR']},
       {'username':'visual-viewer','password-hash':password_hash,'roles':['VIEWER']}]
for label,recordpath,record in records:
    url='jdbc:postgresql://127.0.0.1:55439/'+record['database']
    api_port=int(record['apiBaseUrl'].rsplit(':',1)[1]);management_port=api_port+1
    api_env=env|{'MRANKED_IDENTITY_RECEIPT_DIR':'/private/tmp/mranked-v28-runtime-identity-receipts/'+label,'SPRING_DATASOURCE_URL':url,'SPRING_DATASOURCE_USERNAME':'api_read','SPRING_DATASOURCE_PASSWORD':secrets['API_READ_DB_PASSWORD'],
        'SPRING_FLYWAY_ENABLED':'false','MRANKED_ADMIN_DATABASE_ENABLED':'true','MRANKED_ADMIN_DATABASE_URL':url,'MRANKED_ADMIN_DATABASE_USERNAME':'api_write_admin','MRANKED_ADMIN_DATABASE_PASSWORD':secrets['API_WRITE_ADMIN_DB_PASSWORD'],
        'MRANKED_ADMIN_OFFICIAL_RATING_ENABLED':'false','SPRING_APPLICATION_JSON':json.dumps({'mranked.admin.auth.users':users}),
        'MRANKED_INTEGRATIONS_TELEGRAM':'configured','MRANKED_INTEGRATIONS_VK':'missing','MRANKED_INTEGRATIONS_MAX':'missing','MRANKED_INTEGRATIONS_RUTUBE':'configured',
        'MRANKED_CACHE_REDIS_ENABLED':'false','SERVER_ADDRESS':'127.0.0.1','SERVER_PORT':str(api_port),'MANAGEMENT_SERVER_ADDRESS':'127.0.0.1','MANAGEMENT_SERVER_PORT':str(management_port),
        'MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_INCLUDE':'health,prometheus','MRANKED_EXPORTS_SPOOL_DIRECTORY':'/private/tmp/mranked-'+label+'-v29-spool'}
    pid=int(record['pid'])
    command=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True)
    assert '/private/tmp/mranked-review-v29-final-build/' in command
    os.kill(pid,signal.SIGTERM)
    for attempt in range(100):
        try: os.kill(pid,0)
        except ProcessLookupError: break
        time.sleep(.1)
    else: raise RuntimeError('Previous own runtime did not terminate')
    log=(output/('api-'+label+'.log')).open('w')
    process=subprocess.Popen([java,'-jar',str(jar)],cwd=root,env=api_env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    for attempt in range(180):
        if process.poll() is not None: raise RuntimeError('API exited; inspect log')
        try:
            with urllib.request.urlopen(record['apiBaseUrl']+'/api/v1/health/ready',timeout=2) as response:
                if response.status==200: break
        except Exception: time.sleep(.5)
    else: raise RuntimeError('API readiness timeout')
    record.update(pid=process.pid,jarPath=str(jar),jarSha256=hashlib.sha256(jar.read_bytes()).hexdigest(),schemaVersion=29)
    recordpath.write_text(json.dumps(record,indent=2))
    dsn=make_conninfo(host='127.0.0.1',port=55439,dbname=record['database'],user='mranked_bootstrap',password=secrets['POSTGRES_SUPERUSER_PASSWORD'])
    database=inspect_database(dsn)
    with urllib.request.urlopen(record['apiBaseUrl']+'/api/v1/revision') as response: revision=json.load(response)
    assert database['datasetRevision']==revision['datasetRevision']
    fixture=pathlib.Path(record['fixture'])
    evidence={'environment':'local synthetic representative fixture' if label=='visual' else 'local disposable browser forms fixture',
        'productionAcceptance':False,'apiBaseUrl':record['apiBaseUrl'],'pid':process.pid,'jarPath':str(jar),'jarSha256':record['jarSha256'],
        'database':database,'revision':revision,'sourceSha256':hashlib.sha256(fixture.read_bytes()).hexdigest(),'sourceClock':revision['asOf'],'writerGate':'CLOSED'}
    (output/('runtime-'+label+'.json')).write_text(json.dumps(evidence,indent=2)+'\n')
    print(label,'ready',process.pid,'revision',revision['datasetRevision'],'DBbytes',database['bytes'],flush=True)
