-- 0086 — покрытие М-Рейтинга на главной считается снимком, а не на лету.
--
-- Решение владельца (2026-10-16): всё, что связано с М-Рейтингом, обновляется
-- только вручную из панели управления, а число вузов в покрытии
-- пересчитывается не чаще раза в две недели. Знаменатель (вузы раздела
-- «Социальные сети», 0056) и так снимок кнопки. Числитель — наши вузы с
-- действующим кодом m-rating.ru — до этой миграции считался при каждом
-- построении сводки, а коды привязывало ночное задание, поэтому цифра
-- менялась сама. Теперь кнопка кладёт его в тот же checkpoint
-- (`ratedInstitutions`), а публичное чтение берёт оттуда.
--
-- NULL означает «снимка ещё нет»: сводка тогда считает число на лету, как
-- раньше, до первого нажатия кнопки после выката.
BEGIN;
CREATE OR REPLACE FUNCTION analytics.official_rated_institution_count() RETURNS integer
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO pg_catalog AS $$
  SELECT CASE WHEN value->>'ratedInstitutions' ~ '^[0-9]{1,4}$'
              THEN (value->>'ratedInstitutions')::integer END
    FROM ops_and_admin.operational_checkpoint
   WHERE checkpoint_key='admin.m_rating.coverage' AND scope_type='system'
     AND scope_id IS NULL AND platform IS NULL
   LIMIT 1
$$;
REVOKE ALL ON FUNCTION analytics.official_rated_institution_count() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analytics.official_rated_institution_count() TO api_read;
COMMIT;
