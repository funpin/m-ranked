# Анализ аномальной динамики

Независимый worker `anomaly_analysis` выбирает bounded-кандидатов из
PostgreSQL, фиксирует source dataset revision и публикует новую монотонную
analysis revision. Сбой анализа не блокирует каноническую ревизию и публичные
страницы.

Public API:

- `GET /api/v1/publications/{id}/anomaly-analysis` — состояние и активные
  findings с revision-bound cursor и ETag.

Admin API:

- `POST /api/v1/admin/publications/{id}/anomaly-signals`;
- `POST /api/v1/admin/anomaly-signals/{findingId}/reviews`.

Admin-команды требуют HTTP Basic, роль ADMIN, double-submit CSRF,
`Idempotency-Key` и correlation id. Приватные evidence/comments не выходят
через public views.

Состояние хранится в `analytics.publication_analysis_*`,
`analytics.publication_anomaly_*` и
`ops_and_admin.anomaly_analysis_candidate`. Worker использует отдельную роль
`analytics_worker`, lease с TTL и bounded retry. Термины описывают
статистический сигнал и никогда не утверждают намеренную накрутку.

Проверки: `tests/test_anomaly_analysis.py`,
`tests/test_anomaly_analysis_postgres.py`, API response-contract tests и
frontend history interactions.
