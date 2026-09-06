import hashlib,json,os,pathlib,subprocess,sys
from psycopg.conninfo import make_conninfo
root=pathlib.Path('/Users/funpin/Documents/ChatGPT/TG-monitoring')
secrets=dict(line.split('=',1) for line in pathlib.Path('/private/tmp/mranked-review-it.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
runtime_path=root/'migration/reports/runtime-final-v29-20260906-r2/runtime-visual.json'
runtime=json.loads(runtime_path.read_text())
source=pathlib.Path('/private/tmp/mranked-frontend-review-20260905-v3.sqlite')
source_sha=hashlib.sha256(source.read_bytes()).hexdigest()
assert source_sha==runtime['sourceSha256']
assert hashlib.sha256(pathlib.Path(runtime['jarPath']).read_bytes()).hexdigest()==runtime['jarSha256']
output=root/'operations/performance/evidence/public-read-v29-final-r2'
environment=os.environ|{'PERFORMANCE_DATABASE_URL':'jdbc:postgresql://127.0.0.1:55439/'+runtime['database']['name'],
    'PERFORMANCE_API_READ_PASSWORD':secrets['API_READ_DB_PASSWORD'],
    'PERFORMANCE_INSPECT_DSN':make_conninfo(host='127.0.0.1',port=55439,dbname=runtime['database']['name'],user='mranked_bootstrap',password=secrets['POSTGRES_SUPERUSER_PASSWORD'])}
command=[str(root/'.venv/bin/python'),'-m','operations.performance.rehearse','--jar',runtime['jarPath'],
    '--java','/Users/funpin/Library/Java/JavaVirtualMachines/openjdk-21/Contents/Home/bin/java',
    '--samples','50','--legacy-url','http://127.0.0.1:18080','--output',str(output)]
done=subprocess.run(command,cwd=root,env=environment)
assert hashlib.sha256(source.read_bytes()).hexdigest()==source_sha
report=json.loads((output/'report.json').read_text())
assert report['database']['name']==runtime['database']['name']
assert report['database']['datasetRevision']==runtime['database']['datasetRevision']
assert report['jarSha256']==runtime['jarSha256']
binding={'runtimeEvidence':str(runtime_path.relative_to(root)), 'runtimeEvidenceSha256':hashlib.sha256(runtime_path.read_bytes()).hexdigest(),
    'sourceSha256Before':source_sha,'sourceSha256After':source_sha,'reportSha256':hashlib.sha256((output/'report.json').read_bytes()).hexdigest(),
    'command':command,'jarSha256':report['jarSha256'],'datasetRevision':report['database']['datasetRevision'],'productionAcceptance':False}
(output/'producer.py').write_bytes(pathlib.Path(__file__).read_bytes())
(output/'runtime-binding.json').write_text(json.dumps(binding,indent=2)+'\n')
sys.exit(done.returncode)
