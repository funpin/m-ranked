-- 0095 — «Наш рейтинг» вузов по соцсетям: формула версии 1.
--
-- Собственная открытая формула m-ranked (спек docs/superpowers/specs/2026-11-20-our-rating-design.md):
-- четыре площадки по 25 %, балл площадки — регулярность (дни с публикациями), охват на
-- студента и вовлечённость на логарифмической шкале между p10 и p90 площадки на
-- сентябре–октябре 2026; накрутка вычитается до расчёта. Определение совпадает с
-- api.own_rating.FORMULA_V1, source_hash — sha256 канонического JSON (тест
-- tests/test_own_rating_postgres.py). Снимки пишет ночное задание прогноза той же
-- функцией ops_and_admin.record_rating_forecast (0084) со своим ключом формулы;
-- страницы прогноза и «без накрутки» читают только свои формулы. Первый снимок —
-- ноябрь 2026 (решение владельца 20.11.2026: считать с этого месяца).
--
-- Откат: DELETE FROM rating.rating_run WHERE formula_definition_id IN (SELECT id FROM rating.formula_definition
--          WHERE formula_key = 'm-ranked-own-social');  (rating_result удаляется каскадом)
--        строку формулы удаляет только владелец (опубликованная формула неизменна, 0014).
BEGIN;
SET LOCAL lock_timeout = '5s';

INSERT INTO rating.formula_definition(formula_key, version, status, effective_from, definition, source_hash, published_at)
VALUES ('m-ranked-own-social', 1, 'published', '2026-11-01T00:00:00+03:00',
        '{"formulaKey": "m-ranked-own-social", "version": 1, "timezone": "Europe/Moscow", "firstMonth": "2026-11", "weights": {"telegram": 0.25, "vk": 0.25, "max": 0.25, "rutube": 0.25}, "activeDays": {"perDays": 30, "full": {"telegram": 24, "vk": 24, "max": 24, "rutube": 8}}, "scale": {"kind": "log", "anchors": "p10-p90"}, "reachPerStudent": {"telegram": {"low": 0.065, "high": 0.42}, "vk": {"low": 0.108, "high": 1.33}, "max": {"low": 0.038, "high": 0.27}, "rutube": {"low": 0.0014, "high": 0.14}}, "erv": {"telegram": {"low": 0.0085, "high": 0.036}, "vk": {"low": 0.009, "high": 0.03}, "max": {"low": 0.012, "high": 0.05}, "rutube": {"low": 0.0015, "high": 0.038}}, "minPosts": {"telegram": 8, "vk": 8, "max": 8, "rutube": 4}, "minCoverageDays": 14, "partialBelow": 0.9, "minPlatforms": 3, "matureAfterDays": 3, "closeAfterDay": 7, "rutubeBy": "uploaded", "packs": {"level": 3, "minStrength": 0.7, "perPost": "largest_episode_per_metric", "excludedKinds": ["gap", "write_off"], "views": "max(pack, discounted_views)"}, "lateExcess": {"tailStatus": 2, "minProfiles": 10, "majority": 0.5, "expectedTail": "cohort_median", "combine": "max(packs, late)"}, "evenResponse": {"maxEvenness": {"telegram": 0.1, "vk": 0.25, "max": 0.1}, "minMedianReactions": 30, "minResiduals": 10, "needsLateExcess": true, "cap": "platform_median_erv"}}'::jsonb,
        '825561f2fe4e9de7c08dd0b33819ebc14f19b52a98fb437f362255c1176fb8c2', transaction_timestamp())
ON CONFLICT (formula_key, version) DO NOTHING;

COMMIT;
