"""Сводка главной страницы (миграция 0044): одна готовая строка."""

SUMMARY = """
SELECT institutions, accounts, accounts_by_platform, publications, snapshots, computed_at
  FROM analytics.site_summary
 WHERE id = 1
"""

# Вузы М-Рейтинга (подведомственные Минобрнауки), у которых мы отслеживаем
# хотя бы одну официальную соцсеть: у них есть действующий код m-rating.ru
# (миграция 0078). Тем же запросом кнопка панели снимает число в checkpoint.
RATED_INSTITUTIONS = """
SELECT count(*)::integer AS rated_institutions
FROM catalog.visible_institution institution
WHERE EXISTS (SELECT 1 FROM catalog.visible_platform_account account
              WHERE account.institution_id=institution.id AND account.enabled)
  AND EXISTS (SELECT 1 FROM catalog.institution_external_id code
              WHERE code.institution_id=institution.id AND code.namespace='m-rating'
                AND code.valid_to IS NULL)
"""

COVERAGE = """
SELECT count(*)::integer AS tracked_institutions,
       -- Покрытие — снимок кнопки «Загрузить свежий М‑Рейтинг» (миграция 0086);
       -- до первого снимка число считается на лету тем же условием.
       coalesce(analytics.official_rated_institution_count(),
                count(*) FILTER (WHERE EXISTS (
                    SELECT 1 FROM catalog.institution_external_id code
                     WHERE code.institution_id=institution.id AND code.namespace='m-rating'
                       AND code.valid_to IS NULL)))::integer AS rated_institutions,
       analytics.official_social_rating_count() AS rating_institutions
FROM catalog.visible_institution institution
WHERE EXISTS (SELECT 1 FROM catalog.visible_platform_account account
              WHERE account.institution_id=institution.id AND account.enabled)
"""
