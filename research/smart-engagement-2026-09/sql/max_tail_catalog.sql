BEGIN READ ONLY;
SET LOCAL statement_timeout='30s';
SET LOCAL lock_timeout='2s';
SET LOCAL TIME ZONE 'UTC';
SELECT jsonb_build_object('type','account','id',a.id,'institution',i.canonical_name,'short_name',i.short_name,'title',a.current_title,'enabled',a.enabled,
 'posts',count(p.id),'original_posts',count(p.id) FILTER(WHERE NOT p.is_repost),
 'published_min',min(p.published_at),'published_max',max(p.published_at))
FROM catalog.platform_account a JOIN catalog.institution i ON i.id=a.institution_id
LEFT JOIN ingest.publication p ON p.primary_account_id=a.id AND p.published_at>='2026-08-31' AND p.published_at<'2026-09-28' AND p.deleted_at IS NULL
WHERE a.platform='max' AND a.deleted_at IS NULL
GROUP BY a.id,i.canonical_name,i.short_name;
SELECT jsonb_build_object('type','receipt_coverage','n',count(*),'min',min(observed_at),'max',max(observed_at),'posts',count(DISTINCT publication_id)) FROM ingest.publication_poll_receipt;
COMMIT;
