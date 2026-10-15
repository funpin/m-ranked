-- Аудит охватов 01.09–07.10.2026: рабочие таблицы в схеме research локальной
-- копии БД (дамп прода от 07.10 23:40 UTC). Прод не читается.
-- psql -X -f build.sql   (~6 минут на ноутбуке; 14 млн точек)

create schema if not exists research;

-- Посты окна (с запасом в неделю до 01.09 для волн по старым постам).
drop table if exists research.posts;
create table research.posts as
select p.id, p.primary_account_id account_id, a.platform::text platform, a.institution_id, a.current_username uname,
       p.published_at, p.is_repost, p.publication_type, p.first_observation_age_seconds, p.quality_flags
  from ingest.visible_publication p
  join catalog.platform_account a on a.id = p.primary_account_id
 where p.published_at >= '2026-08-25' and p.published_at < '2026-10-08' and a.deleted_at is null;
create unique index on research.posts(id);

-- Все видимые несинтетические точки (горячие и упакованные), последняя поправка на корзину.
drop table if exists research.pts;
create table research.pts as
select distinct on (pt.publication_id, pt.sampling_bucket)
       pt.publication_id pid, pt.observed_at, pt.age_seconds, pt.views_count v, pt.reactions_count r,
       pt.comments_count c, pt.shares_count s, pt.interval_uncertain iu, pt.reaction_breakdown rb
  from ingest.publication_metric_point pt
  join research.posts p on p.id = pt.publication_id
 where pt.visible and not pt.synthetic and pt.published_month >= '2026-08-01'
 order by pt.publication_id, pt.sampling_bucket, pt.correction_sequence desc;
create index on research.pts(pid, observed_at);

-- Сводка поста: значения к 1/6/24/72 ч, 7 сут и максимум.
drop table if exists research.pf;
create table research.pf as
select pid, count(*) n, min(age_seconds) a0, max(age_seconds) amax,
       max(v) filter (where age_seconds <= 3600) v1h,      max(r) filter (where age_seconds <= 3600) r1h,
       max(v) filter (where age_seconds <= 6*3600) v6h,    max(r) filter (where age_seconds <= 6*3600) r6h,
       max(v) filter (where age_seconds <= 86400) v24,     max(r) filter (where age_seconds <= 86400) r24,
       max(v) filter (where age_seconds <= 3*86400) v72,   max(r) filter (where age_seconds <= 3*86400) r72,
       max(v) vmx, max(r) rmx, max(c) cmx, max(s) smx
  from research.pts group by pid;
create unique index on research.pf(pid);

drop table if exists research.pfa;
create table research.pfa as
select p.*, f.n, f.a0, f.amax, f.v1h, f.r1h, f.v6h, f.r6h, f.v24, f.r24, f.v72, f.r72, f.vmx, f.rmx, f.cmx, f.smx,
       s.level lvl,
       (select string_agg(distinct e->>'pattern', ',') from jsonb_array_elements(s.signals) e) sig
  from research.posts p
  join research.pf f on f.pid = p.id
  left join analytics.post_anomaly_state s on s.publication_id = p.id
 where p.published_at >= '2026-09-01';

-- Приросты по часу возраста поста (для пакетов просмотров, scripts/viewpack.py).
drop table if exists research.pha;
create table research.pha as
with s as (select pid, observed_at, age_seconds, v - lag(v) over w dv, r - lag(r) over w dr,
                  observed_at - lag(observed_at) over w gap
             from research.pts window w as (partition by pid order by observed_at))
select pid, floor(age_seconds/3600)::int ah, sum(dv) dv, sum(dr) dr, max(gap) maxgap
  from s where gap is not null group by 1, 2;
create index on research.pha(pid, ah);

-- Приросты старых (старше суток) постов по часам календаря: волны по стене.
drop table if exists research.ph;
create table research.ph as
with s as (select pid, observed_at, v - lag(v) over w dv, r - lag(r) over w dr,
                  observed_at - lag(observed_at) over w gap, age_seconds
             from research.pts window w as (partition by pid order by observed_at))
select pid, date_trunc('hour', observed_at) h, sum(dv) dv, sum(dr) dr
  from s where age_seconds > 86400 and gap <= interval '3 hours' group by 1, 2;
create index on research.ph(pid);

-- Час аккаунта: сколько старых постов одновременно получили заметный прирост.
drop table if exists research.rwave;
create table research.rwave as
select p.platform, p.account_id, x.h,
       count(*) filter (where x.dv >= greatest(100, 0.15*coalesce(p.v24, 0))) vhit,
       count(*) filter (where x.dr >= greatest(10, 0.2*coalesce(p.r24, 0))) rhit,
       sum(x.dv) dv, sum(x.dr) dr
  from research.ph x join research.pfa p on p.id = x.pid
 where x.h >= '2026-09-01' group by 1, 2, 3;

-- Суточный профиль прироста просмотров постов 6–72 ч по часу МСК.
drop table if exists research.clock;
create table research.clock as
select p.platform, p.account_id,
       extract(hour from (p.published_at + h.ah*interval '1 hour') at time zone 'Europe/Moscow')::int hr,
       sum(h.dv) dv, sum(h.dr) dr
  from research.pha h join research.pfa p on p.id = h.pid
 where h.ah between 6 and 71 and h.maxgap <= interval '70 minutes' group by 1, 2, 3;

-- Подписчики по часам.
drop table if exists research.subh;
create table research.subh as
select platform_account_id aid, date_trunc('hour', observed_at) h,
       (array_agg(subscriber_count order by observed_at desc))[1] sc
  from ingest.account_metric_snapshot
 where observed_at >= '2026-08-25' and observed_at < '2026-10-08'
   and subscriber_count is not null and correction_sequence = 0
 group by 1, 2;
