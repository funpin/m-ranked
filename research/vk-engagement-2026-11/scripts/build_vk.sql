-- Срез ВК 25.08–07.11.2026 на локальной копии mranked_prod_20261107. Схема rvk.
\timing on
create schema if not exists rvk;
drop table if exists rvk.posts;
create table rvk.posts as
select p.id, p.primary_account_id account_id, a.institution_id, a.current_username uname, i.short_name inst,
       p.published_at, p.is_repost, p.publication_type, p.first_observation_age_seconds foa
  from ingest.publication p
  join catalog.platform_account a on a.id = p.primary_account_id
  join catalog.institution i on i.id = a.institution_id
 where a.platform = 'vk' and a.deleted_at is null and p.deleted_at is null
   and p.published_at >= '2026-08-20' and p.published_at < '2026-11-08';
create unique index on rvk.posts(id);
drop table if exists rvk.pts;
create table rvk.pts as
select distinct on (pt.publication_id, pt.sampling_bucket)
       pt.publication_id pid, pt.observed_at, pt.age_seconds, pt.views_count v, pt.reactions_count r,
       pt.comments_count c, pt.shares_count s
  from ingest.publication_metric_point pt
  join rvk.posts p on p.id = pt.publication_id
 where pt.visible and not pt.synthetic and pt.published_month >= '2026-08-01'
 order by pt.publication_id, pt.sampling_bucket, pt.correction_sequence desc;
create index on rvk.pts(pid, observed_at);
-- Сводка поста по возрастам.
drop table if exists rvk.pf;
create table rvk.pf as
select pid, count(*) n, min(age_seconds) a0, max(age_seconds) amax,
       max(v) filter (where age_seconds <= 3600) v1,   max(r) filter (where age_seconds <= 3600) r1,
       max(v) filter (where age_seconds <= 2*3600) v2, max(r) filter (where age_seconds <= 2*3600) r2,
       max(v) filter (where age_seconds <= 6*3600) v6, max(r) filter (where age_seconds <= 6*3600) r6,
       max(v) filter (where age_seconds <= 12*3600) v12, max(r) filter (where age_seconds <= 12*3600) r12,
       max(v) filter (where age_seconds <= 86400) v24, max(r) filter (where age_seconds <= 86400) r24, max(c) filter (where age_seconds <= 86400) c24, max(s) filter (where age_seconds <= 86400) s24,
       max(v) filter (where age_seconds <= 2*86400) v48, max(r) filter (where age_seconds <= 2*86400) r48,
       max(v) filter (where age_seconds <= 3*86400) v72, max(r) filter (where age_seconds <= 3*86400) r72, max(c) filter (where age_seconds <= 3*86400) c72, max(s) filter (where age_seconds <= 3*86400) s72,
       max(v) filter (where age_seconds <= 7*86400) v168, max(r) filter (where age_seconds <= 7*86400) r168,
       max(v) filter (where age_seconds <= 14*86400) v336, max(r) filter (where age_seconds <= 14*86400) r336,
       max(v) vmx, max(r) rmx, max(c) cmx, max(s) smx
  from rvk.pts group by pid;
create unique index on rvk.pf(pid);
-- Приросты по часу возраста (0..335) с календарным часом МСК конца интервала.
drop table if exists rvk.pha;
create table rvk.pha as
with s as (select pid, observed_at, age_seconds, v - lag(v) over w dv, r - lag(r) over w dr, c - lag(c) over w dc, s - lag(s) over w ds,
                  observed_at - lag(observed_at) over w gap
             from rvk.pts window w as (partition by pid order by observed_at))
select pid, floor(age_seconds/3600)::int ah, sum(dv) dv, sum(dr) dr, sum(dc) dc, sum(ds) ds, max(gap) maxgap, count(*) npts
  from s where gap is not null and age_seconds < 336*3600 group by 1, 2;
create index on rvk.pha(pid, ah);
-- Приросты старых (>24ч) постов по календарным часам: волны по стене.
drop table if exists rvk.ph;
create table rvk.ph as
with s as (select pid, observed_at, v - lag(v) over w dv, r - lag(r) over w dr,
                  observed_at - lag(observed_at) over w gap, age_seconds
             from rvk.pts window w as (partition by pid order by observed_at))
select pid, date_trunc('hour', observed_at) h, sum(dv) dv, sum(dr) dr
  from s where age_seconds > 86400 and gap <= interval '3 hours' group by 1, 2;
create index on rvk.ph(pid);
-- Уровни и признаки анализа, находки.
drop table if exists rvk.pfa;
create table rvk.pfa as
select p.*, f.n, f.a0, f.amax, f.v1, f.r1, f.v2, f.r2, f.v6, f.r6, f.v12, f.r12, f.v24, f.r24, f.c24, f.s24, f.v48, f.r48,
       f.v72, f.r72, f.c72, f.s72, f.v168, f.r168, f.v336, f.r336, f.vmx, f.rmx, f.cmx, f.smx,
       st.level lvl, (select string_agg(distinct e->>'pattern', ',') from jsonb_array_elements(st.signals) e) sig
  from rvk.posts p join rvk.pf f on f.pid = p.id
  left join analytics.post_anomaly_state st on st.publication_id = p.id;
create unique index on rvk.pfa(id);
-- Подписчики: последний замер на дату.
drop table if exists rvk.subs;
create table rvk.subs as
select platform_account_id aid, (observed_at at time zone 'Europe/Moscow')::date d,
       (array_agg(subscriber_count order by observed_at desc))[1] sc
  from ingest.account_metric_snapshot s join catalog.platform_account a on a.id = s.platform_account_id
 where a.platform = 'vk' and observed_at >= '2026-08-20' and subscriber_count is not null and correction_sequence = 0
 group by 1, 2;
select count(*) posts from rvk.posts; select count(*) pts from rvk.pts; select count(*) pha from rvk.pha;
