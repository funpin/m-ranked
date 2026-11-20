SET jit=off;
COPY (
WITH acc AS (
  SELECT a.id, a.institution_id, a.platform::text platform, a.enabled, a.created_at,
         (SELECT min(p.published_at) FROM ingest.publication p WHERE p.primary_account_id=a.id) first_pub
    FROM catalog.visible_platform_account a
)
SELECT acc.institution_id, acc.id account_id, acc.platform, acc.enabled, acc.created_at, acc.first_pub,
       p.id pub_id, p.published_at, p.uploaded_at,
       l.views_count v, l.reactions_count r, l.comments_count c, l.shares_count s,
       coalesce(st.level,0) lvl, st.discounted_views dv, st.analyzed_at IS NOT NULL analyzed,
       (SELECT max(greatest(
  coalesce((s->'render'->>'episodeGrowth')::numeric,0),
  coalesce((s->'render'->>'episodeReactions')::numeric,0),
  coalesce((s->'render'->>'burstLower')::numeric,0),
  coalesce((s->'render'->>'burst')::numeric,0),
  coalesce((s->'render'->>'reactionsDelta')::numeric - (s->'render'->>'expected')::numeric,0) * (s->'render'->>'kind'='lead')::int,
  coalesce((s->'render'->>'actual')::numeric - (s->'render'->>'expected')::numeric,0) * (s->'render'->>'kind'<>'lead')::int,
  coalesce((s->'render'->>'slope')::numeric * ((s->'render'->>'endAge')::numeric - (s->'render'->>'startAge')::numeric)/3600,0)))
          FROM jsonb_array_elements(coalesce(st.signals,'[]')) s
         WHERE s->>'metric'='reactions' AND (s->>'strength')::numeric>=0.7) r_ep,
       (SELECT max(greatest(
  coalesce((s->'render'->>'episodeGrowth')::numeric,0),
  coalesce((s->'render'->>'episodeViews')::numeric,0),
  coalesce((s->'render'->>'burstLower')::numeric,0),
  coalesce((s->'render'->>'burst')::numeric,0),
  coalesce((s->'render'->>'actual')::numeric - (s->'render'->>'expected')::numeric,0) * (s->'render'->>'kind'<>'lead')::int,
  coalesce((s->'render'->>'slope')::numeric * ((s->'render'->>'endAge')::numeric - (s->'render'->>'startAge')::numeric)/3600,0)))
          FROM jsonb_array_elements(coalesce(st.signals,'[]')) s
         WHERE s->>'metric'='views' AND (s->>'strength')::numeric>=0.7) v_ep,
       EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(st.signals,'[]')) s
         WHERE s->>'metric'='reactions' AND (s->>'strength')::numeric>=0.7) r_sig
  FROM acc JOIN ingest.publication p ON p.primary_account_id=acc.id AND p.deleted_at IS NULL
   AND coalesce(least(p.uploaded_at, p.published_at), p.published_at) >= '2026-08-25 00:00+03' AND p.published_at < '2026-11-18 00:00+03'
  LEFT JOIN analytics.publication_latest l ON l.publication_id=p.id
  LEFT JOIN analytics.post_anomaly_state st ON st.publication_id=p.id
) TO STDOUT WITH CSV HEADER;
