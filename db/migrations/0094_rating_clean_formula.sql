-- 0094 — «М-Рейтинг без накрутки»: отдельная формула снимков рядом с прогнозом.
--
-- Тот же балл соцсетей, что у прогноза (m-rating-social-forecast версии 2), но из
-- VK и MAX вычитается замеренная накрутка: пакеты по постам уровня 3 (крупнейший
-- эпизод метрики, сила сигнала не ниже 0.7) и «умная» накрутка аккаунта — ровный
-- отклик вместе с длинным хвостом. Определение совпадает с
-- api.rating_clean.FORMULA_CLEAN_V1, source_hash — sha256 канонического JSON (тест
-- tests/test_rating_clean_postgres.py). Снимки пишет ночное задание прогноза той же
-- функцией ops_and_admin.record_rating_forecast; страница прогноза /rating читает
-- только свою формулу и эти снимки не видит.
--
-- Откат: DELETE FROM rating.rating_result WHERE rating_run_id IN (SELECT run.id FROM rating.rating_run run
--          JOIN rating.formula_definition f ON f.id = run.formula_definition_id WHERE f.formula_key = 'm-rating-social-clean');
--        DELETE FROM rating.rating_run WHERE formula_definition_id IN (SELECT id FROM rating.formula_definition
--          WHERE formula_key = 'm-rating-social-clean');
--        строку формулы удаляет только владелец (опубликованная формула неизменна, 0014).
BEGIN;
SET LOCAL lock_timeout = '5s';

INSERT INTO rating.formula_definition(formula_key, version, status, effective_from, definition, source_hash, published_at)
VALUES ('m-rating-social-clean', 1, 'published', '2026-09-01T00:00:00+03:00',
        '{"formulaKey": "m-rating-social-clean", "version": 1, "timezone": "Europe/Moscow", "base": {"formulaKey": "m-rating-social-forecast", "version": 2}, "platforms": ["max", "vk"], "packs": {"level": 3, "minStrength": 0.7, "perPost": "largest_episode_per_metric", "excludedKinds": ["gap", "write_off"], "views": "max(pack, discounted_views)"}, "smart": {"minMedianReactions": 30, "minResiduals": 10, "maxEvenness": {"max": 0.1, "vk": 0.25}, "tailAbove": "cohort_p90", "expectedTail": "cohort_median"}}'::jsonb,
        '5230d474932e9037fb18f981e7c31eea2c3957d8a6cfe2453a95de26dc097d85', transaction_timestamp())
ON CONFLICT (formula_key, version) DO NOTHING;

COMMIT;
