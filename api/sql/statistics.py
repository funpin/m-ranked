"""Bounded publication statistics on the latest cumulative observations."""
from __future__ import annotations

from ..statistics_capabilities import sql_values


CAPABILITIES = f"""capabilities(platform,reactions_supported,comments_supported,shares_supported) AS (
    VALUES {sql_values()}
)"""

SEARCH_PREDICATE = r"""
(
    %(q)s='' OR
    lower(institution.canonical_name) LIKE %(search_pattern)s ESCAPE '\' OR
    lower(coalesce(institution.short_name,'')) LIKE %(search_pattern)s ESCAPE '\' OR
    lower(coalesce(account.current_title,'')) LIKE %(search_pattern)s ESCAPE '\' OR
    lower(coalesce(account.current_username,'')) LIKE %(username_pattern)s ESCAPE '\' OR
    lower(account.canonical_external_id) LIKE %(search_pattern)s ESCAPE '\' OR
    EXISTS (
        SELECT 1 FROM ingest.publication_identity searched_identity
         WHERE searched_identity.publication_id=publication.id
           AND (lower(searched_identity.external_id) LIKE %(search_pattern)s ESCAPE '\'
             OR lower(coalesce(searched_identity.public_url,'')) LIKE %(search_pattern)s ESCAPE '\')
    )
)
"""

MEASURED_COLUMNS = """
CASE WHEN latest.views_quality IN ('invalid','suspected_reset')
     THEN NULL ELSE latest.views_count END AS views,
CASE WHEN latest.reactions_quality IN ('invalid','suspected_reset')
     THEN NULL ELSE latest.reactions_count END AS reactions,
CASE WHEN latest.comments_quality IN ('invalid','suspected_reset')
     THEN NULL ELSE latest.comments_count END AS comments,
CASE WHEN latest.shares_quality IN ('invalid','suspected_reset')
     THEN NULL ELSE latest.shares_count END AS shares
"""

INTERACTIONS_EXPRESSION = """
CASE
  WHEN reactions_supported AND reactions IS NULL THEN NULL
  WHEN comments_supported AND comments IS NULL THEN NULL
  WHEN shares_supported AND shares IS NULL THEN NULL
  ELSE (CASE WHEN reactions_supported THEN reactions ELSE 0 END)
     + (CASE WHEN comments_supported THEN comments ELSE 0 END)
     + (CASE WHEN shares_supported THEN shares ELSE 0 END)
END::bigint
"""


PUBLICATIONS = f"""
WITH params AS (
    SELECT %(as_of)s::timestamptz AS as_of,
           %(as_of)s::timestamptz-CASE %(period)s WHEN '3h' THEN interval '3 hours'
             WHEN '1d' THEN interval '1 day' WHEN '7d' THEN interval '7 days'
             ELSE interval '30 days' END AS cutoff
), {CAPABILITIES}, filtered AS (
    SELECT publication.id AS publication_id,publication.primary_account_id AS account_id,
           publication.published_at,publication.deleted_at,publication.is_repost,
           account.platform::text AS platform,account.institution_id,
           account.current_username,account.current_title,account.canonical_external_id,
           institution.canonical_name AS institution_canonical_name,
           institution.short_name AS institution_short_name
      FROM ingest.visible_publication publication
      JOIN catalog.visible_platform_account account ON account.id=publication.primary_account_id
      JOIN catalog.visible_institution institution ON institution.id=account.institution_id
     CROSS JOIN params
     WHERE account.enabled
       AND (%(platform)s='all' OR account.platform::text=%(platform)s)
       AND publication.published_at>=params.cutoff AND publication.published_at<=params.as_of
       AND {SEARCH_PREDICATE}
), newest AS (
    SELECT filtered.*,
           row_number() OVER(PARTITION BY platform
                             ORDER BY published_at DESC,publication_id DESC) AS newest_position
      FROM filtered
), measured AS (
    SELECT newest.*,capability.reactions_supported,capability.comments_supported,
           capability.shares_supported,{MEASURED_COLUMNS}
      FROM newest
      JOIN capabilities capability USING(platform)
      LEFT JOIN analytics.publication_latest latest ON latest.publication_id=newest.publication_id
       AND latest.observed_at<=(SELECT as_of FROM params)
       AND NOT latest.synthetic AND latest.quality<>'invalid'
     WHERE newest_position<=200
), evaluated AS (
    SELECT measured.*,{INTERACTIONS_EXPRESSION} AS interactions
      FROM measured
), decorated AS (
    SELECT evaluated.*,
           CASE WHEN evaluated.platform='telegram' THEN 'posts' ELSE 'platform_posts' END AS legacy_type,
           evaluated.current_username AS account_username,
           evaluated.current_title AS account_title,
           CASE WHEN interactions IS NOT NULL AND views>0
                THEN interactions::numeric*100/views END AS erv,
           publication_alias.legacy_id,publication_alias.legacy_route,
           institution_alias.legacy_id AS institution_legacy_id,
           account_alias.legacy_id AS account_legacy_id,
           identity.external_id,identity.public_url,
           (SELECT count(*) FROM ingest.publication_identity author
             WHERE author.publication_id=evaluated.publication_id
               AND author.role='joint_author')::integer AS additional_author_count
      FROM evaluated
      LEFT JOIN LATERAL (
          SELECT alias.legacy_id,alias.legacy_route FROM catalog.legacy_entity_alias alias
           WHERE alias.target_uuid=evaluated.publication_id
             AND alias.entity_type=CASE WHEN evaluated.platform='telegram' THEN 'posts' ELSE 'platform_posts' END
           ORDER BY alias.legacy_id LIMIT 1) publication_alias ON true
      LEFT JOIN LATERAL (
          SELECT alias.legacy_id FROM catalog.legacy_entity_alias alias
           WHERE alias.target_uuid=evaluated.institution_id AND alias.entity_type='institutions'
           ORDER BY alias.legacy_id LIMIT 1) institution_alias ON true
      LEFT JOIN LATERAL (
          SELECT alias.legacy_id FROM catalog.legacy_entity_alias alias
           WHERE alias.target_uuid=evaluated.account_id
             AND alias.entity_type=CASE WHEN evaluated.platform='telegram' THEN 'channels' ELSE 'platform_accounts' END
           ORDER BY alias.legacy_id LIMIT 1) account_alias ON true
      LEFT JOIN LATERAL (
          SELECT value.external_id,value.public_url FROM ingest.publication_identity value
           WHERE value.publication_id=evaluated.publication_id AND value.role='primary'
           ORDER BY value.id LIMIT 1) identity ON true
), sortable AS (
    SELECT decorated.*,
           CASE %(publication_sort)s WHEN 'views' THEN views::numeric
             WHEN 'reactions' THEN reactions::numeric
             WHEN 'interactions' THEN interactions::numeric
             WHEN 'published_at' THEN extract(epoch FROM published_at)::numeric
             ELSE erv END AS sort_value
      FROM decorated
), ranked AS (
    SELECT sortable.*,
           row_number() OVER(PARTITION BY platform ORDER BY
             CASE WHEN %(publication_direction)s='desc' THEN sort_value END DESC NULLS LAST,
             CASE WHEN %(publication_direction)s='asc' THEN sort_value END ASC NULLS LAST,
             published_at DESC,publication_id DESC) AS rank
      FROM sortable
)
SELECT * FROM ranked WHERE rank<=50 ORDER BY platform,rank
"""


