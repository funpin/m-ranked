-- 0043 — готовая выдача истории замеров для постов с законченным сбором
--
-- Причина: 24.09.2026 GPTBot обходил по две-три уникальные страницы
-- публикаций в секунду, и каждая стоила около секунды базы: история замеров
-- читается с диска строка за строкой (замеры одного поста разбросаны по
-- страницам таблицы), к каждой — разбивка реакций и опросы сборщика между
-- замерами. У поста старше сорока суток сбор закончен, и эта выдача больше
-- не меняется. Её достаточно посчитать один раз.
--
-- Что хранится: элементы ответа /publications/{id}/history (ровно то, что
-- строит api.dto.history_snapshot) от новых к старым, не больше 2001 — первая
-- страница любого размера до 2000 плюс признак продолжения. Сжато zlib: TOAST
-- сжатые данные повторно не сжимает, поэтому хранение внешнее.
--
-- Когда верить: отпечаток (число снимков поста и наибольший номер) снят до
-- расчёта. API сверяет его с текущим по индексу и при расхождении — поправка
-- или удаление снимка — строит ответ заново, как раньше. Покрытие журналом
-- сборщика идёт до текущего момента и сюда не входит: оно считается живым.
--
-- Права. maintenance пишет (задание api.tools.history_pages) и для этого
-- читает то же, что запрос истории в API; api_read только читает.
CREATE TABLE analytics.publication_history_page (
    publication_id uuid NOT NULL,
    published_month date NOT NULL,
    snapshot_count integer NOT NULL,
    max_snapshot_id bigint NOT NULL,
    items_count integer NOT NULL,
    payload bytea NOT NULL,
    computed_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT publication_history_page_pkey PRIMARY KEY (publication_id),
    CONSTRAINT publication_history_page_counts_check
        CHECK (snapshot_count >= 0 AND max_snapshot_id >= 0 AND items_count BETWEEN 0 AND 2001),
    CONSTRAINT publication_history_page_publication_id_fkey FOREIGN KEY (publication_id)
        REFERENCES ingest.publication(id) ON DELETE CASCADE
);
ALTER TABLE analytics.publication_history_page ALTER COLUMN payload SET STORAGE EXTERNAL;
CREATE INDEX publication_history_page_computed_idx ON analytics.publication_history_page (computed_at);

COMMENT ON TABLE analytics.publication_history_page IS 'Готовая выдача истории замеров (элементы api.dto.history_snapshot, от новых к старым, zlib JSON) для постов с законченным сбором. Верна, пока отпечаток (snapshot_count, max_snapshot_id) совпадает с текущим.';

GRANT SELECT ON TABLE analytics.publication_history_page TO api_read;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE analytics.publication_history_page TO maintenance;
GRANT SELECT ON TABLE ingest.reaction_breakdown TO maintenance;
GRANT SELECT ON TABLE ingest.collection_account_result TO maintenance;
GRANT EXECUTE ON FUNCTION analytics.ordered_history_reactions(text, boolean) TO maintenance;
