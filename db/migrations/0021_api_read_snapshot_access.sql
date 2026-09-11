-- 0021 — доступ роли чтения к таблице наблюдений
-- Написана вручную.

-- Прежде публичное чтение ходило к наблюдениям двумя путями: через
-- представление ingest.publication_metric_snapshot_resolved и через функцию
-- analytics.publication_snapshot_slice, объявленную SECURITY DEFINER. Обе
-- обёртки не скрывают ни одной строки: представление — это та же таблица плюс
-- разрешённый из словаря metric_evidence, а функция лишь добавляет отбор
-- активной коррекции. То есть api_read и раньше видел всё содержимое.
--
-- Цена обёрток измерима. Представление тянет metric_evidence_id, которого нет
-- в индексе, поэтому план вырождается из Index Only Scan в Index Scan:
-- 39 437 буферов вместо 2 242 на чтении 50 публикаций за месяц, в 17 раз
-- дороже. Функция непрозрачна планировщику и вызывается по разу на публикацию.
--
-- Поэтому роль чтения получает саму таблицу. Права не расширяются — меняется
-- только путь к тем же строкам.
GRANT SELECT ON TABLE ingest.publication_metric_snapshot TO api_read;
GRANT SELECT ON TABLE ingest.reaction_breakdown TO api_read;
GRANT SELECT ON TABLE ingest.account_metric_snapshot TO api_read;
