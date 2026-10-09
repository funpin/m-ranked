-- 0078 — код вуза в официальном М-Рейтинге хранится у самого вуза.
--
-- Прежде соответствие «вуз ↔ код m-rating.ru» лежало в
-- api/data/official-m-rating-channel-codes.json и было ключом по
-- Telegram-юзернейму: вуз без канала в этом файле, со сменённым юзернеймом
-- или вовсе без Telegram оставался без всех рейтингов (общего, ВК, MAX,
-- RuTube). Теперь код — внешний идентификатор вуза
-- (catalog.institution_external_id, namespace 'm-rating').
--
-- Перенос: 64 прежних соответствия плюс десять недостающих — БелГУ, РХТУ и
-- восемь вузов, у которых был только август, внесённый вручную. Вузы, которых
-- нет в М-Рейтинге (он охватывает подведомственные Минобрнауки), кода не
-- получают.
--
-- Новые вузы привязываются сами при импорте, если полное название в каталоге
-- совпадает с названием в источнике (ops_and_admin.official_rating_codes).
--
-- Откат: DROP FUNCTION ops_and_admin.official_rating_codes(jsonb);
--   DELETE FROM catalog.institution_external_id WHERE namespace='m-rating';
--   и вернуть файл кодов с прежней версией api/official_rating.py.
BEGIN;
SET LOCAL lock_timeout = '5s';

INSERT INTO catalog.institution_external_id(institution_id, namespace, external_id, valid_from, verified_at)
SELECT DISTINCT ON (seed.code) account.institution_id, 'm-rating', seed.code,
       transaction_timestamp(), transaction_timestamp()
  FROM (VALUES
    ('agrobioteh37', '220'),
    ('bmstu1830', '112'),
    ('bru_live', '2'),
    ('bruniver', '48'),
    ('bsuedu', '7'),
    ('chesuofficial', '209'),
    ('chuvsu21', '210'),
    ('demidyarsu', '214'),
    ('donetsk_donntu', '240'),
    ('ggntu_official', '69'),
    ('gubkin_university', '21'),
    ('guumsk', '68'),
    ('itmoru', '18'),
    ('ivgpu', '76'),
    ('ivsuontherun', '77'),
    ('kbsu1957', '84'),
    ('kchgulife', '92'),
    ('kgu_kostroma', '96'),
    ('khsu_katanova', '206'),
    ('kovrov_kgta', '94'),
    ('ksu_kaluga', '90'),
    ('kursksu', '101'),
    ('maiuniversity', '108'),
    ('marmgu', '236'),
    ('mephi_of', '19'),
    ('miptru', '12'),
    ('mospolytech', '118'),
    ('mpeiuniversity', '122'),
    ('msal_kutafina', '117'),
    ('mslu_official', '111'),
    ('muctr_official', '154'),
    ('ncfulife', '30'),
    ('ncsaru', '175'),
    ('new_guap', '24'),
    ('news_susu', '34'),
    ('niumgsuofficial', '121'),
    ('novosti_au', '218'),
    ('nust_misis', '14'),
    ('nvsunv', '126'),
    ('omsuru', '133'),
    ('orel_sau', '224'),
    ('politehperm', '140'),
    ('prim_gsha', '226'),
    ('pushkininstitute', '67'),
    ('reshetnevuniversity', '5'),
    ('rgsu_life', '151'),
    ('rgu_esenina', '159'),
    ('rgusocteh', '215'),
    ('rosbiotech_official', '115'),
    ('rsukosygin', '152'),
    ('rtumirea_official', '106'),
    ('sochi_university', '181'),
    ('spsutd', '168'),
    ('ssla_official', '170'),
    ('stieglitz_academy', '162'),
    ('stroganovuniversity', '107'),
    ('swsu_kursk', '211'),
    ('syktsuofficial', '182'),
    ('tg_bgu', '44'),
    ('truebstu', '47'),
    ('tuvsu', '191'),
    ('tversu', '186'),
    ('ugrauniversity', '212'),
    ('unidubna_official', '230'),
    ('ursmu_ru', '198'),
    ('usaaa_ru', '197'),
    ('usfe05051930', '199'),
    ('vernadskycfu', '11'),
    ('vgltuofficial', '57'),
    ('vshniacademy', '62'),
    ('vvsu_dv', '53'),
    ('yargau', '229'),
    ('yaroslavlstu', '217'),
    ('zgu_university', '75')
  ) AS seed(username, code)
  JOIN catalog.visible_platform_account account
    ON account.platform = 'telegram' AND lower(account.current_username) = seed.username
 WHERE NOT EXISTS (SELECT 1 FROM catalog.institution_external_id existing
                    WHERE existing.namespace = 'm-rating' AND existing.valid_to IS NULL
                      AND (existing.external_id = seed.code
                           OR existing.institution_id = account.institution_id))
 ORDER BY seed.code, account.institution_id;

