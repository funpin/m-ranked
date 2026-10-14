"""VK cohort from the local prod copy: every own VK post in a window, compact series.

Series are built by the worker's own loader (PostgresAnomalyStore.read_series),
then reduced to (epoch, views, reactions, comments, shares) with None kept.
"""
import pickle, sys
import psycopg
from psycopg.rows import dict_row
from anomaly_analysis.v2.domain import Metric
from anomaly_analysis.v2.store import PostgresAnomalyStore, SeriesTarget
dsn, out, since, until = sys.argv[1:5]
with psycopg.connect(dsn, row_factory=dict_row) as c:
    rows = c.execute("""SELECT p.id, p.published_at, p.publication_type, a.id AS account, a.current_username AS username,
        i.short_name AS institution FROM ingest.publication p
      JOIN catalog.platform_account a ON a.id=p.primary_account_id
      LEFT JOIN catalog.institution i ON i.id=a.institution_id
      WHERE a.platform='vk' AND p.published_at >= %s AND p.published_at < %s""", (since, until)).fetchall()
store = PostgresAnomalyStore(dsn)
meta = {r["id"]: r for r in rows}
posts = []
B = 400
for k in range(0, len(rows), B):
    batch = rows[k:k + B]
    series = store.read_series([SeriesTarget(r["id"], r["published_at"]) for r in batch], kinds_for=())
    for pid, s in series.items():
        if s.is_repost: continue
        m = meta[pid]
        cols = [s.values.get(x) for x in (Metric.VIEWS, Metric.REACTIONS, Metric.COMMENTS, Metric.SHARES)]
        pts = [(t.timestamp(), *[(c[i] if c is not None else None) for c in cols]) for i, t in enumerate(s.observed_at)]
        posts.append({"id": str(pid), "account": str(m["account"]), "username": m["username"], "institution": m["institution"],
                      "type": m["publication_type"], "published": s.published_at.timestamp(), "points": pts})
    print(k + len(batch), len(posts), flush=True, file=sys.stderr)
pickle.dump(posts, open(out, "wb"))
print(len(posts))
