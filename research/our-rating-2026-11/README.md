# «Наш рейтинг» вузов по соцсетям — расчёт на сентябре и октябре 2026

Скрипты анализа к спеку `docs/superpowers/specs/2026-11-20-our-rating-design.md`.
Считают кандидатную формулу без базы, по выгрузкам из локальной копии прода
(только чтение; прод-базу не трогать).

## Выгрузки

Из каталога, где будут лежать CSV, с локальной копией в контейнере
(`<контейнер>` и `<база>` — свои):

```bash
P() { docker exec -i <контейнер> psql -U <суперпользователь> -d <база> -v ON_ERROR_STOP=1 -q; }
P < research/our-rating-2026-11/posts.sql > posts.csv
echo "COPY (SELECT a.id, a.institution_id, a.platform::text platform, a.enabled, a.created_at, (SELECT min(published_at) FROM ingest.publication p WHERE p.primary_account_id=a.id) first_pub, a.current_username, a.current_title FROM catalog.visible_platform_account a) TO STDOUT CSV HEADER" | P > accounts.csv
echo "COPY (SELECT i.id, i.canonical_name, i.short_name, c.external_id code FROM catalog.visible_institution i LEFT JOIN catalog.institution_external_id c ON c.institution_id=i.id AND c.namespace='m-rating' AND c.valid_to IS NULL) TO STDOUT CSV HEADER" | P > inst.csv
echo "COPY (SELECT period, code, name, social_score, max_score, vk_score, rutube_score FROM rating.official_periods() op, rating.official_period_scores(op.period)) TO STDOUT CSV HEADER" | P > official.csv
echo "COPY (SELECT f.account_id, a.institution_id, f.kind, f.platform, f.status, f.window_start, f.window_end, f.metrics, f.method_version FROM analytics.account_anomaly_finding f JOIN catalog.platform_account a ON a.id=f.account_id) TO STDOUT CSV HEADER" | P > findings.csv
echo "COPY (SELECT account_id, computed_for, platform, status, metrics->>'ratio' ratio, metrics->'cohort'->>'median' cmed, metrics->'cohort'->>'threshold' thr, metrics->'cohort'->>'p90' p90, metrics->>'lateReactions' lr, metrics->>'lateViews' lv, metrics->>'earlyReactions' er, metrics->>'earlyViews' ev, metrics->>'earlyRate' erate FROM analytics.account_tail_profile WHERE status IS NOT NULL) TO STDOUT CSV HEADER" | P > tailhist.csv
```

## Запуск

Из каталога с CSV (скрипты читают их из текущего каталога, модули — из своего):

```bash
python3 <репозиторий>/research/our-rating-2026-11/final.py
```

`final.py` печатает корреляции и пишет `final.json` (места, баллы площадок,
подбаллы, метрики); `sens.py` — чувствительность мест к порогам, шкале,
минимальному контингенту и правилу заброшенного Telegram.

- `posts.sql` — посты 25.08–17.11 со счётчиками, уровнем аномалии,
  `discounted_views` и размером крупнейшего эпизода реакций/просмотров по
  сигналам strength ≥ 0.7 (`least(NULL, x)` не используется: размер — `greatest`
  с явными нулями, обрезка по счётчику — в Python).
- `load.py`, `agg.py` — загрузка, покрытие месяца аккаунтом, агрегаты площадки,
  пакеты постов.
- `formula.py` — шкалы, якоря по перцентилям, баллы, места.
- `final.py` — счёт с очисткой постов и аккаунтов, сравнение с М-Рейтингом.

Данные: копия прода на 17.11.2026 23:31 UTC (`mranked_prod_20261117`).
