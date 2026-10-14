import pickle, sys, collections
from datetime import datetime, timezone, date
from uuid import UUID
from anomaly_analysis.v2.domain import Metric, PostSeries
from anomaly_analysis.v2.tail_ledger import build_ledger
from anomaly_analysis.v2.account_findings import LedgerPost, with_texts
from anomaly_analysis.v2.reach_findings import early_response_findings
posts = pickle.load(open(sys.argv[1], 'rb'))
names, items = {}, []
for p in posts:
    pts = p['points']
    observed = tuple(datetime.fromtimestamp(x[0], timezone.utc) for x in pts)
    values = {m: tuple(x[i] for x in pts) for i, m in ((1, Metric.VIEWS), (2, Metric.REACTIONS))}
    s = PostSeries(UUID(p['id']), UUID(p['account']), 'vk', datetime.fromtimestamp(p['published'], timezone.utc), False,
                   observed, values, qualities={m: tuple('exact' for _ in pts) for m in values}, publication_type=p['type'])
    led = build_ledger(s, surges=False)
    names[UUID(p['account'])] = p['username']
    items.append(LedgerPost(s.publication_id, s.account_id, 'vk', s.published_at, False, led, None, p['type']))
found = early_response_findings(items, date(2026, 10, 12))
for f in found:
    print(names[f.account_id], f.status, f.metrics)
    print('  ', with_texts(f).metrics['headline']); print('  ', with_texts(f).metrics['summary'])
