import pickle, sys, itertools, collections, json
from datetime import datetime, timezone, date
from uuid import UUID
from anomaly_analysis.v2.domain import Metric, PostSeries
from anomaly_analysis.v2.tail_ledger import build_ledger
from anomaly_analysis.v2.account_findings import LedgerPost
import anomaly_analysis.v2.reach_findings as rf
posts = pickle.load(open(sys.argv[1], 'rb'))
at = datetime(2026, 10, 13, 21, 0, tzinfo=timezone.utc)
items, names = [], {}
for p in posts:
    pts = [x for x in p['points'] if x[0] <= at.timestamp()]
    if len(pts) < 3: continue
    obs = tuple(datetime.fromtimestamp(x[0], timezone.utc) for x in pts)
    vals = {m: tuple(x[i] for x in pts) for i, m in ((1, Metric.VIEWS), (2, Metric.REACTIONS))}
    s = PostSeries(UUID(p['id']), UUID(p['account']), 'vk', datetime.fromtimestamp(p['published'], timezone.utc), False, obs, vals,
                   qualities={m: tuple('exact' for _ in pts) for m in vals}, publication_type=p['type'])
    names[s.account_id] = p['username']
    items.append(LedgerPost(s.publication_id, s.account_id, 'vk', s.published_at, False, build_ledger(s, at), None, p['type']))
pickle.dump((items, names), open(sys.argv[2], 'wb'))
print(len(items), len(names))
