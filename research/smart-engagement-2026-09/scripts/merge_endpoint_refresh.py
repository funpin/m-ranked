"""Merge a bounded endpoint refresh; preserve the original snapshot history.

SQL execution/transport is external. Never put deployment addresses in this script.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--panel',type=Path,required=True)
p.add_argument('--refresh',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
raw=gzip.decompress(a.panel.read_bytes())
posts=[json.loads(line) for line in raw.splitlines()]
refresh=[json.loads(line) for line in a.refresh.read_bytes().splitlines() if line.startswith(b'{')]
by_id={p['id']:p for p in posts}
for r in refresh:
    if r['id'] not in by_id:
        raise ValueError('refresh contains an unselected publication')
    by_id[r['id']]['refreshed_points']=r['points'] or []
payload=('\n'.join(json.dumps(p,ensure_ascii=False,sort_keys=True) for p in posts)+'\n').encode()
with a.output.open('wb') as f:
    with gzip.GzipFile(fileobj=f,mode='wb',mtime=0) as z:z.write(payload)
print(json.dumps({'refreshed_posts':len(refresh),'original_panel_sha256':hashlib.sha256(raw).hexdigest(),
                  'refresh_sha256':hashlib.sha256(a.refresh.read_bytes()).hexdigest(),
                  'merged_panel_sha256':hashlib.sha256(payload).hexdigest()}))
