import csv, json, math, statistics as st
from collections import defaultdict
from datetime import datetime, timezone, timedelta
MSK = timezone(timedelta(hours=3))
import pathlib
REPO = str(pathlib.Path(__file__).resolve().parents[2])
def ts(x):
    if not x: return None
    x = x.replace('+00', '+00:00') if x.endswith('+00') else x
    return datetime.fromisoformat(x)
def month(d): return d.astimezone(MSK).strftime('%Y-%m')
inst = {r['id']: r for r in csv.DictReader(open('inst.csv'))}
students = {r['institutionId']: r['value'] for r in json.load(open(f'{REPO}/api/data/institution-student-counts.json'))}
posts = []
for r in csv.DictReader(open('posts.csv')):
    r['pub'] = ts(r['published_at']); r['upl'] = ts(r['uploaded_at'])
    for k in ('v','r','c','s','dv','r_ep','v_ep'):
        r[k] = float(r[k]) if r[k] not in ('', None) else None
    r['lvl'] = int(r['lvl']); r['r_sig'] = r['r_sig'] == 't'
    r['created'] = ts(r['created_at']); r['first'] = ts(r['first_pub'])
    posts.append(r)
official = defaultdict(dict)
for r in csv.DictReader(open('official.csv')):
    official[r['period']][r['code']] = r
def covered(r, m):
    start = datetime.fromisoformat(m + '-01T00:00:00+03:00')
    return r['enabled'] == 't' and (r['created'] <= start or (r['first'] is not None and r['first'] < start))
accounts = {}
for r in csv.DictReader(open('accounts.csv')):
    r['created'] = ts(r['created_at']); r['first'] = ts(r['first_pub']); accounts[r['id']] = r
def cover_days(acc, m):
    """Days of the month covered by collection (backfill or catalog start)."""
    import calendar
    y, mo = map(int, m.split('-'))
    start = datetime(y, mo, 1, tzinfo=MSK); days = calendar.monthrange(y, mo)[1]
    end = start + timedelta(days=days)
    if acc['enabled'] != 't': return 0, days
    begin = start if (acc['created'] <= start or (acc['first'] and acc['first'] < start - timedelta(days=0))) else acc['created']
    if begin >= end: return 0, days
    return (end - begin).total_seconds()/86400, days
