# m-ranked

M-Ranked собирает динамику публикаций вузов в Telegram, VK, MAX и Rutube,
хранит наблюдения в PostgreSQL и показывает рейтинги, сравнения и историю.

Production-стек один:

- FastAPI в `api/` — публичный и административный API;
- платформенные Python-сборщики в `collector_target/` и `collector_runtime/`;
- PostgreSQL 18 со схемой из `db/migrations/`;
- Next.js в `frontend/`;
- in-process LRU-кэш с инвалидацией через PostgreSQL `LISTEN/NOTIFY`.

Публичный адрес: [m.funpin.org](https://m.funpin.org).

## Быстрый старт

```bash
make venv
make stand          # http://localhost:3000
make test           # Python и frontend
```

Локальный стенд поднимает чистую PostgreSQL, FastAPI и Next.js. Демонстрационные
пароли лежат только в шаблоне `infra/local/compose.env.example`; собственный
файл можно указать через `MRANKED_COMPOSE_ENV`.

Сборщики запускаются отдельно:

```bash
.venv/bin/python -m collector_target --platform telegram
.venv/bin/python -m collector_target --platform vk
.venv/bin/python -m collector_target --platform max
.venv/bin/python -m collector_target --platform rutube
```

## Проверки

- `.venv/bin/python -m pytest tests anomaly_analysis -q`;
- `cd frontend && pnpm check`;
- чистый bootstrap: `docker compose --env-file infra/local/compose.env.example -f infra/compose.yaml up -d --wait postgres`.

Интеграционные PostgreSQL-тесты требуют DSN из `.env.test`; без них они
пропускаются. API-контракт зафиксирован в
`contracts/openapi/m-ranked-v1.yaml` и проверяется как Python-, так и
frontend-тестами.

## Документация

- [модель и страницы](docs/REFERENCE.md);
- [эксплуатация](docs/OPERATIONS.md);
- [архитектура и ADR](docs/architecture/README.md);
- [развёртывание](operations/runbooks/DEPLOY.md);
- [backup и restore](operations/runbooks/BACKUP_RESTORE.md);
- [правила участия](CONTRIBUTING.md).
