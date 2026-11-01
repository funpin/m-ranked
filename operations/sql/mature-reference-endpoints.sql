-- Конечные точки 24/72 ч для пересборки ориентира признаков 11/12. Только чтение.
-- Та же рамка из 24 MAX-аккаунтов, выбранная до исходов (research/smart-engagement-2026-09/RELEASE.md),
-- активные коррекции на момент доступности, известные снижения до 72 ч. Результат — строка JSON на пост:
--
--   psql -X -q -At -v fit_from=2026-09-13 -v fit_until=2026-09-17 -v cal_from=2026-09-20 \
--        -v cal_until=2026-09-24 -v available_before='2026-09-27 00:00+00' \
--        -f operations/sql/mature-reference-endpoints.sql | gzip > endpoints.jsonl.gz
--
-- Даты — UTC, правые границы исключены. Далее: python -m anomaly_analysis.tools.renew_mature_reference.
--
-- Замеры старше двух суток упаковщик (0059) переносит в ingest.publication_metric_history и удаляет
-- из горячей таблицы, поэтому точки поста — обе части: горячие строки и упакованные версии первых
-- 80 часов (с запасом на версии бакета у границы 72 ч). Распакованная точка сохраняет created_at,
-- бакет и номер коррекции, так что видимость на момент доступности считается как по горячим строкам.
BEGIN READ ONLY;
SET LOCAL statement_timeout='60s';
SET LOCAL lock_timeout='2s';
SET LOCAL TIME ZONE 'UTC';
WITH accounts AS (SELECT value::uuid AS id FROM jsonb_array_elements_text(
 '["0e70f2df-9c22-5358-b567-05cf174c0964", "1002cb2b-a663-5453-8ac5-908bb15b012f", "11504a4a-069e-5fac-b07a-e26b04220f05", "136df0a8-f9f7-4f47-8687-f14a32f74085", "1ee35711-f1ae-53c6-ba3a-0b6c13363def", "28f9015a-cef3-5051-94f8-d9c1d5746a95", "2d1406c4-9657-5129-880f-708552437cda", "3cbe83e5-8f02-5acf-96b3-c6804717063b", "4434e000-be29-55bb-9993-23c338a03ad3", "5a2138f6-34e1-546b-8e10-3e53626f9743", "61e968a9-aee8-53bb-b690-9dcf08fa7339", "63179d57-cd8a-5f2d-ac22-3093c91e8add", "6910ec4d-e51f-42e3-8001-e465e57d5446", "7427f28c-ebc2-5f0f-acb3-b0bff15bf09a", "7722d51a-c0f3-5866-923b-d633de15370f", "7b2f5b7d-4146-5bc3-8449-1812211cb9f8", "7bf05086-98fe-504f-b2bf-748eea87750c", "820d487b-ada6-54cf-b025-3d26f56e9c43", "85befafc-14d5-542b-81b3-3d10c6c97618", "9dbb9387-1c47-59a3-8983-a26bc206eb5f", "b2b7aecb-feeb-47dd-bd16-f1e337f333b3", "bace1ad7-cdb9-5537-8d51-a2ee7158a20a", "c4cde0cf-52e9-50f7-8b33-1c5a8f596d14", "f759bbb5-8e7a-5fd0-9373-79fd5e8c9c8d"]'::jsonb)),
