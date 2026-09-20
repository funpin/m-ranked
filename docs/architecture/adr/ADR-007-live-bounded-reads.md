# ADR-007: Живые bounded-запросы вместо материализованных проекций

- Status: **Accepted**
- Date: 2026-09-13

## Context

Три почасовые проекции занимали около 3.5 ГБ вместе с индексами и требовали
publisher/barrier, из-за которого свежие данные не были видны до пересборки.

## Decision

Overview, statistics, history и compare читают канонические ingest-таблицы живыми
SQL-запросами. Каждый запрос ограничен периодом, платформой, page size и
месяцами партиций. Dataset revision фиксирует согласованный as-of.

Удалены projection publisher, serving barrier и таблицы
`publication_hourly`, `comparison_publication_hourly`,
`comparison_metric_point`.

## Consequences

Схема и write path стали меньше, новые данные видны сразу после commit.
Сравнения дороже по CPU/буферам, поэтому их планы и budgets проверяются на
production-shaped данных. Возврат одной инкрементальной проекции допустим
только после измеренного нарушения бюджета и нового ADR.
