\copy (select * from rvk.pfa) to 'data/pfa.csv' csv header
\copy (select h.pid, h.ah, h.dv, h.dr, h.dc, h.ds, extract(epoch from h.maxgap)::int gap_s, h.npts, extract(hour from (p.published_at + (h.ah+1)*interval '1 hour') at time zone 'Europe/Moscow')::int msk_h, extract(dow from (p.published_at + (h.ah+1)*interval '1 hour') at time zone 'Europe/Moscow')::int msk_dow from rvk.pha h join rvk.posts p on p.id=h.pid) to 'data/pha.csv' csv header
\copy (select x.pid, p.account_id, x.h, x.dv, x.dr from rvk.ph x join rvk.posts p on p.id=x.pid where x.dv >= 50 or x.dr >= 5) to 'data/ph.csv' csv header
\copy (select * from rvk.subs) to 'data/subs.csv' csv header
\copy (select a.id account_id, a.current_username uname, i.short_name inst, f.kind, f.status, f.window_start, f.window_end from analytics.account_anomaly_finding f join catalog.platform_account a on a.id=f.account_id join catalog.institution i on i.id=a.institution_id where a.platform='vk') to 'data/findings.csv' csv header
