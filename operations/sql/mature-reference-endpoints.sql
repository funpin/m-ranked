-- Конечные точки 24/72 ч для пересборки ориентира признаков 11/12. Только чтение.
-- Та же рамка из 24 MAX-аккаунтов, выбранная до исходов (research/smart-engagement-2026-09/RELEASE.md),
-- активные коррекции на момент доступности, известные снижения до 72 ч. Результат — строка JSON на пост:
--
--   psql -X -q -At -v fit_from=2026-09-13 -v fit_until=2026-09-17 -v cal_from=2026-09-20 \
--        -v cal_until=2026-09-24 -v available_before='2026-09-27 00:00+00' \
--        -f operations/sql/mature-reference-endpoints.sql | gzip > endpoints.jsonl.gz
--
-- Даты — UTC, правые границы исключены. Далее: python -m anomaly_analysis.tools.renew_mature_reference.
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
), results AS (
 SELECT p.*,
  (SELECT jsonb_agg(to_jsonb(z) ORDER BY hours) FROM (
   SELECT h.hours,s.* FROM (VALUES(24,3),(72,6)) h(hours,slack)
   LEFT JOIN LATERAL (
    SELECT observed_at,age_seconds,views_count AS v,reactions_count AS r,
     views_quality::text AS vq,reactions_quality::text AS rq,
     interval_uncertain AS uncertain,created_at
    FROM ingest.publication_metric_snapshot raw
    WHERE raw.publication_id=p.id AND raw.published_month=date_trunc('month',p.published_at)::date
      AND raw.age_seconds BETWEEN (h.hours-h.slack)*3600 AND h.hours*3600
      AND NOT raw.synthetic AND raw.created_at<p.available_before AND NOT EXISTS (
      SELECT 1 FROM ingest.publication_metric_snapshot successor
      WHERE successor.published_month=raw.published_month AND successor.publication_id=raw.publication_id
       AND successor.sampling_bucket=raw.sampling_bucket AND successor.correction_sequence>raw.correction_sequence
       AND successor.created_at<p.available_before)
    ORDER BY raw.observed_at DESC,raw.correction_sequence DESC LIMIT 1
   ) s ON true
  ) z) AS points,
  (SELECT coalesce(bool_or(v<previous_v OR r<previous_r),false) FROM (
   SELECT *,max(v) OVER(ORDER BY observed_at ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS previous_v,
     max(r) OVER(ORDER BY observed_at ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS previous_r
   FROM (
    SELECT DISTINCT ON(raw.sampling_bucket) raw.observed_at,
      CASE WHEN raw.views_quality='exact' AND NOT raw.interval_uncertain THEN raw.views_count END AS v,
      CASE WHEN raw.reactions_quality='exact' AND NOT raw.interval_uncertain THEN raw.reactions_count END AS r
    FROM ingest.publication_metric_snapshot raw
    WHERE raw.publication_id=p.id AND raw.published_month=date_trunc('month',p.published_at)::date
     AND raw.age_seconds BETWEEN 0 AND 72*3600 AND NOT raw.synthetic AND raw.created_at<p.available_before AND NOT EXISTS (
      SELECT 1 FROM ingest.publication_metric_snapshot successor
      WHERE successor.published_month=raw.published_month AND successor.publication_id=raw.publication_id
       AND successor.sampling_bucket=raw.sampling_bucket AND successor.correction_sequence>raw.correction_sequence
       AND successor.created_at<p.available_before)
    ORDER BY raw.sampling_bucket,raw.correction_sequence DESC
   ) q
  ) q) AS known_decrease
 FROM posts p
)
SELECT to_jsonb(results) FROM results ORDER BY published_at,id;
COMMIT;
