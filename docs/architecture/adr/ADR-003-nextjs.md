# ADR-003: Next.js для целевого web frontend

- Status: **Proposed**
- Date: 2026-09-02
- Owners: frontend / product
- Related: [target containers](../c4/03-containers-target.puml),
  [cache sequence](../sequences/cache-invalidation.mmd)

## Context

Текущий интерфейс рендерится FastAPI/Jinja и содержит большой общий inline
CSS/JavaScript. Аналитические запросы выполняются при HTTP-request, а public и
admin UI связаны с Python backend. Проекту нужны быстрые индексируемые страницы,
интерактивные графики, контролируемый JS budget, HTTP/cache integration,
постепенная миграция маршрутов и отдельный стабильный API.

## Decision

Использовать Next.js App Router с TypeScript и React для public/admin web.

- Server Components и SSR — default.
- Client Components используются только для графиков, фильтров и действительно
  интерактивных элементов.
- Public страницы получают данные только из versioned Spring API; прямого
  доступа к PostgreSQL нет.
- Route/data cache связывается с dataset revision и domain tags.
- Для публичных стабильных страниц используются ISR/revalidation и HTTP ETag.
- Admin/auth/health/export responses не попадают в public cache.
- Legacy URLs сохраняются либо получают явный permanent redirect.
- Chart library загружается динамически только на маршрутах с графиком;
  зависимость закреплена lockfile и не исполняется с произвольного CDN.
- Next.js собирается в standalone deployment; Nginx отдает hashed static assets
  с `immutable`.
- UI показывает freshness, sample size, coverage, source quality и formula
  version рядом с выводом, где это влияет на интерпретацию.

## Performance and quality budgets

Начальные budgets для production p75 mobile:

- LCP ≤ 2.5 s;
- INP ≤ 200 ms;
- CLS ≤ 0.1;
- route-specific initial JavaScript ≤ 170 KiB gzip, если исключение не принято
  отдельным review;
- API response для overview p95 ≤ 300 ms на cache hit и ≤ 1 s на bounded miss;
- изображения имеют размеры, modern format и lazy loading вне первого экрана.

Budgets проверяются на production-like dataset, а не на пустой локальной БД.

## Consequences

Положительные:

- SSR/metadata помогают discoverability и первому отображению;
- Server Components уменьшают количество JavaScript в browser;
- маршрут можно переносить по одному через Nginx;
- TypeScript/OpenAPI позволяют проверять frontend/backend contract;
- framework поддерживает tag/path revalidation.

Отрицательные:

- появляется Node.js runtime и отдельный build/dependency chain;
- неверное использование Client Components увеличит bundle;
- cache Next.js добавляет еще один слой согласованности;
- framework upgrades требуют регулярной работы.

## Alternatives considered

### Jinja/Thymeleaf server templates

Проще в эксплуатации, но слабее разделяет public API и UI и менее удобно для
сложных интерактивных графиков. Legacy Jinja остается до route-by-route cutover.

### SPA/Vite

Отклонено как default: лишает большую часть публичных страниц серверного HTML и
переносит больше работы/JavaScript в browser. Vite остается допустимым для
изолированного embedded tool, если появится измеренная потребность.

### Full client-side dashboard

Отклонено из-за performance, accessibility и cache/SEO требований.

## Fitness functions

- Lighthouse/Web Vitals budgets проверяются в CI или scheduled environment.
- Bundle analyzer контролирует per-route JavaScript.
- OpenAPI client генерируется/проверяется, breaking change блокирует merge.
- Visual regression и accessibility tests покрывают основные страницы.
- Cache test доказывает, что admin response не доступен через public key.
- Каждый мигрированный URL сравнивается с feature-parity checklist legacy.

## Revisit when

- Node runtime становится главным эксплуатационным bottleneck;
- большинство страниц полностью статичны и framework не дает измеримой пользы;
- другой frontend нужен для отдельного клиента, но versioned API сохраняется.
