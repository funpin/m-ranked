-- 0072 — готовая страница истории для поста с отрицательными номерами снимков.
--
-- Ограничение publication_history_page_counts_check требовало
-- max_snapshot_id >= 0, а номера снимков на проде бывают отрицательными
-- (в сентябре 2,4 млн из 13,8 млн). У поста, все номера которого
-- отрицательны, страница не записывалась: задание history-pages только с
-- 5 по 6 октября упало на этом 24 тысячи раз, и такие посты считались на
-- лету. Номер служит лишь отпечатком свежести и сравнивается на равенство.
--
-- Откат: вернуть max_snapshot_id >= 0 в ограничение (после удаления строк
-- с отрицательным номером).
BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE analytics.publication_history_page DROP CONSTRAINT publication_history_page_counts_check;
ALTER TABLE analytics.publication_history_page ADD CONSTRAINT publication_history_page_counts_check
    CHECK (snapshot_count >= 0 AND items_count >= 0 AND items_count <= 2001);

COMMIT;
