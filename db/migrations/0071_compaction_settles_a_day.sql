-- 0071 — упаковщик берёт пост, когда старые строки накопились за сутки.
--
-- compactable_publications (0059) отдавала любой пост со строкой старше
-- границы горячего слоя. У поста, который ещё наблюдается, такая строка
-- появляется каждые полчаса, и упаковщик переписывал бы его массивы целиком
-- на каждом запуске таймера: ~30 тысяч постов каждые полчаса — запись,
-- WAL и раздувание TOAST ради нескольких новых точек.
--
-- Теперь пост берётся, когда его самая старая горячая строка старше границы
-- ещё на сутки: активный пост перепаковывается раз в сутки, горячий слой
-- держит от 48 до 72 часов. Упаковывается по-прежнему всё старше границы.
--
-- Откат: определение функции из 0059.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE OR REPLACE FUNCTION ingest.compactable_publications(p_boundary timestamptz, p_limit integer)
RETURNS TABLE (publication_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path TO 'pg_catalog', 'ingest'
AS $$
    -- Полусоединение по индексу (publication_id, observed_at): LIMIT
    -- останавливает поиск, не перебирая все горячие строки.
    SELECT p.id
      FROM ingest.publication p
     WHERE EXISTS (SELECT 1 FROM ingest.publication_metric_snapshot s
                    WHERE s.publication_id = p.id AND s.observed_at < p_boundary - interval '1 day')
     LIMIT p_limit
$$;

COMMIT;
