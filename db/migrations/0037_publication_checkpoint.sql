-- 0037 — значения публикации на фиксированных часах после выхода
--
-- Причина: страница сравнения сопоставляет все вузы сразу, и честная мера
-- для этого — не текущий счётчик (у вчерашнего поста он заведомо меньше,
-- чем у позавчерашнего), а значение на одном и том же возрасте: 1, 3, 6, 12,
-- 24, 48, 72 и 168 часов. Живым запросом это поиск снимка на каждую пару
-- «пост и час»: 234 тысячи поисков и 1,5 ГиБ чтения кучи — двадцать секунд
-- на каждое открытие. Но значение на прошедшем часе больше не меняется,
-- поэтому оно пишется один раз и лежит готовым: пересчёт по расписанию
-- дописывает только часы, которые посты успели пройти с прошлого прогона.
--
-- Строка без значений — тоже результат: снимка рядом с этим часом не было
-- (пропуск сбора, пост найден поздно), и искать его снова незачем.
--
-- Права. maintenance пишет (пересчёт идёт тем же заданием, что и витрина
-- обзора), api_read читает. Сборщики, перенос и анализ таблицу не видят.
CREATE TABLE analytics.publication_checkpoint (
    publication_id uuid NOT NULL,
    hour_offset smallint NOT NULL,
    observed_at timestamp with time zone,
    views_count bigint,
    reactions_count bigint,
    comments_count bigint,
    shares_count bigint,
    computed_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT publication_checkpoint_pkey PRIMARY KEY (publication_id, hour_offset),
    CONSTRAINT publication_checkpoint_hour_check
        CHECK (hour_offset = ANY (ARRAY[1, 3, 6, 12, 24, 48, 72, 168])),
    CONSTRAINT publication_checkpoint_counts_check
        CHECK ((views_count IS NULL OR views_count >= 0) AND (reactions_count IS NULL OR reactions_count >= 0)
           AND (comments_count IS NULL OR comments_count >= 0) AND (shares_count IS NULL OR shares_count >= 0)),
    CONSTRAINT publication_checkpoint_publication_id_fkey FOREIGN KEY (publication_id)
        REFERENCES ingest.publication(id) ON DELETE CASCADE
);

COMMENT ON TABLE analytics.publication_checkpoint IS 'Значения публикации на фиксированных часах после выхода для сравнения вузов. Пишется один раз, когда пост прошёл этот час; строка без значений — снимка рядом с часом не было.';
COMMENT ON COLUMN analytics.publication_checkpoint.observed_at IS 'Когда сделан снимок, давший значения. Не раньше часа минус допуск: иначе значение относилось бы к другому возрасту.';

GRANT SELECT ON TABLE analytics.publication_checkpoint TO api_read;
GRANT SELECT, INSERT, DELETE ON TABLE analytics.publication_checkpoint TO maintenance;
