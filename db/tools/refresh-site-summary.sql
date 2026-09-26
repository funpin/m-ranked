-- Пересчёт сводки главной (миграция 0044). Запускается каждым плановым
-- обслуживанием, но считает, только если строке больше :max_age_hours часов:
-- условие NOT EXISTS проверяется до подсчётов, и свежая строка ничего не стоит.
SET statement_timeout = '180s';
SET lock_timeout = '2s';
INSERT INTO analytics.site_summary AS summary (
    id, institutions, accounts, accounts_by_platform, publications, snapshots, computed_at)
SELECT 1,
       (SELECT count(*) FROM catalog.visible_institution),
       (SELECT count(*) FROM catalog.visible_platform_account),
       (SELECT coalesce(jsonb_object_agg(per.platform, per.accounts), '{}'::jsonb)
          FROM (SELECT account.platform::text AS platform, count(*) AS accounts
                  FROM catalog.visible_platform_account account
                 GROUP BY 1) per),
       (SELECT count(*)
          FROM ingest.visible_publication publication
          JOIN catalog.visible_platform_account account ON account.id = publication.primary_account_id),
       (SELECT count(*) FROM ingest.publication_metric_snapshot),
       transaction_timestamp()
 WHERE NOT EXISTS (
       SELECT 1 FROM analytics.site_summary fresh
        WHERE fresh.computed_at > transaction_timestamp() - make_interval(hours => :'max_age_hours'::integer))
ON CONFLICT (id) DO UPDATE SET
    institutions = excluded.institutions, accounts = excluded.accounts,
    accounts_by_platform = excluded.accounts_by_platform, publications = excluded.publications,
    snapshots = excluded.snapshots, computed_at = excluded.computed_at
RETURNING summary.computed_at;
