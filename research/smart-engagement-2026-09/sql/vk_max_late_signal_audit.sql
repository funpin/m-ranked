-- Read-only audit against the frozen local 2026-09-23 database.
-- These are counts of SAVED detector signals, not incidence among all posts.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '15s';

WITH selected AS (
    SELECT account.platform,
           publication.id AS publication_id,
           publication.primary_account_id,
           (signal.item ->> 'startAt')::timestamptz AS start_at,
           (signal.item ->> 'endAt')::timestamptz AS end_at
    FROM analytics.post_anomaly_state AS state
    JOIN ingest.publication AS publication ON publication.id = state.publication_id
    JOIN catalog.platform_account AS account ON account.id = publication.primary_account_id
    CROSS JOIN LATERAL jsonb_array_elements(state.signals) AS signal(item)
    WHERE account.platform IN ('telegram', 'vk', 'max', 'rutube')
      AND signal.item ->> 'pattern' = '2'
      AND signal.item ->> 'metric' = 'views'
      AND (signal.item -> 'render' ->> 'startAge')::numeric BETWEEN 3 * 86400 AND 4 * 86400
), classified AS (
    SELECT selected.*,
           EXISTS (
               SELECT 1
               FROM ingest.publication AS newer
               WHERE newer.primary_account_id = selected.primary_account_id
                 AND newer.id <> selected.publication_id
                 AND newer.published_at BETWEEN selected.start_at - interval '2 hours'
                                            AND selected.end_at + interval '2 hours'
           ) AS nearby_new_publication
    FROM selected
)
SELECT platform,
       count(*) AS saved_late_view_signals,
       count(DISTINCT publication_id) AS posts,
       count(DISTINCT primary_account_id) AS accounts,
       count(*) FILTER (WHERE NOT nearby_new_publication) AS signals_without_nearby_new_post,
       count(DISTINCT publication_id) FILTER (WHERE NOT nearby_new_publication) AS posts_without_nearby_new_post,
       count(DISTINCT primary_account_id) FILTER (WHERE NOT nearby_new_publication) AS accounts_without_nearby_new_post
FROM classified
GROUP BY platform
ORDER BY platform;

ROLLBACK;
