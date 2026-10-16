-- 0083 — время загрузки видео рядом со временем выхода.
--
-- Официальный М-Рейтинг считает видео Rutube за месяц по дате загрузки
-- (created_ts), а не выхода (publication_ts). По дате выхода порог «меньше 5
-- видео — 0» совпадает с официальным в 93 % случаев, по дате загрузки — в 97 %
-- (КГУ Курск, август: 13 видео вышли в августе, загружены в июле — 0).
-- published_at не меняется: на нём держатся месяцы снимков и окно
-- отслеживания.
--
-- Отдельная колонка, а не ключ quality_flags: флаги входят в семантический
-- отпечаток снимка, и новый ключ дал бы каждому видео лишнюю строку снимка.
--
-- ADD COLUMN без значения по умолчанию меняет только каталог: таблица не
-- переписывается, блокировка ACCESS EXCLUSIVE держится миллисекунды.
-- Применять до кода на обеих базах; старый код колонку не замечает.
--
-- Откат: ALTER TABLE ingest.publication DROP COLUMN uploaded_at;
BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE ingest.publication
    ADD COLUMN IF NOT EXISTS uploaded_at timestamp with time zone;

COMMENT ON COLUMN ingest.publication.uploaded_at IS
    'Platform upload time when it differs from publication (RUTUBE created_ts); NULL when the platform has none or it is not yet known. Never cleared by a batch without it.';

COMMIT;
