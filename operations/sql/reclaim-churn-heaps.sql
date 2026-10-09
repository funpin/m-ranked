-- Разовый возврат места у небольших, но раздутых таблиц с постоянными
-- обновлениями. Запускается оператором только по согласованию владельца —
-- это не служба и не миграция:
--   docker exec -i <контейнер базы> sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X' < operations/sql/reclaim-churn-heaps.sql
--
-- Почему нужно: 0061 не даёт таблицам расти дальше, но набранное
-- место автоочистка не возвращает. По отчёту 09.10:
--   ingest.publication_availability_state  715 МБ на 70,7 тыс. строк
--   analytics.post_anomaly_state           501 МБ на 65,1 тыс. строк
--   analytics.publication_latest           227 МБ на 68,6 тыс. строк
-- Живых данных в них на порядок меньше. VACUUM FULL переписывает таблицу
-- заново и отдаёт разницу файловой системе.
--
-- Цена: на время переписывания таблица под ACCESS EXCLUSIVE — чтение и
-- запись в неё ждут. Таблицы маленькие (секунды), но запускать ночью, по
-- одной. Блокировку ждём не дольше 2 с: не дождались — таблица пропускается
-- без вреда, её можно повторить позже. Запись в неё в это время копится в
-- очереди сборщика и приёмника и доходит после — ничего не теряется.
-- Перед запуском: свободно не меньше суммы живых размеров (несколько сотен
-- МБ) — новая копия пишется рядом со старой.
--
-- Горячие партиции замеров сюда не входят: их место возвращает
-- еженедельный reindex-churn.sql (индексы) и сама автоочистка, когда месяц
-- опустеет (пустой хвост таблицы она отрезает).
\set ON_ERROR_STOP off
SET lock_timeout = '2s';
SET statement_timeout = '120s';

SELECT c.oid::regclass AS "до", pg_size_pretty(pg_total_relation_size(c.oid)) AS size
  FROM pg_class c
 WHERE c.oid IN ('ingest.publication_availability_state'::regclass, 'analytics.post_anomaly_state'::regclass,
                 'analytics.publication_latest'::regclass);

VACUUM (FULL, ANALYZE) ingest.publication_availability_state;
VACUUM (FULL, ANALYZE) analytics.publication_latest;
VACUUM (FULL, ANALYZE) analytics.post_anomaly_state;

SELECT c.oid::regclass AS "после", pg_size_pretty(pg_total_relation_size(c.oid)) AS size
  FROM pg_class c
 WHERE c.oid IN ('ingest.publication_availability_state'::regclass, 'analytics.post_anomaly_state'::regclass,
                 'analytics.publication_latest'::regclass);