posts AS (
 SELECT p.id,p.primary_account_id,p.published_at,p.is_repost,
  CASE WHEN p.published_at<:'fit_until'::timestamptz THEN 'fit' ELSE 'cal' END AS fold,
  :'available_before'::timestamptz AS available_before
 FROM ingest.publication p JOIN accounts a ON p.primary_account_id=a.id
 WHERE p.deleted_at IS NULL AND NOT p.is_repost
 AND ((p.published_at>=:'fit_from'::timestamptz AND p.published_at<:'fit_until'::timestamptz)
   OR (p.published_at>=:'cal_from'::timestamptz AND p.published_at<:'cal_until'::timestamptz))
), snapshots AS (
 SELECT s.publication_id,s.observed_at,s.age_seconds,s.views_count,s.reactions_count,s.views_quality,
  s.reactions_quality,s.interval_uncertain,s.synthetic,s.created_at,s.sampling_bucket,s.correction_sequence
 FROM posts p JOIN ingest.publication_metric_snapshot s
  ON s.publication_id=p.id AND s.published_month=date_trunc('month',p.published_at)::date
 UNION ALL
 SELECT u.publication_id,u.observed_at,u.age_seconds,u.views_count,u.reactions_count,u.views_quality,
  u.reactions_quality,u.interval_uncertain,u.synthetic,u.created_at,u.sampling_bucket,u.correction_sequence
 FROM posts p JOIN ingest.publication_metric_history h ON h.publication_id=p.id
 CROSS JOIN LATERAL (SELECT max(t.o)::integer AS hi FROM unnest(h.observed_at) WITH ORDINALITY t(at,o)
                     WHERE t.at<=p.published_at+interval '80 hours') slice
 CROSS JOIN LATERAL ingest.unpack_history(h,1,slice.hi) u
 WHERE slice.hi IS NOT NULL
), visible AS (
 -- Видима на момент доступности последняя записанная к тому времени версия бакета.
 SELECT * FROM (
  SELECT s.*,rank() OVER(PARTITION BY publication_id,sampling_bucket ORDER BY correction_sequence DESC) AS version_rank
  FROM snapshots s WHERE s.created_at<:'available_before'::timestamptz
 ) ranked WHERE version_rank=1 AND NOT synthetic
), endpoints AS (
 SELECT DISTINCT ON(p.id,w.hours) p.id,w.hours,raw.observed_at,raw.age_seconds,raw.views_count AS v,
  raw.reactions_count AS r,raw.views_quality::text AS vq,raw.reactions_quality::text AS rq,
  raw.interval_uncertain AS uncertain,raw.created_at
 FROM posts p CROSS JOIN (VALUES(24,3),(72,6)) w(hours,slack)
 JOIN visible raw ON raw.publication_id=p.id AND raw.age_seconds BETWEEN (w.hours-w.slack)*3600 AND w.hours*3600
 ORDER BY p.id,w.hours,raw.observed_at DESC,raw.correction_sequence DESC
), point_sets AS (
 SELECT z.id,jsonb_agg(to_jsonb(z)-'id' ORDER BY z.hours) AS points FROM (
  SELECT p.id,w.hours,e.observed_at,e.age_seconds,e.v,e.r,e.vq,e.rq,e.uncertain,e.created_at
  FROM posts p CROSS JOIN (VALUES(24),(72)) w(hours) LEFT JOIN endpoints e ON e.id=p.id AND e.hours=w.hours
 ) z GROUP BY z.id
), decreases AS (
 SELECT publication_id,bool_or(v<previous_v OR r<previous_r) AS known_decrease FROM (
  SELECT publication_id,v,r,max(v) OVER w AS previous_v,max(r) OVER w AS previous_r FROM (
   SELECT DISTINCT ON(publication_id,sampling_bucket) publication_id,observed_at,
     CASE WHEN views_quality='exact' AND NOT interval_uncertain THEN views_count END AS v,
     CASE WHEN reactions_quality='exact' AND NOT interval_uncertain THEN reactions_count END AS r
   FROM visible WHERE age_seconds BETWEEN 0 AND 72*3600
   ORDER BY publication_id,sampling_bucket,correction_sequence DESC
  ) q
  WINDOW w AS (PARTITION BY publication_id ORDER BY observed_at ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
 ) q GROUP BY publication_id
), results AS (
 SELECT p.*,s.points,coalesce(d.known_decrease,false) AS known_decrease
 FROM posts p JOIN point_sets s ON s.id=p.id LEFT JOIN decreases d ON d.publication_id=p.id
)
SELECT to_jsonb(results) FROM results ORDER BY published_at,id;
COMMIT;
