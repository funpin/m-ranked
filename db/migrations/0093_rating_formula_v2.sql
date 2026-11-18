-- 0093 — прогноз М-Рейтинга: формула версии 2.
--
-- Подбор 18.11.2026 на опубликованных сентябре и октябре (research/m-rating-forecast/README.md):
-- подбалл VK и MAX — степенная шкала 0.7 вместо логарифма, Rutube считает видео по
-- дате загрузки и добавляет подбалл просмотров на студента, правила «источник не
-- учитывает канал» нет. Определение совпадает с api.rating_forecast.FORMULA_V2,
-- source_hash — sha256 канонического JSON (тест tests/test_rating_forecast_postgres.py).
--
-- Строка версии 1 остаётся опубликованной: её снимки (в том числе итоговый прогноз
-- октября 2026) объясняются своей версией. Ночное задание после выкатки пишет снимки
-- версией 2; страница выбирает снимок месяца по статусу и времени, а не по версии.
--
-- Откат: вернуть код с FORMULA_CURRENT = FORMULA_V1 — задание снова пишет версию 1,
-- снимки версии 2 остаются объяснимыми своей строкой. Саму строку удаляет только
-- владелец: опубликованная формула неизменна (rating.reject_published_formula_mutation, 0014).
BEGIN;
SET LOCAL lock_timeout = '5s';

INSERT INTO rating.formula_definition(formula_key, version, status, effective_from, definition, source_hash, published_at)
VALUES ('m-rating-social-forecast', 2, 'published', '2026-11-01T00:00:00+03:00',
        '{"formulaKey": "m-rating-social-forecast", "version": 2, "timezone": "Europe/Moscow", "weights": {"max": 0.4, "vk": 0.3, "rutube": 0.3}, "scale": {"kind": "power", "exponent": 0.7}, "posts": {"low": 15, "high": 90}, "viewsPerStudent": {"vk": {"low": 0, "high": 1.7}, "max": {"low": 0, "high": 0.33}}, "erv": {"vk": {"low": 0, "high": 0.035}, "max": {"low": 0, "high": 0.08}}, "rutube": {"minVideos": 5, "countBy": "uploaded", "videos": {"low": 20, "high": 150}, "viewsPerStudent": {"low": 0.01, "high": 5}, "depthConstant": 25, "officialBlend": 0.5}, "sourceZeroRule": false, "matureAfterDays": 3, "earlyBeforeDay": 7, "defaultErrors": {"social": 5, "max": 5, "vk": 5, "rutube": 8}}'::jsonb,
        '03b7dfb4edcd9f2e4d4a2b24f77772ee8adfc02913dae09811fcba9056a8372d', transaction_timestamp())
ON CONFLICT (formula_key, version) DO NOTHING;

COMMIT;
