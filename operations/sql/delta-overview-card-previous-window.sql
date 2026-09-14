-- Прошлое окно в витрине карточек обзора.
--
-- В контракте поля previousTotal и previousMedian есть с самого начала, но
-- заполнялись пустотой: живым запросом прошлое окно удваивало стоимость
-- обзора ради значения, которое экран тогда не показывал. Теперь экран
-- показывает — плашка прироста под каждым числом, — а считать это на каждый
-- запрос по-прежнему незачем: числа одинаковы для всех читателей и
-- пересчитываются тем же расписанием, что и текущее окно.
ALTER TABLE analytics.overview_card_metrics
    ADD COLUMN previous_publication_count bigint DEFAULT 0 NOT NULL,
    ADD COLUMN previous_total_views numeric,
    ADD COLUMN previous_median_views numeric,
    ADD COLUMN previous_total_reactions numeric,
    ADD COLUMN previous_median_reactions numeric,
    ADD COLUMN previous_total_comments numeric,
    ADD COLUMN previous_median_comments numeric,
    ADD COLUMN previous_total_shares numeric,
    ADD COLUMN previous_median_shares numeric;

COMMENT ON COLUMN analytics.overview_card_metrics.previous_publication_count IS 'Сколько публикаций попало в предыдущее такое же окно: знаменатель, по которому видно, сравнимы ли периоды.';
COMMENT ON COLUMN analytics.overview_card_metrics.previous_total_reactions IS 'Прирост реакций за предыдущее окно той же длины. Пусто, когда наблюдений на его границе нет и сравнивать не с чем.';