ENTITIES = f"""
WITH params AS (
    SELECT %(as_of)s::timestamptz AS as_of,
           %(as_of)s::timestamptz-CASE %(period)s WHEN '3h' THEN interval '3 hours'
             WHEN '1d' THEN interval '1 day' WHEN '7d' THEN interval '7 days'
             ELSE interval '30 days' END AS cutoff
), {CAPABILITIES}, filtered AS (
    SELECT publication.id AS publication_id,publication.published_at,
           account.platform::text AS platform,account.institution_id,
           institution.canonical_name,institution.short_name
      FROM ingest.visible_publication publication
      JOIN catalog.visible_platform_account account ON account.id=publication.primary_account_id
      JOIN catalog.visible_institution institution ON institution.id=account.institution_id
     CROSS JOIN params
     WHERE account.enabled AND account.platform::text=%(platform)s
       AND publication.published_at>=params.cutoff AND publication.published_at<=params.as_of
       AND {SEARCH_PREDICATE}
), newest AS (
    SELECT filtered.*,
           row_number() OVER(PARTITION BY institution_id
                             ORDER BY published_at DESC,publication_id DESC) AS institution_position
      FROM filtered
), measured AS (
    SELECT newest.*,capability.reactions_supported,capability.comments_supported,
           capability.shares_supported,{MEASURED_COLUMNS}
      FROM newest
      JOIN capabilities capability USING(platform)
      LEFT JOIN analytics.publication_latest latest ON latest.publication_id=newest.publication_id
       AND latest.observed_at<=(SELECT as_of FROM params)
       AND NOT latest.synthetic AND latest.quality<>'invalid'
     WHERE institution_position<=20
), evaluated AS (
    SELECT measured.*,{INTERACTIONS_EXPRESSION} AS interactions
      FROM measured
), aggregated AS (
    SELECT institution_id,min(platform) AS platform,min(canonical_name) AS canonical_name,
           min(short_name) AS short_name,count(*)::integer AS publication_count,
           count(interactions)::integer AS interaction_sample_size,
           count(views)::integer AS view_sample_size,
           count(*) FILTER (WHERE interactions IS NOT NULL AND views>0)::integer AS erv_sample_size,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY interactions)
             FILTER (WHERE interactions IS NOT NULL) AS median_interactions,
           sum(interactions)::bigint AS interactions,sum(views)::bigint AS views,
           CASE WHEN sum(views) FILTER (WHERE interactions IS NOT NULL AND views>0)>0
                THEN sum(interactions) FILTER (WHERE interactions IS NOT NULL AND views>0)::numeric*100
                     /sum(views) FILTER (WHERE interactions IS NOT NULL AND views>0) END AS erv
      FROM evaluated GROUP BY institution_id
), decorated AS (
    SELECT aggregated.*,institution_alias.legacy_id AS institution_legacy_id,
           institution_alias.legacy_route,
           CASE %(entity_sort)s WHEN 'median_interactions' THEN median_interactions::numeric
             WHEN 'interactions' THEN interactions::numeric WHEN 'views' THEN views::numeric
             WHEN 'publications' THEN publication_count::numeric ELSE erv END AS sort_value
      FROM aggregated
      LEFT JOIN LATERAL (
          SELECT alias.legacy_id,alias.legacy_route FROM catalog.legacy_entity_alias alias
           WHERE alias.target_uuid=aggregated.institution_id AND alias.entity_type='institutions'
           ORDER BY alias.legacy_id LIMIT 1) institution_alias ON true
), ranked AS (
    SELECT decorated.*,row_number() OVER(ORDER BY
           CASE WHEN %(entity_direction)s='desc' THEN sort_value END DESC NULLS LAST,
           CASE WHEN %(entity_direction)s='asc' THEN sort_value END ASC NULLS LAST,
           lower(coalesce(short_name,canonical_name)),institution_id) AS rank
      FROM decorated
)
SELECT * FROM ranked WHERE rank<=50 ORDER BY rank
"""
