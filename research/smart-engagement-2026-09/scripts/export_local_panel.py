"""Read-only local Docker/PostgreSQL extraction; raw data is never committed."""
import argparse, gzip, subprocess, hashlib, json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--container',required=True);p.add_argument('--database',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
sql=Path(__file__).resolve().parents[1]/'sql/observable_panel.sql'
cmd=['docker','exec','-i',a.container,'sh','-c','exec psql -X -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1"','sh',a.database]
r=subprocess.run(cmd,input=sql.read_bytes(),stdout=subprocess.PIPE,check=True)
rows=[line for line in r.stdout.splitlines() if line.startswith(b'{')]
for line in rows:json.loads(line)
payload=b'\n'.join(rows)+b'\n';a.output.parent.mkdir(parents=True,exist_ok=True)
with a.output.open('wb') as raw:
 with gzip.GzipFile(fileobj=raw,mode='wb',mtime=0) as f:f.write(payload)
print(json.dumps({'posts':len(rows),'uncompressed_sha256':hashlib.sha256(payload).hexdigest(),'sql_sha256':hashlib.sha256(sql.read_bytes()).hexdigest()}))
