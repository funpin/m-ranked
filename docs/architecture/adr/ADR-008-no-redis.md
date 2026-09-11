# ADR-008: PostgreSQL notifications и LRU вместо Redis

- Status: **Accepted**
- Date: 2026-09-13

## Context

Redis использовался только как общий response cache и транспорт инвалидации.
На одном API-процессе он добавлял отдельный daemon, credential, outbox relay и
режим отказа без доказанной выгоды.

## Decision

FastAPI держит ограниченный LRU-кэш в памяти. Ключ включает dataset revision,
TTL ограничивает жизнь записи, а PostgreSQL `LISTEN/NOTIFY` ускоряет очистку.
Фоновый outbox marker помечает события доставленными отдельной минимальной
ролью. Корректность не зависит от получения уведомления.

## Consequences

Удалены Redis, relay unit и секрет. После горизонтального масштабирования у
каждого API будет собственный LRU; это допустимо благодаря revision key и TTL.
Внешний cache/broker возвращается только по измеренной потребности.
