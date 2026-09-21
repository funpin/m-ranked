# ADR-003: Next.js для web frontend

- Status: **Accepted**
- Date: 2026-09-13
- Owners: frontend / product

## Decision

Использовать Next.js App Router, TypeScript и React для публичного и
административного интерфейса. Все данные приходят только через versioned
FastAPI; прямого доступа к PostgreSQL у web нет.

Server Components и SSR являются default. Client Components остаются для
графиков, фильтров и интерактивных форм. Admin/auth/health responses не
попадают в public cache. OpenAPI client генерируется из замороженного контракта.

## Budgets

- LCP p75 mobile ≤ 2.5 s;
- INP ≤ 200 ms;
- CLS ≤ 0.1;
- route-specific initial JavaScript ≤ 170 KiB gzip;
- overview API p95 ≤ 1 s на bounded miss.

`pnpm check` проверяет lint, типы, контракт, unit/E2E, build и bundle budget.

## Consequences

Next.js даёт серверный HTML, metadata и ограниченный browser bundle, но требует
отдельного Node runtime. Кэш web считается производной оптимизацией; источником
истины остаётся ревизия PostgreSQL и HTTP validators FastAPI.
