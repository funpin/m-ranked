-- Запросы к таблицам build.sql, по разделам README.

-- §2. Волны просмотров по старым постам: часы, где >=10 постов старше суток
-- одновременно получили >= max(100, 15 % своих просмотров к 24 ч).
select r.platform, r.account_id, count(distinct (r.h at time zone 'Europe/Moscow')::date) days,
       count(*) hours, sum(r.dv) views, sum(r.dr) reactions
  from research.rwave r where r.vhit >= 10 group by 1, 2 order by views desc;

-- §2. Волна берёт ровно последние N постов: X — пост получил >=100 за час.
with w as (select account_id, h from research.rwave where vhit >= 10),
     r as (select w.account_id, w.h, p.id,
                  row_number() over (partition by w.account_id, w.h order by p.published_at desc) rk
             from w join research.pfa p on p.account_id = w.account_id and p.published_at < w.h - interval '1 day')
select r.account_id, r.h at time zone 'Europe/Moscow' h,
       string_agg(case when coalesce(x.dv, 0) >= 100 then 'X' else '.' end, '' order by r.rk) ranks
  from r left join research.ph x on x.pid = r.id and x.h = r.h
 where r.rk <= 80 group by 1, 2 order by 2;

-- §2. Место в сумме просмотров ВК с волнами и без них.
with t as (select account_id, sum(vmx) tv from research.pfa where platform = 'vk' group by 1),
     w as (select account_id, sum(dv) wave from research.rwave where vhit >= 10 group by 1)
select t.account_id, t.tv, t.tv - coalesce(w.wave, 0) clean,
       rank() over (order by t.tv desc) rk, rank() over (order by t.tv - coalesce(w.wave, 0) desc) rk_clean
  from t left join w using (account_id) order by rk;

-- §3. Суточная амплитуда: самое тихое окно 4 ч / самое активное.
with w as (select platform, account_id, hr,
                  sum(dv) over (partition by account_id order by hr rows between current row and 3 following) s4
             from (select platform, account_id, hr, dv from research.clock
                   union all select platform, account_id, hr + 24, dv from research.clock) z)
select platform, account_id, min(s4) filter (where hr < 24)::float / nullif(max(s4) filter (where hr < 24), 0) amp,
       sum(s4) filter (where hr < 24) / 4 views
  from w group by 1, 2 having sum(s4) filter (where hr < 24) / 4 >= 20000 order by amp desc;

-- §5. Доля постов уровня 3 у аккаунта против площадки.
with x as (select platform, account_id, count(*) n, count(*) filter (where lvl = 3) l3
             from research.pfa group by 1, 2 having count(*) >= 20)
select x.*, round(100.0*l3/n) pct3,
       (select string_agg(kind, ',') from analytics.account_anomaly_finding f where f.account_id = x.account_id) findings
  from x order by l3::float/n desc;

-- §6. Ступеньки подписчиков: часовой прирост при пробеле сбора не больше 2 ч.
with x as (select aid, h, sc - lag(sc) over w dh, h - lag(h) over w gap
             from research.subh window w as (partition by aid order by h))
select aid, h at time zone 'Europe/Moscow' h, dh from x
 where h >= '2026-09-01' and gap <= interval '2 hours' and abs(dh) >= 100 order by abs(dh) desc;