-- Нормализация названия для автопривязки: регистр, ё/е, кавычки, пробелы.
CREATE FUNCTION ops_and_admin.official_rating_name_key(p_name text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    SET search_path TO 'pg_catalog'
    AS $$
    SELECT btrim(regexp_replace(translate(lower(p_name), 'ё«»"“”„', 'е'), '\s+', ' ', 'g'))
$$;

-- Принимает вузы источника [{code, name}], привязывает непривязанные вузы
-- каталога по точному совпадению полного названия и возвращает действующие
-- соответствия видимых вузов. Привязка однозначна: код и вуз ещё свободны,
-- и название в каталоге встречается ровно один раз.
CREATE FUNCTION ops_and_admin.official_rating_codes(p_items jsonb)
    RETURNS TABLE(institution_id uuid, code text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'catalog', 'ops_and_admin'
    SET lock_timeout TO '10s'
    AS $$
#variable_conflict use_column
BEGIN
    IF jsonb_typeof(p_items) <> 'array' OR jsonb_array_length(p_items) > 10000 THEN
        RAISE EXCEPTION 'invalid official rating items' USING ERRCODE = '22023';
    END IF;
    WITH source AS (
        SELECT DISTINCT btrim(item->>'code') AS code,
               ops_and_admin.official_rating_name_key(item->>'name') AS name_key
          FROM jsonb_array_elements(p_items) item
         WHERE coalesce(btrim(item->>'code'), '') <> ''
           AND coalesce(btrim(item->>'name'), '') <> ''
    ), pair AS (
        SELECT institution.id AS institution_id, source.code,
               count(*) OVER (PARTITION BY source.code) AS per_code,
               count(*) OVER (PARTITION BY institution.id) AS per_institution
          FROM source
          JOIN catalog.visible_institution institution
            ON ops_and_admin.official_rating_name_key(institution.canonical_name) = source.name_key
    )
    INSERT INTO catalog.institution_external_id(institution_id, namespace, external_id, valid_from, verified_at)
    SELECT pair.institution_id, 'm-rating', pair.code, transaction_timestamp(), transaction_timestamp()
      FROM pair
     WHERE pair.per_code = 1 AND pair.per_institution = 1
       AND NOT EXISTS (SELECT 1 FROM catalog.institution_external_id existing
                        WHERE existing.namespace = 'm-rating' AND existing.valid_to IS NULL
                          AND (existing.external_id = pair.code
                               OR existing.institution_id = pair.institution_id));
    RETURN QUERY
    SELECT link.institution_id, link.external_id
      FROM catalog.institution_external_id link
      JOIN catalog.visible_institution institution ON institution.id = link.institution_id
     WHERE link.namespace = 'm-rating' AND link.valid_to IS NULL
     ORDER BY link.external_id;
END $$;

REVOKE ALL ON FUNCTION ops_and_admin.official_rating_name_key(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION ops_and_admin.official_rating_codes(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.official_rating_codes(jsonb) TO api_write_admin;

COMMIT;
